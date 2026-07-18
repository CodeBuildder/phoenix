import type { GraphEdge, GraphNode } from '../../types/graph'
import type { Scenario } from '../../types/chaos'

// All explanation content is computed 100% from live backend data.
// No values are hardcoded — everything here is derived from the real topology,
// real flow counts, real scenario state, and real health status.

export type ExplainTarget =
  | { kind: 'service'; node: GraphNode }
  | { kind: 'flow';    edge: GraphEdge }
  | { kind: 'scenario'; scenario: Scenario }

export interface Section { heading: string; lines: string[] }
export interface ExplainerContent {
  title: string
  subtitle: string
  badge: string
  badgeColor: 'green' | 'yellow' | 'red' | 'cyan' | 'violet'
  sections: Section[]
  actions: string[]
}

// ── service explainer ─────────────────────────────────────────────────────────

export function explainService(
  node: GraphNode,
  allEdges: GraphEdge[],
  scenarios: Scenario[],
): ExplainerContent {
  const incoming = allEdges.filter(e => e.target === node.id)
  const outgoing = allEdges.filter(e => e.source === node.id)
  const flowIn  = incoming.filter(e => e.edge_type === 'flow_observed')
  const flowOut = outgoing.filter(e => e.edge_type === 'flow_observed')
  const envIn   = incoming.filter(e => e.edge_type === 'env_ref')
  const envOut  = outgoing.filter(e => e.edge_type === 'env_ref')

  const depCount = incoming.length
  const riskLevel = depCount >= 3 ? 'critical' : depCount >= 2 ? 'high' : depCount >= 1 ? 'medium' : 'low'
  const badgeColor = riskLevel === 'critical' ? 'red' : riskLevel === 'high' ? 'yellow' : riskLevel === 'medium' ? 'cyan' : 'green'

  const activeScenarios = scenarios.filter(
    s => s.status === 'running' && s.target.namespace === node.namespace,
  )

  const totalFlowsIn  = flowIn.reduce((s, e) => s + e.flow_count, 0)
  const totalFlowsOut = flowOut.reduce((s, e) => s + e.flow_count, 0)

  const sections: Section[] = []

  // What is this service
  sections.push({
    heading: 'What is this',
    lines: [
      `${node.name} is a ${node.kind} running in the ${node.namespace} namespace.`,
      node.cluster_ip
        ? `It is reachable inside the cluster at ClusterIP ${node.cluster_ip}.`
        : `It has no fixed ClusterIP (external or headless service).`,
      Object.keys(node.labels).length > 0
        ? `Labels: ${Object.entries(node.labels).map(([k, v]) => `${k}=${v}`).join(', ')}.`
        : 'No labels found on this service.',
    ],
  })

  // Dependency risk
  if (depCount > 0) {
    sections.push({
      heading: `Blast risk — ${riskLevel.toUpperCase()}`,
      lines: [
        `${depCount} service${depCount !== 1 ? 's' : ''} depend on ${node.name}.`,
        envIn.length > 0
          ? `${envIn.length} service${envIn.length !== 1 ? 's' : ''} reference it via environment-variable DNS URL (static config): ${envIn.map(e => e.source.split('/')[1]).join(', ')}.`
          : '',
        flowIn.length > 0
          ? `${flowIn.length} live Hubble flow${flowIn.length !== 1 ? 's' : ''} arrive here (${totalFlowsIn} packets observed). These are real-time TCP/UDP connections.`
          : '',
        `If ${node.name} fails, all ${depCount} dependent service${depCount !== 1 ? 's' : ''} are immediately impacted.`,
      ].filter(Boolean),
    })
  } else {
    sections.push({
      heading: 'Blast risk — LOW',
      lines: [
        `No other services depend on ${node.name}.`,
        'It is a leaf node in the dependency graph — safe to fault-test without downstream impact.',
      ],
    })
  }

  // What it depends on
  if (outgoing.length > 0) {
    sections.push({
      heading: 'What it depends on',
      lines: [
        ...envOut.map(e => `→ ${e.target.split('/')[1]} (configured via env var${e.env_var ? ` ${e.env_var}` : ''})`),
        ...flowOut.map(e => `→ ${e.target.split('/')[1]} (${e.flow_count} live packets, Hubble-observed)`),
      ],
    })
  }

  // Active chaos
  if (activeScenarios.length > 0) {
    sections.push({
      heading: '⚠ Chaos active in this namespace',
      lines: activeScenarios.map(s =>
        `"${s.name}" — ${s.fault_type} (${s.domain}) is currently running. Started: ${s.started_at ? new Date(s.started_at).toLocaleTimeString() : 'unknown'}.`,
      ),
    })
  }

  // Observe flows
  if (totalFlowsIn + totalFlowsOut > 0) {
    sections.push({
      heading: 'Observed traffic',
      lines: [
        totalFlowsIn  > 0 ? `${totalFlowsIn} packets received from ${flowIn.length} source(s).`  : '',
        totalFlowsOut > 0 ? `${totalFlowsOut} packets sent to ${flowOut.length} destination(s).` : '',
      ].filter(Boolean),
    })
  }

  // Recommendations — derived from real data
  const actions: string[] = []
  if (riskLevel === 'critical' || riskLevel === 'high') {
    actions.push(`Before targeting ${node.name} with chaos, verify all ${depCount} dependent services have circuit breakers or retries configured.`)
    actions.push(`Run blast-radius query (Topology page → "app=${node.name}") to see the full impact chain before injecting faults.`)
  } else if (riskLevel === 'medium') {
    actions.push(`Safe to run limited chaos experiments. Monitor the ${incoming[0]?.source.split('/')[1] ?? 'dependent'} service during any fault injection.`)
  } else {
    actions.push(`${node.name} is a leaf — it is the safest starting point for chaos experiments.`)
    actions.push(`Inject a pod-failure or network-delay scenario against it from the Chaos Lab page.`)
  }
  if (activeScenarios.length > 0) {
    actions.push(`A fault scenario is currently running in ${node.namespace}. Go to Chaos Lab to monitor or stop it.`)
  }

  return {
    title: node.name,
    subtitle: `${node.kind} · ${node.namespace}`,
    badge: riskLevel,
    badgeColor,
    sections,
    actions,
  }
}

