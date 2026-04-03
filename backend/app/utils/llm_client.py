"""
LLM Client with pluggable model guards, English enforcement,
boost model routing, and consecutive message merging.
"""

import inspect
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

from openai import OpenAI

from ..config import Config

logger = logging.getLogger("mirofish.llm_client")


# ---------------------------------------------------------------------------
# Model Guard System
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


class Qwen3Guard(ModelGuard):
    """
    Qwen3 has a 'thinking' mode that outputs <think>...</think> blocks.
    /no_think in the system prompt disables this.
    """
    def match(self, model_name: str) -> bool:
        return "qwen3" in model_name.lower() or "qwen-3" in model_name.lower()

    def preprocess_messages(self, messages):
        messages = _inject_into_system(messages, "/no_think")
        return messages

    def postprocess_response(self, content):
        return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()


class MixtralGuard(ModelGuard):
    """Mixtral requires strict user/assistant message alternation."""
    def match(self, model_name: str) -> bool:
        return "mixtral" in model_name.lower()

    def preprocess_messages(self, messages):
        return _merge_consecutive_roles(messages)


class LlamaGuard(ModelGuard):
    """Llama models have weak Chinese support."""
    def match(self, model_name: str) -> bool:
        return "llama" in model_name.lower()

    def preprocess_messages(self, messages):
        return _merge_consecutive_roles(messages)


class MiniMaxGuard(ModelGuard):
    """MiniMax M2.5 — generally well-behaved, merge roles for safety."""
    def match(self, model_name: str) -> bool:
        return "minimax" in model_name.lower()

    def preprocess_messages(self, messages):
        return _merge_consecutive_roles(messages)


class DeepSeekGuard(ModelGuard):
    """DeepSeek models may also use thinking tags."""
    def match(self, model_name: str) -> bool:
        return "deepseek" in model_name.lower()

    def postprocess_response(self, content):
        return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()


class DefaultGuard(ModelGuard):
    """Fallback: merge roles + strip think tags (safe defaults)."""
    def match(self, model_name: str) -> bool:
        return True

    def preprocess_messages(self, messages):
        return _merge_consecutive_roles(messages)

    def postprocess_response(self, content):
        return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()


# Guard registry — order matters, first match wins
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


def _ensure_english(messages: List[Dict]) -> List[Dict]:
    """Enforce English in system prompt AND last user message."""
    if not messages:
        return [{"role": "system", "content": ENGLISH_INSTRUCTION}]

    result = []
    patched_system = False
    for msg in messages:
        msg = msg.copy()
        if msg["role"] == "system" and not patched_system:
            if "English only" not in msg["content"] and "english only" not in msg["content"]:
                msg["content"] = msg["content"].rstrip() + f"\n{ENGLISH_INSTRUCTION}"
            patched_system = True
        result.append(msg)

    if not patched_system:
        result.insert(0, {"role": "system", "content": ENGLISH_INSTRUCTION})

    # Also append to the last user message — strongest signal before generation
    for i in range(len(result) - 1, -1, -1):
        if result[i]["role"] == "user":
            content = result[i]["content"]
            if "English only" not in content:
                result[i] = result[i].copy()
                result[i]["content"] = content.rstrip() + "\n\n[IMPORTANT: Write your entire response in English only.]"
            break

    return result


# ---------------------------------------------------------------------------
# Boost model routing
# ---------------------------------------------------------------------------

# Modules that should use the boost model
BOOST_MODULES = {
    "app.services.report_agent",
    "app.services.oasis_profile_generator",
}

# Lazy-initialized boost client
_boost_client: Optional[OpenAI] = None
_boost_model: str = ""
_boost_initialized = False


def _get_boost_config():
    """Get or initialize boost model configuration."""
    global _boost_client, _boost_model, _boost_initialized
    if _boost_initialized:
        return _boost_client, _boost_model

    _boost_initialized = True
    boost_api_key = Config.LLM_BOOST_API_KEY
    boost_model = Config.LLM_BOOST_MODEL_NAME

    if not boost_api_key or not boost_model:
        logger.debug("No boost LLM configured")
        return None, ""

    boost_base_url = Config.LLM_BOOST_BASE_URL or Config.LLM_BASE_URL
    _boost_client = OpenAI(api_key=boost_api_key, base_url=boost_base_url)
    _boost_model = boost_model
    logger.info(f"Boost LLM configured: model={boost_model}")
    return _boost_client, _boost_model


def _should_use_boost() -> bool:
    """Check caller stack to see if we should use the boost model."""
    for frame_info in inspect.stack()[2:8]:  # skip _should_use_boost and chat()
        caller_module = frame_info.frame.f_globals.get("__name__", "")
        if any(caller_module.startswith(m) for m in BOOST_MODULES):
            return True
    return False


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class LLMClient:
    """LLM Client with model guards, English enforcement, and boost routing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY not configured")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        Send a chat request with model guards, English enforcement,
        consecutive message merging, and optional boost routing.

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Maximum tokens
            response_format: Response format (e.g. JSON mode)

        Returns:
            Model response text
        """
        # Determine which model/client to use
        active_model = self.model
        active_client = self.client

        boost_client, boost_model = _get_boost_config()
        if boost_client and _should_use_boost():
            active_model = boost_model
            active_client = boost_client
            logger.debug(f"Using boost model: {boost_model}")

        # Get the appropriate guard for the active model
        guard = get_guard(active_model)

        # 1. Enforce English (system + last user message)
        messages = _ensure_english(messages)
        # 2. Model-specific preprocessing
        messages = guard.preprocess_messages(messages)
        # 3. Merge consecutive roles (all models benefit from this)
        messages = _merge_consecutive_roles(messages)

        kwargs = {
            "model": active_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = active_client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content

        # 4. Model-specific postprocessing
        if isinstance(content, str):
            content = guard.postprocess_response(content)

        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Send a chat request and return parsed JSON.

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Maximum tokens

        Returns:
            Parsed JSON object
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # Clean markdown code block markers
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM returned invalid JSON: {cleaned_response}")
