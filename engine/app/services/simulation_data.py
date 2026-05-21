"""
Simulation Data Service — pluggable interface for accessing simulation output.

Reads agent actions, engagement metrics, and round summaries from the
simulation's action logs. Default implementation reads from JSONL files.
Self-hosters can write their own adapter.
"""

import hashlib
import json
import os
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional


def action_id_for(
    simulation_id: str,
    platform: str,
    agent_name: str,
    timestamp: str,
    action_type: str,
    round_num: int,
) -> str:
    """Deterministic 12-char id for a single action.

    Computed on read so we don't need a schema migration. Stable across
    runs as long as the underlying JSONL row doesn't change.
    """
    h = hashlib.sha1(
        f"{simulation_id}|{platform}|{agent_name}|{timestamp}|{action_type}|{round_num}".encode("utf-8")
    ).hexdigest()
    return h[:12]

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("deepmiro.simulation_data")


class SimulationDataService(ABC):
    """Abstract interface for simulation data access."""

    @abstractmethod
    def get_actions(
        self,
        simulation_id: str,
        platform: Optional[str] = None,
        agent_name: Optional[str] = None,
        action_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get simulation actions, optionally filtered."""

    @abstractmethod
    def get_trending(
        self, simulation_id: str, min_engagement: int = 2
    ) -> List[Dict[str, Any]]:
        """Get posts with the most engagement (likes, reposts, comments)."""

    @abstractmethod
    def get_agent_activity(self, simulation_id: str) -> Dict[str, Any]:
        """Per-agent activity stats: action counts, most active, lurkers."""

    @abstractmethod
    def get_round_summary(self, simulation_id: str) -> List[Dict[str, Any]]:
        """Per-round summaries: active agents, action counts, key events."""

    @abstractmethod
    def get_content_posts(
        self, simulation_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get actual post/comment content from agents."""

    def get_authoritative_stats(self, simulation_id: str) -> Dict[str, Any]:
        """Pre-computed counts the LLM is required to use verbatim.

        Default implementation derives stats by re-tallying the action
        log via get_actions(); subclasses may override with a cheaper
        path. Returns ground-truth totals so section prompts inject the
        numbers directly instead of asking the LLM to count rows itself
        (which has been observed to hallucinate).
        """
        # limit=10**9 effectively means "everything"; the default 50 cap
        # would silently truncate and skew the totals.
        actions = self.get_actions(simulation_id, limit=10**9)
        return _summarize_actions(simulation_id, actions)


class JsonlSimulationData(SimulationDataService):
    """Default implementation — reads from JSONL action logs on disk."""

    def _sim_dir(self, simulation_id: str) -> str:
        return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)

    def _load_actions(self, simulation_id: str) -> List[Dict[str, Any]]:
        """Load real agent actions from both platform JSONL files.

        The JSONL log interleaves two kinds of line:
          - lifecycle EVENTS — `{"event_type": "round_start", ...}`,
            round_end, simulation_start, simulation_end
          - agent ACTIONS    — `{"action_type": "CREATE_POST", ...}`

        Only the action lines are returned. Counting event lines as
        actions inflated every total the report relies on (a 90-action
        sim showed up as 178). Event lines are dropped here so every
        downstream consumer — counts, citations, the report's GROUND
        TRUTH block — sees actions only.

        Round field is normalized: the log writes `round`, but legacy
        code reads `round_num`. We copy `round` → `round_num` so both
        keys work and nothing downstream needs to change.

        Each returned action carries an `action_id` — a deterministic
        12-char digest used by the report's citation system to link a
        quote back to a specific row.
        """
        actions = []
        sim_dir = self._sim_dir(simulation_id)
        for platform in ("twitter", "reddit"):
            path = os.path.join(sim_dir, platform, "actions.jsonl")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            action = json.loads(line)
                            # Drop lifecycle event lines — only keep
                            # genuine agent actions.
                            if not action.get("action_type"):
                                continue
                            if "platform" not in action:
                                action["platform"] = platform
                            # Normalize the round field — the log writes
                            # `round`, downstream code reads `round_num`.
                            round_val = action.get("round_num")
                            if round_val is None:
                                round_val = action.get("round", 0)
                            action["round_num"] = int(round_val or 0)
                            action["action_id"] = action_id_for(
                                simulation_id=simulation_id,
                                platform=action.get("platform", platform),
                                agent_name=action.get("agent_name", ""),
                                timestamp=action.get("timestamp", ""),
                                action_type=action.get("action_type", ""),
                                round_num=action["round_num"],
                            )
                            actions.append(action)
                        except json.JSONDecodeError:
                            continue
        return actions

    def get_actions(
        self,
        simulation_id: str,
        platform: Optional[str] = None,
        agent_name: Optional[str] = None,
        action_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        actions = self._load_actions(simulation_id)
        if platform:
            actions = [a for a in actions if a.get("platform") == platform]
        if agent_name:
            q = agent_name.lower()
            actions = [a for a in actions if q in a.get("agent_name", "").lower()]
        if action_type:
            actions = [a for a in actions if a.get("action_type") == action_type]
        return actions[:limit]

    def get_trending(
        self, simulation_id: str, min_engagement: int = 2
    ) -> List[Dict[str, Any]]:
        actions = self._load_actions(simulation_id)

        # Find posts
        posts = {}
        for a in actions:
            if a.get("action_type") in ("CREATE_POST", "QUOTE_POST", "CREATE_COMMENT"):
                content = a.get("action_args", {}).get("content", "")
                if content:
                    key = (a.get("agent_name", ""), content[:100])
                    posts[key] = {
                        "agent_name": a.get("agent_name", ""),
                        "platform": a.get("platform", ""),
                        "content": content,
                        "round": a.get("round_num", 0),
                        "action_type": a.get("action_type"),
                        "likes": 0,
                        "reposts": 0,
                        "comments": 0,
                    }

        # Count engagement (simplified — counts all likes/reposts as engagement)
        like_count = Counter()
        repost_count = Counter()
        for a in actions:
            if a.get("action_type") == "LIKE_POST":
                # Attribute to most recent post in same round
                for key in posts:
                    if posts[key]["round"] <= a.get("round_num", 0):
                        posts[key]["likes"] += 1
                        break
            elif a.get("action_type") == "REPOST":
                for key in posts:
                    if posts[key]["round"] <= a.get("round_num", 0):
                        posts[key]["reposts"] += 1
                        break

        # Filter by engagement
        trending = []
        for key, post in posts.items():
            total = post["likes"] + post["reposts"] + post["comments"]
            if total >= min_engagement:
                post["total_engagement"] = total
                trending.append(post)

        return sorted(trending, key=lambda x: x["total_engagement"], reverse=True)

    def get_agent_activity(self, simulation_id: str) -> Dict[str, Any]:
        actions = self._load_actions(simulation_id)

        agent_stats = defaultdict(lambda: {"total": 0, "posts": 0, "likes": 0, "other": 0})
        for a in actions:
            name = a.get("agent_name", "Unknown")
            atype = a.get("action_type", "")
            agent_stats[name]["total"] += 1
            if atype in ("CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"):
                agent_stats[name]["posts"] += 1
            elif atype in ("LIKE_POST", "LIKE_COMMENT"):
                agent_stats[name]["likes"] += 1
            else:
                agent_stats[name]["other"] += 1

        sorted_agents = sorted(agent_stats.items(), key=lambda x: -x[1]["total"])
        most_active = [{"name": name, **stats} for name, stats in sorted_agents[:10]]
        lurkers = [name for name, stats in sorted_agents if stats["posts"] == 0]

        return {
            "total_agents": len(agent_stats),
            "total_actions": len(actions),
            "most_active": most_active,
            "lurkers": lurkers[:10],
            "lurker_count": len(lurkers),
        }

    def get_round_summary(self, simulation_id: str) -> List[Dict[str, Any]]:
        actions = self._load_actions(simulation_id)

        rounds = defaultdict(lambda: {"actions": 0, "posts": 0, "agents": set()})
        for a in actions:
            r = a.get("round_num", 0)
            rounds[r]["actions"] += 1
            rounds[r]["agents"].add(a.get("agent_name", ""))
            if a.get("action_type") in ("CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"):
                rounds[r]["posts"] += 1

        summaries = []
        for round_num in sorted(rounds.keys()):
            data = rounds[round_num]
            summaries.append({
                "round": round_num,
                "actions": data["actions"],
                "posts": data["posts"],
                "active_agents": len(data["agents"]),
            })
        return summaries

    def get_content_posts(
        self, simulation_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        actions = self._load_actions(simulation_id)
        posts = []
        for a in actions:
            if a.get("action_type") in ("CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"):
                content = a.get("action_args", {}).get("content", "")
                if content:
                    posts.append({
                        "agent_name": a.get("agent_name", ""),
                        "platform": a.get("platform", ""),
                        "action_type": a.get("action_type"),
                        "content": content,
                        "round": a.get("round_num", 0),
                    })
        return posts[:limit]

    def get_authoritative_stats(self, simulation_id: str) -> Dict[str, Any]:
        """Override the default with a direct one-pass tally."""
        return _summarize_actions(simulation_id, self._load_actions(simulation_id))


def _summarize_actions(
    simulation_id: str, actions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Roll a raw action list into the authoritative-stats shape.

    Per-agent first/last round numbers are tracked in the same pass so
    the report can render `[rounds X-Y]` confidence tags without a
    second iteration. Pre-computing here is cheaper than asking the LLM
    to filter the action log itself, and pre-computing once is cheaper
    than re-deriving in the section ReACT loop.
    """
    post_types = {"CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"}
    actions_by_type: Counter = Counter()
    actions_by_platform: Counter = Counter()
    rounds_seen: set = set()
    per_agent_actions: Counter = Counter()
    per_agent_posts: Counter = Counter()
    per_agent_first_round: Dict[str, int] = {}
    per_agent_last_round: Dict[str, int] = {}

    for a in actions:
        atype = a.get("action_type", "UNKNOWN")
        platform = a.get("platform", "unknown")
        name = a.get("agent_name", "Unknown")
        round_num = int(a.get("round_num", 0) or 0)
        actions_by_type[atype] += 1
        actions_by_platform[platform] += 1
        rounds_seen.add(round_num)
        per_agent_actions[name] += 1
        if atype in post_types:
            per_agent_posts[name] += 1
        if name not in per_agent_first_round or round_num < per_agent_first_round[name]:
            per_agent_first_round[name] = round_num
        if name not in per_agent_last_round or round_num > per_agent_last_round[name]:
            per_agent_last_round[name] = round_num

    total_actions = len(actions)
    total_posts = sum(actions_by_type[t] for t in post_types if t in actions_by_type)

    top_actors = [
        {
            "name": name,
            "actions": per_agent_actions[name],
            "posts": per_agent_posts.get(name, 0),
            "first_round": per_agent_first_round.get(name, 0),
            "last_round": per_agent_last_round.get(name, 0),
        }
        for name, _ in per_agent_actions.most_common(10)
    ]

    return {
        "simulation_id": simulation_id,
        "total_actions": total_actions,
        "total_posts": total_posts,
        "actions_by_type": dict(actions_by_type),
        "actions_by_platform": dict(actions_by_platform),
        "total_rounds": len(rounds_seen),
        "max_round": max(rounds_seen) if rounds_seen else 0,
        "total_agents_active": len(per_agent_actions),
        "top_actors": top_actors,
    }


# Default instance
_instance: Optional[SimulationDataService] = None


def get_simulation_data() -> SimulationDataService:
    """Get the simulation data service singleton."""
    global _instance
    if _instance is None:
        _instance = JsonlSimulationData()
    return _instance
