"""
Ask the configured LLM for a JSON object. Use cases own their prompts and decide what to do
when a call fails; these functions raise on any transport or parsing error.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from bakasur.core.config import CoreSettings

TIMEOUT_S = 120.0


def ollama_json(cfg: CoreSettings, prompt: str) -> Any:
    resp = httpx.post(
        f"{cfg.ollama_base_url.rstrip('/')}/api/generate",
        json={
            "model": cfg.llm_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            # Ollama samples at 0.8 by default, giving a different answer per run.
            "options": {"temperature": 0},
        },
        timeout=TIMEOUT_S,
    )
    resp.raise_for_status()
    return json.loads(resp.json().get("response", "{}"))


def openai_compat_json(cfg: CoreSettings, prompt: str) -> Any:
    if not cfg.openai_compat_base_url:
        raise ValueError("openai_compat_base_url is not set")
    resp = httpx.post(
        f"{cfg.openai_compat_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {cfg.openai_compat_api_key}"},
        json={
            "model": cfg.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=TIMEOUT_S,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])
