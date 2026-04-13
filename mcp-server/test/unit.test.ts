import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert";

// ---------------------------------------------------------------------------
// 1. Config loading
// ---------------------------------------------------------------------------
describe("config – loadConfig()", () => {
  const ORIGINAL_ENV = { ...process.env };

  beforeEach(() => {
    // Ensure a clean env for each test
    delete process.env.MIROFISH_URL;
    delete process.env.LLM_API_KEY;
    delete process.env.MCP_API_KEY;
    delete process.env.TRANSPORT;
    delete process.env.HTTP_PORT;
    delete process.env.REQUEST_TIMEOUT_MS;
    delete process.env.MAX_RETRIES;
  });

  afterEach(() => {
    // Restore original env
    process.env = { ...ORIGINAL_ENV };
  });

  // Dynamic import so each test gets a fresh call (loadConfig reads process.env at call time)
  async function loadConfig() {
    const mod = await import("../src/config.js");
    return mod.loadConfig();
  }

  it("returns correct defaults when only LLM_API_KEY is set", async () => {
    process.env.LLM_API_KEY = "test-key-123";
    const cfg = await loadConfig();

    assert.strictEqual(cfg.mirofishUrl, "http://localhost:5001");
    assert.strictEqual(cfg.llmApiKey, "test-key-123");
    assert.strictEqual(cfg.mcpApiKey, undefined);
    assert.strictEqual(cfg.transport, "stdio");
    assert.strictEqual(cfg.httpPort, 3001);
    assert.strictEqual(cfg.requestTimeoutMs, 120_000);
    assert.strictEqual(cfg.maxRetries, 3);
  });

  it("reads all env vars correctly", async () => {
    process.env.LLM_API_KEY = "my-llm-key";
    process.env.MIROFISH_URL = "https://api.mirofish.io";
    process.env.MCP_API_KEY = "secret";
    process.env.TRANSPORT = "http";
    process.env.HTTP_PORT = "9090";
    process.env.REQUEST_TIMEOUT_MS = "30000";
    process.env.MAX_RETRIES = "5";

    const cfg = await loadConfig();

    assert.strictEqual(cfg.mirofishUrl, "https://api.mirofish.io");
    assert.strictEqual(cfg.llmApiKey, "my-llm-key");
    assert.strictEqual(cfg.mcpApiKey, "secret");
    assert.strictEqual(cfg.transport, "http");
    assert.strictEqual(cfg.httpPort, 9090);
    assert.strictEqual(cfg.requestTimeoutMs, 30_000);
    assert.strictEqual(cfg.maxRetries, 5);
  });

  it("throws when LLM_API_KEY is missing", async () => {
    // LLM_API_KEY not set — should fail validation
    await assert.rejects(loadConfig, (err: unknown) => {
      assert.ok(err instanceof Error);
      return true;
    });
  });

  it("throws when MIROFISH_URL is not a valid URL", async () => {
    process.env.LLM_API_KEY = "key";
    process.env.MIROFISH_URL = "not-a-url";

    await assert.rejects(loadConfig, (err: unknown) => {
      assert.ok(err instanceof Error);
      return true;
    });
  });

  it("throws when TRANSPORT is invalid", async () => {
    process.env.LLM_API_KEY = "key";
    process.env.TRANSPORT = "websocket";

    await assert.rejects(loadConfig, (err: unknown) => {
      assert.ok(err instanceof Error);
      return true;
    });
  });

  it("throws when HTTP_PORT is out of range", async () => {
    process.env.LLM_API_KEY = "key";
    process.env.HTTP_PORT = "99999";

    await assert.rejects(loadConfig, (err: unknown) => {
      assert.ok(err instanceof Error);
      return true;
    });
  });
});

