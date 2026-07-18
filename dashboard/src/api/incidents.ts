// Randomised chaos injection — derives target from real live topology + catalog data.
// Nothing hardcoded: fault type comes from /catalog, target from /topology.

import { fetchCatalog } from './faultlib'
import { fetchBlastRadius, fetchTopology } from './graph'
import { triggerScenario } from './chaos'
import type { TriggerPayload } from '../types/chaos'
import type { FaultDomain } from '../types/faultlib'

export type InjectionMode = 'safe' | 'live'

export interface InjectionPreview {
  mode: InjectionMode
  domain: FaultDomain
  faultType: string
  description: string
  taxonomy: string
  targetName: string
  namespace: string
  selector: Record<string, string>
  durationSeconds: number
  affectedServices: number
  payload: TriggerPayload
}

const MODE_DOMAIN: Record<InjectionMode, FaultDomain> = {
  safe: 'simulator',
  live: 'chaos_mesh',
}

const MODE_DURATIONS: Record<InjectionMode, number[]> = {
  safe: [60, 90, 120],
  live: [20, 30, 45],
}

const CONTROL_PLANE = new Set(['phoenix-agent', 'phoenix-chaos', 'phoenix-dashboard'])
const SIMULATOR_TARGETS = [
  { resource_type: 'volume', operation: 'create' },
  { resource_type: 'subnet', operation: 'create' },
  { resource_type: 'instance', operation: 'provision' },
]

export async function prepareInjection(mode: InjectionMode): Promise<InjectionPreview> {
  const catalog = await fetchCatalog()

  if (catalog.length === 0) throw new Error('Fault catalog is empty — faultlib may be unreachable.')

  const domain = MODE_DOMAIN[mode]
  const faults = catalog.filter(entry => entry.domain === domain)
  if (faults.length === 0) throw new Error(`No ${domain} faults are available in the live catalog.`)

  const fault = faults[Math.floor(Math.random() * faults.length)]
  const durations = MODE_DURATIONS[mode]
  const duration = durations[Math.floor(Math.random() * durations.length)]

  if (mode === 'safe') {
    const target = SIMULATOR_TARGETS[Math.floor(Math.random() * SIMULATOR_TARGETS.length)]
    const payload: TriggerPayload = {
      name: `simulation-${target.resource_type}-${fault.fault_type}-${Date.now()}`,
      domain,
      fault_type: fault.fault_type,
      target,
      duration_seconds: duration,
    }
    return {
      mode, domain, faultType: fault.fault_type, description: fault.description,
      taxonomy: fault.taxonomy_category, targetName: `${target.resource_type}/${target.operation}`,
      namespace: 'provisioning simulator', selector: target,
      durationSeconds: duration, affectedServices: 0, payload,
    }
  }

  const topo = await fetchTopology()
  if (topo.nodes.length === 0) throw new Error('No topology nodes — graph service may be unreachable.')

  const candidates = topo.nodes.filter(node =>
    node.namespace === 'phoenix-system' &&
    Object.keys(node.labels).length > 0 &&
    !CONTROL_PLANE.has(node.name),
  )
  if (candidates.length === 0) throw new Error('No labelled services found in phoenix-system.')
  const target = candidates[Math.floor(Math.random() * candidates.length)]

  const payload: TriggerPayload = {
    name: `incident-${target.name}-${fault.fault_type}-${Date.now()}`,
    domain: fault.domain,
    fault_type: fault.fault_type,
    target: {
      namespace: target.namespace,
      label_selector: target.labels,
    },
    duration_seconds: duration,
  }

  const blast = await fetchBlastRadius(target.namespace, fault.fault_type, target.labels)
  return {
    mode,
    domain,
    faultType: fault.fault_type,
    description: fault.description,
    taxonomy: fault.taxonomy_category,
    targetName: target.name,
    namespace: target.namespace,
    selector: target.labels,
    durationSeconds: duration,
    affectedServices: blast.affected_nodes.length,
    payload,
  }
}

export async function executeInjection(preview: InjectionPreview): Promise<string> {
  const scenario = await triggerScenario(preview.payload)
  return scenario.id
}
