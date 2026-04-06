---
name: predict
description: Run a DeepMiro swarm prediction — multi-agent social media simulation that predicts how communities react to events, policies, or announcements. Use when the user says "predict", "simulate", "how will people react", "what would happen if", or wants to model social dynamics.
argument-hint: [scenario] [optional-file-path]
---

# DeepMiro Predict

Run a multi-agent swarm simulation to predict how online communities react to a scenario. Agents with distinct personas (students, journalists, officials, alumni) interact on simulated Twitter and Reddit, producing realistic social media dynamics.

## Setup Check (MUST run before anything else)

Before doing ANY work, call `list_simulations` with `limit: 1` as a connectivity test.

**If it succeeds** (returns a list, even empty): connection is valid, proceed to workflow.

**If it fails with auth/401 error:**
> "DeepMiro needs an API key to connect. Two options:
> 1. **Hosted** (recommended): Sign up at https://deepmiro.org → get your API key → then run:
>    `export DEEPMIRO_API_KEY=dm_your_key_here`
>    and restart Claude Code.
> 2. **Self-hosted**: Run `docker compose up` from the deepmiro repo and update the plugin's `.mcp.json` URL to `http://localhost:3001/mcp` (no auth needed)."

**Stop here if auth fails.** Do not proceed with the workflow.

**If it fails with connection error** (not auth):
> "Can't reach the DeepMiro server. Check that:
> - Your API key is valid (`DEEPMIRO_API_KEY` environment variable)
> - The server is running (if self-hosted: `docker compose up`)
> - Your network can reach deepmiro.org"

**Stop here if connection fails.**

## Arguments

$ARGUMENTS contains the prediction prompt and optionally a file path.

## Workflow

### Step 1: Upload document (if applicable)

If the user provided a file path in $ARGUMENTS, or referenced a file earlier in the conversation (PDF, MD, TXT):

1. Call `upload_document` with the file path
2. Save the returned `document_id`
3. Tell the user: "Uploaded your document — I'll use it to seed the knowledge graph."

If no file, skip to Step 2.

### Step 2: Choose preset

- **"quick"** — 10 agents, 20 rounds. Use when user says "quick", "fast", or "just a rough idea"
- **"standard"** (default) — 20 agents, 40 rounds. Use for most predictions
- **"deep"** — 50 agents, 72 rounds. Use when user says "deep", "thorough", "detailed", or provides a long document

If the user uploaded a large PDF, suggest deep: "This is a detailed document — I'll run a deep simulation with more agents for a thorough analysis."

### Step 3: Create simulation

Call `create_simulation`:
- `prompt`: The scenario from $ARGUMENTS
- `document_id`: From Step 1 (if applicable)
- `preset`: From Step 2

Save the `simulation_id`. Tell the user:

> "Simulation started. I'll narrate what happens as the personas interact. You can keep working — I'll update you as it progresses."

### Step 4: Monitor and narrate

Poll `simulation_status` every 30 seconds. Narrate naturally based on the `phase`:

**building_graph:**
> "Building a knowledge graph from your input... extracting entities and relationships."

**generating_profiles:**
> "Creating personas: 24 of 68 ready so far — Li Wei (Student), Prof. Zhang (Faculty), Campus Daily (Media)..."

**simulating:**
Narrate the simulation like a story using entity names and action content:
> "Round 15/40 — 127 interactions so far.
> Prof. Zhang just tweeted: 'Our research output this semester shows remarkable growth in interdisciplinary collaboration...'
> Li Wei liked the post. Chongqing Upstream News is discussing the campus food controversy on Reddit."

**completed:**
Move to Step 5.

If the simulation takes more than 15 minutes, tell the user: "This deep simulation is still running — I'll let you know when it's done. Feel free to keep working."

### Step 5: Present report

Call `get_report` with the simulation_id. Present the full analysis.

Then offer:
> "The simulation is complete. Want me to:
> - **Interview a persona** — ask any simulated character about their motivations
> - **Run a different scenario** — modify the prompt and simulate again
> - **Search past simulations** — find previous predictions"

### Step 6: Interview (optional)

If the user wants to interview a persona:
1. Call `interview_agent` with the simulation_id, agent name/ID, and the user's question
2. Present the response in character

## Rules

- **Names, not IDs**: Always use entity names ("Prof. Zhang", "Li Wei"). Never show "Agent_34" or "agent_id: 7".
- **No base64**: Never use the `files` parameter on `create_simulation`. Always `upload_document` first.
- **Error recovery**: If the simulation fails, offer to retry with a smaller preset or prompt-only (no document).
- **Quick predict**: If the user just wants a fast opinion without a full simulation, use `quick_predict` instead and mention that a full simulation is available for deeper analysis.
