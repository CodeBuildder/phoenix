export type ScenarioDomain = 'chaos_mesh' | 'simulator'
export type ScenarioStatus = 'pending' | 'running' | 'completed' | 'failed' | 'stopped'

export interface ChaosTarget {
  namespace?: string
  label_selector?: Record<string, string>
  resource_type?: string
  operation?: string
}

export interface Scenario {
  id: string
  name: string
  domain: ScenarioDomain
  fault_type: string
  target: ChaosTarget
  duration_seconds: number | null
  params: Record<string, unknown>
  status: ScenarioStatus
  started_at: string | null
  stopped_at: string | null
  created_at: string
  blast_radius: unknown | null
}

export interface TriggerPayload {
  name: string
  domain: ScenarioDomain
  fault_type: string
  target: ChaosTarget
  duration_seconds?: number
  params?: Record<string, unknown>
}
