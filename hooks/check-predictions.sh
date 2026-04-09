#!/bin/bash
# DeepMiro notification hook
#
# Runs on UserPromptSubmit. Checks if any predictions completed in the background
# since the last check, and injects a systemMessage so Claude can surface it
# to the user in its next response.
#
# Fast path: bails out silently if no API key or no new completions.
# Uses a state file to avoid re-notifying about the same simulation.

set -euo pipefail

API_URL="${MIROFISH_URL:-https://api.deepmiro.org}"
API_KEY="${DEEPMIRO_API_KEY:-}"
STATE_FILE="$HOME/.claude/deepmiro-notified.txt"

# Bail fast if no credentials — user is not a DeepMiro user
if [ -z "$API_KEY" ]; then
  exit 0
fi

# Fetch recent sims (5s timeout — don't slow down user prompts)
response=$(curl -sf --max-time 5 \
  "$API_URL/api/simulation/history?limit=10" \
  -H "Authorization: Bearer $API_KEY" 2>/dev/null || echo "")

if [ -z "$response" ]; then
  exit 0
fi

# Parse completed sims. jq is required.
if ! command -v jq &>/dev/null; then
  exit 0
fi

completed=$(echo "$response" | jq -r '.data[]? | select(.status=="completed") | .simulation_id' 2>/dev/null || echo "")

if [ -z "$completed" ]; then
  exit 0
fi

# Load previously notified sims
mkdir -p "$(dirname "$STATE_FILE")"
touch "$STATE_FILE"

# Find new completions
new_sims=""
while IFS= read -r sim_id; do
  [ -z "$sim_id" ] && continue
  if ! grep -Fxq "$sim_id" "$STATE_FILE" 2>/dev/null; then
    new_sims+="$sim_id "
    echo "$sim_id" >> "$STATE_FILE"
  fi
done <<< "$completed"

if [ -z "$new_sims" ]; then
  exit 0
fi

# Build notification message
count=$(echo "$new_sims" | wc -w | tr -d ' ')
if [ "$count" = "1" ]; then
  sim_id=$(echo "$new_sims" | xargs)
  message="DeepMiro prediction $sim_id just completed. Report is ready — use get_report to view it, or tell the user their prediction is done."
else
  sim_list=$(echo "$new_sims" | xargs | sed 's/ /, /g')
  message="$count DeepMiro predictions just completed: $sim_list. Reports are ready — use get_report to view, or tell the user their predictions are done."
fi

# Emit systemMessage JSON. Claude Code injects this into the LLM's context
# for the next turn, so Claude can proactively tell the user.
jq -nc --arg msg "$message" '{systemMessage: $msg, suppressOutput: true}'
