# Neo4j Adapter for MiroFish

Drop-in replacement for Zep Cloud in MiroFish's backend.

## Attribution

This storage layer is **ported from [MiroShark](https://github.com/aaronjmars/MiroShark)** by [aaronjmars](https://github.com/aaronjmars), licensed under AGPL-3.0.

The following components originate from MiroShark's `backend/app/storage/` directory:
- `graph_storage.py` — Abstract `GraphStorage` interface
- `neo4j_storage.py` — Neo4j implementation with CRUD, NER ingestion, graph reasoning
- `neo4j_schema.py` — Database constraints, vector indexes, fulltext indexes
- `embedding_service.py` — Pluggable embedding (OpenAI-compatible / Ollama)
- `search_service.py` — Hybrid search (70% vector + 30% BM25)
- `ner_extractor.py` — LLM-based named entity recognition and relation extraction

Modifications from the original:
- Removed MiroShark-specific features (Polymarket, belief tracking, Claude Code subprocess provider)
- Replaced Flask config dependencies with standalone env-var config
- Changed default LLM/embedding provider from Ollama to Fireworks AI (OpenAI-compatible)
- Self-contained package with no parent-relative imports

## What this does

MiroFish uses Zep Cloud for knowledge graph storage. This adapter provides
the same interface using a self-hosted Neo4j instance, eliminating the
external cloud dependency.

## Setup

Set environment variables:
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
LLM_API_KEY=your_fireworks_api_key
LLM_BASE_URL=https://api.fireworks.ai/inference/v1
LLM_MODEL_NAME=accounts/fireworks/models/qwen3-8b
```

## Python Dependencies

```
pip install neo4j>=5.0 openai>=1.0 requests>=2.28
```
