"""Обёртка над Gemini API: генерация с инструментами и эмбеддинги.

Модели OpenRouter ("vendor/name") тоже идут через generate: запрос переводится в формат OpenAI,
а ответ собирается обратно в GenerateContentResponse, так что agent.py разницы не видит.
"""
import asyncio
import json
import logging
import re
import time

import aiohttp
import numpy as np
from google import genai
from google.genai import errors, types

import config
import db

log = logging.getLogger(__name__)
client = genai.Client(api_key=config.GEMINI_API_KEY,
                      http_options=types.HttpOptions(timeout=60_000))  # мс: зависший запрос не держит ответ вечно


class QuotaExhausted(Exception):
    """Дневной лимит бесплатного тарифа закончился на всех моделях."""


# Запасные модели: у каждой свой бесплатный дневной лимит
FALLBACK = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest",
            *config.OPENROUTER_MODELS]
_exhausted: dict[str, float] = {}  # модель -> когда снова можно (time.time())


def _quota_wait(e):
    """Секунды до сброса квоты, если это дневной лимит; иначе None (обычный 429 — можно повторить)."""
    if isinstance(e, RouterError):
        return e.reset_in if "per-day" in str(e) else None
    text = str(e)
    if "PerDay" not in text and "free_tier_requests" not in text:
        return None
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", text)
    if not m:
        return 3600
    h, mi, sec = (float(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + sec


def _minute_wait(e):
    """Сколько секунд просит подождать поминутный лимит (429 без PerDay)."""
    if isinstance(e, RouterError):
        return min(e.reset_in, 60)
    m = re.search(r"retry in ([\d.]+)s", str(e)) or re.search(r"retryDelay'?\"?:\s*'?\"?(\d+)s", str(e))
    return float(m.group(1)) if m else 30


async def _retry(fn, *args, **kwargs):
    """Короткие повторы только на 500/503/504. 429 сразу наверх — generate переключит модель."""
    for attempt in range(2):
        try:
            return await fn(*args, **kwargs)
        except errors.APIError as e:
            if getattr(e, "code", None) in (500, 503, 504) and attempt == 0:
                log.warning("Gemini %s, повтор через 2с", e.code)
                await asyncio.sleep(2)
                continue
            raise


async def embed(texts, task="RETRIEVAL_DOCUMENT"):
    """Возвращает нормализованные векторы (можно сравнивать скалярным произведением)."""
    out = []
    for i in range(0, len(texts), 100):
        r = await _retry(
            client.aio.models.embed_content,
            model=config.EMBED_MODEL,
            contents=texts[i:i + 100],
            config=types.EmbedContentConfig(task_type=task, output_dimensionality=config.EMBED_DIM),
        )
        for e in r.embeddings:
            v = np.asarray(e.values, dtype=np.float32)
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
    return out


# ---------- OpenRouter ----------
class RouterError(Exception):
    def __init__(self, code, message, reset_in=60):
        super().__init__(message)
        self.code, self.reset_in = code, reset_in


def is_router(model):
    return "/" in model


def _schema(s):
    """Schema Gemini (type: "OBJECT") → JSON Schema (type: "object")."""
    if isinstance(s, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _schema(v)) for k, v in s.items()}
    return [_schema(x) for x in s] if isinstance(s, list) else s


def _oa_tools(tools):
    out = []
    for d in (fd for t in tools or [] for fd in t.function_declarations or []):
        params = _schema(d.parameters.model_dump(mode="json", exclude_none=True)) if d.parameters else \
            {"type": "object", "properties": {}}
        out.append({"type": "function", "function": {"name": d.name, "description": d.description or "",
                                                     "parameters": params}})
    return out


def _oa_messages(contents, system):
    msgs, pending = [{"role": "system", "content": system}], []  # pending — id вызовов, ждущих ответа
    for c in contents:
        parts = [p for p in c.parts or [] if not p.thought]
        text = "\n".join(p.text for p in parts if p.text)
        if c.role == "model":
            calls = [p.function_call for p in parts if p.function_call]
            pending = [f"call_{len(msgs)}_{i}" for i in range(len(calls))]
            m = {"role": "assistant", "content": text or None}
            if calls:
                m["tool_calls"] = [{"id": i, "type": "function",
                                    "function": {"name": f.name, "arguments": json.dumps(f.args or {}, ensure_ascii=False)}}
                                   for i, f in zip(pending, calls)]
            msgs.append(m)
            continue
        for p in parts:
            if p.function_response:
                msgs.append({"role": "tool", "tool_call_id": pending.pop(0) if pending else "call_0",
                             "content": json.dumps(p.function_response.response, ensure_ascii=False, default=str)})
        if text:
            msgs.append({"role": "user", "content": text})
    return msgs


async def _router_generate(model, contents, system, tools, temperature):
    body = {"model": model, "messages": _oa_messages(contents, system), "temperature": temperature}
    if oa := _oa_tools(tools):
        body["tools"] = oa
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
            async with s.post("https://openrouter.ai/api/v1/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"}) as r:
                data = await r.json(content_type=None)
                status = r.status
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        raise RouterError(503, f"OpenRouter недоступен: {type(e).__name__}")
    err = data.get("error") if isinstance(data, dict) else None
    if err or status >= 400:
        err = err or {}
        code = err.get("code") if isinstance(err.get("code"), int) else status
        reset = (err.get("metadata") or {}).get("headers", {}).get("X-RateLimit-Reset")
        reset_in = max(int(reset) / 1000 - time.time(), 60) if reset else 3600
        raise RouterError(code, f"OpenRouter {code}: {err.get('message', '')} {err.get('metadata') or ''}"[:500],
                          reset_in)
    msg = data["choices"][0]["message"]
    parts = [types.Part.from_text(text=msg["content"])] if msg.get("content") else []
    for c in msg.get("tool_calls") or []:
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
        except ValueError:
            args = {}
        # Gemini 3 требует подпись мысли у вызова функции — у чужих вызовов её нет, ставим служебную
        parts.append(types.Part(function_call=types.FunctionCall(name=c["function"]["name"], args=args),
                                thought_signature=b"skip_thought_signature_validator"))
    u = data.get("usage") or {}
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))] if parts else [],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=u.get("prompt_tokens"), candidates_token_count=u.get("completion_tokens"),
            total_token_count=u.get("total_tokens")))


