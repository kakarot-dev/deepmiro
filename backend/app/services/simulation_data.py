"""
Simulation Data Service — pluggable interface for accessing simulation output.

Reads agent actions, engagement metrics, and round summaries from the
simulation's action logs. Default implementation reads from JSONL files.
Self-hosters can write their own adapter.
"""

import json
import os
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional

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


class JsonlSimulationData(SimulationDataService):
    """Default implementation — reads from JSONL action logs on disk."""

    def _sim_dir(self, simulation_id: str) -> str:
        return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)

    def _load_actions(self, simulation_id: str) -> List[Dict[str, Any]]:
        """Load all actions from both platform JSONL files."""
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
                            if "platform" not in action:
                                action["platform"] = platform
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


# Default instance
_instance: Optional[SimulationDataService] = None


def get_simulation_data() -> SimulationDataService:
    """Get the simulation data service singleton."""
    global _instance
    if _instance is None:
        _instance = JsonlSimulationData()
    return _instance
