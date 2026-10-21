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
client = genai.Client(api_key=config.GEMINI_API_KEY)


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


async def _retry(fn, *args, **kwargs):
    delay = 5
    for attempt in range(5):
        try:
            return await fn(*args, **kwargs)
        except errors.APIError as e:
            if getattr(e, "code", None) == 429 and _quota_wait(e) is not None:
                raise  # дневной лимит — ждать бессмысленно, пусть generate переключит модель
            if getattr(e, "code", None) in (429, 500, 503) and attempt < 4:
                log.warning("Gemini %s, повтор через %ss", e.code, delay)
                await asyncio.sleep(delay)
                delay *= 2
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


async def generate(contents, system, tools):
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
            wait = _quota_wait(e) if code == 429 else None
            if wait is None:
                raise
            _exhausted[model] = time.time() + wait
            last = (model, wait)
            log.warning("Лимит %s исчерпан на %.1f ч — переключаюсь на запасную модель", model, wait / 3600)
            db.log_event("error", "quota", f"{model}: дневной лимит исчерпан, сброс через {wait / 3600:.1f} ч")
    else:
        hours = min((t - time.time() for t in _exhausted.values()), default=(last[1] if last else 3600)) / 3600
        raise QuotaExhausted(f"Бесплатный дневной лимит Gemini закончился на всех моделях. "
                             f"Снова заработает примерно через {max(hours, 0.1):.0f} ч. "
                             f"Чтобы не упираться — включи оплату в Google AI Studio.")
    u = resp.usage_metadata
    db.log_event("llm", model, f"in={getattr(u, 'prompt_token_count', 0) or 0} "
                               f"out={getattr(u, 'candidates_token_count', 0) or 0} "
                               f"total={getattr(u, 'total_token_count', 0) or 0}",
                 int((time.monotonic() - t0) * 1000))
    return resp
