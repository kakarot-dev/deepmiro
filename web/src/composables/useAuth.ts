/**
 * useAuth — detect session-based auth (Better Auth cookie) vs API key.
 *
 * On hosted deployments (app.deepmiro.org), the user logs in on
 * deepmiro.org and gets a cross-subdomain session cookie. The backend's
 * hosted-layer proxy reads the cookie and injects X-User-Id. From the
 * frontend's perspective, we just need to know "am I authenticated?"
 * so we can skip the API key paste prompt.
 *
 * On self-hosted / dev deployments, there's no session — the user pastes
 * their API key once (stored in localStorage) and every request uses it.
 */

import { ref, onMounted } from "vue";
import { http, hasApiKey } from "@/api/client";

interface SessionResponse {
  user?: {
    id: string;
    email?: string;
    name?: string;
  };
  session?: {
    id: string;
  };
}

export type AuthMode = "session" | "api_key" | "unauthenticated";

export function useAuth() {
  const mode = ref<AuthMode>("unauthenticated");
  const userEmail = ref<string | null>(null);
  const userName = ref<string | null>(null);
  const checking = ref(true);

  async function check(): Promise<AuthMode> {
    checking.value = true;
    // 1. Check for a session cookie via Better Auth endpoint
    try {
      const { data } = await http.get<SessionResponse>(
        "/api/auth/get-session",
        { withCredentials: true, timeout: 5000 },
      );
      if (data?.user?.id) {
        mode.value = "session";
        userEmail.value = data.user.email ?? null;
        userName.value = data.user.name ?? null;
        checking.value = false;
        return "session";
      }
    } catch {
      // No session or auth endpoint unavailable → fall through to API key
    }

    // 2. Check for stored API key
    if (hasApiKey()) {
      mode.value = "api_key";
      checking.value = false;
      return "api_key";
    }

    mode.value = "unauthenticated";
    checking.value = false;
    return "unauthenticated";
  }

  onMounted(() => {
    check();
  });

  function signInUrl(redirect?: string): string {
    const target = redirect ?? window.location.href;
    return `https://deepmiro.org/login?redirect=${encodeURIComponent(target)}`;
  }

  return {
    mode,
    userEmail,
    userName,
    checking,
    check,
    signInUrl,
  };
}
