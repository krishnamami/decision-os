// Accord API client — thin fetch wrappers over the FastAPI backend.

import type {
  AdverseAction,
  AgentStat,
  AnalyticsOverview,
  AuditTrail,
  ComplianceHealth,
  DebateResult,
  FunnelStep,
  LoanDetail,
  PipelineResponse,
  ReportRow,
  RiskData,
  SimulationResult,
  SwarmResult,
} from '../types/accord'

// In production the app is built with VITE_API_URL="" so requests go to
// /api/... on the same origin (nginx proxies them). `??` (not `||`) keeps the
// empty string instead of falling back, while an unset var in dev still uses
// the local backend.
const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`)
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`)
  return res.json() as Promise<T>
}

// ── Pipeline ─────────────────────────────────────────────────────────

export function fetchPipeline(
  params?: { status?: string; type?: string; search?: string; period?: string; limit?: number; offset?: number },
): Promise<PipelineResponse> {
  const clean = Object.fromEntries(
    Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== ''),
  )
  const query = new URLSearchParams(clean as Record<string, string>).toString()
  return getJSON<PipelineResponse>(`/api/accord/pipeline${query ? `?${query}` : ''}`)
}

// Append ?period=… when a non-"all" range is selected (backend may ignore it).
function withPeriod(path: string, period?: string): string {
  if (!period || period === 'all') return path
  return `${path}${path.includes('?') ? '&' : '?'}period=${encodeURIComponent(period)}`
}

export function fetchLoan(appId: string): Promise<LoanDetail> {
  return getJSON<LoanDetail>(`/api/accord/loans/${encodeURIComponent(appId)}`)
}

// ── Human-review actions ─────────────────────────────────────────────

export function approveLoan(appId: string, decisionId: string, reviewer: string, notes?: string) {
  return postJSON(
    `/api/accord/loans/${encodeURIComponent(appId)}/decisions/${decisionId}/approve`,
    { reviewer, notes },
  )
}

export function overrideLoan(
  appId: string, decisionId: string, reviewer: string, newOutcome: string, reason?: string,
) {
  return postJSON(
    `/api/accord/loans/${encodeURIComponent(appId)}/decisions/${decisionId}/override`,
    { reviewer, new_outcome: newOutcome, reason },
  )
}

export function revertLoan(appId: string, decisionId: string, reviewer: string, reason?: string) {
  return postJSON(
    `/api/accord/loans/${encodeURIComponent(appId)}/decisions/${decisionId}/revert`,
    { reviewer, reason },
  )
}

// ── MiroFish ─────────────────────────────────────────────────────────

export function runDebate(appId: string, question?: string): Promise<DebateResult> {
  return postJSON<DebateResult>(`/api/accord/mirofish/debate`, {
    application_id: appId,
    question: question || 'Should this loan be approved?',
  })
}

export function runSimulation(scenarioName: string): Promise<SimulationResult> {
  return postJSON<SimulationResult>(`/api/accord/mirofish/simulate`, {
    scenario_name: scenarioName,
  })
}

export function fetchPrebuiltScenarios(): Promise<{ scenarios: Array<{ name: string; type: string; description: string }> }> {
  return getJSON(`/api/accord/mirofish/simulate/prebuilt`)
}

export function runSwarm(): Promise<SwarmResult> {
  return postJSON<SwarmResult>(`/api/accord/mirofish/swarm`, {})
}

export function fetchSwarmLatest(): Promise<SwarmResult> {
  return getJSON<SwarmResult>(`/api/accord/mirofish/swarm/latest`)
}

export interface SimHistoryRow {
  simulation_id: string
  scenario_name: string
  scenario_type: string
  status: string
  total_apps: number
  affected_apps: number
  impact: Record<string, number>
  created_at: string | null
}

export function fetchSimHistory(): Promise<{ simulations: SimHistoryRow[] }> {
  return getJSON(`/api/accord/mirofish/simulate/history`)
}

// Custom what-if: send overrides via `custom` (NOT scenario_name — the backend
// checks scenario_name first and 404s on unknown names). `custom.name` becomes
// the scenario label.
export function runSimulationCustom(
  name: string,
  overrides: Record<string, unknown>,
  type?: 'policy' | 'stress' | 'regulatory',
): Promise<SimulationResult> {
  return postJSON<SimulationResult>(`/api/accord/mirofish/simulate`, { custom: { name, type, overrides } })
}

// ── Analytics ────────────────────────────────────────────────────────

export function fetchAnalytics(period?: string): Promise<AnalyticsOverview> {
  return getJSON<AnalyticsOverview>(withPeriod(`/api/accord/analytics/overview`, period))
}

export function fetchAgents(period?: string): Promise<{ agents: AgentStat[] }> {
  return getJSON(withPeriod(`/api/accord/analytics/agents`, period))
}

export function fetchFunnel(period?: string): Promise<{ funnel: FunnelStep[] }> {
  return getJSON(withPeriod(`/api/accord/analytics/funnel`, period))
}

export function fetchRisk(period?: string): Promise<RiskData> {
  return getJSON(withPeriod(`/api/accord/analytics/risk`, period))
}

// ── Audit ────────────────────────────────────────────────────────────

export function fetchAudit(appId: string): Promise<AuditTrail> {
  return getJSON<AuditTrail>(`/api/accord/audit/${encodeURIComponent(appId)}`)
}

export function fetchComplianceHealth(period?: string): Promise<ComplianceHealth> {
  return getJSON<ComplianceHealth>(withPeriod(`/api/accord/audit/compliance-health`, period))
}

export function fetchAdverseAction(period?: string): Promise<{ total: number; adverse_actions: AdverseAction[] }> {
  return getJSON(withPeriod(`/api/accord/audit/adverse-action?limit=50`, period))
}

export function fetchReports(period?: string): Promise<{ reports: ReportRow[] }> {
  return getJSON(withPeriod(`/api/accord/audit/reports`, period))
}
