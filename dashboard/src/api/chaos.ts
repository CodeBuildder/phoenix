import type { Scenario, TriggerPayload } from '../types/chaos'

const BASE = '/api/chaos'

export async function fetchScenarios(): Promise<Scenario[]> {
  const r = await fetch(`${BASE}/scenarios`)
  if (!r.ok) throw new Error(`scenarios ${r.status}`)
  const data = await r.json()
  return Array.isArray(data) ? data : (data.scenarios ?? data.items ?? [])
}

export async function fetchScenario(id: string): Promise<Scenario> {
  const r = await fetch(`${BASE}/scenarios/${id}`)
  if (!r.ok) throw new Error(`scenario ${r.status}`)
  return r.json()
}

export async function triggerScenario(payload: TriggerPayload): Promise<Scenario> {
  const r = await fetch(`${BASE}/scenarios`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}))
    throw new Error(detail.detail ?? `trigger ${r.status}`)
  }
  return r.json()
}

export async function stopScenario(id: string): Promise<Scenario> {
  const r = await fetch(`${BASE}/scenarios/${id}/stop`, { method: 'POST' })
  if (!r.ok) throw new Error(`stop ${r.status}`)
  return r.json()
}

export async function fetchHealth(): Promise<{ status: string }> {
  const r = await fetch(`${BASE}/health`)
  if (!r.ok) throw new Error('chaos unhealthy')
  return r.json()
}
