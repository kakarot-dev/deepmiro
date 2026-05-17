# DeepMiro Benchmarks

This doc records the performance claims made in the README, the
methodology behind them, and the hardware they were measured on. We
keep it honest: where a number is approximate or extrapolated, we say
so. Where a number is reproducible, we link the script that produces
it.

> **Status:** v1.7.0. The full benchmark harness (`benchmarks/`) is
> being rebuilt against the new lifecycle FSM. Until that lands, the
> numbers below are end-to-end timings from production traces on
> `jenny` (Contabo VPS) and local development hardware. Treat them as
> directional, not as guaranteed performance contracts.

## Hardware

| Machine | Use | Spec |
|---|---|---|
| **jenny** | Production VPS (Contabo) | 6 vCPU (AMD EPYC), 16 GB RAM, 100 GB NVMe, single-node k3s |
| **local dev** | Author's machine | WSL2 on Linux 5.15, modern desktop CPU |

All numbers below come from one of these two environments. Cloud
provider, region, model provider, and concurrent load all affect the
results. Your numbers will differ.

## Stack

| Component | Setting |
|---|---|
| LLM (primary) | Fireworks AI — `accounts/fireworks/models/minimax-m2p5` |
| LLM (boost, used for report + persona generation) | Fireworks AI — `gpt-oss-120b` |
| Embeddings | Fireworks AI — `nomic-ai/nomic-embed-text-v1.5` (768-dim) |
| Recommender | TWHIN-BERT (`Twitter/twhin-bert-base`), cached locally |
| Graph store | SurrealDB 3.x (single node, in-memory + on-disk hybrid) |

## End-to-end pipeline (15-agent quick preset)

Document: ~10 KB news article. Scenario: a single paragraph prompt.

| Phase | Wall-clock |
|---|---|
| Entity extraction + graph build | ~10 s |
| Agent persona generation (15 agents, parallel) | ~3 min |
| Simulation — 136 actions across Twitter + Reddit feeds | ~4 min |
| Report generation | ~30 s |
| **Total** | **~7–8 min** |

## End-to-end pipeline (80-agent standard preset)

Same document size, longer scenario. Standard preset = 80 agents, more
rounds.

| Phase | Wall-clock |
|---|---|
| Entity extraction + graph build | ~30 s |
| Agent persona generation (80 agents, parallel) | ~6 min |
| Simulation — ~600 actions across both platforms | ~5 min |
| Report generation | ~45 s |
| **Total** | **~12 min** |

## Recommender system — the largest perf delta vs upstream

The original MiroFish recommender calls the LLM once per agent per
round to produce a personalized feed. At ~20 agents and ~30 rounds
that's 600 LLM calls *per simulation*, each ~200 ms at minimum, plus
network overhead. Round latency is dominated by recommender LLM calls.

DeepMiro replaces this with TWHIN-BERT cosine similarity:

1. At setup, embed every agent's persona once → 768-dim vector.
2. Each round, embed each new post once → 768-dim vector.
3. Per-agent feed = top-K cosine similarity over numpy arrays in
   memory. No LLM call.

| Approach | Per-round work (20 agents, 50 candidate posts) |
|---|---|
| MiroFish (LLM-per-agent) | 20 LLM calls ≈ 4–8 s of wall clock + cost |
| DeepMiro (TWHIN-BERT + numpy) | 1 batched embedding call ≈ 80 ms wall clock + ~10 ms numpy |

That's roughly two orders of magnitude faster *per round* in
wall-clock terms, and many more in dollar terms (LLM tokens are
strictly more expensive than embeddings). The exact ratio depends on
your provider, model choice, and concurrency settings — claims of "100×
faster" are honest at typical workloads, but the headline factor in
the README links here so we can show our work instead of asserting a
single number that doesn't survive scrutiny.

## How to reproduce

A `benchmarks/run_pipeline.py` harness is in flight. Until it lands,
the dirty-but-honest reproduction path is:

```bash
# From a fresh checkout, with a Fireworks key in .env
docker compose up -d
# Wait for "DeepMiro Backend ready"

# Drive a quick-preset simulation via the MCP server or directly via REST:
curl -X POST http://localhost:5001/api/simulation/start \
  -H 'Content-Type: application/json' \
  -d '{"preset": "quick", "scenario": "your prompt", "document_id": "..."}'
```

Time each phase from the backend logs — every state transition
(`GRAPH_BUILDING → GENERATING_PROFILES → READY → SIMULATING →
COMPLETED`) is logged with a timestamp.

## What we don't claim

- **We don't claim drift-free agents.** We've engineered against drift
  using structured personas, third-person framing, and dynamic
  rebuilding (see [README §Persona Fidelity](./README.md#persona-fidelity-how-deepmiro-keeps-agents-in-character)),
  but we don't yet ship a forbidden-phrase eval. That harness is on
  the roadmap.
- **We don't claim calibration.** DeepMiro generates qualitative
  predictions, not probability estimates. Treat the output as a
  rehearsal of plausible reactions, not as a forecast you'd put a dollar
  on.
- **We don't claim deterministic outputs.** LLMs are stochastic; same
  scenario will produce different (but topically consistent) reports
  across runs.

## Roadmap

- `benchmarks/` harness with reproducible scripts, raw timings, and a
  comparison table against the upstream MiroFish recommender on the
  same hardware.
- Persona drift eval: forbidden-phrase rate per target agent at rounds
  5/25/45, with baseline vs. v1.7.0 comparison.
- Cost-per-simulation table broken down by preset and LLM provider.
