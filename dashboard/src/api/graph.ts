import type { BlastRadiusResponse, TopologyResponse } from '../types/graph'

const BASE = '/api/graph'

export async function fetchTopology(): Promise<TopologyResponse> {
  const r = await fetch(`${BASE}/topology`)
  if (!r.ok) throw new Error(`topology ${r.status}`)
  return r.json()
}

export async function fetchBlastRadius(
  targetNamespace: string,
  faultType: string,
  selector: Record<string, string>,
): Promise<BlastRadiusResponse> {
  const params = new URLSearchParams({ target_namespace: targetNamespace, fault_type: faultType })
  Object.entries(selector).forEach(([k, v]) => params.append('selector', `${k}=${v}`))
  const r = await fetch(`${BASE}/blast-radius?${params}`)
  if (!r.ok) throw new Error(`blast-radius ${r.status}`)
  return r.json()
}

export async function fetchHealth(): Promise<{ status: string }> {
  const r = await fetch(`${BASE}/health`)
  if (!r.ok) throw new Error('graph unhealthy')
  return r.json()
}
