# mirofish-mcp

MCP server that brings [MiroFish](https://github.com/666ghj/MiroFish) swarm intelligence simulations to Claude Code, Claude Desktop, and any MCP-compatible client.

Feed it a scenario. It spawns hundreds of AI agents with unique personas, simulates their social media interactions, and predicts what happens next.

## Tools

| Tool | Description |
|------|-------------|
| `create_simulation` | Launch a full swarm simulation from a prompt + optional documents |
| `simulation_status` | Check progress of a running simulation |
| `get_report` | Generate and retrieve the prediction report |
| `interview_agent` | Chat with a specific simulated agent |
| `list_simulations` | List past simulation runs |
| `search_simulations` | Search simulations by topic |
| `quick_predict` | Fast, lightweight prediction without full simulation |

## Quick Start (Claude Code)

```bash
# Clone and build
git clone https://github.com/kakarot-dev/mirofish-mcp.git
cd mirofish-mcp/mcp-server
npm install && npm run build

# Configure
cp .env.example .env
# Edit .env with your settings
```

Add to your Claude Code MCP config (`~/.claude/config.json`):

```json
{
  "mcpServers": {
    "mirofish": {
      "command": "node",
      "args": ["/path/to/mirofish-mcp/mcp-server/dist/index.js"],
      "env": {
        "MIROFISH_URL": "http://localhost:5001",
        "LLM_API_KEY": "your_fireworks_api_key"
      }
    }
  }
}
```

## Self-Hosted (Docker)

Run the full stack locally with one command:

```bash
cp .env.example .env
# Edit .env with your API keys

cd docker
docker compose up -d
```

This starts:
- **MiroFish backend** (Flask) on port 5001
- **Neo4j** (graph database) on port 7687
- **Redis** (caching) on port 6379
- **mirofish-mcp** (MCP server) on port 3001

## Hosted Service

Coming soon at [mirofishmcp.tech](https://mirofishmcp.tech).

No setup required — just add the MCP server URL to your Claude config.

## Presets

| Preset | Agents | Rounds | Best for |
|--------|--------|--------|----------|
| `quick` | 10 | 20 | Fast estimates |
| `standard` | 20 | 40 | Balanced analysis |
| `deep` | 50 | 72 | Comprehensive predictions |

## Architecture

```
Claude Code/Desktop
       │ MCP Protocol
       ▼
  mirofish-mcp (TypeScript)
       │ REST API
       ▼
  MiroFish Backend (Flask)
       │
   ┌───┴───┐
   ▼       ▼
 Neo4j   LLM API
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MIROFISH_URL` | `http://localhost:5001` | MiroFish backend URL |
| `LLM_API_KEY` | — | Fireworks AI or any OpenAI-compatible API key |
| `TRANSPORT` | `stdio` | `stdio` for Claude Code, `http` for Claude Desktop |
| `HTTP_PORT` | `3001` | Port for HTTP transport |
| `MCP_API_KEY` | — | Optional auth key for hosted mode |

## License

[AGPL-3.0](LICENSE) — Free to use, modify, and distribute. If you offer this as a service, you must open-source your changes.

## Acknowledgements

This project builds on the work of several open-source projects. We are grateful to their creators and contributors.

### Core Engine
- **[MiroFish](https://github.com/666ghj/MiroFish)** by [Guo Hangjiang](https://github.com/666ghj) — The swarm intelligence simulation engine that powers everything. mirofish-mcp is a wrapper around MiroFish, not a replacement. Licensed under AGPL-3.0.

### Neo4j Storage Layer
- **[MiroShark](https://github.com/aaronjmars/MiroShark)** by [aaronjmars](https://github.com/aaronjmars) — Our Neo4j adapter (replacing Zep Cloud) is ported from MiroShark's storage layer, including the `GraphStorage` abstraction, `Neo4jStorage` implementation, hybrid search (vector + BM25), LLM-based NER extraction, and embedding service. Licensed under AGPL-3.0.

### Simulation Framework
- **[OASIS](https://github.com/camel-ai/oasis)** by [CAMEL-AI](https://github.com/camel-ai) — The Open Agent Social Interaction Simulations framework that MiroFish uses to run multi-agent simulations at scale.

### MCP Protocol
- **[Model Context Protocol](https://modelcontextprotocol.io/)** by [Anthropic](https://anthropic.com) — The protocol that makes this integration with Claude Code and Claude Desktop possible.

### Infrastructure
- **[Fireworks AI](https://fireworks.ai/)** — Default LLM inference provider for the hosted service.
