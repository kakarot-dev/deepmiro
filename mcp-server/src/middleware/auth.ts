// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import type { Request, Response, NextFunction } from "express";
import { timingSafeEqual } from "node:crypto";
import type { AuthContext, AuthProvider } from "../types/index.js";

// Extend Express Request to carry auth context
declare global {
  namespace Express {
    interface Request {
      authContext?: AuthContext;
    }
  }
}

/**
 * Create auth middleware.
 *
 * In hosted mode, the CF Worker has already validated the API key and set
 * X-User-Id / X-User-Tier headers. We just read those.
 *
 * In self-hosted mode, falls back to MCP_API_KEY timing-safe comparison.
 *
 * If an AuthProvider is supplied, it takes precedence over both.
 */
export function createAuthMiddleware(
  apiKey?: string,
  provider?: AuthProvider,
  originSecret?: string,
) {
  const keyBuffer = apiKey ? Buffer.from(apiKey) : null;
  const originSecretBuffer = originSecret ? Buffer.from(originSecret) : null;

  return async (req: Request, res: Response, next: NextFunction) => {
    // 1. Check for hosted-mode headers (set by CF Worker)
    const userId = req.headers["x-user-id"] as string | undefined;
    const userTier = req.headers["x-user-tier"] as string | undefined;
    if (userId && userTier) {
      // Verify the request actually came through the CF Worker
      if (originSecretBuffer) {
        const provided = req.headers["x-origin-secret"] as string | undefined;
        if (!provided) {
          res.status(403).json({ error: "Missing origin secret" });
          return;
        }
        const providedBuf = Buffer.from(provided);
        if (providedBuf.length !== originSecretBuffer.length || !timingSafeEqual(providedBuf, originSecretBuffer)) {
          res.status(403).json({ error: "Invalid origin secret" });
          return;
        }
      }
      req.authContext = { userId, tier: userTier };
      return next();
    }

    // 2. If a custom auth provider is supplied, try it
    if (provider) {
      try {
        const ctx = await provider.validateRequest(req);
        if (ctx) {
          req.authContext = ctx;
          return next();
        }
      } catch {
        // Provider failed — fall through to API key check
      }
      res.status(401).json({ error: "Authentication failed" });
      return;
    }

    // 3. Self-hosted: MCP_API_KEY timing-safe check
    if (!keyBuffer) return next(); // No key configured = open access

    const authHeader = req.headers.authorization;
    if (!authHeader?.startsWith("Bearer ")) {
      res.status(401).json({ error: "Missing or invalid Authorization header" });
      return;
    }

    const provided = Buffer.from(authHeader.slice(7));
    if (provided.length !== keyBuffer.length || !timingSafeEqual(provided, keyBuffer)) {
      res.status(403).json({ error: "Invalid API key" });
      return;
    }

    next();
  };
}
