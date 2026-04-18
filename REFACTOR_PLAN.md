# DeepMiro v2 Refactor — Lifecycle + MCP + Frontend

> Execution plan for full rewrite. Dev-stage, no backward compat, delete old code aggressively.
>
> **Read order:** §0 Defaults → §1 Backend → §2 MCP → §3 Frontend. Execute phases in order, each phase must leave the repo in a shippable state.

---

## §0. Defaults + Decisions (resolved)

| Question | Decision | Reason |
|---|---|---|
| Framework | **Vue 3 + Vite + TypeScript** | MiroFish frontend is Vue, 90% portable |
| Realtime transport | **SSE** | No extra infra, Flask-native |
| Auth | **`X-API-Key` header** (same env var MCP uses: `DEEPMIRO_API_KEY`) | Matches MCP pattern |
| Port | **`5001:5001` published by default** | UI accessible on `docker compose up` |
| Graph edge source | **OASIS sqlite `mode=ro`** mid-sim | Simpler than snapshot file |
| Setup view | **Include "start from browser"** in v1 | Essential for non-Code users |
| SSE auth | Accept `?api_key=` query param (EventSource can't send custom headers) | Pragmatic, dev-stage |
| Watchdog | `DEEPMIRO_WATCHDOG_STALE_SECONDS=180`, monitor emits HEARTBEAT every 30s | Avoids false positives |
| `simulation_run` table | **Drop entirely**, merge into `simulation` table | One source of truth |
| `InteractionView` | **Defer to v1.1** (delete now) | Not in scope |
| Ontology/graph in state machine | **Yes** — covered by `GRAPH_BUILDING` / `GENERATING_PROFILES` | Unified lifecycle |

**Colors** (confirmed from hosted dashboard + README):

| Var | Value | Use |
|---|---|---|
| `--primary` | `#22d3ee` | CTA, active state, graph cyan |
| `--accent` | `#0891b2` | Hover, secondary actions |
| `--bg` | `#0a0f14` | Page background (dark mode default) |
| `--card` | `#0f1620` | Card/panel background |
| `--fg` | `#e6edf3` | Primary text |
| `--muted` | `#8b98a5` | Secondary text |
| `--border` | `#1e2a36` | Dividers |
| `--success` | `#22c55e` | Completed state |
| `--warning` | `#f59e0b` | Warnings |
| `--danger` | `#ef4444` | Failed state |

---

## §1. Backend — SimulationLifecycle Refactor

### 1.1 New package: `engine/app/services/lifecycle/`

Module list (all new files):

| File | Purpose |
|---|---|
| `__init__.py` | Export public API: `SimState`, `bus`, `store`, `watchdog` |
| `states.py` | `SimState` Enum + `ALLOWED` transition dict + `assert_transition()` |
| `events.py` | `Event` dataclass + `EventBus` class + module-level `bus` singleton |
| `store.py` | `SimSnapshot` dataclass + `LifecycleStore` class + module-level `store` singleton |
| `watchdog.py` | `LifecycleWatchdog` thread class, started once from `create_app()` |
| `persistence.py` | Atomic JSON writer (`write_state_atomic`), SurrealDB upsert helper |

### 1.2 `SimState` enum (exact values)

```
CREATED
GRAPH_BUILDING
GENERATING_PROFILES
READY
SIMULATING
COMPLETED
FAILED
CANCELLED
INTERRUPTED
```

`TERMINAL = {COMPLETED, FAILED, CANCELLED, INTERRUPTED}`

Transitions:

| From | Allowed → |
|---|---|
| `CREATED` | `GRAPH_BUILDING`, `FAILED`, `CANCELLED` |
| `GRAPH_BUILDING` | `GENERATING_PROFILES`, `FAILED`, `CANCELLED` |
| `GENERATING_PROFILES` | `READY`, `FAILED`, `CANCELLED` |
| `READY` | `SIMULATING`, `FAILED`, `CANCELLED` |
| `SIMULATING` | `COMPLETED`, `FAILED`, `CANCELLED`, `INTERRUPTED` |
| terminals | (none) |

### 1.3 `Event` dataclass

Fields: `seq: int`, `sim_id: str`, `ts: str (ISO)`, `type: str`, `payload: dict`.

Event types:
- `STATE_CHANGED` — payload: `{from, to, reason}`
- `ACTION` — payload: `{round, platform, agent_id, agent_name, action_type, action_args}`
- `ROUND_END` — payload: `{round, platform, simulated_hours, actions_in_round}`
- `HEARTBEAT` — payload: `{}` — every 30s from monitor even if idle
- `ERROR` — payload: `{error, context}`
- `POST` — convenience: emitted alongside `ACTION` when `action_type == CREATE_POST`

### 1.4 `EventBus` API

| Method | Purpose |
|---|---|
| `emit(sim_id, event_type, payload) -> Event` | Append to buffer, notify condition, return with seq populated |
| `subscribe(sim_id, last_event_id=None)` | Generator yielding events; blocks on condition until new events or sim terminal |
| `replay(sim_id, since_seq)` | One-shot list of buffered events after seq |
| `close(sim_id)` | Release buffer + condition on sim removal |

Buffer: `collections.deque(maxlen=2000)` per sim. Module-level `_RLock` guards the bus dict. Monotonic `_seq` counter per sim.

### 1.5 `SimSnapshot` dataclass (the ONE state record)

Fields (flat, replaces both old `state.json` and `run_state.json`):

```
simulation_id: str
project_id: str
graph_id: str | None
state: SimState
current_round: int
total_rounds: int
simulated_hours: float
total_simulation_hours: float
twitter_current_round: int
reddit_current_round: int
twitter_simulated_hours: float
reddit_simulated_hours: float
twitter_running: bool
reddit_running: bool
twitter_actions_count: int
reddit_actions_count: int
twitter_completed: bool
reddit_completed: bool
enable_twitter: bool
enable_reddit: bool
process_pid: int | None
entities_count: int
profiles_count: int
config_generated: bool
config_reasoning: str
started_at: str | None
updated_at: str
completed_at: str | None
error: str | None
recent_actions: list[dict]  # cap 50
```

Written to **one file**: `<sim_dir>/state.json` (replaces `run_state.json`).

### 1.6 `LifecycleStore` API

| Method | Purpose |
|---|---|
| `get(sim_id)` | Load snapshot (cached in memory, disk fallback) |
| `list(project_id=None)` | All snapshots |
| `create(sim_id, **fields) -> SimSnapshot` | New sim, state=CREATED |
| `transition(sim_id, new_state, **fields) -> SimSnapshot` | Validate → mutate → persist → emit |
| `update(sim_id, **fields) -> SimSnapshot` | Non-state mutation (counters, rounds), persist + emit |
| `record_action(sim_id, action_dict) -> SimSnapshot` | Append to recent_actions + bump counter + emit ACTION |
| `record_round_end(sim_id, platform, round, simulated_hours)` | Emit ROUND_END |
| `delete(sim_id)` | Cleanup snapshot + bus |

All mutations: per-sim `threading.Lock` held during `load → mutate → persist → emit`. Every writer (Flask handler, monitor thread, recovery, watchdog) goes through this.

`_persist(snapshot)`:
1. Write `<sim>/state.json` via `persistence.write_state_atomic` (tmp file + rename)
2. Best-effort SurrealDB upsert to `simulation` table (single row)
3. On DB failure: log `WARN`, return normally (disk is ground truth)

### 1.7 `LifecycleWatchdog` thread

- Started once in `create_app()`, daemon thread.
- Every 15s: for each sim with `state == SIMULATING`:
  - `stale_seconds = now - bus.last_event_ts[sim]`
  - If `stale_seconds > DEEPMIRO_WATCHDOG_STALE_SECONDS` (default 180):
    - Log
    - Emit `ERROR` event with `reason="subprocess_stalled"`
    - `SimulationRunner._terminate_process(sim_id)`
    - `store.transition(sim_id, FAILED, error="Subprocess stalled: no events in N seconds")`

### 1.8 `SimulationRunner` refactor

Delete from `engine/app/services/simulation_runner.py`:
- `SimulationRunState` dataclass
- `RoundSummary` dataclass
- `RunnerStatus` Enum (replaced by `SimState`)
- `_run_states` class dict
- `_save_run_state`, `_load_run_state`
- `_check_all_platforms_completed`
- `_mark_outer_simulation_completed`, `_mark_outer_simulation_failed`
- Every `[SURREAL_SAVE]` print statement
- Every `run_state.json` read/write

Keep (refactored):
- `start_simulation(sim_id, ...)` — now just: `store.transition(sim_id, SIMULATING)` + spawn subprocess + start monitor thread
- `stop_simulation(sim_id)` — terminate + `store.transition(sim_id, CANCELLED)`
- `_monitor_simulation(sim_id)` — pure event source, body:
  ```
  while not terminal:
    tail twitter/actions.jsonl, reddit/actions.jsonl
    for each new jsonl line:
      if event_type == "simulation_end":
        store.transition(sim_id, COMPLETED)
        return
      elif event_type == "round_end":
        store.record_round_end(sim_id, platform, round, hours)
      else:  # action
        store.record_action(sim_id, action_dict)
    if no lines in 30s: bus.emit(sim_id, "HEARTBEAT", {})
    if process.poll() is not None: break  # subprocess exited
    sleep 2
  if process.returncode != 0:
    store.transition(sim_id, FAILED, error=_extract_error_reason(...))
  ```
- `_extract_error_reason`, `_terminate_process`, `register_cleanup`
- `get_all_actions` — **move to new module** `engine/app/services/actions_reader.py` (not lifecycle-concerned)

### 1.9 `SimulationManager` refactor

Delete from `engine/app/services/simulation_manager.py`:
- `SimulationStatus` Enum (use `SimState` instead)
- All direct `state.json` reads/writes (use `store.get` / `store.transition`)
- `_save_simulation_state` (absorbed into `LifecycleStore`)
- `get_simulation`, `update_status`, etc. — delete or thin-wrap to `store`

Keep:
- Orchestration logic for `create_and_run` pipeline (called from new backend endpoint in §1.11)

### 1.10 Recovery path

Rewrite `_recover_interrupted_simulations` in `engine/app/__init__.py`:
- Walk `Config.OASIS_SIMULATION_DATA_DIR` for directories containing `state.json`
- For each non-terminal snapshot:
  - If `process_pid` is set AND process is dead: `store.transition(sim_id, INTERRUPTED, error="Pod restart")`
  - If `process_pid` alive: leave alone (rare)
  - Else: `store.transition(sim_id, INTERRUPTED)`
- All writes via `store`. ~30 lines total (was ~200).

### 1.11 REST endpoints (in `engine/app/api/simulation.py`)

**New:**
- `POST /api/simulation/create-and-run` — body: `{prompt, preset, platform, document_id?, rounds?}`. Backend runs: ontology gen → graph build → prepare → start. Returns `{simulation_id}` immediately. Lifecycle transitions through `GRAPH_BUILDING` → `GENERATING_PROFILES` → `SIMULATING`.
- `GET /api/simulation/<id>/status` — returns `SimSnapshot.to_dict()` + computed `recent_posts`, `progress_percent`.
- `GET /api/simulation/<id>/events` — SSE stream. Accepts `Last-Event-ID` header and `?api_key=` query param. Sends `id: <seq>\ndata: <json>\n\n` for each event. `HEARTBEAT` comment every 20s.
- `POST /api/simulation/<id>/cancel` — renamed from `/stop`. Calls `store.transition(CANCELLED)`.

**Delete:**
- `GET /api/simulation/<id>/run-status`
- `GET /api/simulation/<id>/run-status/detail`
- `POST /api/simulation/close-env`
- `GET /api/simulation/env-status`

**Keep:**
- `GET /api/simulation/history`
- `GET /api/simulation/<id>/posts`, `/actions`, `/profiles`, `/timeline`
- `GET /api/report/*`
- `POST /api/documents/upload`

### 1.12 Middleware: `engine/app/middleware/auth.py` (new)

- `require_api_key(view_func)` decorator.
- Reads `X-API-Key` header OR `?api_key=` query param (events only).
- Compares to `os.environ['DEEPMIRO_API_KEY']`.
- Empty env var = middleware is no-op (dev mode).

Applied:
- **Required**: all mutating routes (POST/PUT/DELETE on `/api/simulation/*`, `/api/report/*`), `/api/simulation/<id>/events`
- **Open**: `/api/simulation/<id>/status`, `/api/simulation/history`, `/health`

### 1.13 SurrealDB schema change

New migration file: `engine/app/storage/migrations/v2_unify_simulation.surql`:
1. Read all rows from `simulation_run`
2. For each row, upsert matching `simulation` row with merged fields (runner_status → state, counters, etc.)
3. `REMOVE TABLE simulation_run`
4. `DEFINE FIELD state ON simulation TYPE string ASSERT $value INSIDE ["CREATED","GRAPH_BUILDING","GENERATING_PROFILES","READY","SIMULATING","COMPLETED","FAILED","CANCELLED","INTERRUPTED"]`
5. Add new fields: `recent_actions`, `total_rounds`, `current_round`, etc.

Delete from `engine/app/storage/surrealdb_backend.py`:
- `upsert_run_state`, `get_run_state`, `update_run_state`
- `detect_interrupted_simulations` (rewrite against `simulation` table, move to `LifecycleStore`)
- Any `simulation_run` references

### 1.14 Test cleanup

Delete tests touching: `run_state.json`, `simulation_run` table, `pipelineTrackers`, `_save_run_state`, `_check_all_platforms_completed`.

New tests:
- `engine/tests/test_lifecycle_store.py` — transitions, atomic persist, event emission, DB failure tolerance
- `engine/tests/test_event_bus.py` — subscribe/replay, Last-Event-ID, buffer overflow
- `engine/tests/test_watchdog.py` — stale detection, HEARTBEAT debouncing
- `engine/tests/test_sse_endpoint.py` — HTTP streaming, reconnect, auth
- `engine/tests/test_recovery.py` — startup reconcile

### 1.15 Phase 1 done-when

- [ ] All old state.json/run_state.json dual writes deleted
- [ ] `SimState` is the only status enum referenced
- [ ] `LifecycleStore` is the only state writer
- [ ] SurrealDB has one `simulation` table
- [ ] `/status` + `/events` endpoints work via curl
- [ ] Watchdog catches hung subprocesses
- [ ] Existing MCP is BROKEN (expected — fixed in Phase 2)
- [ ] Frontend is untouched (Phase 3)
- [ ] All Phase 1 tests green

---

## §2. MCP Server — Thin Client Against New Backend

### 2.1 Delete from `mcp-server/src/client/mirofish-client.ts`

- `pipelineTrackers` Map + `PipelineTracker` type
- `runFullPipelineInBackground`
- `notifyPredictionReady`
- `pollTaskUntilDone`, `pollSimulationUntilDone`, `pollPrepareUntilDone`, `pollReportUntilDone`
- `getSimulationRunStatus`, `getSimulationRunStatusDetail`, `getPrepareStatus`, `getGraphTaskStatus`
- `generateOntology`, `buildGraph`, `getProject`, `createSimulationRecord`, `prepareSimulation`, `startSimulation`

### 2.2 New `MirofishClient` (thin) — final method list

| Method | Endpoint |
|---|---|
| `healthCheck()` | `GET /health` |
| `createAndRun(params)` | `POST /api/simulation/create-and-run` |
| `getStatus(simId)` | `GET /api/simulation/<id>/status` |
| `subscribeEvents(simId, handlers) -> Closeable` | SSE to `/events` |
| `cancelSimulation(simId)` | `POST /api/simulation/<id>/cancel` |
| `listSimulations(limit)` | `GET /api/simulation/history` |
| `searchSimulations(query)` | `GET /api/simulation/history` (client-side filter) |
| `getReport(simId, force?)` | `GET /api/report/by-simulation/<id>` or `POST /api/report/generate` |
| `interviewAgent(simId, agentId, prompt)` | `POST /api/simulation/<id>/interview` |
| `uploadDocument(filePath)` | `POST /api/documents/upload` |
| `getSimulationProfiles(simId)` | `GET /api/simulation/<id>/profiles` |
| `getSimulationActions(simId, params)` | `GET /api/simulation/<id>/actions` |
| `getSimulationPosts(simId, params)` | `GET /api/simulation/<id>/posts` |
| `getSimulationTimeline(simId)` | `GET /api/simulation/<id>/timeline` |

Axios interceptor: inject `X-API-Key` from `DEEPMIRO_API_KEY` env.

### 2.3 SSE client (new file: `mcp-server/src/client/event-stream.ts`)

- Wraps `eventsource` npm package (Node doesn't have native EventSource).
- Install: `npm i eventsource @types/eventsource`.
- Auto-reconnect with exponential backoff, Last-Event-ID replay.
- Handler interface: `onStateChanged`, `onAction`, `onRoundEnd`, `onError`, `onHeartbeat`.

### 2.4 Refactor `create-simulation.ts`

New behavior:
- One `client.createAndRun()` call, returns `simulation_id` immediately.
- Return message: `"Prediction started. Call simulation_status to wait for completion."`
- Remove all `pending_` ID shenanigans.

### 2.5 Refactor `simulation-status.ts`

Delete: `resolvePendingStatus`, `resolvePreparingStatus`, `resolveRunningStatus`, `resolveCompletedStatus`, `snapshotKey`.

New logic:
1. `const snapshot = await client.getStatus(simId)`
2. If `snapshot.state` is terminal OR `args.wait === false`: format + return.
3. Else (long-poll): open SSE, wait up to 50s for `STATE_CHANGED` or `ROUND_END` event, then `getStatus` fresh, return.
4. When `state === COMPLETED`: also call `getReport(simId)` and embed `report_markdown` + `display_instructions`.

Build `recent_posts` from `snapshot.recent_actions` filtered to `action_type in {CREATE_POST, CREATE_COMMENT}`. Keep `narration_hint` string.

### 2.6 Update types in `mcp-server/src/types/index.ts`

Delete: `PipelineTracker`, `SimulationRunStatus`, `PrepareStatusDetail`, `RichSimulationStatus` (replaced by `SimStatusResponse`).

Add:
```
enum SimState { CREATED, GRAPH_BUILDING, GENERATING_PROFILES, READY, SIMULATING, COMPLETED, FAILED, CANCELLED, INTERRUPTED }

interface SimSnapshot {
  simulation_id: string
  project_id: string
  state: SimState
  current_round: number
  total_rounds: number
  // ... all fields from §1.5
  recent_actions: ActionRecord[]
}

interface LifecycleEvent {
  seq: number
  sim_id: string
  ts: string
  type: "STATE_CHANGED" | "ACTION" | "ROUND_END" | "HEARTBEAT" | "ERROR" | "POST"
  payload: Record<string, unknown>
}

interface SimStatusResponse extends SimSnapshot {
  progress_percent: number
  recent_posts?: PostSummary[]
  narration_hint?: string
  report_markdown?: string
  display_instructions?: string
}
```

### 2.7 `.mcpb` manifest update

- `mcp-server/manifest.json` bump to `2.0.0`
- No other manifest changes needed (user_config stays)

### 2.8 Phase 2 done-when

- [ ] `mirofish-client.ts` under 300 lines (was ~650)
- [ ] No `pipelineTrackers` references anywhere in `mcp-server/src/`
- [ ] `npm run build` passes
- [ ] Claude Desktop + Claude Code can run a sim end-to-end against new backend
- [ ] `simulation_status` returns report inline when sim completes

---

## §3. Frontend — `deepfish/web/` (new)

### 3.1 Directory structure (target)

```
web/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── public/
│   └── favicon.svg
└── src/
    ├── main.ts
    ├── App.vue
    ├── router/
    │   └── index.ts
    ├── styles/
    │   ├── theme.css              # CSS vars (§0 palette)
    │   ├── animations.css         # keyframes + durations
    │   └── base.css               # reset, global
    ├── api/
    │   ├── client.ts              # axios instance + X-API-Key
    │   └── simulation.ts          # typed API methods
    ├── lib/
    │   ├── events.ts              # SSE wrapper class
    │   ├── archetypes.ts          # archetype → color map
    │   ├── markdown.ts            # markdown-it setup + Prism
    │   └── format.ts              # date, number formatters
    ├── composables/
    │   ├── useSimulationEvents.ts # SSE + snapshot merge
    │   ├── useReport.ts
    │   └── useApiKey.ts           # localStorage + prompt
    ├── types/
    │   └── api.ts                 # mirrors MCP types/index.ts
    ├── views/
    │   ├── SetupView.vue          # / — start a new sim
    │   ├── HistoryView.vue        # /history
    │   ├── SimulationRunView.vue  # /sim/:simId
    │   └── ReportView.vue         # /sim/:simId/report
    └── components/
        ├── AppHeader.vue
        ├── LifecycleBar.vue       # state machine stepper
        ├── GraphPanel.vue         # d3 force graph
        ├── ActionFeed.vue         # realtime agent posts
        ├── AgentChip.vue          # colored agent badge
        ├── PlatformProgress.vue   # twitter/reddit counters
        ├── ReportMarkdown.vue     # renders markdown report
        ├── ApiKeyPrompt.vue       # first-time key paste dialog
        └── ui/
            ├── Button.vue
            ├── Card.vue
            ├── Badge.vue
            └── TextArea.vue
```

### 3.2 Phase 3A — Copy + strip MiroFish

1. `cp -r ~/mirofish/MiroFish/frontend/ ~/mirofish/deepfish/web/`
2. Delete:
   - `src/i18n/`, `src/components/LanguageSwitcher.vue`
   - `src/store/pendingUpload.js`
   - `src/components/Step1GraphBuild.vue`
   - `src/views/MainView.vue`, `src/views/Process.vue`
   - `src/views/SimulationView.vue` (the pre-run intermediate page)
   - `src/views/InteractionView.vue`
   - Any Zep-tagged component
   - Billing / marketing / account components
3. Remove deps: `vue-i18n`
4. Add deps: `markdown-it`, `prismjs`, `@types/markdown-it`, `dompurify`, `@types/dompurify`, `typescript`, `vue-tsc`
5. Convert `src/api/*.js` → `src/api/*.ts`
6. `grep -rn '\$t(' src/` → replace every i18n call with English literal
7. `grep -rn '#[0-9a-fA-F]{3,8}' src/` → replace with `var(--*)` CSS vars

### 3.3 Phase 3B — API + SSE client

**`src/api/client.ts`**:
- Axios instance, `baseURL = import.meta.env.VITE_API_BASE_URL || window.location.origin`
- Request interceptor: `config.headers['X-API-Key'] = getApiKey()`
- Response interceptor: on 401, clear stored key, route to setup

**`src/api/simulation.ts`** methods (1:1 with backend):
- `getStatus(id)`, `createSim(params)`, `cancelSim(id)`, `listSims(limit?)`, `searchSims(q)`
- `getReport(id, force?)`, `uploadDoc(file)`, `interviewAgent(...)`
- `getPosts(id, params)`, `getProfiles(id)`, `getActions(id, params)`, `getTimeline(id)`

**`src/lib/events.ts`** — `SimulationEventStream` class:
- Constructor: `(simId, apiKey)` — opens EventSource at `/api/simulation/<simId>/events?api_key=<key>`
- Handlers: `onStateChanged`, `onAction`, `onRoundEnd`, `onError`, `onHeartbeat`, `onClose`
- Auto-reconnect with exponential backoff
- `close()` — terminate stream

**`src/composables/useSimulationEvents.ts`**:
- Input: `simId: Ref<string>`
- Returns reactive refs:
  - `state: Ref<SimState>`
  - `currentRound: Ref<number>`
  - `totalRounds: Ref<number>`
  - `actions: Ref<ActionRecord[]>` (cap 100, prepended)
  - `agents: Ref<Agent[]>`
  - `edges: Ref<Edge[]>`
  - `progress: Ref<number>`
  - `error: Ref<string | null>`
  - `isConnected: Ref<boolean>`
- On mount: `getStatus()` → hydrate refs → open `SimulationEventStream`
- On SSE events: update refs (reactive)
- On unmount: close stream

### 3.4 Phase 3C — Core views

**`SetupView.vue`** (`/`):
- Prompt textarea (min 20 chars, placeholder: enriched example)
- Preset select (quick/standard/deep)
- Platform checkboxes (twitter, reddit; default both)
- Optional file input (.pdf/.md/.txt, max 10MB)
- Submit → `createSim()` → router push `/sim/<id>`
- If no API key stored: show `ApiKeyPrompt` first

**`HistoryView.vue`** (`/history`):
- Call `listSims(20)`, render table: agent name, status badge, created_at, entity count
- Click row → `/sim/<id>` if terminal, else `/sim/<id>` live

**`SimulationRunView.vue`** (`/sim/:simId`):
- Uses `useSimulationEvents(simId)`
- Layout:
  ```
  ┌─────────────────────────────────┐
  │  LifecycleBar (CREATED→...→DONE) │
  ├──────────────────┬──────────────┤
  │                  │              │
  │   GraphPanel     │  ActionFeed  │
  │     (60%)        │    (40%)     │
  │                  │              │
  ├──────────────────┴──────────────┤
  │ PlatformProgress · Cancel · ... │
  └─────────────────────────────────┘
  ```
- On `state === COMPLETED`: show "View Report" button → `/sim/<id>/report`

**`ReportView.vue`** (`/sim/:simId/report`):
- `useReport(simId)` → markdown from backend
- Render via `ReportMarkdown.vue`
- "Regenerate" button (force=true)
- "Back to live view" link

### 3.5 Phase 3D — Key components

**`LifecycleBar.vue`**:
- Props: `state: SimState`, `progress: number`
- Horizontal stepper: GRAPH_BUILDING → GENERATING_PROFILES → SIMULATING → COMPLETED
- Active segment: `--primary` bg, animated fill (`transition: width 400ms`)
- Past segments: `--muted` with checkmark
- Future: `--border`
- Failed state: red badge replaces current segment

**`GraphPanel.vue`** (port of MiroFish `GraphPanel.vue`):
- Props: `agents: Agent[]`, `edges: Edge[]`
- Keeps d3 force simulation (`forceSimulation`, `forceLink`, `forceManyBody`, `forceCollide`)
- Canvas or SVG rendering (SVG for <100 nodes, switch to canvas for more)
- Watch `agents` deep:
  - New: `enter()` with `r=0 → targetR`, `opacity 0 → 1`, spring ease 600ms
  - Update (post count change): `transition(300).attr('r', newR)`
  - Removed: `exit().transition().attr('r', 0).remove()`
- Watch `edges`: new edges animate `stroke-dashoffset` full → 0 over 500ms
- Node colors from `archetypes.ts` map (TechCEO→cyan, Politician→violet, AppDev→lime, Journalist→orange, etc.)
- Hover: foreignObject tooltip with agent name + last post snippet (truncated 140 chars)
- Drag + zoom + pan retained from MiroFish

**`ActionFeed.vue`**:
- Props: `actions: ActionRecord[]`
- `<TransitionGroup name="feed-slide" tag="ul">`
- Each `<li>`: AgentChip (colored by archetype) + action type badge + content + ago timestamp
- CSS `.feed-slide-enter-active`: `translateY(-20px) → 0` + `filter: blur(4px) → 0`, 400ms, `cubic-bezier(0.22, 1, 0.36, 1)`
- Virtual scroll only if >100 items

**`AgentChip.vue`**:
- Props: `agent: Agent` or `{name, archetype}`
- Renders: colored circle (archetype color) + name

**`PlatformProgress.vue`**:
- Props: `twitter: {round, total, actions}`, `reddit: {round, total, actions}`
- Two side-by-side bars showing round progress per platform + action count

**`ApiKeyPrompt.vue`**:
- Modal on first load if no key in localStorage
- Text input + save button
- Store via `useApiKey()` composable

**`ReportMarkdown.vue`**:
- Props: `markdown: string`
- Uses `markdown-it` + `prism` (via `markdown.ts` lib)
- Sanitize output with `DOMPurify`

### 3.6 Phase 3E — Animations (`src/styles/animations.css`)

Keyframes:
- `@keyframes action-slide-in` — translateY + blur, 400ms, `cubic-bezier(0.22, 1, 0.36, 1)`
- `@keyframes node-pop-in` — scale 0.3 → 1 overshoot, `cubic-bezier(0.34, 1.56, 0.64, 1)`
- `@keyframes step-advance` — LifecycleBar transition
- `@keyframes pulse-primary` — active node pulse (subtle 2s loop)
- `@keyframes edge-draw` — stroke-dashoffset tween
- `@keyframes fade-in` — 200ms opacity

CSS variables (at `:root`):
- `--duration-fast: 200ms`
- `--duration-normal: 400ms`
- `--duration-slow: 700ms`
- `--ease-out: cubic-bezier(0.22, 1, 0.36, 1)`
- `--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1)`

### 3.7 Phase 3F — Docker + Flask serving

**`docker/Dockerfile.backend`** — multi-stage:
```
FROM node:20-slim AS web-build
WORKDIR /build
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
...existing backend stage...
COPY --from=web-build /build/dist /app/deepmiro/web/dist
```

**`engine/app/__init__.py`**:
- `app = Flask(__name__, static_folder=os.environ.get('WEB_DIST', '/app/deepmiro/web/dist'), static_url_path='')`
- Catch-all route:
  ```
  @app.route('/', defaults={'path': ''})
  @app.route('/<path:path>')
  def spa(path):
      if path.startswith('api/') or path == 'health': abort(404)
      full = os.path.join(app.static_folder, path)
      if path and os.path.exists(full): return send_from_directory(app.static_folder, path)
      return send_from_directory(app.static_folder, 'index.html')
  ```
- Guard: if `static_folder` dir missing (local Python dev), skip catch-all

**`docker-compose.yml`**:
- Uncomment `ports: ["5001:5001"]` on backend service
- Add comment explaining UI is now at `http://localhost:5001/`

**`helm-chart/templates/ingress.yaml`**:
- Broaden path from `/api` to `/` so UI is served through ingress

### 3.8 Phase 3G — Final sweeps

- `grep -rn '\$t(\|i18n\|locale\|中文\|登录\|zh' web/src/` → delete
- `grep -rn 'zep\|Zep' web/src/` → replace with "knowledge graph"
- `grep -rn 'mirofish\|MiroFish' web/src/` → replace with `deepmiro` / `DeepMiro` where user-facing
- `grep -rn 'setInterval\|setTimeout' web/src/` → audit; should all be SSE-based
- Update `web/README.md` with dev setup: `npm ci && npm run dev` (proxy to :5001)

### 3.9 Phase 3 done-when

- [ ] `cd web && npm run dev` opens UI at :3000, proxies API to :5001
- [ ] `docker compose up` serves UI at :5001 after rebuild
- [ ] New user flow: paste API key → create sim → watch live view with graph + feed → view report
- [ ] Node entry/exit animations visible
- [ ] Action feed slides in new items
- [ ] No Chinese strings remain
- [ ] Zero polling in `web/src/` (all realtime via SSE)
- [ ] Theme colors applied consistently (cyan primary, dark bg)
- [ ] Helm chart works end-to-end on jenny

---

## §4. Execution order summary

```
┌─────────────────┐
│ Phase 1 (§1)    │  Backend lifecycle refactor
│ 2-3 dev-days    │  Breaks MCP temporarily (expected)
└────────┬────────┘
         │ ships: backend works, MCP broken
         ▼
┌─────────────────┐
│ Phase 2 (§2)    │  MCP thin-client rewrite
│ 1 dev-day       │  Requires Phase 1 merged
└────────┬────────┘
         │ ships: MCP + backend work end-to-end
         ▼
┌─────────────────┐
│ Phase 3 (§3)    │  Frontend port + refactor
│ 3-4 dev-days    │  No backend changes, independent
└─────────────────┘
         ▼ ships: full stack
```

Total: ~6-8 dev-days.

After each phase, commit + tag + deploy via helm upgrade on jenny.

---

## §5. Files that will be deleted (exhaustive)

```
engine/app/services/simulation_runner.py
  — SimulationRunState, RoundSummary, RunnerStatus classes
  — _save_run_state, _load_run_state, _check_all_platforms_completed
  — _mark_outer_simulation_completed, _mark_outer_simulation_failed
  — _run_states class dict
  — every [SURREAL_SAVE] print
  — _tail_sim_log subprocess log forwarder (replaced by bus HEARTBEAT)

engine/app/services/simulation_manager.py
  — SimulationStatus enum
  — direct state.json reads/writes
  — _save_simulation_state

engine/app/api/simulation.py
  — GET /run-status, /run-status/detail routes
  — /close-env, /env-status routes
  — old /stop route (renamed /cancel)

engine/app/storage/surrealdb_backend.py
  — upsert_run_state, get_run_state, update_run_state
  — simulation_run table schema
  — detect_interrupted_simulations (moves to LifecycleStore)

mcp-server/src/client/mirofish-client.ts
  — pipelineTrackers, PipelineTracker
  — runFullPipelineInBackground, notifyPredictionReady
  — pollTaskUntilDone, pollSimulationUntilDone, pollPrepareUntilDone, pollReportUntilDone
  — getSimulationRunStatus, getSimulationRunStatusDetail, getPrepareStatus, getGraphTaskStatus
  — generateOntology, buildGraph, getProject, createSimulationRecord, prepareSimulation, startSimulation

mcp-server/src/tools/simulation-status.ts
  — resolvePendingStatus, resolvePreparingStatus, resolveRunningStatus, resolveCompletedStatus
  — snapshotKey helper

mcp-server/src/types/index.ts
  — PipelineTracker, SimulationRunStatus, PrepareStatusDetail, RichSimulationStatus

web/ (entire MiroFish port, then strip)
  — src/i18n/
  — src/components/LanguageSwitcher.vue
  — src/store/pendingUpload.js
  — src/views/MainView.vue, Process.vue, SimulationView.vue, InteractionView.vue
  — src/components/Step1GraphBuild.vue (Zep-specific)
  — billing/marketing/account components
  — vue-i18n dep
```

---

## §6. New files (exhaustive)

```
engine/app/services/lifecycle/__init__.py
engine/app/services/lifecycle/states.py
engine/app/services/lifecycle/events.py
engine/app/services/lifecycle/store.py
engine/app/services/lifecycle/persistence.py
engine/app/services/lifecycle/watchdog.py
engine/app/services/actions_reader.py  (moved from simulation_runner)
engine/app/middleware/auth.py
engine/app/storage/migrations/v2_unify_simulation.surql
engine/tests/test_lifecycle_store.py
engine/tests/test_event_bus.py
engine/tests/test_watchdog.py
engine/tests/test_sse_endpoint.py
engine/tests/test_recovery.py

mcp-server/src/client/event-stream.ts

web/package.json, tsconfig.json, vite.config.ts, index.html
web/src/main.ts, App.vue
web/src/router/index.ts
web/src/styles/theme.css, animations.css, base.css
web/src/api/client.ts, simulation.ts
web/src/lib/events.ts, archetypes.ts, markdown.ts, format.ts
web/src/composables/useSimulationEvents.ts, useReport.ts, useApiKey.ts
web/src/types/api.ts
web/src/views/SetupView.vue, HistoryView.vue, SimulationRunView.vue, ReportView.vue
web/src/components/AppHeader.vue, LifecycleBar.vue, GraphPanel.vue, ActionFeed.vue,
                    AgentChip.vue, PlatformProgress.vue, ReportMarkdown.vue, ApiKeyPrompt.vue
web/src/components/ui/Button.vue, Card.vue, Badge.vue, TextArea.vue
web/README.md
```

---

## §7. Environment variables (final list)

| Var | Purpose | Default |
|---|---|---|
| `DEEPMIRO_API_KEY` | API key for mutating routes + SSE | (empty = no auth) |
| `DEEPMIRO_WATCHDOG_STALE_SECONDS` | Stall detection threshold | `180` |
| `WEB_DIST` | Path to built frontend | `/app/deepmiro/web/dist` |
| `VITE_API_BASE_URL` | Frontend dev proxy target | `http://localhost:5001` |
| `VITE_DEEPMIRO_API_KEY` | Dev-mode key auto-inject | (empty) |

Existing vars unchanged: `SURREAL_URL`, `SURREAL_PASS`, `LLM_API_KEY`, `TWHIN_URL`, etc.

---

## §8. Sonnet continuation instructions

When picking this up:

1. Read §0 for decisions — don't reopen them.
2. Start with Phase 1 (§1), complete it fully before Phase 2.
3. Each subsection (§1.1, §1.2, etc.) is a discrete commit. Small commits, easy revert.
4. Run `python3 -c "import ast; ast.parse(open(path).read())"` after each Python file edit.
5. For MCP (§2): `npm run build` must pass before commit.
6. For frontend (§3): `npm run build && npm run type-check` must pass.
7. After each phase: tag `v2.0.0-phase1`, `v2.0.0-phase2`, `v2.0.0-phase3`, then final `v2.0.0`.
8. Deploy to jenny via existing helm workflow after each phase.
9. Do NOT add backward-compat shims. If old code references old APIs, delete the old code.
10. When in doubt about a name or pattern: match the hosted dashboard at `/home/axel/deepmiro-hosted/dashboard/` (React + Tailwind there, Vue + custom CSS here, but naming conventions transfer).
