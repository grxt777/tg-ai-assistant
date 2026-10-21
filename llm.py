"""Обёртка над Gemini API: генерация с инструментами и эмбеддинги."""
import asyncio
import logging

import numpy as np
from google import genai
from google.genai import errors, types

import config

log = logging.getLogger(__name__)
client = genai.Client(api_key=config.GEMINI_API_KEY)


async def _retry(fn, *args, **kwargs):
    delay = 5
    for attempt in range(5):
        try:
            return await fn(*args, **kwargs)
        except errors.APIError as e:
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


async def generate(contents, system, tools):
    return await _retry(
        client.aio.models.generate_content,
        model=config.MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            tools=tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.7,
        ),
    )
