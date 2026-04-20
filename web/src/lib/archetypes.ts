/**
 * Archetype = a persona's *type label* shown on badges/chips and used
 * for the cluster-grouping fallback.
 *
 * Earlier this file held a keyword regex resolver that bucketed every
 * persona's free-text `entity_type` into ~12 hand-rolled archetypes
 * (TechCEO, Journalist, etc.). That system was brittle: any profession
 * description that didn't match a regex fell into "Other", and once
 * the user added "short seller" / "automaker" / "insurance company"
 * personas the buckets stopped reflecting reality.
 *
 * The new approach: don't bucket at all. Each persona's archetype
 * label is just their `entity_type` text (truncated for badges).
 * Color is per-persona (lib/colors.ts) — every individual is distinct.
 *
 * Cluster edges no longer exist (they were a synthetic crutch). The
 * graph stays connected via real fact edges, scenario hub edges, and
 * the bridge fallback for orphaned nodes.
 */

import { personaColor } from "@/lib/colors";

export interface Archetype {
  /** Short, displayable label for a Badge. */
  label: string;
  /** Full text — what the LLM emitted, used in tooltips/sheets. */
  full: string;
  color: string;
}

/** Human-facing label for the fixed role taxonomy. The enum itself
 *  is stable — this is just for display. */
export const ROLE_LABELS: Record<string, string> = {
  public_figure: "Public figure",
  organization: "Organization",
  regulator: "Regulator",
  advocate: "Advocate",
  journalist: "Journalist",
  investor: "Investor",
  competitor: "Competitor",
  customer: "Customer",
  community: "Community",
  academic: "Academic",
  partner: "Partner",
  insider: "Insider",
  other: "Other",
  Scenario: "Scenario",
};

/** Tint per role — soft, desaturated. Graph node color stays
 *  per-persona; this is for badge chip backgrounds only. */
export const ROLE_COLORS: Record<string, string> = {
  public_figure: "#60a5fa",
  organization: "#fbbf24",
  regulator: "#c084fc",
  advocate: "#4ade80",
  journalist: "#fb923c",
  investor: "#facc15",
  competitor: "#f87171",
  customer: "#818cf8",
  community: "#f472b6",
  academic: "#7dd3fc",
  partner: "#2dd4bf",
  insider: "#a3e635",
  other: "#cbd5e1",
  Scenario: "#22d3ee",
};

export function labelForRole(role?: string): string {
  if (!role) return "Persona";
  return ROLE_LABELS[role] ?? role;
}

export function colorForRole(role?: string): string {
  if (!role) return ROLE_COLORS.other;
  return ROLE_COLORS[role] ?? ROLE_COLORS.other;
}

const DEFAULT_ARCHETYPE: Archetype = { label: "Persona", full: "Persona", color: "#cbd5e1" };

function shorten(s: string, max = 26): string {
  const trimmed = s.trim();
  if (trimmed.length <= max) return trimmed;
  // Try cutting at a natural break (em-dash, hyphen, comma) before max.
  const cut = trimmed.slice(0, max);
  const lastBreak = Math.max(
    cut.lastIndexOf(" — "),
    cut.lastIndexOf(" - "),
    cut.lastIndexOf(", "),
  );
  if (lastBreak > max * 0.4) return cut.slice(0, lastBreak).trim();
  return cut.replace(/\s+\S*$/, "") + "…";
}

export function resolveArchetype(entityType?: string, name?: string): Archetype {
  if (!entityType) return DEFAULT_ARCHETYPE;
  return {
    label: shorten(entityType),
    full: entityType,
    color: name ? personaColor(name) : DEFAULT_ARCHETYPE.color,
  };
}

/** Resolve archetype preferring role when present. Returns the
 *  human-readable role label from ROLE_LABELS with the role color,
 *  falling back to the free-text entity_type resolution. */
export function resolveRoleArchetype(
  role?: string,
  entityType?: string,
  name?: string,
): Archetype {
  if (role && ROLE_LABELS[role]) {
    return {
      label: ROLE_LABELS[role],
      full: entityType || ROLE_LABELS[role],
      color: ROLE_COLORS[role] ?? DEFAULT_ARCHETYPE.color,
    };
  }
  return resolveArchetype(entityType, name);
}
