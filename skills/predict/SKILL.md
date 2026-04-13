---
name: predict
description: Run a DeepMiro swarm prediction — simulate how hundreds of AI agents with distinct personas would react to a scenario. Invoke whenever the user asks to predict, simulate, or forecast reactions to an event, announcement, product, policy, or hypothetical — EVEN IF the scenario is vague or missing. The skill handles clarification from within; do NOT ask for details in plain chat first. Trigger phrases include "predict", "predict something", "can you predict", "run a prediction", "do a prediction", "simulate", "run a simulation", "how will people react", "how will X react to Y", "what would happen if", "forecast reactions", "model the response".
argument-hint: "[scenario] [optional-file-path]"
---

# DeepMiro Predict

## Step 0: Setup Check (MUST run first)

Check if the `create_simulation` MCP tool exists and is callable.

**If tools ARE available:** Skip to Step 1.

**If tools are NOT available (MCP disconnected):**

Say only this (short, one block):

> DeepMiro simulates how real personas react to a scenario. Not set up yet — paste your API key (get one at https://deepmiro.org) or say "install it" for setup instructions.

Then wait. Do NOT explain what the simulation would contain, do NOT offer a "quick take", do NOT describe the stakeholders. Keep it under 40 words.

### Auto-setup

**If they provide an API key (starts with `dm_`):**

The DeepMiro plugin's MCP config uses `${DEEPMIRO_API_KEY}` — a shell env var interpolation. You need to set that env var in a place Claude Code will pick up on its next start. The cleanest place is `~/.claude/settings.json` under the `env` field.

Steps:
1. Read `~/.claude/settings.json` using the Read tool
2. Parse the JSON
3. Add or update the `env` field:
   ```json
   "env": {
     "DEEPMIRO_API_KEY": "<their_key>"
   }
   ```
   (preserve any existing `env` entries — merge, don't overwrite)
4. Write the updated settings.json back
5. Tell the user:
   > "API key saved to your Claude Code settings. **Restart Claude Code now** — exit and run `claude` again. After restart, the DeepMiro tools will be available."

**If they don't have the plugin installed yet**, tell them:
> Run this once to install the plugin:
> ```bash
> claude plugin marketplace add kakarot-dev/deepmiro
> claude plugin install deepmiro@deepmiro-marketplace
> ```
> Then I'll save your API key to settings and you restart Claude Code.

**If they say self-hosted:**

Ask for their engine URL (default: `http://localhost:5001`). Read `~/.claude/settings.json`, update the `env` field:
```json
"env": {
  "MIROFISH_URL": "<their_url>"
}
```
Self-hosters don't need an API key.

**If they don't know / want help:**

Walk them through it:
1. "Go to https://deepmiro.org and create a free account"
2. "Go to Dashboard → API Keys and create a new key"
3. "Paste the key here and I'll save it to your Claude Code settings"

### After setup:

> "Done — API key saved. **Please restart Claude Code** (exit and run `claude` again) so the DeepMiro plugin can pick up your key. Then say **'predict [your scenario]'**."

**Important:** Do NOT try to call the MCP tools in this same session — they won't work until Claude Code restarts and respawns the plugin's MCP server with the new env var.

---

## Step 1: Connectivity Test

Call `list_simulations` with `limit: 1`.

- **Success:** Proceed to workflow.
- **Auth/401 error:** Run Step 0 setup flow.
- **Connection error:** "Can't reach DeepMiro. Check your API key and connection."

---

## Workflow

### Step 2: Upload document (if applicable)

If a file path is in $ARGUMENTS or the user referenced a file:

1. **Check file first** using the Read tool or Bash:
   - Verify it exists
   - Check size: must be under 10MB. If larger, tell the user:
     > "That file is too large (max 10MB). Try a smaller document, or extract the key sections into a text file."
   - Check type: PDF, MD, or TXT only. If other format:
     > "DeepMiro accepts PDF, Markdown, or plain text files. Can you convert it?"

2. **Upload the file:**
   - Call the `upload_document` MCP tool with the absolute file path
   - It reads the file locally and uploads to the backend, returning a `document_id`
   - Pass that `document_id` to `create_simulation` in the next step

3. Tell user: "Uploaded your document — I'll use it to build the knowledge graph."

No file? Skip to Step 3.

### Step 2.5: Enrich the prompt (IMPORTANT — do this for every prediction)

Before sending the prompt to DeepMiro, YOU must enrich it. The simulation engine extracts named entities from the prompt to create personas. A vague prompt like "how will people react to X" produces zero personas.

**Your job:** Rewrite the user's prompt into a rich scenario description that includes:
- **Specific stakeholder groups** with descriptive names (not just "people")
- **Named organizations** that would be involved
- **The context** — what happened, when, why it matters
- **Opposing viewpoints** — who supports, who opposes, who's neutral

**Example:**
User says: "How will crypto affect government record keeping?"

You rewrite to: "A major US government agency announces it will pilot blockchain-based record keeping for land titles and tax records. Key stakeholders include: the Government Accountability Office (GAO), the National Institute of Standards and Technology (NIST), the American Bankers Association, Coinbase and Ethereum Foundation as blockchain advocates, the Electronic Frontier Foundation (EFF) representing privacy concerns, state-level IT directors from Texas and California, taxpayer advocacy groups, and investigative journalists from The Washington Post and Wired. The debate centers on transparency vs privacy, cost savings vs implementation risk, and innovation vs proven systems."

**Show the user what you changed:**
> "Your prompt was a bit broad for the simulation engine — I've added some context to help it create better personas. Here's what I'm sending:
>
> *[show the enriched prompt]*
>
> Want me to adjust anything before I run it?"

Wait for confirmation, then proceed. Do NOT list specific personas — the engine decides who to create based on the text.

### Step 3: Choose preset

- **"quick"** — user said "quick", "fast", "rough idea" → 10 agents, 20 rounds
- **"standard"** (default) — most predictions → 20 agents, 40 rounds
- **"deep"** — user said "deep", "thorough", or uploaded a large PDF → 50+ agents, 72 rounds

If large document uploaded, suggest deep: "This is a detailed document — running deep simulation with 50+ personas."

### Step 4: Create simulation

Call `create_simulation` with prompt, document_id (optional), preset.

After calling `create_simulation`, immediately schedule a background check-in using `CronCreate`:

```
CronCreate(
  cron: "*/2 * * * *",   // every 2 minutes
  recurring: true,
  prompt: "Check simulation_status for <sim_id>. If still running, share any new interesting agent activity briefly. If completed, call get_report and present it. If failed, tell the user what went wrong. Delete this cron job once the simulation is complete or failed."
)
```

Then tell the user something short:
> "Started your prediction. I'll check on it every couple minutes and update you as the personas start reacting."

Do NOT:
- Mention "graph building", "generating profiles", "phases", "pipeline", "personas are built", or any internal steps
- Show simulation IDs like `sim_xxxxx` or `pending_proj_xxxxx` to the user (keep them internal — use them when calling tools, never print)
- Dump percentages, round counts like "Round 0/72", or action counters
- Pre-describe what the report will contain

The user only needs to see **what the personas are doing/saying**, not how the backend is running.

### Step 5: Narrate what the agents do

On each check-in (triggered by the scheduled cron), call `simulation_status` and share only what's interesting — **what the personas are saying or doing**.

**While still setting up:** say nothing at all. Skip this check-in. Wait for the next one.

**While simulating:** narrate real agent activity from `recent_actions`. Quote them naturally:
> "Prof. Zhang just posted: 'Our research output this semester shows remarkable growth...'
> Meanwhile Li Wei is liking every Chongqing Upstream News post."

Use actual names and post content. Do NOT mention:
- Round numbers, action counts, percentages
- Simulation IDs
- "Phase" names or pipeline steps
- Backend status like "graph ready" or "agents spawned"

Make it feel like a story unfolding — the kind of thing you'd read in a live-blog, not a server log.

**completed:** Call `CronDelete` with the cron job ID to stop the check-ins, then move to Step 6 — call `get_report` and present the report.

**failed:** Call `CronDelete` to stop check-ins, tell the user what went wrong in one sentence, offer to retry.

### Background hook (automatic)

There's also a hook (`hooks/check-predictions.sh` — UserPromptSubmit) that fires on every user message and injects a notification when a prediction completes. It's a safety net — if the cron gets lost (session restart, crash), the hook will still alert Claude on the next user prompt.

If the hook injects a "prediction X completed" message but you've already handled it via the cron, just acknowledge briefly and don't re-present the report.

**While still setting up (phase = building_graph or generating_profiles):**
Say nothing, or at most one short line like:
> "Still setting up..."

Don't announce "building graph" or "generating personas" or percentages. That's internal noise.

**While simulating (phase = simulating):**
Narrate real agent activity from `recent_actions`. Quote them:
> "Prof. Zhang just posted: 'Our research output this semester shows remarkable growth...'
> Meanwhile Li Wei is liking every Chongqing Upstream News post."

Use actual names and content. Make it feel like you're watching a story unfold, not reading logs.

**completed:** Move to Step 6.

If over 15 minutes: "Still running — I'll let you know when it's done."

### Step 6: Present report

Call `get_report`. Present the full analysis to the user.

Then offer next steps:
> "Simulation complete! You can:
> - **Interview a persona** — 'ask Li Wei why he liked that post'
> - **Run another scenario** — 'predict [new scenario]'
> - **Search past sims** — 'show my past predictions'"

### Step 7: Interview (optional)

If user wants to talk to a persona:
1. Call `interview_agent` with simulation_id, agent name, and their question
2. Present the response in character — as if the persona is answering directly

---

## Rules

- **Names, never IDs** — say "Prof. Zhang" not "Agent_34" or "agent_id: 7"
- **File uploads** — always use `upload_document` MCP tool first, pass the returned `document_id` to `create_simulation`. Never base64 encode files in prompts.
- **Error recovery** — if simulation fails, offer to retry with a smaller preset
- **Cancel a runaway** — if a sim is taking too long, producing bad output, or was started by mistake, use `cancel_simulation`. Partial action log is preserved.
- **Be conversational** — narrate the simulation like you're watching it unfold, not reading logs
