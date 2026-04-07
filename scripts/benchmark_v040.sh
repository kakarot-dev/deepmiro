#!/bin/bash
# =============================================================
# DeepMiro v0.4.0 Benchmark Script
# Run on jenny (VPS) via: nohup bash benchmark_v040.sh &> /opt/mirofish/bench_v040.log &
# =============================================================
set -euo pipefail

KUBECONFIG=/etc/rancher/k3s/k3s.yaml
export KUBECONFIG

TAG="v0.4.0"
NAMESPACE="default"
BACKEND_DEPLOY="deepmiro-backend"
API_URL="http://localhost:5000"
BENCH_DIR="/opt/mirofish/bench_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BENCH_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$BENCH_DIR/bench.log"; }

# ----- Step 1: Deploy v0.4.0 -----
log "=== Deploying $TAG ==="
kubectl set image deployment/$BACKEND_DEPLOY \
  backend=ghcr.io/kakarot-dev/deepmiro-engine:$TAG \
  --namespace=$NAMESPACE

log "Waiting for rollout..."
kubectl rollout status deployment/$BACKEND_DEPLOY --namespace=$NAMESPACE --timeout=120s
log "Rollout complete."

# Wait for backend to be healthy
for i in $(seq 1 30); do
  if curl -sf "$API_URL/api/health" > /dev/null 2>&1; then
    log "Backend healthy."
    break
  fi
  sleep 2
done

# ----- Step 2: Record baseline -----
log "=== Recording system baseline ==="
free -h | tee "$BENCH_DIR/mem_before.txt"
kubectl top pods --namespace=$NAMESPACE 2>/dev/null | tee "$BENCH_DIR/pods_before.txt" || true

# ----- Step 3: Create simulation via API -----
# Use a small test prompt (no PDF upload needed for benchmark)
log "=== Creating benchmark simulation ==="
SIM_RESPONSE=$(curl -sf -X POST "$API_URL/api/simulation/create" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze the social media reputation of Wuhan University. Consider student sentiment, faculty research output, campus culture, and international rankings. Include perspectives from current students, alumni, prospective students, media commentators, and university administrators.",
    "preset": "standard",
    "enable_twitter": true,
    "enable_reddit": true
  }')

SIM_ID=$(echo "$SIM_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('simulation_id',''))" 2>/dev/null)

if [ -z "$SIM_ID" ]; then
  log "ERROR: Failed to create simulation. Response: $SIM_RESPONSE"
  exit 1
fi
log "Simulation created: $SIM_ID"
echo "$SIM_ID" > "$BENCH_DIR/sim_id.txt"

# ----- Step 4: Poll until complete -----
log "=== Polling simulation status ==="
START_TIME=$(date +%s)

while true; do
  STATUS_RESP=$(curl -sf "$API_URL/api/simulation/$SIM_ID/status" 2>/dev/null || echo '{}')
  STATUS=$(echo "$STATUS_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null)
  ROUND=$(echo "$STATUS_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('run_state',{}); print(f\"{r.get('current_round',0)}/{r.get('total_rounds',0)}\")" 2>/dev/null)

  ELAPSED=$(( $(date +%s) - START_TIME ))

  log "  Status: $STATUS | Round: $ROUND | Elapsed: ${ELAPSED}s"

  # Capture memory mid-sim
  if [ "$((ELAPSED % 60))" -lt 10 ]; then
    kubectl top pods --namespace=$NAMESPACE 2>/dev/null >> "$BENCH_DIR/pods_during.txt" || true
  fi

  case "$STATUS" in
    completed|report_ready|report_generated)
      log "=== Simulation completed! ==="
      break
      ;;
    failed|error)
      log "ERROR: Simulation failed."
      echo "$STATUS_RESP" > "$BENCH_DIR/error.json"
      break
      ;;
  esac

  sleep 10
done

END_TIME=$(date +%s)
TOTAL_ELAPSED=$(( END_TIME - START_TIME ))

# ----- Step 5: Capture results -----
log "=== Results ==="
log "Total wall-clock time: ${TOTAL_ELAPSED}s ($(( TOTAL_ELAPSED / 60 ))m $(( TOTAL_ELAPSED % 60 ))s)"

free -h | tee "$BENCH_DIR/mem_after.txt"
kubectl top pods --namespace=$NAMESPACE 2>/dev/null | tee "$BENCH_DIR/pods_after.txt" || true

# Grab simulation logs for timing breakdown
BACKEND_POD=$(kubectl get pods -l app=$BACKEND_DEPLOY --namespace=$NAMESPACE -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$BACKEND_POD" ]; then
  kubectl logs "$BACKEND_POD" --namespace=$NAMESPACE --tail=500 2>/dev/null | \
    grep -E "(Round|step=|fetch=|total=|模拟循环完成|AVM|semaphore|Rec table)" \
    > "$BENCH_DIR/timing_lines.txt" 2>/dev/null || true
fi

# Save final status
echo "$STATUS_RESP" > "$BENCH_DIR/final_status.json"

log "=== Benchmark complete ==="
log "Results saved to: $BENCH_DIR"
log ""
log "Key metrics:"
log "  Wall-clock time: ${TOTAL_ELAPSED}s"
log "  Simulation ID:   $SIM_ID"
log "  Timing breakdown: $BENCH_DIR/timing_lines.txt"
log "  Memory snapshots: $BENCH_DIR/pods_*.txt"
