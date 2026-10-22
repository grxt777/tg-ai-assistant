"""Обёртка над Gemini API: генерация с инструментами и эмбеддинги."""
import asyncio
import logging
import re
import time

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
FALLBACK = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
_exhausted: dict[str, float] = {}  # модель -> когда снова можно (time.time())


def _quota_wait(e):
    """Секунды до сброса квоты, если это дневной лимит; иначе None (обычный 429 — можно повторить)."""
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
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=db.setting("temperature", 0.7, float),
    )
    last = None
    for model in _candidates():
        t0 = time.monotonic()
        try:
            resp = await _retry(client.aio.models.generate_content, model=model, contents=contents, config=cfg)
            break
        except errors.APIError as e:
            code = getattr(e, "code", None)
            if code == 404 and model != current_model():  # запасная модель недоступна этому ключу
                _exhausted[model] = time.time() + 86400
                continue
            if code in (500, 503, 504):  # модель перегружена или не успела — пробуем следующую
                log.warning("%s: %s — переключаюсь на запасную модель", model, code)
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
