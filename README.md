<div align="center">

<img src="./static/image/deepmiro-lockup.png" alt="DeepMiro" width="420"/>

<br/>

**A swarm intelligence engine that rehearses the future.**

Feed it a document. Describe a scenario. Watch hundreds of AI agents with distinct personalities, memories, and social instincts interact — and return with a prediction.

[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](./LICENSE)
[![npm](https://img.shields.io/npm/v/deepmiro-mcp?style=flat-square&label=npm&color=22d3ee)](https://www.npmjs.com/package/deepmiro-mcp)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](#rehearse-the-future-in-60-seconds)
[![Website](https://img.shields.io/badge/deepmiro.org-live-22d3ee?style=flat-square)](https://deepmiro.org)

<br/>

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/98AO1I?referralCode=pYCUQd&utm_medium=integration&utm_source=template&utm_campaign=generic)

<sub>One-click self-host — four services, one API key, ~60 seconds. <a href="#rehearse-the-future-in-60-seconds">Full walkthrough ↓</a></sub>

</div>

---

## Contents

- [What It Does](#what-it-does)
- [How It Works](#how-it-works)
- [Quick Start](#quick-start) — get an API key, install in 2 min
- [Self-Host (Docker / Railway)](#rehearse-the-future-in-60-seconds)
- [MCP Server](#mcp-server) — tools available
- [What's Different](#whats-different) — vs the original MiroFish
- [Persona Fidelity](#persona-fidelity-how-deepmiro-keeps-agents-in-character) — the drift problem and how we fix it
- [Monorepo Structure](#monorepo-structure)
- [Use Cases](#use-cases)
- [Acknowledgments](#acknowledgments)
- [License](#license)

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

### 1. Get an API key

Sign up at [deepmiro.org](https://deepmiro.org) → Dashboard → API Keys. Your key looks like `dm_xxxxxxxxx`.

### 2. Install

Pick the install path for your client. **Don't install the `.mcpb` desktop extension if you're using Claude Code or Claude Cowork** — those need the plugin to get the `/predict` skill, background polling, and live narration.

#### Claude Desktop → use `.mcpb`

1. Download `deepmiro.mcpb` from the [latest release](https://github.com/kakarot-dev/deepmiro/releases/latest)
2. Claude Desktop → Settings → Extensions → Advanced settings → Install Extension → pick the file
3. Paste your API key when prompted

#### Claude Code & Claude Cowork → use the plugin

The plugin ships the `/predict` skill — the MCP alone is missing the orchestration logic (background polling via cron, live agent narration, the setup wizard).

```bash
claude plugin marketplace add kakarot-dev/deepmiro
claude plugin install deepmiro@deepmiro-marketplace
export DEEPMIRO_API_KEY=dm_your_key   # or set in ~/.claude/settings.json
```

Restart Claude Code, then say `/predict` or `predict how people will react to [scenario]`.

#### Everywhere else → npm package

Generic MCP install for clients that aren't Claude Desktop, Claude Code, or Claude Cowork:

| Client | Install |
|--------|---------|
| **OpenAI Codex** | `codex plugin install kakarot-dev/deepmiro` |
| **ChatGPT Desktop** | Settings → MCP Servers → Add → `npx deepmiro-mcp` with env `DEEPMIRO_API_KEY` |
| **Cursor / Windsurf** | Settings → MCP → Add → `npx deepmiro-mcp` with env `DEEPMIRO_API_KEY` |
| **VS Code (Copilot)** | Add to `.vscode/mcp.json`: `"deepmiro": {"command": "npx", "args": ["-y", "deepmiro-mcp"], "env": {"DEEPMIRO_API_KEY": "dm_xxx"}}` |

## Rehearse the Future in 60 Seconds

Four services, one compose file, one API key.

<br/>

### What gets deployed

| Service | Role |
|---|---|
| **backend** | Flask engine that runs the OASIS multi-agent simulations |
| **mcp** | Public entry point for AI tools (Claude, Cursor, VS Code) |
| **twhin-sidecar** | Shared TWHIN-BERT embedding service (loads once per pod) |
| **surrealdb** | Graph + vector + document store for agents and reports |

<br/>

### What you need

- A **Fireworks AI** key ([fireworks.ai](https://fireworks.ai), ~$5 free credit) — covers primary LLM, boost, and embeddings in one key. Any OpenAI-compatible API also works.
- `openssl rand -hex 32` for your SurrealDB root password.
- ~$5–10/month of Railway credit if you're using the template.

<br/>

### Option A — Railway one-click

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/98AO1I?referralCode=pYCUQd&utm_medium=integration&utm_source=template&utm_campaign=generic)

Railway reads `docker-compose.yml` from the repo root and prompts for `LLM_API_KEY` + `SURREAL_PASSWORD`. The MCP service gets a public `*.up.railway.app` URL — hand that to your AI tools.

> **Note — LLM provider on Railway.** The template ships with **Fireworks** as the default (primary: `minimax-m2p5`, boost: `gpt-oss-120b`, embeddings: `nomic-embed-text-v1.5` — one key covers all three). Any OpenAI-compatible API works — to swap to OpenAI, Together, Groq, Ollama, vLLM, or anything else, change `LLM_BASE_URL` and `LLM_MODEL_NAME` on the backend service's Variables tab after deploy. Same for `LLM_BOOST_*` if you want a separate reasoning model, and `EMBEDDING_*` if you want a different embedding provider.

<br/>

### Option B — Docker (self-hosted)

```bash
git clone https://github.com/kakarot-dev/deepmiro.git
cd deepmiro && cp .env.example .env
```

Edit `.env` — two required variables:

```bash
LLM_API_KEY=your-fireworks-or-openai-key
SURREAL_PASS=$(openssl rand -hex 32)
```

Start everything:

```bash
docker compose up -d
```

This pulls pre-built images from GHCR and starts four services:

| Service | Port | Description |
|---|---|---|
| `mcp` | 3001 (public) | MCP server — the only exposed port |
| `backend` | 5001 (internal) | Flask simulation engine |
| `surrealdb` | 8000 (internal) | Graph + vector store |
| `twhin-sidecar` | 7001 (internal) | Shared TWHIN-BERT embeddings |

First startup takes ~2 minutes (TWHIN-BERT model warm-up). Check readiness:

```bash
docker compose logs -f twhin-sidecar   # wait for "TWHIN-BERT ready"
docker compose logs backend            # wait for "MiroFish Backend 启动完成"
```

To build from source instead of pulling images:

```bash
docker compose -f docker-compose.yml \
  --build \
  -f docker/Dockerfile.backend \
  up -d
```

Or uncomment the `build:` blocks in `docker-compose.yml` and comment out the `image:` lines.

MCP lives on `http://localhost:3001`. Backend and SurrealDB stay internal to the compose network unless you explicitly publish them (see `docker-compose.yml` comments for how).

<br/>

### Wire it into Claude Desktop

Add DeepMiro to your Claude Desktop config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

For a local Docker deployment:

```json
{
  "mcpServers": {
    "deepmiro": { "url": "http://localhost:3001/mcp" }
  }
}
```

For Railway or any public deployment:

```json
{
  "mcpServers": {
    "deepmiro": { "url": "https://your-app.up.railway.app/mcp" }
  }
}
```

Restart Claude Desktop after editing. Then ask: *"Use DeepMiro to simulate how 100 senior engineers would react to a return-to-office mandate"* — and paste the memo.

<br/>

### What it costs

- **Railway:** ~$5–10/month (four services, ~4 GB resident)
- **LLM:** ~$0.10–0.20 per quick-preset simulation on Fireworks
- **TWHIN-BERT:** zero — runs locally in the sidecar

<br/>

### Security

MCP ships with no auth by default — set `MCP_API_KEY` in `.env` before exposing it to the internet. The backend REST API is internal-only out of the box.

> **Skip the deploy entirely?** Use the hosted version at **[deepmiro.org](https://deepmiro.org)** — same engine, same models, no Docker.

## MCP Server

DeepMiro is an [MCP](https://modelcontextprotocol.io) server. MCP is the universal standard adopted by Claude, ChatGPT, Gemini, Cursor, VS Code, and every major AI client — one server, works everywhere.

```bash
npx deepmiro-mcp
```

Available tools: `create_simulation`, `simulation_status`, `get_report`, `interview_agent`, `upload_document`, `list_simulations`, `search_simulations`, `simulation_data`, `cancel_simulation`.

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

## Persona Fidelity: How DeepMiro Keeps Agents In Character

Multi-agent LLM simulations have a dirty secret: **personas drift**. By round 20, Tucker Carlson starts quoting the ACLU. By round 45, Marco Rubio sounds like Bernie Sanders. Every distinct voice collapses into the same bland "helpful assistant" register.

This isn't a prompting problem — it's an attention decay problem. [Kim et al. (COLM 2024)](https://arxiv.org/abs/2402.10962) proved that LLM attention to system-prompt tokens decays geometrically over turns. LLaMA2-70B drifts significantly within **8 turns**. Larger models drift more, not less. A 2KB persona cannot compete with 50KB of accumulated conversation history.

Every naive multi-agent simulation hits this wall. DeepMiro doesn't, because we copied what [Stanford's Generative Agents (Park et al. 2023)](https://arxiv.org/abs/2304.03442) did for their 25-agent Smallville simulation — with some practical shortcuts.

### What we do

**1. Structured personas with explicit negative examples.**
Every agent gets a structured profile alongside the prose bio:
- `ideology_anchor` — a 2-5 word partisan tag ("conservative populist", "progressive labor")
- `core_beliefs` — 3-5 first-person declarative statements, no hedging
- `verbal_tics` — 3-5 literal phrases the person actually uses
- `never_say` — 3-5 sentences the person would refuse to utter
- `speaking_style` — register + rhetorical habits

The `never_say` block is the drift killer. Models drift toward the centroid of what they say. Explicit negative examples (*"Tucker Carlson would never say 'I stand with the ACLU'"*) anchor the LLM against that collapse.

**2. Dynamic persona regeneration per round.**
Instead of locking the persona in at the system-prompt level and watching attention decay from round 1, we rebuild `system_message.content` before every agent acts. Each round, the agent sees a fresh **third-person** character brief:

```
# Character Brief: Tucker Carlson

The agent in this conversation is Tucker Carlson.
You are simulating how Tucker Carlson would respond.

## What Tucker Carlson Would NEVER Say
- "I stand with the ACLU"
- "We need to find common ground with progressives"
...

## What Tucker Carlson Has Said Recently
- "Permanent Washington wants you to believe..."
- "Let's pause for a moment — they're not even hiding it"
...

## Task
What would Tucker Carlson actually do? React in his authentic voice.
Do not become a neutral assistant. Do not seek balance.
```

The persona never gets stale because it's built fresh from the same structured fields every turn.

**3. Third-person framing.**
"You are Tucker Carlson" triggers RLHF helpful-assistant sycophancy — the model tries to be polite and balanced because that's how it was trained to respond to "you are X" instructions. Third-person framing ("the agent is Tucker Carlson", "what would Tucker Carlson do?") bypasses that trigger entirely. This single change is load-bearing.

**4. Self-consistency anchor.**
Each round injects the agent's **own** 3 most recent posts as reference material. Tucker Carlson sees what he just said, which makes him more likely to say something consistent with it. This is cheap drift resistance — no extra LLM calls, just reading from the action log.

**5. No accumulated chat history.**
Unlike naive multi-agent setups, DeepMiro does NOT feed each agent the rolling conversation history from previous rounds. Agents get their fresh persona + the current feed observations. Attention stays focused on character + present context, not on 50KB of stale noise.

### What we don't do

- **We don't script reactions.** Agents aren't told "mock liberal content" or "support conservative content" — that would script the outcome and destroy the simulation's predictive value. The emergent behavior is the whole point.
- **We don't filter feeds by ideology.** Tucker Carlson sees AOC's posts. That's how he has something to push back against. Echo chambers are not simulations.
- **We don't fork OASIS.** The entire fix is a runtime wrapper around CAMEL's agent pager. No upstream drift, no fork maintenance.

### Research foundations

| Technique | Source |
|---|---|
| Attention decay over system prompts | [Kim et al. — Measuring and Controlling Persona Drift (COLM 2024)](https://arxiv.org/abs/2402.10962) |
| Third-person framing bypasses RLHF sycophancy | [Park et al. — Generative Agents (Stanford 2023)](https://arxiv.org/abs/2304.03442) |
| Negative examples > positive instruction | [Examining Identity Drift in LLM Agents (arXiv 2412.00804)](https://arxiv.org/abs/2412.00804) |
| Dynamic persona summary per action | [Park et al. — Generative Agents (Stanford 2023)](https://arxiv.org/abs/2304.03442) |
| JSON personas collapse to neutral register | [Persona-Aware Contrastive Learning (ACL 2025)](https://aclanthology.org/2025.findings-acl.1344.pdf) |

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
