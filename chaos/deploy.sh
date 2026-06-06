#!/bin/bash
# Phoenix Chaos Injection Engine — build and deploy to cluster
# Issue #2: https://github.com/CodeBuildder/phoenix/issues/2
#
# Usage: ./deploy.sh

set -euo pipefail

NAMESPACE="phoenix-system"
IMAGE_NAME="phoenix-chaos"
IMAGE_TAG="latest"
NODES=(192.168.139.42 192.168.139.77 192.168.139.45)

echo "==> Building chaos engine Docker image..."
cd "$(dirname "$0")"
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

echo "==> Loading image into k3s nodes..."
for node in "${NODES[@]}"; do
  docker save "${IMAGE_NAME}:${IMAGE_TAG}" | \
    ssh -i ~/.orbstack/ssh/id_ed25519 "kaushikkumaran@${node}" \
    "sudo k3s ctr images import -"
done

echo "==> Applying namespace..."
kubectl apply -f k8s/namespace.yaml

echo "==> Applying RBAC (chaos-mesh.org CRD access)..."
kubectl apply -f k8s/rbac.yaml

echo "==> Deploying chaos engine..."
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

echo "==> Waiting for rollout..."
kubectl rollout status deployment/phoenix-chaos -n "${NAMESPACE}" --timeout=120s

echo "==> Chaos engine deployed successfully."
echo "    Health: kubectl port-forward -n phoenix-system svc/phoenix-chaos 8080:80"
echo "    Logs:   kubectl logs -n phoenix-system -l app=phoenix-chaos -f"
echo "    Events in Grafana/Loki: {app=\"phoenix-chaos\"} | json | event_type != \"\""
