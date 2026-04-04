---
name: predict
description: Run a DeepMiro swarm prediction — multi-agent social media simulation to predict how communities react to events, policies, or announcements. Use when the user says "predict", "simulate", "how will people react", "what would happen if", or wants to model social dynamics.
argument-hint: [scenario] [optional-file-path]
---

# DeepMiro Predict

Run a multi-agent swarm simulation to predict how online communities
will react to a scenario.

## Arguments

$ARGUMENTS contains the prediction prompt and optionally a file path.
Parse it to extract:
- The scenario description (required)
- An optional file path if the user references a document (PDF, MD, TXT)

## Workflow

### Step 1: Upload document (if file provided)

If a file path is present in $ARGUMENTS or the user has referenced a file
in the conversation:

1. Call the `upload_document` MCP tool with the file path
2. Save the returned `document_id`

If no file, skip to Step 2.

### Step 2: Create simulation

Call the `create_simulation` MCP tool:
- `prompt`: The scenario description from $ARGUMENTS
- `document_id`: From Step 1 (if applicable)
- `preset`: "standard" unless the user asks for "quick" or "deep"

Save the returned `simulation_id`.

Tell the user: "Started simulation `{simulation_id}`. I'll check progress
every 30 seconds — you can keep working and I'll update you as it progresses."

### Step 3: Monitor progress

Poll `simulation_status` every 30 seconds. On each poll, display a
natural-language update based on the `phase` field:

**building_graph**: "Building knowledge graph... {progress}%"

**generating_profiles**: "Spawning personas: {profiles_generated}/{entities_count}.
Latest: {recent_profiles}"

**simulating**: "Round {current_round}/{total_rounds} — {total_actions} actions.
{recent_actions summary with agent names and content}"

**completed**: Move to Step 4.

When `phase` is `simulating`, narrate what's happening using entity names
and action content from `recent_actions`. Example:

> Round 15/40 — 127 actions so far. Prof. Zhang just tweeted:
> "Our research output this semester shows remarkable growth..."
> Li Wei liked the post. Campus Daily is browsing Reddit.

### Step 4: Get report

Call the `get_report` MCP tool with the simulation_id.
Present the report to the user.

Then offer: "Want me to interview any of the simulated personas?
You can ask them questions about their motivations and reactions."

## Important rules

- ALWAYS use entity/persona names ("Prof. Zhang", "Li Wei") in updates.
  Never show "Agent_34" or "agent_id: 7".
- If the simulation takes more than 20 minutes, warn the user and
  suggest checking back later.
- If `simulation_status` returns an error, inform the user and suggest
  retrying.
- Do NOT use the `files` parameter on `create_simulation` with base64
  encoding. Always use `upload_document` first, then pass `document_id`.

## Setup

This skill requires the DeepMiro MCP server to be connected.

**Hosted (recommended):**
1. Sign up at https://deepmiro.org and get your API key
2. Set `DEEPMIRO_API_KEY` in your environment
3. The plugin's `.mcp.json` handles the rest

**Self-hosted:**
1. Run `docker compose up` from the deepmiro repo
2. Update `.mcp.json` to point to your local instance
