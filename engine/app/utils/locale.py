"""English-only translation lookup.

DeepMiro is English-only. This module used to support per-thread locale
switching with a Chinese translation file; that machinery was removed in
v1.7.0 along with `locales/zh.json` and `locales/languages.json`. The
public function signatures (`t`, `get_locale`, `set_locale`,
`get_language_instruction`) are preserved so the existing 14 call sites
keep working. `set_locale` is a no-op; `get_locale` always returns 'en'.

Translations live in `locales/en.json` and are loaded once at import.
"""

import json
import os
from typing import Any

_LOCALES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'locales')

with open(os.path.join(_LOCALES_DIR, 'en.json'), 'r', encoding='utf-8') as _f:
    _MESSAGES: dict = json.load(_f)

_LLM_INSTRUCTION = (
    "You MUST write ALL output in English only. Do not use any other "
    "language under any circumstances."
)


def set_locale(_locale: str) -> None:
    """No-op. English is the only supported locale."""
    return None


def get_locale() -> str:
    return 'en'


def t(key: str, **kwargs: Any) -> str:
    """Look up `key` (dotted path) in the English translation table.

    Returns the key itself if the path doesn't exist, so missing
    translations are visible during dev rather than silently empty.
    """
    value: Any = _MESSAGES
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if value is None:
        return key

    if kwargs and isinstance(value, str):
        for k, v in kwargs.items():
            value = value.replace(f'{{{k}}}', str(v))

    return value


def get_language_instruction() -> str:
    return _LLM_INSTRUCTION
