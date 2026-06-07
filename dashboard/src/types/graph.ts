export interface GraphNode {
  id: string
  name: string
  namespace: string
  kind: 'Service' | 'Deployment' | 'ExternalService'
  labels: Record<string, string>
  cluster_ip: string | null
}

export interface GraphEdge {
  source: string
  target: string
  edge_type: 'env_ref' | 'flow_observed'
  flow_count: number
  env_var: string | null
}

export interface TopologyResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
  topology_sources: string[]
  node_count: number
  edge_count: number
  observed_at: string
}

export interface AffectedNode {
  node_id: string
  name: string
  namespace: string
  distance_hops: number
  severity: 'high' | 'medium' | 'low'
  via_edge_types: string[]
}

export interface BlastRadiusResponse {
  target_namespace: string
  target_selector: Record<string, string>
  fault_type: string
  matched_nodes: string[]
  affected_nodes: AffectedNode[]
  topology_sources: string[]
  computed_at: string
}
