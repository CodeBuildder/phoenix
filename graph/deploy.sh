#!/usr/bin/env bash
# Copyright (c) 2026 Kaushikkumaran
# Deploy phoenix-graph to the k3s cluster.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IMAGE_NAME="phoenix-graph"
IMAGE_TAG="latest"
NODES=(192.168.139.42 192.168.139.77 192.168.139.45)

echo "==> Building phoenix-graph image..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

echo "==> Loading image onto all k3s nodes..."
for node in "${NODES[@]}"; do
  docker save "${IMAGE_NAME}:${IMAGE_TAG}" | \
    ssh -i ~/.orbstack/ssh/id_ed25519 "kaushikkumaran@${node}" \
    "sudo k3s ctr images import -"
done

echo "==> Applying namespace and RBAC..."
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml

echo "==> Deploying phoenix-graph..."
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

echo "==> Waiting for rollout..."
kubectl rollout status -n phoenix-system deploy/phoenix-graph --timeout=90s

echo ""
echo "==> phoenix-graph is live."
echo ""
echo "Port-forward: kubectl port-forward -n phoenix-system svc/phoenix-graph 8080:80"
echo "Health check: curl http://localhost:8080/health"
echo "Topology:     curl http://localhost:8080/topology | jq ."
