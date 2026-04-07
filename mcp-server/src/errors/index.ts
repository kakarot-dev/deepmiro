// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { McpError, ErrorCode } from "@modelcontextprotocol/sdk/types.js";
import type { AxiosError } from "axios";
import type { MirofishApiResponse } from "../types/index.js";

export class MirofishBackendError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number,
    public readonly backendError?: string,
  ) {
    super(message);
    this.name = "MirofishBackendError";
  }
}

export class SimulationNotFoundError extends MirofishBackendError {
  constructor(simulationId: string) {
    super(`Simulation not found: ${simulationId}`, 404);
    this.name = "SimulationNotFoundError";
  }
}

export class SimulationNotReadyError extends MirofishBackendError {
  constructor(simulationId: string, currentStatus: string) {
    super(`Simulation ${simulationId} is not ready (status: ${currentStatus})`, 400);
    this.name = "SimulationNotReadyError";
  }
}

export function toMcpError(err: unknown): McpError {
  if (err instanceof McpError) return err;

  if (err instanceof MirofishBackendError) {
    if (err.statusCode === 404 || err.statusCode === 400) {
      return new McpError(ErrorCode.InvalidParams, err.message);
    }
    return new McpError(ErrorCode.InternalError, err.message);
  }

  if (isAxiosError(err)) {
    if (!err.response) {
      return new McpError(ErrorCode.InternalError, `MiroFish backend unreachable: ${err.message}`);
    }
    const body = err.response.data as MirofishApiResponse;
    return new McpError(
      ErrorCode.InternalError,
      `MiroFish backend error (${err.response.status}): ${body?.error ?? err.message}`,
    );
  }

  if (err instanceof Error) {
    return new McpError(ErrorCode.InternalError, err.message);
  }

  return new McpError(ErrorCode.InternalError, String(err));
}

function isAxiosError(err: unknown): err is AxiosError {
  return (err as AxiosError)?.isAxiosError === true;
}

export async function withRetry<T>(
  fn: () => Promise<T>,
  maxRetries: number,
  retryableCheck?: (err: unknown) => boolean,
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      const shouldRetry = retryableCheck?.(err) ?? isTransientError(err);
      if (!shouldRetry || attempt === maxRetries) throw err;
      await sleep(500 * Math.pow(2, attempt));
    }
  }
  throw lastError;
}

function isTransientError(err: unknown): boolean {
  if (isAxiosError(err)) {
    const status = err.response?.status;
    if (!status) return true;
    return status === 429 || status >= 500;
  }
  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