// ---------------------------------------------------------------------------
// 2. Error handling
// ---------------------------------------------------------------------------
describe("errors", () => {
  it("MirofishBackendError stores statusCode and backendError", async () => {
    const { MirofishBackendError } = await import("../src/errors/index.js");
    const err = new MirofishBackendError("boom", 502, "traceback info");

    assert.strictEqual(err.message, "boom");
    assert.strictEqual(err.statusCode, 502);
    assert.strictEqual(err.backendError, "traceback info");
    assert.strictEqual(err.name, "MirofishBackendError");
    assert.ok(err instanceof Error);
  });

  it("SimulationNotFoundError has 404 status and correct message", async () => {
    const { SimulationNotFoundError } = await import("../src/errors/index.js");
    const err = new SimulationNotFoundError("sim-abc-123");

    assert.strictEqual(err.statusCode, 404);
    assert.ok(err.message.includes("sim-abc-123"));
    assert.strictEqual(err.name, "SimulationNotFoundError");
  });

  it("SimulationNotReadyError has 400 status", async () => {
    const { SimulationNotReadyError } = await import("../src/errors/index.js");
    const err = new SimulationNotReadyError("sim-xyz", "preparing");

    assert.strictEqual(err.statusCode, 400);
    assert.ok(err.message.includes("sim-xyz"));
    assert.ok(err.message.includes("preparing"));
    assert.strictEqual(err.name, "SimulationNotReadyError");
  });

  describe("toMcpError", () => {
    it("returns McpError as-is", async () => {
      const { McpError, ErrorCode } = await import(
        "@modelcontextprotocol/sdk/types.js"
      );
      const { toMcpError } = await import("../src/errors/index.js");

      const original = new McpError(ErrorCode.InvalidRequest, "already mcp");
      const result = toMcpError(original);
      assert.strictEqual(result, original);
    });

    it("maps 404 MirofishBackendError to InvalidParams", async () => {
      const { ErrorCode } = await import(
        "@modelcontextprotocol/sdk/types.js"
      );
      const { toMcpError, MirofishBackendError } = await import(
        "../src/errors/index.js"
      );

      const err = new MirofishBackendError("not found", 404);
      const mcp = toMcpError(err);
      assert.strictEqual(mcp.code, ErrorCode.InvalidParams);
      assert.ok(mcp.message.includes("not found"));
    });

    it("maps 400 MirofishBackendError to InvalidParams", async () => {
      const { ErrorCode } = await import(
        "@modelcontextprotocol/sdk/types.js"
      );
      const { toMcpError, MirofishBackendError } = await import(
        "../src/errors/index.js"
      );

      const err = new MirofishBackendError("bad request", 400);
      const mcp = toMcpError(err);
      assert.strictEqual(mcp.code, ErrorCode.InvalidParams);
    });

    it("maps 500 MirofishBackendError to InternalError", async () => {
      const { ErrorCode } = await import(
        "@modelcontextprotocol/sdk/types.js"
      );
      const { toMcpError, MirofishBackendError } = await import(
        "../src/errors/index.js"
      );

      const err = new MirofishBackendError("server error", 500);
      const mcp = toMcpError(err);
      assert.strictEqual(mcp.code, ErrorCode.InternalError);
    });

    it("maps plain Error to InternalError", async () => {
      const { ErrorCode } = await import(
        "@modelcontextprotocol/sdk/types.js"
      );
      const { toMcpError } = await import("../src/errors/index.js");

      const mcp = toMcpError(new Error("oops"));
      assert.strictEqual(mcp.code, ErrorCode.InternalError);
      assert.ok(mcp.message.includes("oops"));
    });

    it("maps string to InternalError", async () => {
      const { ErrorCode } = await import(
        "@modelcontextprotocol/sdk/types.js"
      );
      const { toMcpError } = await import("../src/errors/index.js");

      const mcp = toMcpError("raw string error");
      assert.strictEqual(mcp.code, ErrorCode.InternalError);
      assert.ok(mcp.message.includes("raw string error"));
    });

    it("maps axios-like error without response to InternalError mentioning unreachable", async () => {
      const { ErrorCode } = await import(
        "@modelcontextprotocol/sdk/types.js"
      );
      const { toMcpError } = await import("../src/errors/index.js");

      const axiosErr = Object.assign(new Error("ECONNREFUSED"), {
        isAxiosError: true,
        response: undefined,
      });
      const mcp = toMcpError(axiosErr);
      assert.strictEqual(mcp.code, ErrorCode.InternalError);
      assert.ok(mcp.message.includes("unreachable"));
    });

    it("maps axios-like error with response to InternalError showing status", async () => {
      const { ErrorCode } = await import(
        "@modelcontextprotocol/sdk/types.js"
      );
      const { toMcpError } = await import("../src/errors/index.js");

      const axiosErr = Object.assign(new Error("Request failed"), {
        isAxiosError: true,
        response: {
          status: 503,
          data: { success: false, error: "Service Unavailable" },
        },
      });
      const mcp = toMcpError(axiosErr);
      assert.strictEqual(mcp.code, ErrorCode.InternalError);
      assert.ok(mcp.message.includes("503"));
      assert.ok(mcp.message.includes("Service Unavailable"));
    });
  });

  describe("withRetry", () => {
    it("returns immediately on first success", async () => {
      const { withRetry } = await import("../src/errors/index.js");
      let calls = 0;
      const result = await withRetry(
        async () => {
          calls++;
          return "ok";
        },
        3,
        () => true,
      );
      assert.strictEqual(result, "ok");
      assert.strictEqual(calls, 1);
    });

    it("retries and succeeds after failures", async () => {
      const { withRetry } = await import("../src/errors/index.js");
      let calls = 0;
      const result = await withRetry(
        async () => {
          calls++;
          if (calls < 3) throw new Error(`fail-${calls}`);
          return "recovered";
        },
        5,
        () => true, // always retryable
      );
      assert.strictEqual(result, "recovered");
      assert.strictEqual(calls, 3);
    });

    it("throws after exhausting retries", async () => {
      const { withRetry } = await import("../src/errors/index.js");
      let calls = 0;
      await assert.rejects(
        () =>
          withRetry(
            async () => {
              calls++;
              throw new Error("always-fail");
            },
            2,
            () => true,
          ),
        (err: unknown) => {
          assert.ok(err instanceof Error);
          assert.strictEqual(err.message, "always-fail");
          return true;
        },
      );
      assert.strictEqual(calls, 3); // initial + 2 retries
    });

    it("does not retry when retryableCheck returns false", async () => {
      const { withRetry } = await import("../src/errors/index.js");
      let calls = 0;
      await assert.rejects(
        () =>
          withRetry(
            async () => {
              calls++;
              throw new Error("non-retryable");
            },
            5,
            () => false,
          ),
        (err: unknown) => {
          assert.ok(err instanceof Error);
          return true;
        },
      );
      assert.strictEqual(calls, 1); // no retries
    });
  });
});

