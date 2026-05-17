"""Configuration management — loads from project-root .env, validates at startup."""

import os
import secrets
from dotenv import load_dotenv


# Load project-root .env (relative to engine/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')
if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # Production: fall back to ambient environment (no .env file)
    load_dotenv(override=True)


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


class Config:
    """Flask configuration. Critical values are validated by Config.validate()
    at app startup — see engine/app/__init__.py."""

    # --- Flask ---
    # SECRET_KEY: must be set in production. We generate a fresh random value
    # if unset so local dev doesn't crash, but Config.validate() warns when
    # the generated value is used (sessions don't survive restarts).
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    _SECRET_KEY_FROM_ENV = bool(os.environ.get('SECRET_KEY'))

    # DEBUG defaults to False. Override with FLASK_DEBUG=true for local dev.
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # Disable ASCII escaping so non-Latin characters render natively in responses.
    JSON_AS_ASCII = False

    # --- LLM (OpenAI-compatible) ---
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.fireworks.ai/inference/v1')
    LLM_MODEL_NAME = os.environ.get(
        'LLM_MODEL_NAME',
        'accounts/fireworks/models/minimax-m2p5',
    )

    # Boost LLM (high-quality model for report + persona generation).
    # Each boost var falls back to the corresponding primary LLM var
    # when unset — so users on a single-provider setup (e.g. one
    # Fireworks key for everything) don't have to duplicate values.
    LLM_BOOST_API_KEY = (
        os.environ.get('LLM_BOOST_API_KEY')
        or os.environ.get('LLM_API_KEY', '')
    )
    LLM_BOOST_BASE_URL = (
        os.environ.get('LLM_BOOST_BASE_URL')
        or os.environ.get('LLM_BASE_URL', '')
    )
    LLM_BOOST_MODEL_NAME = (
        os.environ.get('LLM_BOOST_MODEL_NAME')
        or os.environ.get('LLM_MODEL_NAME', '')
    )

    # --- Graph storage backend ---
    # "surrealdb" (default) or "zep" (legacy fallback).
    GRAPH_BACKEND = os.environ.get('GRAPH_BACKEND', 'surrealdb')

    # SurrealDB (used when GRAPH_BACKEND=surrealdb)
    SURREAL_URL = os.environ.get('SURREAL_URL', 'ws://localhost:8000')
    SURREAL_NAMESPACE = os.environ.get('SURREAL_NAMESPACE', 'mirofish')
    SURREAL_DATABASE = os.environ.get('SURREAL_DATABASE', 'production')
    SURREAL_USER = os.environ.get('SURREAL_USER', 'root')
    # SURREAL_PASS is SurrealDB's native env var name (read by the
    # `surreal start` CLI directly). SURREAL_PASSWORD is our legacy
    # name from MiroFish days. Accept either.
    SURREAL_PASSWORD = (
        os.environ.get('SURREAL_PASS')
        or os.environ.get('SURREAL_PASSWORD', '')
    )

    # --- Embeddings (used by SurrealDB backend for vector search) ---
    EMBEDDING_PROVIDER = os.environ.get('EMBEDDING_PROVIDER', 'openai')
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'nomic-ai/nomic-embed-text-v1.5')
    EMBEDDING_BASE_URL = os.environ.get(
        'EMBEDDING_BASE_URL',
        os.environ.get('LLM_BASE_URL', 'https://api.fireworks.ai/inference/v1'),
    )
    EMBEDDING_API_KEY = os.environ.get(
        'EMBEDDING_API_KEY',
        os.environ.get('LLM_API_KEY', ''),
    )
    EMBEDDING_DIMENSIONS = int(os.environ.get('EMBEDDING_DIMENSIONS', '768'))

    # --- File upload ---
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # --- Text processing ---
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    # --- OASIS simulation ---
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__), '../uploads/simulations',
    )

    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST',
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE',
    ]

    # --- Report agent ---
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(
        os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'),
    )
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    # --- Network timeouts (seconds) ---
    LLM_TIMEOUT_SECONDS = int(os.environ.get('LLM_TIMEOUT_SECONDS', '30'))
    SURREAL_TIMEOUT_SECONDS = int(os.environ.get('SURREAL_TIMEOUT_SECONDS', '30'))

    @classmethod
    def validate(cls):
        """Return a list of missing-required-config error messages.

        Callers should fail startup if this returns a non-empty list — see
        engine/app/__init__.py for the enforcement point.
        """
        errors = []

        if not cls.LLM_API_KEY:
            errors.append(
                "LLM_API_KEY is not set. Get a key from your LLM provider "
                "(Fireworks, OpenAI, etc.) and set it in your .env file."
            )

        if cls.GRAPH_BACKEND == 'surrealdb':
            if not cls.SURREAL_URL:
                errors.append(
                    "SURREAL_URL is not set. Point this at the SurrealDB "
                    "service URL (ws://surrealdb:8000 in docker-compose, "
                    "ws://<chart>-surreal:8000 in helm)."
                )
            if not cls.SURREAL_PASSWORD:
                errors.append(
                    "SURREAL_PASSWORD is not set. Generate a strong value "
                    "with `openssl rand -hex 32` and set it in your .env "
                    "file. It must match the password the surrealdb service "
                    "was started with."
                )

        return errors

    @classmethod
    def warnings(cls):
        """Return non-fatal config warnings. Logged at startup."""
        msgs = []
        if not cls._SECRET_KEY_FROM_ENV:
            msgs.append(
                "SECRET_KEY not set — using a randomly generated value. "
                "Sessions will not survive process restarts. Set SECRET_KEY "
                "in production (e.g. `openssl rand -hex 32`)."
            )
        if cls.DEBUG:
            msgs.append(
                "FLASK_DEBUG is enabled — disable for production by unsetting "
                "FLASK_DEBUG or setting it to false."
            )
        return msgs
