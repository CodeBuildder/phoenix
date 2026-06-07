// Phoenix Agent API client

const BASE = '/api/agent'

export type AgentNode =
  | 'detect' | 'diagnose' | 'heal_plan' | 'approve'
  | 'execute' | 'verify' | 'report' | 'done' | 'aborted' | 'error'

export type ApprovalStatus = 'not_required' | 'pending' | 'approved' | 'rejected'

export interface DiagnosisResult {
  causal_chain:       string
  recommended_action: string
  action_target:      string
  risk:               'low' | 'high'
  rationale:          string
}

export interface AgentRun {
  scenario_id:     string
  scenario:        Record<string, unknown>
  blast_radius:    Record<string, unknown> | null
  catalog_entry:   Record<string, unknown> | null
  memory_context:  string | null
  diagnosis:       DiagnosisResult | null
  action_result:   string | null
  approval_status: ApprovalStatus
  verify_result:   string | null
  node:            AgentNode
  error:           string | null
  started_at:      string
  updated_at:      string
  completed_at:    string | null
  mttr_seconds:    number | null
}

export interface MemoryRecord {
  id:                number
  fault_type:        string
  taxonomy_category: string | null
  target_namespace:  string | null
  action_taken:      string
  outcome:           string
  mttr_seconds:      number | null
  diagnosis:         string | null
  timestamp:         string
}

async function _fetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, opts)
  if (!r.ok) throw new Error(`agent ${r.status}: ${path}`)
  return r.json()
}

export async function fetchRuns(): Promise<AgentRun[]> {
  return _fetch<AgentRun[]>('/runs')
}

export async function fetchRun(scenarioId: string): Promise<AgentRun> {
  return _fetch<AgentRun>(`/runs/${scenarioId}`)
}

export async function approveAction(scenarioId: string): Promise<void> {
  await _fetch(`/runs/${scenarioId}/approve`, { method: 'POST' })
}

export async function rejectAction(scenarioId: string): Promise<void> {
  await _fetch(`/runs/${scenarioId}/reject`, { method: 'POST' })
}

export async function fetchMemory(): Promise<MemoryRecord[]> {
  return _fetch<MemoryRecord[]>('/memory')
}

export async function agentHealth(): Promise<{ status: string; active_runs: number }> {
  return _fetch('/health')
}
