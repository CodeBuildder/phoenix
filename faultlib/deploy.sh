#!/bin/bash
# Phoenix Fault Library & Taxonomy Classifier — build and deploy to cluster
# Issue #3: https://github.com/CodeBuildder/phoenix/issues/3
#
# Usage: ./deploy.sh

set -euo pipefail

NAMESPACE="phoenix-system"
IMAGE_NAME="phoenix-faultlib"
IMAGE_TAG="latest"
NODES=(192.168.139.42 192.168.139.77 192.168.139.45)

echo "==> Building fault library Docker image..."
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

echo "==> Deploying fault library..."
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

echo "==> Waiting for rollout..."
kubectl rollout status deployment/phoenix-faultlib -n "${NAMESPACE}" --timeout=120s

echo "==> Fault library deployed successfully."
echo "    Health: kubectl port-forward -n phoenix-system svc/phoenix-faultlib 8080:80"
echo "    Logs:   kubectl logs -n phoenix-system -l app=phoenix-faultlib -f"
