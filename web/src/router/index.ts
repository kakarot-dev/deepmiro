import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { hasApiKey, http } from "@/api/client";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "setup",
    component: () => import("@/views/SetupView.vue"),
  },
  {
    path: "/history",
    name: "history",
    component: () => import("@/views/HistoryView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/sim/:simId",
    name: "sim",
    component: () => import("@/views/SimulationRunView.vue"),
    props: true,
    meta: { requiresAuth: true },
  },
  {
    path: "/sim/:simId/report",
    name: "report",
    component: () => import("@/views/ReportView.vue"),
    props: true,
    meta: { requiresAuth: true },
  },
  {
    path: "/:pathMatch(.*)*",
    redirect: "/",
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

/**
 * Auth guard — routes with `meta.requiresAuth` need either a Better Auth
 * session cookie OR a stored API key. Cached session check to avoid
 * hitting the backend on every navigation.
 */
let cachedSessionValid: boolean | null = null;
let cachedAt = 0;
const SESSION_CACHE_MS = 30_000;

async function hasValidSession(): Promise<boolean> {
  const now = Date.now();
  if (cachedSessionValid !== null && now - cachedAt < SESSION_CACHE_MS) {
    return cachedSessionValid;
  }
  try {
    const { data } = await http.get("/api/auth/get-session", {
      withCredentials: true,
      timeout: 4000,
      validateStatus: (s) => s >= 200 && s < 500,
    });
    const valid = !!(data as { user?: { id?: string } } | null)?.user?.id;
    cachedSessionValid = valid;
    cachedAt = now;
    return valid;
  } catch {
    cachedSessionValid = false;
    cachedAt = now;
    return false;
  }
}

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth) return true;
  if (hasApiKey()) return true;
  const sessionOk = await hasValidSession();
  if (sessionOk) return true;
  // Redirect to setup which will prompt for API key or sign-in link
  return {
    name: "setup",
    query: { redirect: to.fullPath },
  };
});
