// TypeScript types mirroring the Accord API responses.

export type Outcome = 'allow' | 'recommend' | 'escalate' | 'block'
export type LoanStatus =
  | 'halted'
  | 'blocked'
  | 'in_review'
  | 'clear_to_close'
  | 'in_progress'
export type Urgency = 'CRITICAL' | 'URGENT' | 'REVIEW' | 'ON TRACK'

// One decision cell in the pipeline grid.
export interface PipelineDecision {
  outcome: Outcome | null
  confidence: number | null
  reviewed: boolean
  reviewer: string | null
}

export interface PipelineRow {
  application_id: string
  borrower_name: string
  loan_type: string | null
  loan_purpose: string | null
  loan_amount: number | null
  credit_score: number | null
  ltv: number | null
  dti: number | null
  interest_rate: number | null
  status: LoanStatus
  urgency: Urgency
  blocking_persona: string | null
  decisions: Record<string, PipelineDecision>
}

export interface PipelineKPIs {
  total: number
  in_review: number
  blocked: number
  clear_to_close: number
  halted: number
}

export interface PipelineResponse {
  total: number
  kpis: PipelineKPIs
  applications: PipelineRow[]
}

// ── Loan detail ──────────────────────────────────────────────────────

export interface Signal {
  key: string
  value: string
  status: 'pass' | 'fail' | 'warn' | 'no_data' | 'info'
  detail: string
}

export interface Evidence {
  document: string
  detail: string
}

export interface DecisionDetail {
  decision_id: string
  persona_name: string
  wave: number
  outcome: Outcome
  confidence: number | null
  mode: string
  reviewed: boolean
  reviewer: string | null
  reviewed_at: string | null
  human_action: string | null
  stale: boolean
  explanation: string
  signals: Signal[]
  evidence: Evidence[]
  rule: string | null
  rule_version_id?: string | null
  rule_version_short?: string | null
  rule_version_number?: number | null
  rule_version_effective_from?: string | null
  governed_by?: GovernedBy[]
}

export interface GovernedBy {
  type?: string
  citation?: string | null
  rule_name?: string
  agency?: string
  authority?: string
  threshold_field?: string
  effective_value?: number | string
  source?: string
  floor_enforced?: boolean
  note?: string
  expression?: string
}

export interface RainCheck {
  rate_locked: boolean
  pinned_rule_version: string | null
  pinned_version_number: number | null
  pinned_at: string | null
  application_date: string | null
  current_rule_version_id: string | null
  current_version_number: number | null
  protected: boolean
  protection_reason: string
}

export interface LoanDetail {
  application_id: string
  borrower_email?: string | null
  loan_number?: string | null
  borrower: {
    name: string
    employer: string | null
    age: number | null
    story: string
  }
  metrics: {
    loan_amount: number | null
    credit_score: number | null
    ltv: number | null
    dti: number | null
    interest_rate: number | null
    lock_days_remaining: number | null
    income_stated?: number | null
    income_verified?: number | null
  }
  qm?: {
    status: 'safe_harbor' | 'rebuttable_presumption' | 'non_qm' | 'pending'
    determination: string
    citation: string
    tests: { test: string; value: string; limit: string; pass: boolean | null }[]
  }
  examiner_readiness?: { score: number; missing: string[] }
  rain_check?: RainCheck
  conversational_summary?: {
    summary: string
    issue: string | null
    whats_good: string
    next_step: string
    headline: string
    tone: 'red' | 'amber' | 'green'
  }
  status: LoanStatus
  urgency: Urgency
  blocking_persona: string | null
  // Assignment + escalation context (from loan_detail JOINs; null when not escalated).
  assigned_to?: string | null
  assigned_to_name?: string | null
  escalated_by?: string | null
  escalated_by_name?: string | null
  escalated_at?: string | null
  escalation_reason?: string | null
  escalation_category?: string | null
  decisions: DecisionDetail[]
  documents: Array<Record<string, unknown>>
  graph_edges: Array<Record<string, unknown>>
  conditions: Array<Record<string, unknown>>
  activity: Array<{ actor: string; action: string; target: string | null; detail: unknown; at: string | null }>
}

