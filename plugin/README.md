# DeepMiro — Predict anything with AI agent swarms

Swarm prediction engine — simulate how communities react to events, policies, and announcements.

## Install

### Claude Code (one command)

```bash
claude mcp add deepmiro -e DEEPMIRO_API_KEY=dm_your_key -- npx -y deepmiro-mcp
```

Get your free API key at [deepmiro.org](https://deepmiro.org).

### Any MCP Client (ChatGPT, Cursor, VS Code, Windsurf)

```bash
DEEPMIRO_API_KEY=dm_your_key npx deepmiro-mcp
```

Add `npx deepmiro-mcp` as an MCP server in your client's settings.

### Self-Hosted (no API key needed)

```bash
git clone https://github.com/kakarot-dev/deepmiro
cd deepmiro && docker compose -f docker/docker-compose.yml up -d
claude mcp add deepmiro -e MIROFISH_URL=http://localhost:5001 -- npx -y deepmiro-mcp
```

## Usage

```
predict How will crypto twitter react to ETH ETF rejection?
```

```
predict Analyze reputation based on this report /path/to/report.pdf
```

### Presets
- **quick** — 10 agents, fast results
- **standard** (default) — 20 agents, balanced
- **deep** — 50+ agents, thorough analysis

### After simulation
- View the full report
- Interview any simulated persona ("ask Li Wei why he disagreed")
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
- [npm](https://www.npmjs.com/package/deepmiro-mcp)
- [License: AGPL-3.0](https://github.com/kakarot-dev/deepmiro/blob/main/LICENSE)
