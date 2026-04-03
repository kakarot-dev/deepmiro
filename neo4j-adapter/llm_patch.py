# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 kakarot-dev
"""
Patch MiroFish's LLMClient for production compatibility.

Fixes:
1. Merge consecutive messages with the same role (Mixtral, Llama compatibility)
2. Inject /no_think into system prompts (disables Qwen3's thinking mode)
3. Enforce English output in all system prompts
"""

import logging
import re

logger = logging.getLogger("mirofish.llm_patch")

NO_THINK_TAG = "/no_think"
ENGLISH_INSTRUCTION = "You MUST write ALL output in English only."


def merge_consecutive_messages(messages):
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


def inject_no_think(messages):
    """
    Inject /no_think into the first system message to disable Qwen3's
    chain-of-thought mode. Without this, Qwen3 spends all tokens on
    <think> reasoning and produces no actual content.
    """
    if not messages:
        return messages

    result = []
    injected = False
    for msg in messages:
        msg = msg.copy()
        if msg["role"] == "system" and not injected:
            content = msg["content"]
            # Add /no_think if not already present
            if NO_THINK_TAG not in content:
                content = content.rstrip() + f"\n{NO_THINK_TAG}"
            # Add English instruction if not already present
            if "English only" not in content and "english only" not in content:
                content = content.rstrip() + f"\n{ENGLISH_INSTRUCTION}"
            msg["content"] = content
            injected = True
        result.append(msg)

    # If no system message exists, prepend one
    if not injected:
        result.insert(0, {
            "role": "system",
            "content": f"{ENGLISH_INSTRUCTION}\n{NO_THINK_TAG}"
        })

    return result


def strip_think_tags(content):
    """Remove any remaining <think> tags from response content."""
    if not content:
        return content
    return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()


def patch_llm_client():
    """
    Monkey-patch MiroFish's LLMClient.chat() with all fixes.
    """
    try:
        from app.utils.llm_client import LLMClient

        original_chat = LLMClient.chat

        def patched_chat(self, messages, **kwargs):
            # 1. Inject /no_think + English instruction
            messages = inject_no_think(messages)
            # 2. Merge consecutive same-role messages
            messages = merge_consecutive_messages(messages)
            # 3. Call original
            result = original_chat(self, messages, **kwargs)
            # 4. Strip any remaining think tags (belt + suspenders)
            if isinstance(result, str):
                result = strip_think_tags(result)
            return result

        LLMClient.chat = patched_chat
        logger.info("LLMClient patched: /no_think + English + merge + strip")
    except ImportError:
        logger.warning("Could not patch LLMClient — app.utils.llm_client not found")
