/**
 * Archetype → color + label mapping.
 *
 * Node colors in the GraphPanel are keyed by the agent's entity_type
 * from the OASIS profile. Keep this list aligned with DeepMiro's
 * common ontology outputs.
 */

export interface Archetype {
  label: string;
  color: string;
  description?: string;
}

const ARCHETYPE_MAP: Record<string, Archetype> = {
  TechCEO: { label: "Tech CEO", color: "#2dd4bf" },
  TechExecutive: { label: "Tech Exec", color: "#2dd4bf" },
  TechBillionaire: { label: "Tech Billionaire", color: "#2dd4bf" },
  PlatformCompany: { label: "Platform", color: "#818cf8" },
  PlatformCeo: { label: "Platform CEO", color: "#2dd4bf" },
  PlatformModerator: { label: "Moderator", color: "#f472b6" },

  Journalist: { label: "Journalist", color: "#fb923c" },
  TechJournalist: { label: "Tech Journalist", color: "#fb923c" },
  MediaPersonality: { label: "Media", color: "#fb923c" },
  PoliticalCommentator: { label: "Commentator", color: "#fb923c" },

  Politician: { label: "Politician", color: "#c084fc" },
  GovernmentOfficial: { label: "Gov't Official", color: "#c084fc" },
  RegulatoryBody: { label: "Regulator", color: "#c084fc" },

  AdvocacyGroup: { label: "Advocacy", color: "#4ade80" },
  DigitalRightsOrganization: { label: "Digital Rights", color: "#4ade80" },
  CivilLibertiesGroup: { label: "Civil Rights", color: "#4ade80" },

  Corporation: { label: "Corporation", color: "#facc15" },
  Company: { label: "Company", color: "#facc15" },
  Brand: { label: "Brand", color: "#facc15" },
  Advertiser: { label: "Advertiser", color: "#facc15" },

  AppDeveloper: { label: "Developer", color: "#a3e635" },
  Developer: { label: "Developer", color: "#a3e635" },

  AcademicResearcher: { label: "Researcher", color: "#7dd3fc" },
  Scientist: { label: "Scientist", color: "#7dd3fc" },
  Professor: { label: "Professor", color: "#7dd3fc" },

  Subreddit: { label: "Subreddit", color: "#f472b6" },
  Community: { label: "Community", color: "#f472b6" },
  AlternativePlatform: { label: "Alt Platform", color: "#f472b6" },

  VentureCapitalist: { label: "VC", color: "#facc15" },
  FinancialAnalyst: { label: "Analyst", color: "#facc15" },

  Student: { label: "Student", color: "#cbd5e1" },
  Person: { label: "Person", color: "#cbd5e1" },
  PowerUser: { label: "Power User", color: "#f472b6" },
  ContentCreator: { label: "Creator", color: "#fb923c" },
  RedditCoFounder: { label: "Co-founder", color: "#2dd4bf" },
};

const DEFAULT_ARCHETYPE: Archetype = {
  label: "Other",
  color: "#cbd5e1",
};

/**
 * Keyword → archetype scoring. The persona's `entity_type` from the
 * profile generator is free text (e.g. "Chief Executive Officer of
 * Apple Inc." or "Investment Bank - Technology Sector Equity Research"),
 * NOT a structured enum. So we keyword-match against the lowercased
 * description and pick the archetype with the highest score.
 *
 * Each rule contributes its weight when its pattern hits. Higher
 * weights reflect higher specificity — "vc" wins over "fund" when
 * both match.
 */
