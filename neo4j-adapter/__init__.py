"""
MiroFish Neo4j Adapter

Self-contained graph storage layer backed by Neo4j Community Edition.
Provides: graph CRUD, NER/RE text ingestion, hybrid search (vector + keyword),
and graph reasoning queries.

Supported LLM/embedding providers (OpenAI-compatible):
  - Fireworks AI (default)
  - OpenRouter
  - OpenAI
  - Ollama (local)

Environment variables:
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD    — Neo4j connection
  LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME — LLM for NER extraction
  EMBEDDING_PROVIDER, EMBEDDING_MODEL,
  EMBEDDING_BASE_URL, EMBEDDING_API_KEY,
  EMBEDDING_DIMENSIONS                      — Embedding configuration
"""

from .config import Config
from .graph_storage import GraphStorage
from .neo4j_storage import Neo4jStorage
from .embedding_service import EmbeddingService, EmbeddingError
from .search_service import SearchService
from .ner_extractor import NERExtractor
from .llm_client import LLMClient, create_llm_client

__all__ = [
    "Config",
    "GraphStorage",
    "Neo4jStorage",
    "EmbeddingService",
    "EmbeddingError",
    "SearchService",
    "NERExtractor",
    "LLMClient",
    "create_llm_client",
]
