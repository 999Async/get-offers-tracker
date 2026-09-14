"""Load local model settings as data, without shell evaluation or secret diagnostics."""

import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from getoffers_agent.assistant.provider import ModelConfig

KEYS = frozenset(
    {
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_INPUT_PRICE_PER_MILLION",
        "LLM_OUTPUT_PRICE_PER_MILLION",
        "LLM_MAX_OUTPUT_TOKENS",
    }
)


def load_model_config(env_file: Path | None = None, environ=None) -> ModelConfig | None:
    values = dict(os.environ if environ is None else environ)
    if env_file:
        seen = set()
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key not in KEYS or key in seen:
                raise ValueError("invalid_or_duplicate_model_setting")
            seen.add(key)
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError("invalid_quoted_model_setting")
                value = value[1:-1]
            values[key] = value  # Deliberately no interpolation, expansion, or execution.
    model, key = values.get("LLM_MODEL", ""), values.get("LLM_API_KEY", "")
    if not model and not key:
        return None
    if not model or not key:
        raise ValueError("incomplete_model_configuration")
    try:

        def price(name):
            return Decimal(values[name]) if values.get(name) else None

        return ModelConfig(
            base_url=values.get("LLM_BASE_URL", "https://api.openai.com/v1"),
            model=model,
            api_key=key,
            input_price=price("LLM_INPUT_PRICE_PER_MILLION"),
            output_price=price("LLM_OUTPUT_PRICE_PER_MILLION"),
            max_output_tokens=int(values.get("LLM_MAX_OUTPUT_TOKENS", "3000")),
        )
    except (ValueError, InvalidOperation):
        raise ValueError("invalid_model_configuration") from None
