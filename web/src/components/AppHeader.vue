<script setup lang="ts">
import { useRoute } from "vue-router";
import { computed } from "vue";
import { useAuth } from "@/composables/useAuth";

const route = useRoute();
const activeRoute = computed(() => route.name);

const { mode, userName, userEmail, signInUrl } = useAuth();

const isAuthenticated = computed(
  () => mode.value === "session" || mode.value === "api_key",
);
</script>

<template>
  <header class="app-header">
    <router-link to="/" class="brand">
      <img src="/logo.png" alt="DeepMiro" class="brand-logo" />
    </router-link>

    <nav class="app-nav">
      <router-link
        to="/"
        class="nav-link"
        :class="{ active: activeRoute === 'setup' }"
      >
        New prediction
      </router-link>
      <router-link
        v-if="isAuthenticated"
        to="/history"
        class="nav-link"
        :class="{ active: activeRoute === 'history' }"
      >
        History
      </router-link>
    </nav>

    <div class="app-account">
      <div v-if="mode === 'session'" class="account-chip">
        <span class="account-dot" />
        {{ userName || userEmail || "Signed in" }}
      </div>
      <a
        v-else-if="mode === 'unauthenticated'"
        :href="signInUrl()"
        class="sign-in"
      >
        Sign in
      </a>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--gap-lg);
  height: 56px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated);
  z-index: 10;
  position: relative;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  color: var(--fg-strong);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.brand:hover {
  color: var(--fg-strong);
}

.brand-logo {
  height: 28px;
  width: auto;
  display: block;
}

.app-nav {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
}

.nav-link {
  padding: 6px 14px;
  border-radius: var(--radius-full);
  color: var(--fg-muted);
  font-size: 13px;
  font-weight: 500;
  transition:
    color var(--duration-fast) var(--ease-out),
    background var(--duration-fast) var(--ease-out);
}

.nav-link:hover {
  color: var(--fg);
  background: var(--card);
}

.nav-link.active {
  color: var(--primary);
  background: var(--primary-muted);
}

.app-account {
  display: flex;
  align-items: center;
  margin-left: auto;
  padding-left: var(--gap-md);
}

.account-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-full);
  font-size: 12px;
  color: var(--fg-muted);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--success);
}

.sign-in {
  padding: 6px 14px;
  background: var(--primary);
  color: var(--bg);
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  transition:
    background var(--duration-fast) var(--ease-out);
}

.sign-in:hover {
  background: var(--primary-hover);
  color: var(--bg);
}
</style>
