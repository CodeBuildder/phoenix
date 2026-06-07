import type { Classification, FaultCatalogEntry, RankingsResponse } from '../types/faultlib'

const BASE = '/api/faultlib'

export async function fetchCatalog(): Promise<FaultCatalogEntry[]> {
  const r = await fetch(`${BASE}/catalog`)
  if (!r.ok) throw new Error(`catalog ${r.status}`)
  const data = await r.json()
  return Array.isArray(data) ? data : (data.entries ?? data.items ?? [])
}

export async function fetchCatalogEntry(
  domain: string,
  faultType: string,
): Promise<FaultCatalogEntry> {
  const r = await fetch(`${BASE}/catalog/${domain}/${faultType}`)
  if (!r.ok) throw new Error(`catalog entry ${r.status}`)
  return r.json()
}

export async function fetchRankings(): Promise<RankingsResponse> {
  const r = await fetch(`${BASE}/rankings`)
  if (!r.ok) throw new Error(`rankings ${r.status}`)
  return r.json()
}

export async function classify(
  domain: string,
  faultType: string,
): Promise<Classification> {
  const r = await fetch(`${BASE}/classify?domain=${domain}&fault_type=${faultType}`, {
    method: 'POST',
  })
  if (!r.ok) throw new Error(`classify ${r.status}`)
  return r.json()
}

export async function fetchHealth(): Promise<{ status: string }> {
  const r = await fetch(`${BASE}/health`)
  if (!r.ok) throw new Error('faultlib unhealthy')
  return r.json()
}