// ── flow explainer ────────────────────────────────────────────────────────────

export function explainFlow(
  edge: GraphEdge,
  allNodes: GraphNode[],
): ExplainerContent {
  const srcNode = allNodes.find(n => n.id === edge.source)
  const dstNode = allNodes.find(n => n.id === edge.target)
  const srcName = srcNode?.name ?? edge.source.split('/')[1]
  const dstName = dstNode?.name ?? edge.target.split('/')[1]

  const isFlow = edge.edge_type === 'flow_observed'
  const badgeColor: 'cyan' | 'violet' = isFlow ? 'cyan' : 'violet'

  const sections: Section[] = [
    {
      heading: 'What is this connection',
      lines: isFlow
        ? [
            `${srcName} is actively sending packets to ${dstName}.`,
            `This connection was detected by Cilium Hubble at the eBPF kernel layer — it reflects real network traffic, not just configuration.`,
            `${edge.flow_count} packets were forwarded in the last observation window.`,
          ]
        : [
            `${srcName} has ${dstName} configured as a dependency via an environment variable${edge.env_var ? ` (${edge.env_var})` : ''}.`,
            `This is a static configuration dependency — it means ${srcName} was deployed expecting ${dstName} to be reachable.`,
            `Hubble has not observed live traffic on this path yet, so it may be an infrequently-used code path.`,
          ],
    },
    {
      heading: 'Source service',
      lines: [
        `${srcName} lives in namespace ${srcNode?.namespace ?? 'unknown'}.`,
        srcNode?.cluster_ip ? `ClusterIP: ${srcNode.cluster_ip}` : '',
      ].filter(Boolean),
    },
    {
      heading: 'Destination service',
      lines: [
        `${dstName} lives in namespace ${dstNode?.namespace ?? 'unknown'}.`,
        dstNode?.cluster_ip ? `ClusterIP: ${dstNode.cluster_ip}` : '',
      ].filter(Boolean),
    },
    {
      heading: 'What happens if this breaks',
      lines: isFlow
        ? [
            `If ${dstName} becomes unavailable, ${srcName} will start receiving connection errors or timeouts on this path.`,
            `Depending on whether ${srcName} has retries/circuit breakers, this may cascade or self-resolve.`,
            `Flow count was ${edge.flow_count} — ${edge.flow_count > 10 ? 'this is a hot path, high impact' : 'low traffic, lower immediate impact'}.`,
          ]
        : [
            `If ${dstName} is unavailable, ${srcName} may fail at startup or when it first tries to reach ${dstName}.`,
            `Since no live traffic has been observed, the failure may only surface under specific conditions.`,
          ],
    },
  ]

  const actions = isFlow
    ? [
        `To stress-test this path: trigger a network-delay or packet-loss scenario targeting ${dstName} from the Chaos Lab page.`,
        `Check the Topology page, enter namespace=${dstNode?.namespace ?? ''} and selector app=${dstName} to see the full blast radius.`,
      ]
    : [
        `This dependency is configured but not yet observed live. Consider running a quick load test to confirm it is reachable.`,
        `To fault-test: trigger a pod-failure scenario on ${dstName} and observe if ${srcName} handles it gracefully.`,
      ]

  return {
    title: `${srcName} → ${dstName}`,
    subtitle: isFlow ? 'Hubble eBPF observed flow' : 'env-var configured dependency',
    badge: isFlow ? 'live flow' : 'env ref',
    badgeColor,
    sections,
    actions,
  }
}

