"""
LLM client — OpenAI-compatible chat + JSON extraction.

Works with any OpenAI-compatible provider:
  - Fireworks AI  (default)
  - OpenRouter
  - OpenAI
  - Ollama (local)
  - Any other /v1/chat/completions endpoint
"""

import json
import os
import re
import logging
from typing import Optional, Dict, Any, List

from openai import OpenAI

from .config import Config

logger = logging.getLogger("mirofish.llm_client")


def create_llm_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 300.0,
) -> "LLMClient":
    """Factory: create an LLMClient from explicit args or env-based Config."""
    return LLMClient(api_key=api_key, base_url=base_url, model=model, timeout=timeout)


class LLMClient:
    """LLM client using the OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0,
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError(
                "LLM_API_KEY is not configured. "
                "Set it as an environment variable or pass api_key= explicitly."
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
        )

        # Ollama context window size — prevents prompt truncation on local models.
        self._num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))

    def _is_ollama(self) -> bool:
        """Heuristic: talking to Ollama if the port is 11434."""
        return "11434" in (self.base_url or "")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
    ) -> str:
        """Send a chat completion request, return the assistant's text."""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        # Ollama needs num_ctx via extra_body to avoid prompt truncation.
        if self._is_ollama() and self._num_ctx:
            kwargs["extra_body"] = {"options": {"num_ctx": self._num_ctx}}

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""

        # Strip <think> reasoning blocks that some models include.
        content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """Send a chat request and parse the response as JSON."""
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        # Clean markdown code-block wrappers.
        cleaned = response.strip()
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            raise ValueError(f"LLM returned invalid JSON: {cleaned[:500]}")
