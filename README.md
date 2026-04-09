<div align="center">

<img src="./static/image/deepmiro-lockup.png" alt="DeepMiro" width="420"/>

<br/>

**A swarm intelligence engine that rehearses the future.**

Feed it a document. Describe a scenario. Watch hundreds of AI agents with distinct personalities, memories, and social instincts interact — and return with a prediction.

[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](./LICENSE)
[![npm](https://img.shields.io/npm/v/deepmiro-mcp?style=flat-square&label=npm&color=22d3ee)](https://www.npmjs.com/package/deepmiro-mcp)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](#self-host)
[![Website](https://img.shields.io/badge/deepmiro.org-live-22d3ee?style=flat-square)](https://deepmiro.org)

</div>

---

## What It Does

DeepMiro extracts entities and relationships from any document — a policy draft, a market report, a chapter of a novel — and constructs a parallel digital world. Inside it, hundreds of autonomous agents form opinions, argue on simulated social platforms, shift allegiances, and produce emergent behavior that no single prompt could predict.

You get back a structured prediction report and a living world you can interrogate, agent by agent.

> **Input:** A PDF and a question in plain language.
> **Output:** A detailed prediction report + an interactive simulation you can explore.

## How It Works

```
Document ──► Entity Extraction ──► Agent Generation ──► Dual-Platform Simulation ──► Prediction Report
              (NER + GraphRAG)    (personas, memory,     (Twitter-like + Reddit-like     (ReportAgent with
                                   social networks)       parallel interaction)            deep analysis tools)
```

| Phase | What happens |
|-------|-------------|
| **Graph Build** | Extracts entities, relationships, and context from your documents. Builds a knowledge graph via GraphRAG. |
| **Environment Setup** | Generates agent personas with distinct personalities, beliefs, and social connections. |
| **Simulation** | Agents interact across dual platforms (Twitter-like and Reddit-like) in parallel. Dynamic memory updates each round. |
| **Report Generation** | A ReportAgent analyzes the post-simulation environment — sentiment shifts, faction formation, viral dynamics, outcome trajectories. |
| **Deep Interaction** | Chat with any agent to understand their reasoning. Query the ReportAgent for follow-up analysis. |

## Quick Start

### Hosted (recommended)

Get a free API key at [deepmiro.org](https://deepmiro.org), then connect from any AI client:

| Client | Install |
|--------|---------|
| **Claude Code** | `claude mcp add deepmiro -e DEEPMIRO_API_KEY=dm_xxx -- npx -y deepmiro-mcp` |
| **OpenAI Codex** | `codex plugin install kakarot-dev/deepmiro` |
| **Claude Desktop** | Add to `claude_desktop_config.json`: `"deepmiro": {"command": "npx", "args": ["-y", "deepmiro-mcp"], "env": {"DEEPMIRO_API_KEY": "dm_xxx"}}` |
| **ChatGPT Desktop** | Settings → MCP Servers → Add → `npx deepmiro-mcp` with env `DEEPMIRO_API_KEY` |
| **Cursor / Windsurf** | Settings → MCP → Add → `npx deepmiro-mcp` with env `DEEPMIRO_API_KEY` |
| **VS Code (Copilot)** | Add to `.vscode/mcp.json`: `"deepmiro": {"command": "npx", "args": ["-y", "deepmiro-mcp"], "env": {"DEEPMIRO_API_KEY": "dm_xxx"}}` |

Or just say "predict" in Claude Code or Codex — the built-in skill will walk you through setup.

### Self-host

No API key needed. Run the engine locally and point the MCP server at it:

```bash
git clone https://github.com/kakarot-dev/deepmiro.git
cd deepmiro
cp .env.example .env    # add your LLM API key
docker compose -f docker/docker-compose.yml up -d

# Connect your AI client to the local engine
claude mcp add deepmiro -e MIROFISH_URL=http://localhost:5001 -- npx -y deepmiro-mcp
```

```env
# Required in .env
LLM_API_KEY=your_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini

SURREALDB_URL=ws://localhost:8000/rpc
SURREALDB_USER=root
SURREALDB_PASS=root
```

## MCP Server

DeepMiro is an [MCP](https://modelcontextprotocol.io) server. MCP is the universal standard adopted by Claude, ChatGPT, Gemini, Cursor, VS Code, and every major AI client — one server, works everywhere.

```bash
npx deepmiro-mcp
```

Available tools: `create_simulation`, `quick_predict`, `simulation_status`, `get_report`, `interview_agent`, `upload_document`, `list_simulations`, `search_simulations`.

## What's Different

DeepMiro is a performance-focused fork of the original [MiroFish](https://github.com/666ghj/MiroFish) engine. Same OASIS simulation core, rebuilt infrastructure:

| Component | MiroFish (original) | DeepMiro |
|-----------|-------------------|----------|
| **Recommendation engine** | Full LLM call every round (~200s/round) | Cached [TWHIN-BERT](https://huggingface.co/Twitter/twhin-bert-base) embeddings (~15ms/round) |
| **Entity extraction** | Sequential NER | 5-worker parallel NER via ThreadPoolExecutor |
| **Graph build time** | ~5 minutes | ~56 seconds |
| **Graph database** | Zep Cloud (proprietary) | SurrealDB (self-hosted, open-source) |
| **Vector search** | Cloud-dependent | Hybrid HNSW + BM25 (local, 768-dim cosine) |
| **Embedding model** | Tied to Zep | `nomic-embed-text-v1.5` via Fireworks (swappable) |
| **Document ingestion** | Manual text input | Upload endpoint with magic-byte validation (PDF, MD, TXT) |
| **LLM provider** | Alibaba Qwen (hardcoded) | Any OpenAI-compatible API |
| **Deployment** | Docker only | Docker + Helm chart + k3s-ready |

### Benchmarks

15-agent quick simulation, enriched prompt, measured end-to-end:

| Stage | Time |
|-------|------|
| Graph build | ~10s |
| Agent generation | ~3 min |
| Simulation (110 Twitter + 26 Reddit actions) | ~4 min |
| **Total pipeline** | **~7 min (quick) / ~12 min (standard, 80 agents)** |

The biggest win is the recommendation system: TWHIN-BERT embeddings are computed once per user at setup, then only new posts are embedded incrementally each round. Cosine similarity via numpy replaces what was previously a full LLM inference call — **13,000x faster per round**.

## Monorepo Structure

```
deepmiro/
├── engine/              # Python Flask simulation backend
│   ├── app/
│   │   ├── api/         # REST endpoints (simulation, graph, documents, report)
│   │   ├── services/    # Graph builder, simulation runner, report agent
│   │   ├── storage/     # SurrealDB adapter, embedding service, NER
│   │   └── utils/       # LLM client, retry logic, logging
│   └── pyproject.toml
├── mcp-server/          # TypeScript MCP server (npm: deepmiro-mcp)
│   └── src/
├── .claude-plugin/      # Claude Code plugin + marketplace manifests
├── .codex-plugin/       # OpenAI Codex plugin manifest
├── .agents/             # Codex marketplace catalog
├── .mcp.json            # MCP config (auto-loaded when running `claude` here)
├── skills/predict/      # /predict skill (auto-setup, narration, interviews)
├── helm-chart/          # Kubernetes (k3s) deployment
├── docker/              # Dockerfiles + compose
├── docs/                # Landing page
└── locales/             # i18n (en, zh)
```

## Use Cases

| Domain | Example |
|--------|---------|
| **Market analysis** | Upload an earnings report. *"How will retail investors react to this guidance revision?"* |
| **Policy testing** | Upload a draft regulation. *"What public backlash should we expect, and from which demographics?"* |
| **PR & comms** | Upload a press release. *"How will this announcement play on social media over 48 hours?"* |
| **Competitive analysis** | Upload competitor product specs. *"How will our user base respond to this feature gap?"* |
| **Creative exploration** | Upload a novel's first 80 chapters. *"What ending would emerge from these character dynamics?"* |
| **Crisis simulation** | Upload an incident report. *"How does public opinion evolve if we respond with X vs Y?"* |

## Acknowledgments

DeepMiro is a fork of [MiroFish](https://github.com/666ghj/MiroFish), originally created by Guo Hangjiang and supported by Shanda Group. The simulation layer is powered by [OASIS](https://github.com/camel-ai/oasis) from the CAMEL-AI team.

## License

[AGPL-3.0](./LICENSE)

---

<div align="center">

**[deepmiro.org](https://deepmiro.org)** · Built by [Joel Libni](https://github.com/kakarot-dev)

</div>
