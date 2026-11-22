/** Shapes the Procurement desk reads from the engine. */

export interface SubjectHit {
  subject_id: string
  pack_id: string
  label: string
}

export interface SubjectClaim {
  claim_id: string
  severity: string
  domain: string
  title: string
  via?: string
}

export interface SubjectClaims {
  subject_id: string
  label: string
  pack_id: string
  claims: SubjectClaim[]
}

export interface CostsPayload {
  spent: { usd?: number; runs?: number; days?: number }
  estimates: Record<string, { usd: number | null }>
}
