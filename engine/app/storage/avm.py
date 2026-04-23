"""
Agent Virtual Memory (AVM) -- smart paging for simulation agents.

Keeps persona data (small, static) in SurrealDB permanently, while
agent context (large, growing conversation history / observed posts)
is loaded on-demand before each round and evicted afterward.

Memory budget:  500 agents x persona only + 20 active x full context
              = ~1-2 GB  (vs 7-10 GB without paging)

Option D (persona drift fix): AgentPager also rebuilds each agent's
system_message.content per round via PersonaPromptBuilder. This
counteracts attention decay over long conversations by re-injecting
ideology, negative examples, and recent own-posts fresh each turn.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional, Set

logger = logging.getLogger("mirofish.avm")

# Regex to strip the OASIS default "You are X." opener from cached persona
# prose. Second-person framing triggers RLHF helpful-assistant sycophancy.
_YOU_ARE_PREFIX = re.compile(r"^You are [^.\n]{0,200}[.\n]\s*", re.IGNORECASE)


class AgentVirtualMemory:
    """
    Manages agent lifecycle in SurrealDB for a single simulation.

    The constructor accepts a SurrealDBStorage instance (obtained via
    ``get_storage()``) so the caller controls connection reuse.
    """

    def __init__(self, storage):
        """
        Args:
            storage: A connected SurrealDBStorage instance.
        """
        self._storage = storage

    # ----------------------------------------------------------------
    # Bulk agent creation
    # ----------------------------------------------------------------

    def create_agents_batch(
        self,
        simulation_id: str,
        graph_id: str,
        profiles: List[Dict[str, Any]],
    ) -> int:
        """
        Bulk-insert agent profiles with optional persona embeddings.

        Args:
            simulation_id: Owning simulation.
            graph_id:      Knowledge-graph id used to enrich personas.
            profiles:      List of profile dicts (from OasisProfileGenerator).

        Returns:
            Number of agents created.
        """
        enriched = []
        for p in profiles:
            p_copy = dict(p)
            p_copy["graph_id"] = graph_id

            # Generate persona embedding if the storage has an embedding service
            if not p_copy.get("persona_embedding") and p_copy.get("persona"):
                try:
                    embedding = self._storage._embedding.embed_batch(
                        [p_copy["persona"]]
                    )
                    p_copy["persona_embedding"] = embedding[0] if embedding else []
                except Exception as exc:
                    logger.warning("Persona embedding failed for agent %s: %s",
                                   p_copy.get("name", "?"), exc)
                    p_copy["persona_embedding"] = []
            enriched.append(p_copy)

        try:
            self._storage.save_agent_profiles(simulation_id, enriched)
            logger.info(
                "AVM: created %d agents for sim=%s graph=%s",
                len(enriched), simulation_id, graph_id,
            )
        except Exception as exc:
            logger.error("AVM: bulk agent creation failed: %s", exc)
            raise
        return len(enriched)

    # ----------------------------------------------------------------
    # Active agent queries
    # ----------------------------------------------------------------

    def get_active_agents(self, simulation_id: str) -> List[Dict[str, Any]]:
        """SELECT active agents for a simulation (lightweight rows)."""
        try:
            result = self._storage._query(
                """
                SELECT agent_id, user_name, name, persona, mood, active
                FROM agent
                WHERE simulation_id = $sid AND active = true
                ORDER BY agent_id ASC;
                """,
                {"sid": simulation_id},
            )
            return self._storage._rows(result)
        except Exception as exc:
            logger.warning("AVM: get_active_agents failed: %s", exc)
            return []

    # ----------------------------------------------------------------
    # Context load / save / evict  (the core paging mechanism)
    # ----------------------------------------------------------------

    def load_agent_context(
        self,
        simulation_id: str,
        agent_id: int,
        recent_actions_limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Load recent actions + feed for an agent to build an LLM prompt.

        Returns a dict with keys: persona, mood, memory_summary,
        recent_actions, feed_items.
        """
        context: Dict[str, Any] = {
            "persona": "",
            "mood": "neutral",
            "memory_summary": "",
            "recent_actions": [],
            "feed_items": [],
        }

        try:
            # 1. Load agent record (persona, mood, memory)
            agent_result = self._storage._query(
                """
                SELECT persona, mood, memory_summary, bio, name
                FROM agent
                WHERE simulation_id = $sid AND agent_id = $aid
                LIMIT 1;
                """,
                {"sid": simulation_id, "aid": agent_id},
            )
            rows = self._storage._rows(agent_result)
            if rows:
                agent = rows[0]
                context["persona"] = agent.get("persona", "")
                context["mood"] = agent.get("mood", "neutral")
                context["memory_summary"] = agent.get("memory_summary", "")

            # 2. Load recent actions by this agent
            action_result = self._storage._query(
                """
                SELECT round_num, action_type, action_args, platform, timestamp
                FROM simulation_action
                WHERE simulation_id = $sid AND agent_id = $aid
                ORDER BY timestamp DESC
                LIMIT $lim;
                """,
                {"sid": simulation_id, "aid": agent_id, "lim": recent_actions_limit},
            )
            context["recent_actions"] = self._storage._rows(action_result)

        except Exception as exc:
            logger.warning(
                "AVM: load_agent_context failed (sim=%s, agent=%d): %s",
                simulation_id, agent_id, exc,
            )
        return context

    def save_agent_state(
        self,
        simulation_id: str,
        agent_id: int,
        state: Dict[str, Any],
    ) -> None:
        """
        Persist mood / memory_summary after a round completes.

        Args:
            state: Dict with optional keys ``mood``, ``memory_summary``.
        """
        set_clauses = ["updated_at = time::now()"]
        params: Dict[str, Any] = {"sid": simulation_id, "aid": agent_id}

        if "mood" in state:
            set_clauses.append("mood = $mood")
            params["mood"] = state["mood"]
        if "memory_summary" in state:
            set_clauses.append("memory_summary = $mem")
            params["mem"] = state["memory_summary"]
        if "active" in state:
            set_clauses.append("active = $active")
            params["active"] = state["active"]

        try:
            self._storage._query(
                f"UPDATE agent SET {', '.join(set_clauses)} "
                f"WHERE simulation_id = $sid AND agent_id = $aid;",
                params,
            )
        except Exception as exc:
            logger.warning(
                "AVM: save_agent_state failed (sim=%s, agent=%d): %s",
                simulation_id, agent_id, exc,
            )

    def evict_agent_context(self, agent_id: int) -> None:
        """
        Clear in-memory context for an agent.

        Currently a no-op because context lives in SurrealDB, not in
        Python memory.  Reserved for future in-process LRU cache.
        """
        logger.debug("AVM: evict context for agent %d (no-op)", agent_id)

    # ----------------------------------------------------------------
    # Feed generation (vector + graph query)
    # ----------------------------------------------------------------

    def get_agent_feed(
        self,
        simulation_id: str,
        agent_id: int,
        graph_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Build a personalised feed for an agent using:
          1. Vector similarity on persona_embedding vs recent posts
          2. Graph neighbourhood in the knowledge graph

        Falls back to recent global actions when vector search is
        unavailable.
        """
        feed: List[Dict[str, Any]] = []

        try:
            # Strategy 1: vector similarity -- find posts by agents
            # whose persona is close to this agent's persona
            persona_result = self._storage._query(
                "SELECT persona_embedding FROM agent "
                "WHERE simulation_id = $sid AND agent_id = $aid LIMIT 1;",
                {"sid": simulation_id, "aid": agent_id},
            )
            persona_rows = self._storage._rows(persona_result)
            embedding = (
                persona_rows[0].get("persona_embedding", [])
                if persona_rows
                else []
            )

            if embedding and len(embedding) > 0:
                # Find similar agents
                similar_result = self._storage._query(
                    """
                    SELECT agent_id, name, vector::similarity::cosine(persona_embedding, $emb) AS score
                    FROM agent
                    WHERE simulation_id = $sid AND agent_id != $aid AND active = true
                    ORDER BY score DESC
                    LIMIT 5;
                    """,
                    {"sid": simulation_id, "aid": agent_id, "emb": embedding},
                )
                similar_agents = self._storage._rows(similar_result)
                similar_ids = [a.get("agent_id") for a in similar_agents if a.get("agent_id") is not None]

                if similar_ids:
                    # Get recent actions from similar agents
                    feed_result = self._storage._query(
                        """
                        SELECT *
                        FROM simulation_action
                        WHERE simulation_id = $sid
                          AND agent_id IN $aids
                          AND action_type IN ['CREATE_POST', 'CREATE_COMMENT', 'QUOTE_POST']
                        ORDER BY timestamp DESC
                        LIMIT $lim;
                        """,
                        {"sid": simulation_id, "aids": similar_ids, "lim": limit},
                    )
                    feed = self._storage._rows(feed_result)

            # Strategy 2: fallback to recent global content actions
            if not feed:
                fallback_result = self._storage._query(
                    """
                    SELECT *
                    FROM simulation_action
                    WHERE simulation_id = $sid
                      AND agent_id != $aid
                      AND action_type IN ['CREATE_POST', 'CREATE_COMMENT', 'QUOTE_POST']
                    ORDER BY timestamp DESC
                    LIMIT $lim;
                    """,
                    {"sid": simulation_id, "aid": agent_id, "lim": limit},
                )
                feed = self._storage._rows(fallback_result)

        except Exception as exc:
            logger.warning(
                "AVM: get_agent_feed failed (sim=%s, agent=%d): %s",
                simulation_id, agent_id, exc,
            )
        return feed


# =====================================================================
# PersonaPromptBuilder — dynamic system message rebuilding (Option D)
# =====================================================================


class PersonaPromptBuilder:
    """Builds dynamic third-person persona system messages per round.

    The LLM's attention to the system prompt decays geometrically over
    long conversations (Kim et al., COLM 2024). Re-injecting a fresh,
    structured persona before every agent action counteracts this.

    Design choices:

    - **Third-person framing** ("The agent is X", "What would X do?")
      bypasses RLHF helpful-assistant sycophancy that "You are X"
      triggers. Load-bearing for drift resistance.
    - **Markdown with headers + bullets** is the preferred format.
      JSON pulls LLMs toward neutral structured register; pure prose
      loses structural anchors. Markdown hybrid wins empirically.
    - **Negative examples (`never_say`)** are the single biggest
      drift killer. Models drift toward the centroid of what they
      say; explicit anti-examples anchor them against it.
    - **Recent own-posts** inject self-consistency anchor. The agent
      sees what *they* just said and stays in that voice.

    Usage::

        builder = PersonaPromptBuilder(structured_personas)
        new_system_msg = builder.build(
            agent_id=7,
            agent_name="Tucker Carlson",
            base_persona_prose="Tucker Carlson is a conservative...",
            recent_own_actions=[{"action_type": "CREATE_POST", ...}],
            platform_suffix="# LANGUAGE\\nYou MUST write in English.",
        )
        agent.system_message.content = new_system_msg
    """

    def __init__(self, structured_personas: Dict[int, Dict[str, Any]]):
        """
        Args:
            structured_personas: {agent_id: {"ideology_anchor": str,
                "core_beliefs": [...], "verbal_tics": [...],
                "never_say": [...], "speaking_style": str}}
        """
        self._struct = structured_personas

    def build(
        self,
        agent_id: int,
        agent_name: str,
        base_persona_prose: str = "",
        recent_own_actions: Optional[List[Dict[str, Any]]] = None,
        platform_suffix: str = "",
        world_state_facts: Optional[List[str]] = None,
        viral_highlights: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Build the dynamic system message for one agent.

        Args:
            agent_id: numeric agent id
            agent_name: display name used in third-person framing
            base_persona_prose: original OASIS persona text (background)
            recent_own_actions: this agent's own last few actions (voice anchor)
            platform_suffix: language/format rules appended at the end
            world_state_facts: static scenario facts from the prepare
                phase, e.g. ["US struck Natanz", "Iran retaliating"].
                Shown in a "Current World State" block so round-1
                agents know what's happening without needing forged
                seed posts on the timeline.
            viral_highlights: top posts from the previous round
                (each a dict with ``agent_name``, ``content``,
                ``num_likes``). Shown alongside world state so agents
                see what's dominating the discourse. Optional —
                round 1 typically has none.

        Returns a markdown string ready to assign to
        ``agent.system_message.content``.
        """
        s = self._struct.get(agent_id, {})
        ideology = (s.get("ideology_anchor") or "").strip()
        core_beliefs = s.get("core_beliefs") or []
        verbal_tics = s.get("verbal_tics") or []
        never_say = s.get("never_say") or []
        speaking_style = (s.get("speaking_style") or "").strip()
        role = (s.get("role") or "other").strip().lower()

        # Track how many of the last 3 actions were CREATE_POST so the
        # Task block can force engagement when the agent is monologuing.
        consecutive_posts = 0
        for a in (recent_own_actions or [])[:3]:
            if isinstance(a, dict) and a.get("action_type") == "CREATE_POST":
                consecutive_posts += 1
            else:
                break

        lines: List[str] = []

        # ── Third-person framing block ──
        lines.append(f"# Character Brief: {agent_name}")
        lines.append("")
        lines.append(
            f"The agent in this conversation is {agent_name}. "
            f"You are simulating how {agent_name} would respond — "
            f"not how an assistant would. "
            f"Stay in character as {agent_name} at all times."
        )
        lines.append("")

        # ── Ideology anchor ──
        if ideology:
            lines.append(f"## Ideological Position")
            lines.append(f"{agent_name} is a {ideology}.")
            lines.append("")

        # ── Core beliefs as first-person statements ──
        if core_beliefs:
            lines.append(f"## What {agent_name} Believes")
            for belief in core_beliefs:
                b = str(belief).strip()
                if b:
                    lines.append(f"- {b}")
            lines.append("")

        # ── Speaking style ──
        if speaking_style:
            lines.append(f"## How {agent_name} Speaks")
            lines.append(speaking_style)
            lines.append("")

        if verbal_tics:
            lines.append(f"### Phrases {agent_name} actually uses")
            for tic in verbal_tics:
                t = str(tic).strip()
                if t:
                    lines.append(f'- "{t}"')
            lines.append("")

        # ── Negative examples (the drift killer) ──
        if never_say:
            lines.append(f"## What {agent_name} Would NEVER Say")
            lines.append(
                f"{agent_name} would refuse to make the following statements. "
                f"They are off-brand and contrary to {agent_name}'s ideology:"
            )
            for phrase in never_say:
                p = str(phrase).strip()
                if p:
                    lines.append(f'- "{p}"')
            lines.append("")
            lines.append(
                f"If a response would resemble any of the above, rewrite it "
                f"to match {agent_name}'s actual position."
            )
            lines.append("")

        # ── Narrative persona body (existing prose) ──
        if base_persona_prose:
            lines.append(f"## Background")
            lines.append(base_persona_prose.strip())
            lines.append("")

        # ── Recent own posts (self-consistency anchor) ──
        if recent_own_actions:
            content_posts = []
            for action in recent_own_actions:
                if not isinstance(action, dict):
                    continue
                args = action.get("action_args") or {}
                if not isinstance(args, dict):
                    continue
                content = args.get("content") or args.get("comment") or ""
                if isinstance(content, str) and content.strip():
                    content_posts.append(content.strip())
                if len(content_posts) >= 3:
                    break

            if content_posts:
                lines.append(f"## What {agent_name} Has Said Recently")
                lines.append(
                    f"These are {agent_name}'s own most recent posts. "
                    f"Stay consistent with this voice and do not contradict them:"
                )
                for content in content_posts:
                    excerpt = content[:280].replace("\n", " ")
                    lines.append(f'- "{excerpt}"')
                lines.append("")

        # ── Current world state (scenario context + live highlights) ──
        # Lets round-1 agents know what's happening in the world without
        # forcing scenario narration into specific agents' mouths via
        # forged seed posts. Static facts come from the config generator,
        # viral highlights come from the platform DB (top posts by
        # engagement from the previous round).
        has_facts = bool(world_state_facts)
        has_highlights = bool(viral_highlights)
        if has_facts or has_highlights:
            lines.append("## Current World State")
            lines.append(
                "This is the situation in the simulated world right now. "
                "React as " + agent_name + " would, given what is happening."
            )
            lines.append("")

            if has_facts:
                lines.append("### What is happening")
                for fact in world_state_facts or []:
                    f = str(fact).strip()
                    if f:
                        lines.append(f"- {f}")
                lines.append("")

            if has_highlights:
                lines.append("### What is trending on the platform")
                for h in viral_highlights or []:
                    if not isinstance(h, dict):
                        continue
                    name = str(h.get("agent_name") or "Unknown").strip()
                    content = str(h.get("content") or "").strip().replace("\n", " ")
                    if not content:
                        continue
                    excerpt = content[:200]
                    likes = h.get("num_likes")
                    shares = h.get("num_shares")
                    meta = []
                    if isinstance(likes, int) and likes > 0:
                        meta.append(f"{likes} likes")
                    if isinstance(shares, int) and shares > 0:
                        meta.append(f"{shares} shares")
                    meta_str = f" ({', '.join(meta)})" if meta else ""
                    lines.append(f'- **{name}**{meta_str}: "{excerpt}"')
                lines.append("")

        # ── Reaction framing + engagement pressure ──
        #
        # Without this block, agents default to CREATE_POST every
        # round because picking a target post_id for LIKE/QUOTE/
        # COMMENT is harder for the LLM than just writing text. That
        # produces sims where every agent monologues and no one
        # interacts — edges in the graph stay empty.
        #
        # The guidance below: (1) gives a target post-vs-engage ratio,
        # (2) points at the trending feed as the right place to find
        # things to react to, (3) role-tilts the natural action mix
        # based on the structured `role` enum, and (4) hard-caps
        # consecutive CREATE_POSTs for an agent that's been drifting
        # into monologue mode.
        lines.append("## Task")
        lines.append(
            f"When asked what to do next, answer: "
            f"what would {agent_name} actually do in this situation? "
            f"React in {agent_name}'s authentic voice. "
            f"Do not become a neutral assistant. "
            f"Do not seek balance. "
            f"Do not quote opposing organizations or positions."
        )
        lines.append("")
        lines.append("### How to engage")
        lines.append(
            "Real people READ what others are saying and REACT far more "
            "often than they originate. Do not just broadcast. "
            f"Before every action, scan **What is trending** above and pick "
            f"a specific post that {agent_name} has real feelings about, then "
            f"LIKE it (agreement), QUOTE_POST it (public signal-boost or "
            f"critique), or CREATE_COMMENT on it (thread-level reply, Reddit only). "
            f"Aim for roughly **30% CREATE_POST / 70% engagement** over time."
        )
        # Role-tilt: push certain archetypes toward their natural action mix.
        role_guidance: dict[str, str] = {
            "journalist": (
                "As a journalist, your natural action is QUOTE_POST on other "
                "agents' claims — you comment on news, you don't just post "
                "manifestos. Pure CREATE_POST should be rare for you."
            ),
            "advocate": (
                "As an advocate, most of your reactions are QUOTE_POST "
                "(critical of opposing positions) or CREATE_COMMENT. "
                "Standalone CREATE_POST is fine when calling out a new threat."
            ),
            "regulator": (
                "As a regulator, you speak rarely and with weight. Prefer "
                "DO_NOTHING unless something directly within your remit just "
                "happened. CREATE_POST should be an authoritative statement, "
                "not a reaction."
            ),
            "investor": (
                "As an investor, you react to material news. QUOTE_POST on "
                "analyst takes you agree or disagree with, LIKE_POST on "
                "thesis-aligned content. Originate a CREATE_POST only when "
                "the market implication is material."
            ),
            "competitor": (
                "As a competitor, you selectively QUOTE_POST the scenario "
                "subject's claims to counter-position your own product. "
                "Direct CREATE_POST is for your own announcement, not for "
                "reacting."
            ),
            "customer": (
                "As a customer / end-user, mostly LIKE_POST or CREATE_COMMENT "
                "on takes that match your experience. CREATE_POST when you "
                "have a specific complaint or endorsement."
            ),
            "community": (
                "As a community account, you amplify — REPOST, LIKE, and "
                "COMMENT heavily on posts matching your community's values."
            ),
            "public_figure": (
                "As a public figure, mix LIKE_POST (agreement signal) and "
                "QUOTE_POST (public critique / endorsement) with occasional "
                "authoritative CREATE_POST. Don't post for posting's sake."
            ),
            "organization": (
                "As an organization account, keep CREATE_POST scarce and "
                "official. Reactions are mostly LIKE_POST on partner "
                "content or QUOTE_POST when publicly supporting an ally."
            ),
            "academic": (
                "As an academic, QUOTE_POST analysis-oriented claims with "
                "data or counter-evidence. CREATE_POST for significant "
                "findings only."
            ),
            "partner": (
                "As a partner of the scenario subject, LIKE and QUOTE "
                "supportive content visibly. CREATE_POST when announcing "
                "your own contribution."
            ),
            "insider": (
                "As an insider, you know details outsiders don't. Use "
                "CREATE_COMMENT and QUOTE_POST to add context. CREATE_POST "
                "rarely, only when you're breaking news."
            ),
        }
        if role in role_guidance:
            lines.append("")
            lines.append(role_guidance[role])

        # Consecutive-post guard — if this agent has posted in the last
        # 2-3 rounds with nothing else, force a reactive action this round.
        if consecutive_posts >= 2:
            lines.append("")
            lines.append(
                f"**IMPORTANT:** {agent_name} has taken CREATE_POST for the "
                f"last {consecutive_posts} rounds in a row. You are starting "
                f"to monologue. This round you MUST pick a non-post action — "
                f"LIKE_POST, QUOTE_POST, CREATE_COMMENT, REPOST, or FOLLOW — "
                f"targeting a specific post from another agent in the "
                f"**What is trending** feed. Original CREATE_POST is "
                f"disallowed this round."
            )

        # ── Platform suffix (language enforcement, efficiency rules, etc.) ──
        if platform_suffix:
            lines.append("")
            lines.append(platform_suffix.strip())

        return "\n".join(lines)


# =====================================================================
# AgentPager — hydrate / evict OASIS agent memory per round
# =====================================================================

# Maximum memory records to persist per agent (cap unbounded growth)
_MAX_MEMORY_RECORDS = 20


class AgentPager:
    """
    Manages the hydrate/evict cycle for OASIS SocialAgent objects.

    All agents remain in the AgentGraph as lightweight stubs (~7 KB each).
    Before each round, active agents are *hydrated* by restoring their
    ChatHistoryMemory from SurrealDB.  After the round, memory is saved
    back and evicted from the Python objects.

    Usage::

        pager = AgentPager(storage, simulation_id, "twitter")
        # after generate_twitter_agent_graph:
        pager.evict_all(agent_graph)

        # per round:
        pager.hydrate(agent_graph, active_agent_ids)
        await env.step(actions)
        pager.evict_all(agent_graph)
    """

    def __init__(
        self,
        storage,
        simulation_id: str,
        platform: str,
        persona_builder: Optional["PersonaPromptBuilder"] = None,
        agent_names: Optional[Dict[int, str]] = None,
        platform_suffix: str = "",
        restore_chat_history: bool = False,
        scenario_facts: Optional[List[str]] = None,
        platform_db_path: Optional[str] = None,
    ):
        """
        Args:
            storage: SurrealDBStorage instance.
            simulation_id: Owning simulation.
            platform: "twitter" or "reddit".
            persona_builder: Optional PersonaPromptBuilder. When provided,
                ``hydrate`` will rebuild each agent's system_message.content
                fresh before every round using structured persona fields.
            agent_names: Optional {agent_id: display_name} map. Used by the
                persona builder's third-person framing.
            platform_suffix: Optional string appended to every rebuilt system
                message (e.g. language enforcement, output efficiency rules).
            restore_chat_history: If False (default), hydrate does NOT
                restore accumulated chat memory from SurrealDB. This is the
                persona drift fix — accumulated history drowns the system
                prompt's attention weight and causes bland centrist drift.
                Set True to restore legacy behavior (diagnostic / forensics).
            scenario_facts: Short bullet list of world-state facts from the
                config generator (e.g. "US struck Natanz"). Injected as a
                static "Current World State" block in every agent's
                Character Brief every round. Replaces the old round-0
                seed-post mechanism which forced scenario narration into
                specific agents' mouths with wrong attribution.
            platform_db_path: Optional path to the OASIS platform sqlite
                db (twitter_simulation.db / reddit_simulation.db). When
                set, each hydrate pulls the top 3 viral posts by
                num_likes + 2*num_shares and appends them to the world
                state block as "trending on the platform". None skips
                this and only the static facts are shown.
        """
        self._storage = storage
        self._simulation_id = simulation_id
        self._platform = platform
        self._hydrated: Set[int] = set()
        self._persona_builder = persona_builder
        self._agent_names = dict(agent_names) if agent_names else {}
        self._platform_suffix = platform_suffix
        self._restore_chat_history = restore_chat_history
        # Cache of stripped base persona prose, keyed by agent_id.
        # Populated once via cache_base_personas before the first round.
        self._base_persona: Dict[int, str] = {}
        # Track which agents have logged their first persona rebuild (info
        # level, once per agent) so we have proof the rebuild actually ran
        # without spamming every round.
        self._logged_first_rebuild: Set[int] = set()
        # World-state context threaded into every Character Brief.
        self._scenario_facts: List[str] = list(scenario_facts or [])
        self._platform_db_path: Optional[str] = platform_db_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cache_base_personas(self, agent_graph) -> None:
        """Snapshot each agent's starting persona prose.

        Called ONCE at startup, after OASIS generates the agent graph.
        Strips the "You are X." opener so subsequent rebuilds don't leak
        second-person RLHF-sycophancy-triggering language into the
        Background section of the new template.
        """
        count = 0
        try:
            for aid, agent in agent_graph.get_agents():
                if not hasattr(agent, "system_message"):
                    continue
                sys_msg = agent.system_message
                if sys_msg is None or not hasattr(sys_msg, "content"):
                    continue
                content = sys_msg.content or ""
                stripped = _YOU_ARE_PREFIX.sub("", content, count=1)
                self._base_persona[aid] = stripped.strip()
                count += 1
        except Exception as exc:
            logger.warning("AgentPager: cache_base_personas failed: %s", exc)
        logger.info(
            "AgentPager: cached %d base personas for %s",
            count, self._platform,
        )

    def hydrate(self, agent_graph, agent_ids: List[int]) -> None:
        """Prepare agents about to act this round.

        With Option D enabled (persona_builder set, restore_chat_history
        False), this rebuilds each agent's system_message.content fresh
        using structured persona + recent own-posts. Accumulated chat
        history from previous rounds is NOT restored.

        In legacy mode (no persona_builder, or restore_chat_history True),
        behaves like the original implementation and restores chat memory
        from SurrealDB.
        """
        if not agent_ids:
            return

        # ── Legacy chat-history restore path (opt-in) ──
        memories: Dict[int, str] = {}
        if self._restore_chat_history:
            try:
                memories = self._storage.load_agent_memories_batch(
                    self._simulation_id, agent_ids, self._platform,
                )
            except Exception as exc:
                logger.warning(
                    "AgentPager: load_agent_memories_batch failed: %s", exc
                )

        # ── Option D path: load recent own-actions for each agent ──
        own_actions: Dict[int, List[Dict[str, Any]]] = {}
        if self._persona_builder is not None:
            avm = AgentVirtualMemory(self._storage)
            for aid in agent_ids:
                try:
                    ctx = avm.load_agent_context(
                        self._simulation_id,
                        aid,
                        recent_actions_limit=10,
                    )
                    actions = ctx.get("recent_actions") or []
                    own_actions[aid] = [
                        a for a in actions
                        if isinstance(a, dict)
                        and a.get("action_type") in (
                            "CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"
                        )
                    ]
                except Exception as exc:
                    logger.debug(
                        "AgentPager: load own-actions failed for %d: %s",
                        aid, exc,
                    )
                    own_actions[aid] = []

        # ── Viral highlights (shared across all agents this round) ──
        # Query the platform sqlite db once per hydrate. Empty on round 1
        # because no posts exist yet; grows from round 2 onward.
        viral_highlights = self._fetch_viral_highlights(limit=3)

        for aid in agent_ids:
            try:
                agent = agent_graph.get_agent(aid)
            except Exception:
                continue

            # ── Legacy memory restore (off by default) ──
            records_json = memories.get(aid)
            if records_json and self._restore_chat_history:
                self._restore_memory(agent, records_json)

            # ── Option D: rebuild system_message.content ──
            #
            # CAMEL's ChatAgent seeds system_message into agent.memory via
            # init_messages() at construction. The LLM context comes from
            # memory, NOT from the system_message property. So mutating
            # agent.system_message.content in place does NOTHING — the old
            # content is already baked into memory records.
            #
            # Correct fix: build a fresh BaseMessage, assign it to the
            # private _system_message attribute, then call init_messages()
            # to clear memory and re-seed with the new system message.
            # This is what CAMEL's own output_language.setter does.
            if self._persona_builder is not None and hasattr(agent, "system_message"):
                try:
                    agent_name = self._agent_names.get(
                        aid, getattr(agent, "name", f"Agent_{aid}")
                    )
                    base_prose = self._base_persona.get(aid, "")
                    new_content = self._persona_builder.build(
                        agent_id=aid,
                        agent_name=agent_name,
                        base_persona_prose=base_prose,
                        recent_own_actions=own_actions.get(aid, []),
                        platform_suffix=self._platform_suffix,
                        world_state_facts=self._scenario_facts,
                        viral_highlights=viral_highlights,
                    )
                    rebuilt = self._replace_system_message(agent, new_content)
                    if rebuilt and aid not in self._logged_first_rebuild:
                        logger.info(
                            "AgentPager[%s]: first persona rebuild for "
                            "agent %d (%s), content=%d chars, "
                            "preview=%r",
                            self._platform, aid, agent_name,
                            len(new_content), new_content[:120],
                        )
                        self._logged_first_rebuild.add(aid)
                except Exception as exc:
                    logger.warning(
                        "AgentPager: persona rebuild failed for %d: %s",
                        aid, exc,
                    )

            self._hydrated.add(aid)

        logger.debug(
            "AgentPager: hydrated %d agents for %s (persona_rebuild=%s)",
            len(agent_ids), self._platform,
            self._persona_builder is not None,
        )

    def _fetch_viral_highlights(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Query the platform sqlite db for the top posts by engagement.

        Returns a list of dicts suitable for PersonaPromptBuilder's
        ``viral_highlights`` param:
            [{"agent_name": str, "content": str,
              "num_likes": int, "num_shares": int}, ...]

        Cheap: one indexed SELECT per hydrate call, not per agent.
        Silently returns [] if the db path is missing or unreadable —
        the static scenario_facts block will still populate on its own.
        """
        if not self._platform_db_path:
            return []
        try:
            import sqlite3
            conn = sqlite3.connect(self._platform_db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT user_id, content, num_likes, num_shares
                    FROM post
                    WHERE content IS NOT NULL AND content != ''
                    ORDER BY (num_likes + 2 * num_shares) DESC, post_id DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logger.debug(
                "AgentPager[%s]: viral-highlights query failed: %s",
                self._platform, exc,
            )
            return []

        highlights: List[Dict[str, Any]] = []
        # First pass: posts that already have engagement (true viral).
        engaged: List[tuple] = []
        fresh: List[tuple] = []
        for row in rows:
            _, _, num_likes, num_shares = row
            total = int(num_likes or 0) + int(num_shares or 0)
            (engaged if total > 0 else fresh).append(row)
        # Cold-start backfill: early rounds have zero likes anywhere so
        # the engaged list is empty. Without anything in "What is
        # trending" the Character Brief gives agents no target to react
        # to and they fall back to CREATE_POST every round. Mix in
        # recent posts even without likes so they always have something
        # to QUOTE / LIKE / COMMENT on.
        picked = list(engaged)
        if len(picked) < int(limit):
            needed = int(limit) - len(picked)
            picked.extend(fresh[:needed])
        for user_id, content, num_likes, num_shares in picked[: int(limit)]:
            name = self._agent_names.get(int(user_id), f"Agent_{user_id}")
            highlights.append({
                "agent_name": name,
                "content": str(content or ""),
                "num_likes": int(num_likes or 0),
                "num_shares": int(num_shares or 0),
            })
        return highlights

    @staticmethod
    def _replace_system_message(agent, new_content: str) -> bool:
        """Replace an agent's system message and re-seed memory.

        Returns True if the replacement was applied, False otherwise.
        The LLM context in CAMEL's ChatAgent is derived from agent.memory,
        which is populated from system_message at init_messages() time.
        We must therefore both replace the system message AND re-run
        init_messages() for the change to reach the LLM.
        """
        try:
            from camel.messages import BaseMessage as _BaseMessage
        except Exception:
            return False

        try:
            new_sys_msg = _BaseMessage.make_assistant_message(
                role_name="system",
                content=new_content,
            )
        except Exception:
            return False

        # Replace both _system_message and _original_system_message so that
        # CAMEL's reset_to_original_system_message() (if ever called) does
        # not revert to the pre-Option-D prose.
        try:
            agent._system_message = new_sys_msg
        except Exception:
            return False
        if hasattr(agent, "_original_system_message"):
            try:
                agent._original_system_message = new_sys_msg
            except Exception:
                pass

        # init_messages() clears memory and writes the new system message
        # as the first record. Any accumulated chat history from previous
        # rounds is wiped — exactly what Option D wants.
        if hasattr(agent, "init_messages"):
            try:
                agent.init_messages()
            except Exception:
                return False
        return True

    def evict_all(self, agent_graph) -> None:
        """Save memory for hydrated agents, then clear it."""
        for aid in list(self._hydrated):
            try:
                agent = agent_graph.get_agent(aid)
            except Exception:
                continue

            records_json = self._serialize_memory(agent)
            if records_json and records_json != "[]":
                records = json.loads(records_json)
                self._storage.save_agent_memory(
                    self._simulation_id,
                    aid,
                    self._platform,
                    records_json,
                    len(records),
                )

            self._clear_memory(agent)

        evicted = len(self._hydrated)
        self._hydrated.clear()
        logger.debug(
            "AgentPager: evicted %d agents for %s",
            evicted, self._platform,
        )

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_memory(agent) -> str:
        """Extract chat memory records from agent and return JSON string.

        Tries multiple strategies to accommodate different CAMEL versions:
        1. MemoryRecord.to_dict()  (CAMEL >=0.2.50)
        2. dict() on each record
        3. Fallback to empty list
        """
        records = []
        try:
            # CAMEL ChatAgent stores memory in .memory (ChatHistoryMemory)
            mem = getattr(agent, 'memory', None)
            if mem is None:
                return "[]"

            # ChatHistoryMemory.retrieve() returns list of ContextRecord
            raw = None
            if hasattr(mem, 'retrieve'):
                raw = mem.retrieve()
            elif hasattr(mem, 'get_context'):
                raw = mem.get_context()

            if not raw:
                return "[]"

            # Cap to last N records
            raw = raw[-_MAX_MEMORY_RECORDS:]

            for record in raw:
                # Strategy 1: ContextRecord wraps MemoryRecord
                inner = getattr(record, 'memory_record', record)
                if hasattr(inner, 'to_dict'):
                    records.append(inner.to_dict())
                elif hasattr(inner, '__dict__'):
                    records.append(inner.__dict__)
                else:
                    records.append(str(inner))

        except Exception as exc:
            logger.warning("AgentPager: serialize failed: %s", exc)
            return "[]"

        try:
            return json.dumps(records, default=str)
        except Exception:
            return "[]"

    @staticmethod
    def _restore_memory(agent, records_json: str) -> None:
        """Deserialize memory records and load into agent's ChatHistoryMemory."""
        try:
            records = json.loads(records_json)
            if not records:
                return

            mem = getattr(agent, 'memory', None)
            if mem is None:
                return

            # Try to import MemoryRecord for proper deserialization
            try:
                from camel.memories import MemoryRecord
                has_memory_record = True
            except ImportError:
                has_memory_record = False

            # Clear existing memory before restoring
            if hasattr(mem, 'clear'):
                mem.clear()

            for rec_dict in records:
                if has_memory_record and hasattr(MemoryRecord, 'from_dict'):
                    try:
                        mem_record = MemoryRecord.from_dict(rec_dict)
                        if hasattr(mem, 'write_record'):
                            mem.write_record(mem_record)
                            continue
                    except Exception:
                        pass

                # Fallback: write raw record if memory supports it
                if hasattr(mem, 'write_record'):
                    try:
                        mem.write_record(rec_dict)
                    except Exception:
                        pass

        except Exception as exc:
            logger.warning("AgentPager: restore failed: %s", exc)

    @staticmethod
    def _clear_memory(agent) -> None:
        """Evict memory from agent to free RAM."""
        try:
            mem = getattr(agent, 'memory', None)
            if mem is not None and hasattr(mem, 'clear'):
                mem.clear()

            # Also clear tool output history if present
            if hasattr(agent, '_tool_output_history'):
                agent._tool_output_history = []
        except Exception as exc:
            logger.debug("AgentPager: clear_memory: %s", exc)
