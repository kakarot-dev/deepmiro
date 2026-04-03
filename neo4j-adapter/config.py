"""
Configuration for the MiroFish Neo4j adapter.

All settings are read from environment variables. No .env auto-loading —
the caller (MiroFish MCP server) is responsible for setting env vars.
"""

import os


class Config:
    """Configuration loaded from environment variables."""

    # --- Neo4j ---
    NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

    # --- LLM (OpenAI-compatible — works with OpenRouter, Fireworks, etc.) ---
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.fireworks.ai/inference/v1")
    LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "accounts/fireworks/models/llama-v3p1-8b-instruct")

    # --- Embedding ---
    # EMBEDDING_PROVIDER: "openai" (any OpenAI-compatible endpoint, including Fireworks)
    #                     "ollama" (local Ollama /api/embed endpoint)
    EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai")
    EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
    EMBEDDING_BASE_URL = os.environ.get(
        "EMBEDDING_BASE_URL",
        os.environ.get("LLM_BASE_URL", "https://api.fireworks.ai/inference/v1"),
    )
    EMBEDDING_API_KEY = os.environ.get(
        "EMBEDDING_API_KEY",
        os.environ.get("LLM_API_KEY", ""),
    )
    EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "768"))

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of configuration errors (empty = OK)."""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is not set")
        if not cls.NEO4J_URI:
            errors.append("NEO4J_URI is not set")
        if not cls.NEO4J_PASSWORD:
            errors.append("NEO4J_PASSWORD is not set")
        return errors

    @classmethod
    def reload(cls) -> None:
        """Re-read all values from the current environment.

        Useful after the caller has injected env vars at runtime.
        """
        cls.NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        cls.NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
        cls.NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

        cls.LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
        cls.LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.fireworks.ai/inference/v1")
        cls.LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "accounts/fireworks/models/llama-v3p1-8b-instruct")

        cls.EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai")
        cls.EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
        cls.EMBEDDING_BASE_URL = os.environ.get(
            "EMBEDDING_BASE_URL",
            os.environ.get("LLM_BASE_URL", "https://api.fireworks.ai/inference/v1"),
        )
        cls.EMBEDDING_API_KEY = os.environ.get(
            "EMBEDDING_API_KEY",
            os.environ.get("LLM_API_KEY", ""),
        )
        cls.EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "768"))
