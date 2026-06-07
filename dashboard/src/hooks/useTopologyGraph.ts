import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import type { GraphEdge, GraphNode } from '../types/graph'

export interface SimNode extends d3.SimulationNodeDatum, GraphNode {
  x: number
  y: number
}

export interface SimEdge extends d3.SimulationLinkDatum<SimNode> {
  edge: GraphEdge
}

export function useTopologyGraph(
  svgRef: React.RefObject<SVGSVGElement>,
  nodes: GraphNode[],
  edges: GraphEdge[],
  highlightIds: Set<string>,
) {
  const simRef = useRef<d3.Simulation<SimNode, SimEdge> | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const width = svgRef.current.clientWidth
    const height = svgRef.current.clientHeight

    const simNodes: SimNode[] = nodes.map(n => ({
      ...n,
      x: width / 2 + (Math.random() - 0.5) * 200,
      y: height / 2 + (Math.random() - 0.5) * 200,
    }))

    const nodeById = new Map(simNodes.map(n => [n.id, n]))

    const simEdges: SimEdge[] = edges
      .map(e => ({
        source: nodeById.get(e.source)!,
        target: nodeById.get(e.target)!,
        edge: e,
      }))
      .filter(e => e.source && e.target)

    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 4]).on('zoom', event => {
      g.attr('transform', event.transform)
    })
    svg.call(zoom)

    const g = svg.append('g')

    // Arrow markers
    const defs = svg.append('defs')
    for (const type of ['env_ref', 'flow_observed']) {
      defs
        .append('marker')
        .attr('id', `arrow-${type}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 20)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', type === 'flow_observed' ? '#06b6d4' : '#8b5cf6')
    }

    const link = g
      .append('g')
      .selectAll('line')
      .data(simEdges)
      .join('line')
      .attr('stroke', d => d.edge.edge_type === 'flow_observed' ? '#06b6d4' : '#8b5cf6')
      .attr('stroke-opacity', 0.5)
      .attr('stroke-width', d => d.edge.edge_type === 'flow_observed' ? 1.5 : 1)
      .attr('marker-end', d => `url(#arrow-${d.edge.edge_type})`)

    const node = g
      .append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(simNodes)
      .join('g')
      .attr('cursor', 'pointer')
      .call(
        d3
          .drag<SVGGElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart()
            d.fx = d.x
            d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x
            d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) sim.alphaTarget(0)
            d.fx = null
            d.fy = null
          }),
      )

    node
      .append('circle')
      .attr('r', 14)
      .attr('fill', d => {
        if (highlightIds.has(d.id)) return '#ef4444'
        if (d.kind === 'ExternalService') return '#1a2a45'
        return '#1f3358'
      })
      .attr('stroke', d => {
        if (highlightIds.has(d.id)) return '#ef4444'
        return '#3b82f6'
      })
      .attr('stroke-width', d => highlightIds.has(d.id) ? 2.5 : 1)

    node
      .append('text')
      .attr('dy', 26)
      .attr('text-anchor', 'middle')
      .attr('font-size', 9)
      .attr('font-family', 'JetBrains Mono, monospace')
      .attr('fill', '#94a3b8')
      .text(d => d.name.length > 18 ? d.name.slice(0, 16) + '…' : d.name)

    const sim = d3
      .forceSimulation<SimNode>(simNodes)
      .force('link', d3.forceLink<SimNode, SimEdge>(simEdges).id(d => d.id).distance(90))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(28))
      .on('tick', () => {
        link
          .attr('x1', d => (d.source as SimNode).x)
          .attr('y1', d => (d.source as SimNode).y)
          .attr('x2', d => (d.target as SimNode).x)
          .attr('y2', d => (d.target as SimNode).y)
        node.attr('transform', d => `translate(${d.x},${d.y})`)
      })
      .on('end', () => setReady(true))

    simRef.current = sim

    return () => {
      sim.stop()
    }
  }, [nodes, edges, highlightIds, svgRef])

  return { ready }
}
