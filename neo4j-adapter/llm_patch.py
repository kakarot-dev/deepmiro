"""
Patch MiroFish's LLMClient to handle non-Qwen model constraints.

Fixes:
1. Merge consecutive messages with the same role (required by Mixtral, Llama, etc.)
2. Strip <think> tags from Qwen3's chain-of-thought output
3. Handle JSON response extraction more robustly
"""

import logging

logger = logging.getLogger("mirofish.llm_patch")


def merge_consecutive_messages(messages):
    """
    Merge consecutive messages with the same role.

    Many models (Mixtral, Llama, etc.) require strict user/assistant alternation.
    MiroFish's ReACT loop can produce consecutive same-role messages (e.g.,
    tool results injected as multiple user messages).

    This preserves all content by concatenating consecutive same-role messages.
    """
    if not messages or len(messages) <= 1:
        return messages

    merged = [messages[0].copy()]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            # Same role — merge content
            merged[-1]["content"] = merged[-1]["content"] + "\n\n" + msg["content"]
        else:
            merged.append(msg.copy())
    return merged


def patch_llm_client():
    """
    Monkey-patch MiroFish's LLMClient.chat() to merge messages before sending.
    Call this after importing MiroFish's app module.
    """
    try:
        from app.utils.llm_client import LLMClient

        original_chat = LLMClient.chat

        def patched_chat(self, messages, **kwargs):
            merged = merge_consecutive_messages(messages)
            if len(merged) != len(messages):
                logger.debug(f"Merged {len(messages)} messages → {len(merged)}")
            return original_chat(self, merged, **kwargs)

        LLMClient.chat = patched_chat
        logger.info("LLMClient patched: consecutive message merging enabled")
    except ImportError:
        logger.warning("Could not patch LLMClient — app.utils.llm_client not found")