// ── MiroFish ─────────────────────────────────────────────────────────

export interface AgentPosition {
  agent_id: string
  agent_name: string
  round: number
  position: Outcome
  confidence: number
  reasoning: string
  key_signals: Array<Record<string, unknown>>
  responding_to: string[] | null
  changed_from: string | null
}

export interface DebateRound {
  round_number: number
  positions: AgentPosition[]
  new_signals_shared: string[]
  consensus_reached: boolean
}

export interface DebateResult {
  debate_id: string
  application_id: string
  question: string
  rounds: DebateRound[]
  final_consensus: string
  consensus_count: Record<string, number>
  dissenting_agents: string[]
  recommendation: string
  emergent_insights: string[]
  total_duration_seconds: number
  created_at: string
}

export interface SimulationFlip {
  application_id: string
  borrower_name: string
  decision_id: string
  from_outcome: string
  to_outcome: string
  reason: string
  loan_amount: number
}

export interface SimulationResult {
  simulation_id: string
  scenario: { name: string; type: string; overrides: Record<string, unknown> }
  status: string
  total_apps: number
  affected_apps: number
  flipped: SimulationFlip[]
  impact: Record<string, number>
  agent_insights: string[]
}

export interface SwarmInsight {
  insight_type: string
  severity: 'critical' | 'warning' | 'info' | 'emergent'
  detected_by: string[]
  description: string
  affected_apps: string[]
  evidence: Array<Record<string, unknown>>
}

export interface SwarmResult {
  swarm_id: string
  total_apps_scanned: number
  insights: SwarmInsight[]
  agent_summaries: Record<string, string>
  created_at?: string | null
}

// ── Analytics ────────────────────────────────────────────────────────

export interface AnalyticsOverview {
  total_loans: number
  total_volume: number
  avg_score: number
  avg_ltv: number
  avg_dti: number
  avg_rate: number
  approval_rate: number
}

export interface AgentStat {
  persona: string
  decision_id: string
  total: number
  allow_pct: number
  block_pct: number
  recommend_pct: number
  escalate_pct: number
  override_pct: number
  avg_review_minutes: number | null
}

export interface FunnelStep {
  wave: number
  entered: number
  passed: number
  blocked: number
  pass_rate: number
}

export interface Concentration {
  name: string
  count: number
  pct: number
}

export interface RiskData {
  by_geography: Concentration[]
  by_employer: Concentration[]
  by_product: Concentration[]
  high_ltv: number
  high_dti: number
  total: number
}

// ── Audit ────────────────────────────────────────────────────────────

export interface AuditVersion {
  decision_id: string
  persona: string
  version: number
  outcome: string
  mode: string
  human_action: string | null
  reviewer: string | null
  override_reason: string | null
  stale: boolean
  decided_at: string | null
  acted_at: string | null
}

export interface AuthorityEvent {
  decision_id: string
  from: string
  to: string
  trigger: string
  by: string | null
  at: string | null
}

export interface SlaEntry {
  decision_id: string
  persona: string
  sla_seconds: number | null
  actual_seconds: number | null
  met: boolean
}

export interface AuditTrail {
  application_id: string
  versions: AuditVersion[]
  authority_chain: AuthorityEvent[]
  sla: SlaEntry[]
}

export interface AdverseAction {
  application_id: string
  borrower: string
  block_reason: string
  days_since_decision: number | null
  notice_status: string
}

export interface ReportRow {
  id: string
  name: string
  record_count: number
  last_run: string | null
  status: string
}

export interface ComplianceHealth {
  hmda_pct: number
  adverse_pending: number
  overrides: number
  sla_pct: number
  segregation_flags: number
}
