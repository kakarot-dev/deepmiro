# DeepMiro Plugin for Claude Code

Swarm prediction engine — simulate how communities react to events, policies, and announcements using multi-agent social media simulations.

## Quick Start

### Hosted (recommended)

1. Get an API key at [deepmiro.org](https://deepmiro.org)
2. Set your key:
   ```bash
   export DEEPMIRO_API_KEY=dm_your_key_here
   ```
3. Install the plugin:
   ```bash
   claude plugin install deepmiro
   ```
4. Run a prediction:
   ```
   /deepmiro:predict How will crypto twitter react to ETH ETF rejection?
   ```

### Self-Hosted

1. Clone and run:
   ```bash
   git clone https://github.com/kakarot-dev/deepmiro
   cd deepmiro
   docker compose up -d
   ```
2. Install the plugin:
   ```bash
   claude plugin install deepmiro
   ```
3. Update the plugin's `.mcp.json` to point to your local instance:
   ```json
   {
     "deepmiro": {
       "type": "http",
       "url": "http://localhost:3001/mcp"
     }
   }
   ```

## Usage

### Predict with a prompt
```
/deepmiro:predict How will students react to the new campus housing policy?
```

### Predict with a document
```
/deepmiro:predict Analyze reputation based on this report /path/to/report.pdf
```

### Presets
- **quick** — 10 agents, fast results
- **standard** (default) — 20 agents, balanced
- **deep** — 50+ agents, thorough analysis

### After simulation
- View the full report
- Interview any simulated persona
- Search past simulations

## MCP Tools

| Tool | Description |
|---|---|
| `create_simulation` | Start a new prediction |
| `simulation_status` | Check progress with rich status updates |
| `get_report` | Get the analysis report |
| `interview_agent` | Chat with a simulated persona |
| `upload_document` | Upload a PDF/MD/TXT for analysis |
| `list_simulations` | View past predictions |
| `search_simulations` | Search by topic |
| `quick_predict` | Instant prediction without full simulation |

## Links

- [DeepMiro](https://deepmiro.org)
- [GitHub](https://github.com/kakarot-dev/deepmiro)
- [License: AGPL-3.0](https://github.com/kakarot-dev/deepmiro/blob/main/LICENSE)
