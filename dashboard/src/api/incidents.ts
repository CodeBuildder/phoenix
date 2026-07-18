// Randomised chaos injection — derives target from real live topology + catalog data.
// Nothing hardcoded: fault type comes from /catalog, target from /topology.

import { fetchCatalog } from './faultlib'
import { fetchTopology } from './graph'
import { triggerScenario } from './chaos'
import type { TriggerPayload } from '../types/chaos'
import type { TaxonomyCategory } from '../types/faultlib'

export type ImpactLevel = 'low' | 'medium' | 'high' | 'random'

// Map user-chosen impact level → fault taxonomy categories from the live catalog
const IMPACT_CATEGORIES: Record<ImpactLevel, TaxonomyCategory[]> = {
  low:    ['transient', 'quota-limit'],
  medium: ['resource-exhaustion'],
  high:   ['cascading', 'network-partition'],
  random: ['transient', 'cascading', 'resource-exhaustion', 'network-partition', 'quota-limit'],
}

// Duration (seconds) per impact level — higher impact = shorter window (safer)
const IMPACT_DURATIONS: Record<ImpactLevel, number[]> = {
  low:    [60, 90, 120],
  medium: [30, 60, 90],
  high:   [20, 30, 45],
  random: [30, 60, 90, 120],
}

export async function injectRandomChaos(impact: ImpactLevel = 'random'): Promise<string> {
  const [catalog, topo] = await Promise.all([fetchCatalog(), fetchTopology()])

  if (catalog.length === 0) throw new Error('Fault catalog is empty — faultlib may be unreachable.')
  if (topo.nodes.length === 0) throw new Error('No topology nodes — graph service may be unreachable.')

  // Filter catalog to the chosen impact level
  const allowed = IMPACT_CATEGORIES[impact]
  const filtered = catalog.filter(e => allowed.includes(e.taxonomy_category))
  if (filtered.length === 0) throw new Error(`No faults in catalog match impact level "${impact}". Try "random".`)

  const fault    = filtered[Math.floor(Math.random() * filtered.length)]
  const durations = IMPACT_DURATIONS[impact]
  const duration = durations[Math.floor(Math.random() * durations.length)]

  const candidates = topo.nodes.filter(n => n.namespace === 'phoenix-system' && Object.keys(n.labels).length > 0)
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

  const scenario = await triggerScenario(payload)
  return scenario.id
}
