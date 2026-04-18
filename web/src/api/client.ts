/**
 * Axios instance + API key injection.
 *
 * In dev (vite dev server on :3000), requests to /api/* are proxied
 * to :5001 via vite.config.ts. In prod (bundle served by Flask),
 * baseURL is the same origin.
 *
 * API key is read from localStorage. If not set, requests to
 * mutating routes will 401 and the SetupView will prompt for one.
 */

import axios, { AxiosError, type AxiosInstance } from "axios";

const API_KEY_STORAGE = "deepmiro_api_key";

export function getApiKey(): string {
  // Allow env override for self-hosted dev mode
  const envKey = (import.meta.env.VITE_DEEPMIRO_API_KEY as string | undefined) ?? "";
  if (envKey) return envKey;
  return localStorage.getItem(API_KEY_STORAGE) ?? "";
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key.trim());
}

export function clearApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE);
}

export function hasApiKey(): boolean {
  return getApiKey().length > 0;
}

const baseURL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (typeof window !== "undefined" ? window.location.origin : "");

export const http: AxiosInstance = axios.create({
  baseURL,
  timeout: 60_000,
  // Send Better Auth session cookie on every request — required so the
  // hosted layer (deepmiro-hosted) can resolve the user and inject
  // X-User-Id for the backend. Works on same-origin (deepmiro.org) and
  // cross-subdomain (app.deepmiro.org ↔ deepmiro.org) thanks to
  // Better Auth's SameSite=None + Domain=.deepmiro.org config.
  withCredentials: true,
});

// Inject X-API-Key on every request
http.interceptors.request.use((config) => {
  const key = getApiKey();
  if (key) {
    config.headers["X-API-Key"] = key;
  }
  return config;
});

// Global error handling: log 401s + bubble up
http.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      console.warn("API returned 401 — api key missing or invalid");
    }
    return Promise.reject(err);
  },
);
