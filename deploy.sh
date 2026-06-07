#!/usr/bin/env bash
# Phoenix — root deploy script
#
# Builds, loads, and deploys all Phoenix services to the k3s cluster.
# Safe to re-run: apply is idempotent, rollout restart handles image refresh.
#
# Usage:
#   ./deploy.sh                        deploy everything
#   ./deploy.sh sim chaos              deploy specific services only
#   ./deploy.sh --restart              skip build+load, just restart running pods
#   ./deploy.sh --restart dashboard    restart one service only
#
# Services: sim | chaos | faultlib | graph | dashboard

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── config ────────────────────────────────────────────────────────────────────

NAMESPACE="phoenix-system"
NODES=(192.168.139.42 192.168.139.77 192.168.139.45)
SSH_KEY="$HOME/.orbstack/ssh/id_ed25519"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"

ALL_SERVICES=(sim chaos faultlib graph dashboard)

# service → image name
declare -A IMAGE=(
  [sim]=phoenix-sim
  [chaos]=phoenix-chaos
  [faultlib]=phoenix-faultlib
  [graph]=phoenix-graph
  [dashboard]=phoenix-dashboard
)

# service → k8s deployment name
declare -A DEPLOY_NAME=(
  [sim]=phoenix-sim
  [chaos]=phoenix-chaos
  [faultlib]=phoenix-faultlib
  [graph]=phoenix-graph
  [dashboard]=phoenix-dashboard
)

# services that have k8s/rbac.yaml
RBAC_SERVICES=(chaos graph)

# port-forward hints (local:remote) shown at the end
declare -A PORTS=(
  [sim]="8083:80"
  [chaos]="8082:80"
  [faultlib]="8081:80"
  [graph]="8080:80"
  [dashboard]="3000:80"
)

# ── colors ────────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}==>${NC} $*"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  !${NC} $*"; }
die()  { echo -e "${RED}  ✗${NC} $*" >&2; exit 1; }

# ── argument parsing ──────────────────────────────────────────────────────────

RESTART_ONLY=false
SELECTED=()

for arg in "$@"; do
  case "$arg" in
    --restart) RESTART_ONLY=true ;;
    sim|chaos|faultlib|graph|dashboard) SELECTED+=("$arg") ;;
    *) die "Unknown argument: $arg. Valid services: ${ALL_SERVICES[*]}" ;;
  esac
done

