---
description: Run a DeepMiro swarm prediction — simulate how communities react to events. Use when user says "predict", "simulate", "how will people react", or "what would happen if".
argument-hint: [scenario] [optional-file-path]
---

# DeepMiro Predict

## Step 0: Setup Check (MUST run first)

Check if the `create_simulation` MCP tool exists and is callable.

**If tools ARE available:** Skip to Step 1.

**If tools are NOT available (MCP disconnected):**

Explain what DeepMiro does and offer setup. Keep it focused on outcomes, not how it works internally:

> **DeepMiro** predicts how people will react to things — policies, announcements, controversies, product launches.
>
> Instead of guessing, it creates real personas (journalists, critics, supporters, officials) and lets them debate your scenario. You get back:
> - **Who says what** — actual posts and reactions from each persona
> - **How opinion shifts** — who gets convinced, who pushes back, what goes viral
> - **A full analysis report** — with the key takeaways
> - **The ability to ask any persona why** — interview them directly about their reasoning
>
> You can also upload documents (PDFs, reports) to ground the prediction in real data.
>
> **To connect DeepMiro:**
> 1. **Hosted** (recommended) — get your API key at https://deepmiro.org and paste it here
> 2. **Self-hosted** — run locally with Docker
> 3. **Manual** — I'll give you the commands

Then wait for their response.

### Auto-setup (if user provides API key or says self-hosted)

**If they provide an API key (any string, typically starts with `dm_`):**

Try to run:
```bash
claude mcp add deepmiro --transport http https://api.deepmiro.org/mcp -e DEEPMIRO_API_KEY=<their_key>
```

Also try to install a standalone `/predict` skill so they can use the short name:
```bash
mkdir -p ~/.claude/skills/predict
```
Then write `~/.claude/skills/predict/SKILL.md` with this same skill content.

**If they say self-hosted:**

Ask for their backend URL (default: `http://localhost:3001/mcp`), then:
```bash
claude mcp add deepmiro --transport http <url>
```

### If user denies permissions or chooses manual:

Give them copy-paste commands:
> Run this in your terminal:
> ```bash
> # Hosted:
> claude mcp add deepmiro --transport http https://api.deepmiro.org/mcp -e DEEPMIRO_API_KEY=dm_your_key
>
> # Or self-hosted:
> claude mcp add deepmiro --transport http http://localhost:3001/mcp
> ```
> Then restart Claude Code.

### After any setup path:

> "Setup complete! Restart Claude Code for the connection to activate.
> Then just say **'predict [your scenario]'** or use `/predict`."

**Stop here. Do not proceed until MCP is connected.**

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
   - If `upload_document` MCP tool is available (stdio/local): call it with the file path
   - If MCP tool is NOT available or errors (remote/hosted mode): upload via curl instead:
     ```bash
     curl -sf -X POST "$DEEPMIRO_URL/api/documents/upload" \
       -H "Authorization: Bearer $DEEPMIRO_API_KEY" \
       -F "file=@/path/to/file.pdf"
     ```
   - Extract `document_id` from the response

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

> "Simulation started! I'll narrate what happens as the personas interact.
> You can keep working — I'll update you as it progresses."

### Step 5: Monitor and narrate

Poll `simulation_status` every 30 seconds. Narrate naturally based on `phase`:

**building_graph:**
> "Building a knowledge graph from your input... extracting entities and relationships. {progress}%"

**generating_profiles:**
> "Creating personas: {profiles_generated} of {entities_count} ready — {recent_profiles}"
> Example: "Li Wei (Student), Prof. Zhang (Faculty), Campus Daily (Media)..."

**simulating:**
Narrate the simulation like a story. Use entity names and action content from `recent_actions`:
> "Round 15/40 — 127 interactions so far.
> Prof. Zhang just tweeted: 'Our research output this semester shows remarkable growth...'
> Li Wei liked the post. Chongqing Upstream News is discussing the controversy on Reddit."

**completed:** Move to Step 6.

If over 15 minutes: "The deep simulation is still running — I'll let you know when it's done. Feel free to keep working."

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
- **No base64 file uploads** — always use `upload_document` first, pass `document_id` to `create_simulation`
- **Error recovery** — if simulation fails, offer to retry with a smaller preset
- **Quick predict** — if user just wants a fast take without a full simulation, use `quick_predict` and mention the full sim is available for deeper analysis
- **Be conversational** — narrate the simulation like you're watching it unfold, not reading logs
