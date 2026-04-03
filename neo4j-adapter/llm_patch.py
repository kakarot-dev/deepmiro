# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 kakarot-dev
"""
Modular LLM Patch System for MiroFish.

Each model family has its own guard/adapter that handles quirks:
- Message preprocessing (merge roles, inject flags)
- Response postprocessing (strip tags, clean output)
- English enforcement

Add new model guards by subclassing ModelGuard and registering.
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

logger = logging.getLogger("mirofish.llm_patch")


# ---------------------------------------------------------------------------
# Base class — all model guards extend this
# ---------------------------------------------------------------------------

class ModelGuard(ABC):
    """Base class for model-specific preprocessing and postprocessing."""

    @abstractmethod
    def match(self, model_name: str) -> bool:
        """Return True if this guard handles the given model name."""
        ...

    def preprocess_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Transform messages before sending to the LLM."""
        return messages

    def postprocess_response(self, content: str) -> str:
        """Transform response content after receiving from the LLM."""
        return content


# ---------------------------------------------------------------------------
# Qwen3 Guard — /no_think, strip <think> tags
# ---------------------------------------------------------------------------

class Qwen3Guard(ModelGuard):
    """
    Qwen3 has a 'thinking' mode that outputs <think>...</think> blocks,
    consuming tokens on reasoning instead of actual content.
    /no_think in the system prompt disables this.
    """

    def match(self, model_name: str) -> bool:
        return "qwen3" in model_name.lower() or "qwen-3" in model_name.lower()

    def preprocess_messages(self, messages):
        messages = _inject_into_system(messages, "/no_think")
        return messages

    def postprocess_response(self, content):
        return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()


# ---------------------------------------------------------------------------
# Mixtral Guard — strict role alternation
# ---------------------------------------------------------------------------

class MixtralGuard(ModelGuard):
    """
    Mixtral requires strict user/assistant message alternation.
    Consecutive same-role messages cause 400 errors.
    """

    def match(self, model_name: str) -> bool:
        return "mixtral" in model_name.lower()

    def preprocess_messages(self, messages):
        return _merge_consecutive_roles(messages)


# ---------------------------------------------------------------------------
# Llama Guard — English enforcement (weak Chinese support)
# ---------------------------------------------------------------------------

class LlamaGuard(ModelGuard):
    """
    Llama models have weak Chinese support and may produce
    empty outlines when given Chinese-heavy context.
    """

    def match(self, model_name: str) -> bool:
        return "llama" in model_name.lower()

    def preprocess_messages(self, messages):
        return _merge_consecutive_roles(messages)


# ---------------------------------------------------------------------------
# MiniMax Guard — handle potential format quirks
# ---------------------------------------------------------------------------

class MiniMaxGuard(ModelGuard):
    """MiniMax M2.5 — generally well-behaved, merge roles for safety."""

    def match(self, model_name: str) -> bool:
        return "minimax" in model_name.lower()

    def preprocess_messages(self, messages):
        return _merge_consecutive_roles(messages)


# ---------------------------------------------------------------------------
# DeepSeek Guard — has <think> tags like Qwen3
# ---------------------------------------------------------------------------

class DeepSeekGuard(ModelGuard):
    """DeepSeek models may also use thinking tags."""

    def match(self, model_name: str) -> bool:
        return "deepseek" in model_name.lower()

    def postprocess_response(self, content):
        return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()


# ---------------------------------------------------------------------------
# Default Guard — applies to any unrecognized model
# ---------------------------------------------------------------------------

class DefaultGuard(ModelGuard):
    """Fallback: merge roles + strip think tags (safe defaults)."""

    def match(self, model_name: str) -> bool:
        return True

    def preprocess_messages(self, messages):
        return _merge_consecutive_roles(messages)

    def postprocess_response(self, content):
        return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()


# ---------------------------------------------------------------------------
# Guard registry
# ---------------------------------------------------------------------------

GUARD_REGISTRY: List[ModelGuard] = [
    Qwen3Guard(),
    MixtralGuard(),
    LlamaGuard(),
    MiniMaxGuard(),
    DeepSeekGuard(),
    DefaultGuard(),  # Must be last — catches everything
]


def get_guard(model_name: str) -> ModelGuard:
    """Find the appropriate guard for a model name."""
    for guard in GUARD_REGISTRY:
        if guard.match(model_name):
            return guard
    return DefaultGuard()


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

ENGLISH_INSTRUCTION = "You MUST write ALL output in English only."


def _inject_into_system(messages: List[Dict], tag: str) -> List[Dict]:
    """Inject a tag into the first system message."""
    if not messages:
        return [{"role": "system", "content": f"{ENGLISH_INSTRUCTION}\n{tag}"}]

    result = []
    injected = False
    for msg in messages:
        msg = msg.copy()
        if msg["role"] == "system" and not injected:
            content = msg["content"]
            if tag not in content:
                content = content.rstrip() + f"\n{tag}"
            msg["content"] = content
            injected = True
        result.append(msg)

    if not injected:
        result.insert(0, {"role": "system", "content": f"{ENGLISH_INSTRUCTION}\n{tag}"})

    return result


def _merge_consecutive_roles(messages: List[Dict]) -> List[Dict]:
    """Merge consecutive messages with the same role."""
    if not messages or len(messages) <= 1:
        return messages

    merged = [messages[0].copy()]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            merged[-1]["content"] = merged[-1]["content"] + "\n\n" + msg["content"]
        else:
            merged.append(msg.copy())
    return merged


def _ensure_english_system(messages: List[Dict]) -> List[Dict]:
    """Ensure the system prompt has English enforcement."""
    if not messages:
        return [{"role": "system", "content": ENGLISH_INSTRUCTION}]

    result = []
    patched = False
    for msg in messages:
        msg = msg.copy()
        if msg["role"] == "system" and not patched:
            if "English only" not in msg["content"] and "english only" not in msg["content"]:
                msg["content"] = msg["content"].rstrip() + f"\n{ENGLISH_INSTRUCTION}"
            patched = True
        result.append(msg)

    if not patched:
        result.insert(0, {"role": "system", "content": ENGLISH_INSTRUCTION})

    return result


# ---------------------------------------------------------------------------
# Main patch function
# ---------------------------------------------------------------------------

def patch_llm_client():
    """
    Monkey-patch MiroFish's LLMClient.chat() with modular model guards.
    """
    try:
        from app.utils.llm_client import LLMClient

        original_chat = LLMClient.chat

        def patched_chat(self, messages, **kwargs):
            guard = get_guard(self.model)

            # 1. Enforce English
            messages = _ensure_english_system(messages)
            # 2. Model-specific preprocessing
            messages = guard.preprocess_messages(messages)
            # 3. Merge consecutive roles (all models benefit from this)
            messages = _merge_consecutive_roles(messages)
            # 4. Call original
            result = original_chat(self, messages, **kwargs)
            # 5. Model-specific postprocessing
            if isinstance(result, str):
                result = guard.postprocess_response(result)
            return result

        LLMClient.chat = patched_chat
        logger.info("LLMClient patched: modular model guard system active")
    except ImportError:
        logger.warning("Could not patch LLMClient — app.utils.llm_client not found")