// ---------------------------------------------------------------------------
// 3. Auth middleware
// ---------------------------------------------------------------------------
describe("auth middleware – createAuthMiddleware()", () => {
  // Minimal Express-like mocks
  function mockReq(authHeader?: string) {
    return {
      headers: authHeader !== undefined ? { authorization: authHeader } : {},
    } as unknown as import("express").Request;
  }

  function mockRes() {
    let statusCode: number | undefined;
    let body: unknown;
    const res = {
      status(code: number) {
        statusCode = code;
        return res;
      },
      json(data: unknown) {
        body = data;
        return res;
      },
      get statusCode_() {
        return statusCode;
      },
      get body_() {
        return body;
      },
    };
    return res as unknown as import("express").Response & {
      statusCode_: number | undefined;
      body_: unknown;
    };
  }

  it("returns passthrough middleware when no apiKey is provided", async () => {
    const { createAuthMiddleware } = await import("../src/middleware/auth.js");
    const mw = createAuthMiddleware();

    let called = false;
    const next = () => {
      called = true;
    };

    mw(mockReq(), mockRes(), next as unknown as import("express").NextFunction);
    assert.strictEqual(called, true);
  });

  it("returns passthrough middleware when apiKey is undefined", async () => {
    const { createAuthMiddleware } = await import("../src/middleware/auth.js");
    const mw = createAuthMiddleware(undefined);

    let called = false;
    const next = () => {
      called = true;
    };

    mw(mockReq(), mockRes(), next as unknown as import("express").NextFunction);
    assert.strictEqual(called, true);
  });

  it("rejects requests without Authorization header", async () => {
    const { createAuthMiddleware } = await import("../src/middleware/auth.js");
    const mw = createAuthMiddleware("super-secret");

    let nextCalled = false;
    const next = () => {
      nextCalled = true;
    };
    const res = mockRes();

    mw(mockReq(), res, next as unknown as import("express").NextFunction);
    assert.strictEqual(nextCalled, false);
    assert.strictEqual(res.statusCode_, 401);
  });

  it("rejects requests with non-Bearer Authorization header", async () => {
    const { createAuthMiddleware } = await import("../src/middleware/auth.js");
    const mw = createAuthMiddleware("super-secret");

    let nextCalled = false;
    const next = () => {
      nextCalled = true;
    };
    const res = mockRes();

    mw(
      mockReq("Basic dXNlcjpwYXNz"),
      res,
      next as unknown as import("express").NextFunction,
    );
    assert.strictEqual(nextCalled, false);
    assert.strictEqual(res.statusCode_, 401);
  });

  it("rejects requests with wrong API key", async () => {
    const { createAuthMiddleware } = await import("../src/middleware/auth.js");
    const mw = createAuthMiddleware("super-secret");

    let nextCalled = false;
    const next = () => {
      nextCalled = true;
    };
    const res = mockRes();

    mw(
      mockReq("Bearer wrong-key"),
      res,
      next as unknown as import("express").NextFunction,
    );
    assert.strictEqual(nextCalled, false);
    assert.strictEqual(res.statusCode_, 403);
  });

  it("accepts requests with correct API key", async () => {
    const { createAuthMiddleware } = await import("../src/middleware/auth.js");
    const mw = createAuthMiddleware("super-secret");

    let nextCalled = false;
    const next = () => {
      nextCalled = true;
    };
    const res = mockRes();

    mw(
      mockReq("Bearer super-secret"),
      res,
      next as unknown as import("express").NextFunction,
    );
    assert.strictEqual(nextCalled, true);
    // res should not have been called with status
    assert.strictEqual(res.statusCode_, undefined);
  });
});

