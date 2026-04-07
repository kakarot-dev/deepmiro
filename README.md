<div align="center">

<img src="./static/image/deepmiro-lockup.png" alt="DeepMiro Engine" width="420"/>

<br/>

**A swarm intelligence engine that rehearses the future.**

Feed it a document. Describe a scenario. Watch thousands of AI agents with distinct personalities, memories, and social instincts interact — and return with a prediction.

[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](./LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](#-docker-deployment)
[![Website](https://img.shields.io/badge/deepmiro.org-live-22d3ee?style=flat-square)](https://deepmiro.org)

</div>

---

## 🧠 What It Does

DeepMiro extracts entities and relationships from any document — a policy draft, a market report, a chapter of a novel — and constructs a parallel digital world. Inside it, hundreds of autonomous agents form opinions, argue on simulated social platforms, shift allegiances, and produce emergent behavior that no single prompt could predict.

You get back a structured prediction report and a living world you can interrogate, agent by agent.

> **Input:** A PDF and a question in plain language.
> **Output:** A detailed prediction report + an interactive simulation you can explore.

## ⚙️ How It Works

```
Document ──► Entity Extraction ──► Agent Generation ──► Dual-Platform Simulation ──► Prediction Report
              (NER + GraphRAG)    (personas, memory,     (Twitter-like + Reddit-like     (ReportAgent with
                                   social networks)       parallel interaction)            deep analysis tools)
```

Five phases, fully automated:

| Phase | What happens |
|-------|-------------|
| 🔗 **Graph Build** | Extracts entities, relationships, and context from your documents. Builds a knowledge graph via GraphRAG. |
| 🧬 **Environment Setup** | Generates agent personas with distinct personalities, beliefs, and social connections. Configures behavioral parameters. |
| 🌐 **Simulation** | Agents interact across dual platforms (Twitter-like and Reddit-like) in parallel. Dynamic memory updates each round. |
| 📊 **Report Generation** | A ReportAgent analyzes the post-simulation environment — sentiment shifts, faction formation, viral dynamics, outcome trajectories. |
| 💬 **Deep Interaction** | Chat with any agent to understand their reasoning. Query the ReportAgent for follow-up analysis. |

## 🔑 Key Capabilities

- 📄 **Document-seeded worlds** — upload PDFs, reports, articles. The engine extracts reality seeds and builds a simulation around them.
- 🤖 **Autonomous agents** — each agent has a unique persona, long-term memory, and behavioral logic. They aren't scripted — they emerge.
- 🔀 **Dual-platform dynamics** — agents interact on both a Twitter-like and Reddit-like platform simultaneously, producing richer social dynamics.
- 👁️ **God's-eye control** — inject variables mid-simulation, adjust scenarios, test counterfactuals.
- 📈 **Structured reports** — the ReportAgent produces analysis with sentiment breakdowns, key faction identification, and outcome probabilities.
- 🎙️ **Agent interrogation** — after simulation, interview any agent to understand their beliefs and decision process.

## 🔥 What's Different

DeepMiro is a performance-focused fork of the original [MiroFish](https://github.com/666ghj/MiroFish) engine. Same OASIS simulation core, rebuilt infrastructure:

| Component | MiroFish (original) | DeepMiro |
|-----------|-------------------|----------|
| **Recommendation engine** | Full LLM call every round (~200s/round) | Cached [TWHIN-BERT](https://huggingface.co/Twitter/twhin-bert-base) embeddings (~15ms/round) |
| **Entity extraction** | Sequential NER processing | 5-worker parallel NER via ThreadPoolExecutor |
| **Graph build time** | ~5 minutes | ~56 seconds |
| **Graph database** | Zep Cloud (proprietary, external dependency) | SurrealDB (self-hosted, open-source) |
| **Vector search** | Cloud-dependent | Hybrid HNSW + BM25 (local, 768-dim cosine) |
| **Embedding model** | Tied to Zep | `nomic-embed-text-v1.5` via Fireworks (swappable) |
| **Document ingestion** | Manual text input | Upload endpoint with magic-byte validation + PyMuPDF sanitization (PDF, MD, TXT) |
| **Database concurrency** | Standard SQLite | WAL mode for concurrent reads during simulation |
| **LLM provider** | Alibaba Qwen (hardcoded) | Any OpenAI-compatible API (configurable) |
| **Deployment** | Docker only | Docker + Helm chart + k3s-ready |

### ⚡ Benchmarks

15-agent quick simulation, enriched prompt, measured end-to-end:

| Stage | Time |
|-------|------|
| Graph build | ~10s |
| Agent generation | ~3 min |
| Simulation (110 Twitter + 26 Reddit actions) | ~4 min |
| **Total pipeline** | **~7 min (quick) / ~12 min (standard, 80 agents)** |

The biggest win is the recommendation system: TWHIN-BERT embeddings are computed once per user at setup, then only new posts are embedded incrementally each round. Cosine similarity via numpy replaces what was previously a full LLM inference call — **13,000x faster per round**.

## 🚀 Quick Start

### Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| 🐍 **Python** | 3.11 – 3.12 | `python --version` |
| 📦 **Node.js** | 18+ | `node -v` |
| ⚙️ **uv** | Latest | `uv --version` |

### 1. Configure

```bash
cp .env.example .env
```

Required environment variables:

```env
# LLM — any OpenAI-compatible API
LLM_API_KEY=your_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o

# Database
SURREALDB_URL=ws://localhost:8000/rpc
SURREALDB_USER=root
SURREALDB_PASS=root
```

### 2. Install

```bash
npm run setup:all
```

Or step by step:

```bash
npm run setup:backend   # Python dependencies (auto-creates venv)
```

### 3. Run

```bash
npm run dev
```

| Service | URL |
|---------|-----|
| 🔌 Backend API | `http://localhost:5001` |

> **Web UI:** A new dashboard is coming soon. For now, interact via the [DeepMiro MCP plugin](https://github.com/kakarot-dev/deepmiro) for Claude Code, or use the REST API directly.

### 🐳 Docker Deployment

```bash
cp .env.example .env    # configure your keys
docker compose up -d
```

## 🏗️ Architecture

```
deepmiro-engine/
├── backend/                 # Python Flask API
│   ├── app/
│   │   ├── api/            # REST endpoints (simulation, graph, documents, report)
│   │   ├── services/       # Core logic (graph builder, simulation runner, report agent)
│   │   ├── storage/        # SurrealDB adapter, embedding service, NER
│   │   └── utils/          # LLM client, retry logic, logging
│   └── pyproject.toml
├── (frontend — coming soon)
├── locales/                 # i18n (en, zh)
├── docker-compose.yml
└── Dockerfile
```

## 💡 Use Cases

| Domain | Example |
|--------|---------|
| 📉 **Market analysis** | Upload an earnings report. Ask: *"How will retail investors react to this guidance revision?"* |
| 🏛️ **Policy testing** | Upload a draft regulation. Ask: *"What public backlash should we expect, and from which demographics?"* |
| 📣 **PR & comms** | Upload a press release. Ask: *"How will this announcement play on social media over 48 hours?"* |
| 🏁 **Competitive analysis** | Upload competitor product specs. Ask: *"How will our user base respond to this feature gap?"* |
| 📖 **Creative exploration** | Upload a novel's first 80 chapters. Ask: *"What ending would emerge from these character dynamics?"* |
| 🚨 **Crisis simulation** | Upload an incident report. Ask: *"How does public opinion evolve if we respond with X vs Y?"* |

## 🙏 Acknowledgments

DeepMiro Engine is a fork of [MiroFish](https://github.com/666ghj/MiroFish), originally created by Guo Hangjiang and supported by Shanda Group. The simulation layer is powered by [OASIS](https://github.com/camel-ai/oasis) from the CAMEL-AI team.

## 📄 License

[AGPL-3.0](./LICENSE)

---

<div align="center">

**[deepmiro.org](https://deepmiro.org)** · Built by [Joel Libni](https://github.com/kakarot-dev)

</div>
