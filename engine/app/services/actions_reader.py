"""
actions_reader — pure readers over the actions.jsonl files written by the
sim subprocess.

These are queries, not lifecycle-concerned. They were previously bolted
onto SimulationRunner; extracted here so SimulationRunner is purely about
subprocess management + event emission.

Output is plain dicts. No dataclasses, no enums — the Flask handlers and
MCP tool serialize to JSON directly.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from ..config import Config

logger = logging.getLogger("mirofish.actions_reader")


def _sim_dir(simulation_id: str) -> str:
    return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)


def _read_actions_from_file(
    file_path: str,
    default_platform: Optional[str] = None,
    platform_filter: Optional[str] = None,
    agent_id: Optional[int] = None,
    round_num: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Read action records from a single JSONL file.

    Skips event entries (round_start, round_end, simulation_end) and
    records without an agent_id. Returns a list of action dicts with
    normalized keys:
      round_num, timestamp, platform, agent_id, agent_name,
      action_type, action_args, result, success
    """
    if not os.path.exists(file_path):
        return []

    actions: list[dict[str, Any]] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Skip event entries (simulation_start, round_start, round_end, simulation_end)
            if "event_type" in data:
                continue
            # Skip records without agent_id (non-agent actions)
            if "agent_id" not in data:
                continue

            record_platform = data.get("platform") or default_platform or ""

            # Apply filters
            if platform_filter and record_platform != platform_filter:
                continue
            if agent_id is not None and data.get("agent_id") != agent_id:
                continue
            if round_num is not None and data.get("round") != round_num:
                continue

            actions.append({
                "round_num": data.get("round", 0),
                "timestamp": data.get("timestamp", ""),
                "platform": record_platform,
                "agent_id": data.get("agent_id", 0),
                "agent_name": data.get("agent_name", ""),
                "action_type": data.get("action_type", ""),
                "action_args": data.get("action_args", {}),
                "result": data.get("result"),
                "success": data.get("success", True),
            })

    return actions


def get_all_actions(
    simulation_id: str,
    platform: Optional[str] = None,
    agent_id: Optional[int] = None,
    round_num: Optional[int] = None,
) -> list[dict[str, Any]]:
    """All actions across both platforms, sorted newest-first.

    Args:
        simulation_id: sim ID
        platform: filter ('twitter' or 'reddit'; None = both)
        agent_id: filter by agent id
        round_num: filter by round

    Returns:
        list of action dicts, sorted by timestamp descending.
    """
    sim_dir = _sim_dir(simulation_id)
    actions: list[dict[str, Any]] = []

    if not platform or platform == "twitter":
        actions.extend(_read_actions_from_file(
            os.path.join(sim_dir, "twitter", "actions.jsonl"),
            default_platform="twitter",
            platform_filter=platform,
            agent_id=agent_id,
            round_num=round_num,
        ))

    if not platform or platform == "reddit":
        actions.extend(_read_actions_from_file(
            os.path.join(sim_dir, "reddit", "actions.jsonl"),
            default_platform="reddit",
            platform_filter=platform,
            agent_id=agent_id,
            round_num=round_num,
        ))

    # Legacy single-file fallback for sims from before the per-platform split
    if not actions:
        actions = _read_actions_from_file(
            os.path.join(sim_dir, "actions.jsonl"),
            default_platform=None,
            platform_filter=platform,
            agent_id=agent_id,
            round_num=round_num,
        )

    actions.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return actions


def get_actions(
    simulation_id: str,
    limit: int = 100,
    offset: int = 0,
    platform: Optional[str] = None,
    agent_id: Optional[int] = None,
    round_num: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Paged slice of the full action list."""
    actions = get_all_actions(
        simulation_id=simulation_id,
        platform=platform,
        agent_id=agent_id,
        round_num=round_num,
    )
    return actions[offset:offset + limit]


def get_recent_posts(simulation_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Last N content-producing actions (CREATE_POST / CREATE_COMMENT / QUOTE_POST).

    Used by the /status endpoint to give MCP + frontend narration material
    without them having to paginate all actions.
    """
    all_actions = get_all_actions(simulation_id)
    posts = [
        a for a in all_actions
        if a.get("action_type") in ("CREATE_POST", "CREATE_COMMENT", "QUOTE_POST")
        and a.get("action_args", {}).get("content")
    ]
    # Already sorted newest-first by get_all_actions
    return posts[:limit]


def get_timeline(
    simulation_id: str,
    start_round: int = 0,
    end_round: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Per-round summary. Aggregates actions by round with agent + type counts."""
    actions = get_all_actions(simulation_id)
    rounds: dict[int, dict[str, Any]] = {}

    for action in actions:
        r = int(action.get("round_num") or 0)
        if r < start_round:
            continue
        if end_round is not None and r > end_round:
            continue

        if r not in rounds:
            rounds[r] = {
                "round_num": r,
                "twitter_actions": 0,
                "reddit_actions": 0,
                "active_agents": set(),
                "action_types": {},
                "first_action_time": action["timestamp"],
                "last_action_time": action["timestamp"],
            }

        bucket = rounds[r]
        if action["platform"] == "twitter":
            bucket["twitter_actions"] += 1
        elif action["platform"] == "reddit":
            bucket["reddit_actions"] += 1

        bucket["active_agents"].add(action["agent_id"])
        atype = action["action_type"]
        bucket["action_types"][atype] = bucket["action_types"].get(atype, 0) + 1
        bucket["last_action_time"] = action["timestamp"]

    result: list[dict[str, Any]] = []
    for r in sorted(rounds.keys()):
        b = rounds[r]
        result.append({
            "round_num": r,
            "twitter_actions": b["twitter_actions"],
            "reddit_actions": b["reddit_actions"],
            "total_actions": b["twitter_actions"] + b["reddit_actions"],
            "active_agents_count": len(b["active_agents"]),
            "active_agents": sorted(b["active_agents"]),
            "action_types": b["action_types"],
            "first_action_time": b["first_action_time"],
            "last_action_time": b["last_action_time"],
        })
    return result


def get_agent_stats(simulation_id: str) -> list[dict[str, Any]]:
    """Per-agent action statistics, sorted by total activity desc."""
    actions = get_all_actions(simulation_id)
    stats: dict[int, dict[str, Any]] = {}

    for action in actions:
        agent_id = action["agent_id"]
        if agent_id not in stats:
            stats[agent_id] = {
                "agent_id": agent_id,
                "agent_name": action["agent_name"],
                "total_actions": 0,
                "twitter_actions": 0,
                "reddit_actions": 0,
                "action_types": {},
                "first_action_time": action["timestamp"],
                "last_action_time": action["timestamp"],
            }
        s = stats[agent_id]
        s["total_actions"] += 1
        if action["platform"] == "twitter":
            s["twitter_actions"] += 1
        elif action["platform"] == "reddit":
            s["reddit_actions"] += 1
        atype = action["action_type"]
        s["action_types"][atype] = s["action_types"].get(atype, 0) + 1
        s["last_action_time"] = action["timestamp"]

    return sorted(stats.values(), key=lambda x: x["total_actions"], reverse=True)
