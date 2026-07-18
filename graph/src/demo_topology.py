"""Deterministic, explicitly synthetic topology for the cluster-free judge demo."""

from models import Edge, Node, TopologyResponse


def build_demo_topology() -> TopologyResponse:
    services = [
        ("edge", "gateway", "frontend"),
        ("storefront", "web", "frontend"),
        ("storefront", "checkout", "api"),
        ("payments", "payment-api", "api"),
        ("payments", "fraud-engine", "worker"),
        ("orders", "order-api", "api"),
        ("orders", "order-worker", "worker"),
        ("data", "postgres-primary", "database"),
        ("data", "redis-cache", "cache"),
        ("observability", "prometheus", "monitoring"),
        ("argus-system", "argus-agent", "security"),
        ("phoenix-system", "phoenix-agent", "resilience"),
    ]
    nodes = [
        Node(
            id=f"{namespace}/{name}", name=name, namespace=namespace,
            labels={"app": name, "tier": tier, "demo-data": "synthetic"},
            cluster_ip=f"10.96.{index // 250}.{index % 250 + 10}",
        )
        for index, (namespace, name, tier) in enumerate(services)
    ]
    dependencies = [
        ("edge/gateway", "storefront/web", 1840),
        ("storefront/web", "storefront/checkout", 1320),
        ("storefront/checkout", "payments/payment-api", 710),
        ("storefront/checkout", "orders/order-api", 930),
        ("payments/payment-api", "payments/fraud-engine", 480),
        ("payments/payment-api", "data/postgres-primary", 650),
        ("payments/fraud-engine", "data/redis-cache", 390),
        ("orders/order-api", "orders/order-worker", 820),
        ("orders/order-worker", "data/postgres-primary", 760),
        ("storefront/checkout", "data/redis-cache", 1140),
        ("observability/prometheus", "payments/payment-api", 160),
        ("observability/prometheus", "orders/order-api", 160),
        ("argus-system/argus-agent", "edge/gateway", 240),
        ("phoenix-system/phoenix-agent", "storefront/checkout", 180),
    ]
    edges = [
        Edge(source=source, target=target, edge_type="flow_observed", flow_count=flows)
        for source, target, flows in dependencies
    ]
    return TopologyResponse(
        nodes=nodes, edges=edges, topology_sources=["synthetic_fixture"],
        node_count=len(nodes), edge_count=len(edges),
    )
