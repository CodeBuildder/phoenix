export type TaxonomyCategory =
  | 'transient'
  | 'cascading'
  | 'resource-exhaustion'
  | 'network-partition'
  | 'quota-limit'

export type FaultDomain = 'chaos_mesh' | 'simulator'

export interface FaultCatalogEntry {
  domain: FaultDomain
  fault_type: string
  mechanism: string
  description: string
  blast_radius_shape: string
  typical_symptoms: string[]
  taxonomy_category: TaxonomyCategory
  category_rationale: string
}

export interface ComponentRanking {
  component: string
  domain: FaultDomain
  tallies: {
    transient: number
    cascading: number
    resource_exhaustion: number
    network_partition: number
    quota_limit: number
    total: number
  }
}

export interface RankingsResponse {
  rankings: ComponentRanking[]
  scenarios_considered: number
  scenarios_excluded: number
  generated_at: string
}

export interface Classification {
  domain: FaultDomain
  fault_type: string
  taxonomy_category: TaxonomyCategory
  rationale: string
}
