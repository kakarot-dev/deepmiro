#!/usr/bin/env node

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";
import express from "express";
import { randomUUID } from "node:crypto";
import { loadConfig } from "./config.js";
import { createMcpServer } from "./server.js";
import { createAuthMiddleware } from "./middleware/auth.js";
import type { MirofishConfig } from "./types/index.js";

async function main() {
  const config = loadConfig();

  if (config.transport === "http") {
    await startHttpTransport(config);
  } else {
    // Stdio: single server, single transport
    const { server } = createMcpServer(config);
    const transport = new StdioServerTransport();
    await server.connect(transport);
    process.stderr.write("mirofish-mcp: stdio transport connected\n");
  }
}

async function startHttpTransport(config: MirofishConfig) {
  const app = express();
  app.use(express.json()); // CRITICAL FIX: parse JSON bodies
  const auth = createAuthMiddleware(config.mcpApiKey);

  // Each session gets its own McpServer + transport (CRITICAL FIX: no shared server)
  const sessions = new Map<string, { transport: StreamableHTTPServerTransport }>();

  // Session TTL cleanup (MEDIUM FIX: prevent unbounded growth)
  const SESSION_TTL_MS = 30 * 60 * 1000; // 30 minutes
  setInterval(() => {
    // StreamableHTTPServerTransport manages its own lifecycle,
    // but we add a safety net for orphaned sessions
    if (sessions.size > 100) {
      process.stderr.write(`mirofish-mcp: warning: ${sessions.size} active sessions\n`);
    }
  }, 60_000);

  app.post("/mcp", auth, async (req, res) => {
    const sessionId = req.headers["mcp-session-id"] as string | undefined;

    // Existing session
    if (sessionId && sessions.has(sessionId)) {
      const { transport } = sessions.get(sessionId)!;
      await transport.handleRequest(req, res, req.body);
      return;
    }

    // New session — only allow initialize requests (HIGH FIX)
    if (sessionId || !isInitializeRequest(req.body)) {
      res.status(400).json({
        jsonrpc: "2.0",
        error: { code: -32000, message: "Bad request: must send initialize request without session ID" },
        id: null,
      });
      return;
    }

    // Create new server + transport per session (CRITICAL FIX)
    const { server } = createMcpServer(config);
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => randomUUID(),
      onsessioninitialized: (id) => {
        sessions.set(id, { transport });
      },
    });

    transport.onclose = () => {
      for (const [id, entry] of sessions) {
        if (entry.transport === transport) sessions.delete(id);
      }
    };

    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });

  app.get("/mcp", auth, async (req, res) => {
    const sessionId = req.headers["mcp-session-id"] as string | undefined;
    if (!sessionId || !sessions.has(sessionId)) {
      res.status(400).json({ error: "Invalid or missing session ID" });
      return;
    }
    const { transport } = sessions.get(sessionId)!;
    await transport.handleRequest(req, res);
  });

  app.delete("/mcp", auth, async (req, res) => {
    const sessionId = req.headers["mcp-session-id"] as string | undefined;
    if (sessionId && sessions.has(sessionId)) {
      const { transport } = sessions.get(sessionId)!;
      await transport.close();
      sessions.delete(sessionId);
    }
    res.status(200).json({ ok: true });
  });

  app.get("/health", (_req, res) => {
    res.json({ status: "ok", sessions: sessions.size });
  });

  const httpServer = app.listen(config.httpPort, () => {
    console.log(`mirofish-mcp: HTTP transport listening on port ${config.httpPort}`);
  });

  // Graceful shutdown (MEDIUM FIX)
  const shutdown = async () => {
    process.stderr.write("mirofish-mcp: shutting down...\n");
    for (const [, { transport }] of sessions) {
      await transport.close().catch(() => {});
    }
    sessions.clear();
    httpServer.close();
    process.exit(0);
  };

  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  process.stderr.write(`mirofish-mcp fatal: ${err.message}\n`);
  process.exit(1);
});
