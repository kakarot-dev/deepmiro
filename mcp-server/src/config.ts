// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { MirofishConfig } from "./types/index.js";

// Treat empty strings as "unset" for env var defaults. Some callers
// (plugin manifests with unresolved ${VAR} interpolation, helm with
// missing values keys, Railway deploy templates with blank fields)
// emit empty strings where undefined would round-trip through to
// Zod's .default() cleanly. Without this preprocess, MIROFISH_URL=""
// would hit .url() validation and crash the MCP server with a loop
// of "Invalid url" errors at startup.
const emptyStringAsUndefined = (v: unknown) =>
  typeof v === "string" && v.trim() === "" ? undefined : v;

const envSchema = z.object({
  MIROFISH_URL: z.preprocess(
    emptyStringAsUndefined,
    z.string().url().default("https://api.deepmiro.org"),
  ),
  DEEPMIRO_API_KEY: z.preprocess(emptyStringAsUndefined, z.string().optional()),
  LLM_API_KEY: z.preprocess(emptyStringAsUndefined, z.string().optional()),
  MCP_API_KEY: z.preprocess(emptyStringAsUndefined, z.string().optional()),
  ORIGIN_SECRET: z.preprocess(emptyStringAsUndefined, z.string().optional()),
  TRANSPORT: z.enum(["stdio", "http"]).default("stdio"),
  HTTP_PORT: z.coerce.number().int().min(1).max(65535).default(3001),
  REQUEST_TIMEOUT_MS: z.coerce.number().int().positive().default(120_000),
  MAX_RETRIES: z.coerce.number().int().min(0).max(10).default(3),
});

export function loadConfig(): MirofishConfig {
  const parsed = envSchema.parse(process.env);
  return {
    mirofishUrl: parsed.MIROFISH_URL,
    llmApiKey: parsed.LLM_API_KEY ?? "",
    deepmiroApiKey: parsed.DEEPMIRO_API_KEY,
    mcpApiKey: parsed.MCP_API_KEY,
    originSecret: parsed.ORIGIN_SECRET,
    transport: parsed.TRANSPORT,
    httpPort: parsed.HTTP_PORT,
    requestTimeoutMs: parsed.REQUEST_TIMEOUT_MS,
    maxRetries: parsed.MAX_RETRIES,
  };
}