const KEYWORD_RULES: { archetype: keyof typeof ARCHETYPE_MAP; pattern: RegExp; weight: number }[] = [
  // Tech leadership
  { archetype: "TechCEO", pattern: /\b(ceo|chief executive)\b/, weight: 6 },
  { archetype: "TechCEO", pattern: /\b(founder|co-founder)\b/, weight: 4 },
  { archetype: "TechExecutive", pattern: /\b(cto|cfo|coo|chief\s+\w+\s+officer|executive|president)\b/, weight: 4 },

  // Media
  { archetype: "Journalist", pattern: /\b(journalist|reporter|correspondent|editor)\b/, weight: 8 },
  { archetype: "TechJournalist", pattern: /\b(tech(nology)?\s+(journalist|reporter|writer))\b/, weight: 9 },
  { archetype: "MediaPersonality", pattern: /\b(youtube|youtuber|content creator|product reviewer|reviewer|host|podcaster)\b/, weight: 7 },
  { archetype: "PoliticalCommentator", pattern: /\b(commentator|pundit|columnist)\b/, weight: 7 },

  // Politics + government
  { archetype: "Politician", pattern: /\b(senator|representative|congressman|congresswoman|politician|mayor|governor)\b/, weight: 8 },
  { archetype: "GovernmentOfficial", pattern: /\b(government official|gov't official|official|secretary|administrator|attorney general)\b/, weight: 6 },
  { archetype: "RegulatoryBody", pattern: /\b(regulator|commission|fcc|ftc|sec|doj|department of)\b/, weight: 7 },

  // Business / finance
  { archetype: "VentureCapitalist", pattern: /\b(venture capital|vc|venture capitalist)\b/, weight: 8 },
  { archetype: "FinancialAnalyst", pattern: /\b(analyst|equity research|investment bank|wealth management|securities)\b/, weight: 7 },
  { archetype: "Corporation", pattern: /\b(corporation|conglomerate|enterprise|company|inc|corp\.?|llc|ltd|gmbh)\b/, weight: 4 },
  { archetype: "Brand", pattern: /\b(brand|advertiser|consumer brand)\b/, weight: 5 },

  // Tech / platforms / studios
  { archetype: "PlatformCompany", pattern: /\b(platform|social (network|media)|hardware (and|&) software)\b/, weight: 5 },
  { archetype: "Corporation", pattern: /\b(studio|entertainment|gaming|distribution)\b/, weight: 4 },
  { archetype: "AppDeveloper", pattern: /\b(developer|engineer|programmer|software engineer)\b/, weight: 5 },

  // Research + academia
  { archetype: "AcademicResearcher", pattern: /\b(researcher|research|scientist|phd|ph\.d|professor)\b/, weight: 6 },

  // Communities + advocacy
  { archetype: "AdvocacyGroup", pattern: /\b(advocacy|nonprofit|civil (rights|liberties)|aclu|eff)\b/, weight: 7 },
  { archetype: "Community", pattern: /\b(subreddit|community|forum|fediverse)\b/, weight: 6 },
  { archetype: "Subreddit", pattern: /\br\/\w+/, weight: 9 },
];

// Catch-alls if no keyword scored — biased toward the most common
// archetypes for a given grammatical pattern.
function fallbackArchetype(lower: string): keyof typeof ARCHETYPE_MAP | null {
  if (/\b(tech(nology)?|vr|ar|ai|software)\b/.test(lower)) return "PlatformCompany";
  if (/\b(news|media|publication)\b/.test(lower)) return "MediaPersonality";
  if (/\b(invest(ment|or)|fund|capital|bank|finance|financial)\b/.test(lower)) return "FinancialAnalyst";
  return null;
}

export function resolveArchetype(entityType?: string): Archetype {
  if (!entityType) return DEFAULT_ARCHETYPE;
  // 1. Exact key match (canonical archetype names from the DB)
  if (ARCHETYPE_MAP[entityType]) return ARCHETYPE_MAP[entityType];
  const lower = entityType.toLowerCase();
  // 2. Case-insensitive direct match
  for (const [key, value] of Object.entries(ARCHETYPE_MAP)) {
    if (key.toLowerCase() === lower) return value;
  }
  // 3. Keyword scoring on the free-text description
  let best: { archetype: keyof typeof ARCHETYPE_MAP; score: number } | null = null;
  for (const rule of KEYWORD_RULES) {
    if (rule.pattern.test(lower)) {
      const cur = best?.score ?? 0;
      if (rule.weight > cur) best = { archetype: rule.archetype, score: rule.weight };
    }
  }
  if (best && ARCHETYPE_MAP[best.archetype]) return ARCHETYPE_MAP[best.archetype];
  // 4. Heuristic fallback by domain keywords
  const fb = fallbackArchetype(lower);
  if (fb && ARCHETYPE_MAP[fb]) return ARCHETYPE_MAP[fb];
  return DEFAULT_ARCHETYPE;
}
