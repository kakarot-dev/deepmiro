# Contributing to DeepMiro

Thanks for your interest in contributing.

## Getting Started

1. Fork the repo
2. Clone your fork
3. Create a branch: `git checkout -b feat/your-feature`
4. Make your changes
5. Run tests: `cd mcp-server && npm test`
6. Push and open a PR

## Development Setup

```bash
# MCP server (TypeScript)
cd mcp-server
npm install
npm run dev          # Watch mode
npm run typecheck    # Type checking
npm run build        # Production build

# Full stack (Docker)
cd docker
cp ../.env.example ../.env
docker compose up -d
```

## Project Structure

```
mcp-server/     TypeScript MCP server
docker/         Docker Compose for self-hosting
helm-chart/     Kubernetes deployment
neo4j-adapter/  Neo4j replacement for Zep Cloud
docs/           Documentation
```

## Code Style

- TypeScript strict mode
- No `any` types
- Prefer explicit error handling over try/catch-all

## What We Need Help With

- Testing against different LLM providers
- Neo4j adapter improvements
- Documentation and examples
- Bug reports from real-world usage

## License

By contributing, you agree that your contributions will be licensed under AGPL-3.0.
