/**
 * Browser EventSource wrapper for the backend's /events SSE endpoint.
 *
 * EventSource can't send custom headers, so the API key goes in the
 * query string. The backend middleware accepts either `X-API-Key`
 * header or `api_key` query param specifically for /events.
 *
 * Auto-reconnects with Last-Event-ID (native EventSource behavior).
 * Emits typed callbacks via a simple event-emitter pattern.
 */

import { getApiKey } from "@/api/client";
import type { LifecycleEvent, LifecycleEventType, SimSnapshot } from "@/types/api";

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (typeof window !== "undefined" ? window.location.origin : "");

export interface EventStreamHandlers {
  onSnapshot?: (snapshot: SimSnapshot) => void;
  onEvent?: (event: LifecycleEvent) => void;
  onStateChanged?: (event: LifecycleEvent) => void;
  onAction?: (event: LifecycleEvent) => void;
  onRoundEnd?: (event: LifecycleEvent) => void;
  onError?: (event: LifecycleEvent) => void;
  onHeartbeat?: (event: LifecycleEvent) => void;
  onTerminal?: (event: LifecycleEvent) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onConnectionError?: (err: Event) => void;
}

export class SimulationEventStream {
  private es: EventSource | null = null;
  private closed = false;

  constructor(
    private simulationId: string,
    private handlers: EventStreamHandlers,
    private lastEventId?: number,
  ) {
    this.open();
  }

  private open(): void {
    const key = getApiKey();
    const params = new URLSearchParams();
    if (key) params.set("api_key", key);
    if (this.lastEventId !== undefined) params.set("since", String(this.lastEventId));
    const qs = params.toString();
    const url = `${BASE_URL}/api/simulation/${this.simulationId}/events${qs ? "?" + qs : ""}`;

    // withCredentials: true ensures Better Auth session cookies are sent
    // cross-subdomain (e.g. deepmiro.org ↔ app.deepmiro.org). The backend
    // and hosted layer are configured with SameSite=None + Secure.
    this.es = new EventSource(url, { withCredentials: true });

    this.es.addEventListener("open", () => {
      this.handlers.onOpen?.();
    });

    this.es.addEventListener("snapshot", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SimSnapshot;
        this.handlers.onSnapshot?.(data);
      } catch (err) {
        console.warn("Malformed snapshot payload:", err);
      }
    });

    const dispatch = (type: LifecycleEventType, e: MessageEvent) => {
      try {
        const evt = JSON.parse(e.data) as LifecycleEvent;
        this.handlers.onEvent?.(evt);
        switch (type) {
          case "STATE_CHANGED":
            this.handlers.onStateChanged?.(evt);
            // terminal check
            const newState = String(evt.payload?.to ?? "");
            if (["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(newState)) {
              this.handlers.onTerminal?.(evt);
            }
            break;
          case "ACTION":
          case "POST":
            this.handlers.onAction?.(evt);
            break;
          case "ROUND_END":
            this.handlers.onRoundEnd?.(evt);
            break;
          case "ERROR":
            this.handlers.onError?.(evt);
            break;
          case "HEARTBEAT":
            this.handlers.onHeartbeat?.(evt);
            break;
        }
      } catch (err) {
        console.warn(`Malformed ${type} event:`, err);
      }
    };

    const eventTypes: LifecycleEventType[] = [
      "STATE_CHANGED",
      "ACTION",
      "ROUND_END",
      "ERROR",
      "HEARTBEAT",
      "POST",
      "REPLAY_TRUNCATED",
    ];
    for (const type of eventTypes) {
      this.es.addEventListener(type, (e) => dispatch(type, e as MessageEvent));
    }

    this.es.onerror = (err) => {
      if (this.closed) return;
      this.handlers.onConnectionError?.(err);
      // EventSource auto-reconnects; we don't explicitly reopen.
    };
  }

  close(): void {
    this.closed = true;
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this.handlers.onClose?.();
  }
}