// ---------------------------------------------------------------------------
// 4. Types – just verify the module imports cleanly
// ---------------------------------------------------------------------------
describe("types", () => {
  it("imports types/index without error", async () => {
    const mod = await import("../src/types/index.js");
    // Module should exist; it only exports types so keys may be empty at runtime
    assert.ok(mod !== null && mod !== undefined);
  });
});

// ---------------------------------------------------------------------------
// 5. Server creation
// ---------------------------------------------------------------------------
describe("server – createMcpServer()", () => {
  it("returns an object with server and client properties", async () => {
    const { createMcpServer } = await import("../src/server.js");

    const config = {
      mirofishUrl: "http://localhost:5001",
      llmApiKey: "test-key",
      mcpApiKey: undefined,
      transport: "stdio" as const,
      httpPort: 3001,
      requestTimeoutMs: 120_000,
      maxRetries: 3,
    };

    const result = createMcpServer(config);

    assert.ok(result, "createMcpServer should return a truthy value");
    assert.ok(result.server, "result should have a server property");
    assert.ok(result.client, "result should have a client property");
  });

  it("server has expected shape (McpServer instance)", async () => {
    const { createMcpServer } = await import("../src/server.js");
    const { McpServer } = await import(
      "@modelcontextprotocol/sdk/server/mcp.js"
    );

    const config = {
      mirofishUrl: "http://localhost:5001",
      llmApiKey: "test-key",
      mcpApiKey: undefined,
      transport: "stdio" as const,
      httpPort: 3001,
      requestTimeoutMs: 120_000,
      maxRetries: 3,
    };

    const { server } = createMcpServer(config);
    assert.ok(server instanceof McpServer, "server should be an McpServer instance");
  });

  it("client has expected methods", async () => {
    const { createMcpServer } = await import("../src/server.js");

    const config = {
      mirofishUrl: "http://localhost:5001",
      llmApiKey: "test-key",
      mcpApiKey: undefined,
      transport: "stdio" as const,
      httpPort: 3001,
      requestTimeoutMs: 120_000,
      maxRetries: 3,
    };

    const { client } = createMcpServer(config);
    assert.strictEqual(typeof client.healthCheck, "function");
    assert.strictEqual(typeof client.getSimulation, "function");
    assert.strictEqual(typeof client.listSimulations, "function");
    assert.strictEqual(typeof client.interviewAgent, "function");
    assert.strictEqual(typeof client.cancelSimulation, "function");
  });
});