# Default to all services if none specified
if [ ${#SELECTED[@]} -eq 0 ]; then
  SELECTED=("${ALL_SERVICES[@]}")
fi

# ── preflight ─────────────────────────────────────────────────────────────────

preflight() {
  log "Preflight checks..."

  if ! kubectl get nodes &>/dev/null; then
    die "kubectl can't reach the cluster. Run: kubectl config use-context argus"
  fi

  if ! $RESTART_ONLY && ! docker info &>/dev/null; then
    die "Docker is not running. Open OrbStack."
  fi

  # Ensure namespace exists
  if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    log "Creating namespace $NAMESPACE..."
    kubectl apply -f "$SCRIPT_DIR/sim/k8s/namespace.yaml"
  fi

  ok "Cluster reachable · namespace $NAMESPACE ready"
}

# ── node image load (parallel across nodes) ───────────────────────────────────

load_to_nodes() {
  local image="$1"
  local pids=()
  local failed=()

  log "  Loading ${BOLD}${image}:latest${NC} to ${#NODES[@]} nodes in parallel..."

  for node in "${NODES[@]}"; do
    (
      docker save "${image}:latest" | \
        ssh $SSH_OPTS "kaushikkumaran@${node}" \
        "sudo k3s ctr images import -" \
        2>/dev/null
    ) &
    pids+=($!)
  done

  for i in "${!pids[@]}"; do
    if ! wait "${pids[$i]}"; then
      failed+=("${NODES[$i]}")
    fi
  done

  if [ ${#failed[@]} -gt 0 ]; then
    die "Failed to load image to nodes: ${failed[*]}"
  fi

  ok "  Image loaded to all ${#NODES[@]} nodes"
}

# ── build dashboard npm first ─────────────────────────────────────────────────

build_dashboard_frontend() {
  log "  Building dashboard frontend (npm)..."
  cd "$SCRIPT_DIR/dashboard"
  npm ci --silent
  npm run build --silent
  ok "  Frontend built → dist/"
  cd "$SCRIPT_DIR"
}

# ── deploy one service ────────────────────────────────────────────────────────

deploy_service() {
  local svc="$1"
  local dir="$SCRIPT_DIR/$svc"
  local image="${IMAGE[$svc]}"
  local deploy="${DEPLOY_NAME[$svc]}"

  echo ""
  echo -e "${BOLD}── $svc ──────────────────────────────────────────────${NC}"

  if $RESTART_ONLY; then
    if kubectl get deployment "$deploy" -n "$NAMESPACE" &>/dev/null; then
      log "  Restarting $deploy..."
      kubectl rollout restart deployment/"$deploy" -n "$NAMESPACE"
      kubectl rollout status deployment/"$deploy" -n "$NAMESPACE" --timeout=120s
      ok "  $svc restarted"
    else
      warn "  $deploy not found in cluster — skipping (run without --restart to deploy)"
    fi
    return
  fi

  # Dashboard: build frontend before docker build
  if [ "$svc" = "dashboard" ]; then
    build_dashboard_frontend
  fi

  log "  Building Docker image ${image}:latest..."
  docker build -t "${image}:latest" "$dir" --quiet
  ok "  Image built"

  load_to_nodes "$image"

  log "  Applying k8s manifests..."

  # Namespace (only services that have it)
  if [ -f "$dir/k8s/namespace.yaml" ]; then
    kubectl apply -f "$dir/k8s/namespace.yaml" --output=name 2>/dev/null | sed 's/^/    /'
  fi

  # RBAC (chaos, graph)
  if [ -f "$dir/k8s/rbac.yaml" ]; then
    kubectl apply -f "$dir/k8s/rbac.yaml" --output=name 2>/dev/null | sed 's/^/    /'
  fi

  kubectl apply -f "$dir/k8s/deployment.yaml" --output=name 2>/dev/null | sed 's/^/    /'
  kubectl apply -f "$dir/k8s/service.yaml"    --output=name 2>/dev/null | sed 's/^/    /'

  # Force restart so pods pick up the new image (same tag, new bytes)
  kubectl rollout restart deployment/"$deploy" -n "$NAMESPACE" 2>/dev/null || true

  log "  Waiting for rollout..."
  kubectl rollout status deployment/"$deploy" -n "$NAMESPACE" --timeout=120s

  ok "  $svc is live"
}

# ── port-forwards ────────────────────────────────────────────────────────────

PF_PIDS=()

cleanup() {
  echo ""
  log "Shutting down port-forwards..."
  for pid in "${PF_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  echo -e "${GREEN}  ✓${NC} Done."
}

start_port_forwards() {
  echo ""
  log "Starting port-forwards..."

  # Kill any existing port-forwards for these services to avoid conflicts
  for svc in "${SELECTED[@]}"; do
    local local_port="${PORTS[$svc]%%:*}"
    lsof -ti :"$local_port" 2>/dev/null | xargs kill -9 2>/dev/null || true
  done

  sleep 0.5

  for svc in "${SELECTED[@]}"; do
    local port="${PORTS[$svc]}"
    local name="${DEPLOY_NAME[$svc]}"
    local local_port="${port%%:*}"
    kubectl port-forward -n "$NAMESPACE" "svc/$name" "$port" \
      --address=127.0.0.1 &>/dev/null &
    PF_PIDS+=($!)
    ok "  $name → http://localhost:${local_port}"
  done

  trap cleanup EXIT INT TERM

  echo ""
  echo -e "${GREEN}${BOLD}Phoenix is up.${NC}"
  echo ""

  # Print the dashboard URL prominently if deployed
  if [[ " ${SELECTED[*]} " == *" dashboard "* ]]; then
    echo -e "  ${BOLD}Dashboard:${NC}  http://localhost:3000"
  fi

  echo ""
  echo -e "${BOLD}Logs:${NC}"
  for svc in "${SELECTED[@]}"; do
    local name="${DEPLOY_NAME[$svc]}"
    printf "  %-12s kubectl logs -n %s -l app=%s -f\n" "$svc" "$NAMESPACE" "$name"
  done
  echo ""
  echo -e "  ${YELLOW}Ctrl+C to stop port-forwards${NC}"
  echo ""

  # Wait for all port-forward processes — keep script alive
  wait "${PF_PIDS[@]}" 2>/dev/null || true
}

# ── main ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}Phoenix deploy${NC} · services: ${SELECTED[*]}${RESTART_ONLY:+ · restart-only mode}"
echo ""

preflight

for svc in "${SELECTED[@]}"; do
  deploy_service "$svc"
done

start_port_forwards