def _has_media(contents):
    return any(p.inline_data or p.file_data for c in contents for p in c.parts or [])


def current_model():
    return db.setting("model", config.MODEL)


def _candidates():
    main = current_model()
    chain = [main] + [m for m in FALLBACK if m != main]
    if db.setting("fallback", "1") == "0":
        chain = [main]
    now = time.time()
    return [m for m in chain if _exhausted.get(m, 0) <= now]


async def generate(contents, system, tools, _retried=False):
    temperature = db.setting("temperature", 0.7, float)
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=temperature,
    )
    chain = _candidates()
    if _has_media(contents):  # голос и картинки понимает только Gemini
        now = time.time()
        chain = [m for m in chain if not is_router(m)] or \
            [m for m in FALLBACK if not is_router(m) and _exhausted.get(m, 0) <= now][:1]
    last = None
    for model in chain:
        t0 = time.monotonic()
        try:
            if is_router(model):
                resp = await _router_generate(model, contents, system, tools, temperature)
            else:
                resp = await _retry(client.aio.models.generate_content, model=model, contents=contents, config=cfg)
            break
        except (errors.APIError, RouterError) as e:
            code = getattr(e, "code", None)
            if code == 404 and model != current_model():  # запасная модель недоступна этому ключу
                _exhausted[model] = time.time() + 86400
                continue
            if code in (500, 502, 503, 504):  # модель перегружена или не успела — пробуем следующую
                log.warning("%s: %s — переключаюсь на запасную модель", model, code)
                continue
            if isinstance(e, RouterError) and code != 429 and model != current_model():
                log.warning("%s: %s — пропускаю", model, e)  # например, 402: кончился баланс OpenRouter
                _exhausted[model] = time.time() + 3600
                continue
            if code != 429:
                raise
            wait = _quota_wait(e)
            if wait is None:  # поминутный лимит: не ждём, а сразу берём другую модель
                _exhausted[model] = time.time() + _minute_wait(e)
                log.warning("Поминутный лимит %s — переключаюсь на запасную модель", model)
                continue
            _exhausted[model] = time.time() + wait
            last = (model, wait)
            log.warning("Лимит %s исчерпан на %.1f ч — переключаюсь на запасную модель", model, wait / 3600)
            db.log_event("error", "quota", f"{model}: дневной лимит исчерпан, сброс через {wait / 3600:.1f} ч")
    else:
        now = time.time()
        soonest = min((t - now for t in _exhausted.values() if t > now), default=0)
        if 0 < soonest <= 60 and not _retried:  # все упёрлись в поминутный лимит — подождём один раз
            await asyncio.sleep(soonest)
            return await generate(contents, system, tools, _retried=True)
        if last is None or soonest <= 60:  # дневной лимит ни при чём
            raise QuotaExhausted("Gemini сейчас перегружен или упёрся в поминутный лимит. Попробуй через минуту.")
        hours = soonest / 3600
        raise QuotaExhausted(f"Бесплатный дневной лимит Gemini закончился на всех моделях. "
                             f"Снова заработает примерно через {max(hours, 0.1):.0f} ч. "
                             f"Чтобы не упираться — включи оплату в Google AI Studio.")
    u = resp.usage_metadata
    db.log_event("llm", model, f"in={getattr(u, 'prompt_token_count', 0) or 0} "
                               f"out={getattr(u, 'candidates_token_count', 0) or 0} "
                               f"total={getattr(u, 'total_token_count', 0) or 0}",
                 int((time.monotonic() - t0) * 1000))
    return resp


TRANSCRIBE_PROMPT = ("Дословно расшифруй речь из этой записи на языке оригинала. "
                     "Верни только текст, без пояснений и кавычек. Если речи нет — верни пустую строку.")


async def transcribe(data: bytes, mime: str) -> str:
    """Голос → текст. Слушать умеет только Gemini — Мирик тоже присылает свои голосовые сюда."""
    contents = [types.Content(role="user", parts=[types.Part.from_bytes(data=data, mime_type=mime),
                                                   types.Part.from_text(text=TRANSCRIBE_PROMPT)])]
    resp = await generate(contents, "Ты точный стенографист.", None)
    return (resp.text or "").strip()