// ── scenario explainer ────────────────────────────────────────────────────────

export function explainScenario(
  scenario: Scenario,
  allNodes: GraphNode[],
  allEdges: GraphEdge[],
): ExplainerContent {
  const targetNs = scenario.target.namespace ?? 'unknown'
  const targetSelector = scenario.target.label_selector ?? {}
  const selectorStr = Object.entries(targetSelector).map(([k, v]) => `${k}=${v}`).join(', ')

  const matchedNodes = allNodes.filter(n =>
    n.namespace === targetNs &&
    Object.entries(targetSelector).every(([k, v]) => n.labels[k] === v),
  )

  const impactedByMatched = matchedNodes.flatMap(node => {
    const deps = allEdges.filter(e => e.target === node.id)
    return deps.map(e => e.source.split('/')[1])
  })
  const uniqueImpacted = [...new Set(impactedByMatched)]

  const badgeColor = scenario.status === 'running' ? 'red'
    : scenario.status === 'completed' ? 'green'
    : scenario.status === 'failed' ? 'yellow'
    : 'cyan'

  const durationStr = scenario.duration_seconds != null
    ? `${scenario.duration_seconds}s`
    : 'indefinite'

  const sections: Section[] = [
    {
      heading: 'What this fault does',
      lines: [
        `Fault type: ${scenario.fault_type} (domain: ${scenario.domain}).`,
        selectorStr
          ? `Target: services matching ${selectorStr} in namespace ${targetNs}.`
          : `Target: all services in namespace ${targetNs}.`,
        `Duration: ${durationStr}.`,
        matchedNodes.length > 0
          ? `${matchedNodes.length} service${matchedNodes.length !== 1 ? 's' : ''} matched from live topology: ${matchedNodes.map(n => n.name).join(', ')}.`
          : 'No services from the current topology matched this selector.',
      ],
    },
    {
      heading: 'Current status',
      lines: [
        `Status: ${scenario.status}.`,
        scenario.started_at ? `Started at: ${new Date(scenario.started_at).toLocaleString()}.` : '',
        scenario.stopped_at ? `Stopped at: ${new Date(scenario.stopped_at).toLocaleString()}.` : '',
      ].filter(Boolean),
    },
  ]

  if (uniqueImpacted.length > 0) {
    sections.push({
      heading: 'Downstream services at risk',
      lines: [
        `${uniqueImpacted.length} service${uniqueImpacted.length !== 1 ? 's' : ''} depend on the targeted service(s) and may be impacted:`,
        ...uniqueImpacted.map(n => `• ${n}`),
      ],
    })
  } else {
    sections.push({
      heading: 'Downstream impact',
      lines: ['No downstream services were found that depend on the targeted services. Fault is contained.'],
    })
  }

  if (Object.keys(scenario.params).length > 0) {
    sections.push({
      heading: 'Fault parameters',
      lines: Object.entries(scenario.params).map(([k, v]) => `${k}: ${JSON.stringify(v)}`),
    })
  }

  const actions: string[] = []
  if (scenario.status === 'running') {
    actions.push('Go to Chaos Lab → click Stop to halt this scenario immediately.')
    if (uniqueImpacted.length > 0) {
      actions.push(`Monitor these services for degradation: ${uniqueImpacted.join(', ')}.`)
    }
  } else if (scenario.status === 'completed' || scenario.status === 'stopped') {
    actions.push('Check if all affected services recovered. Re-trigger if you want to reproduce.')
  } else if (scenario.status === 'failed') {
    actions.push('The scenario failed to inject. Check that Chaos Mesh is installed and the target selector is correct.')
  }

  return {
    title: scenario.name,
    subtitle: `${scenario.fault_type} · ${scenario.domain}`,
    badge: scenario.status,
    badgeColor,
    sections,
    actions,
  }
}
