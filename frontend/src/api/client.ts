// Accord API client — thin fetch wrappers over the FastAPI backend.

import type {
  AgentStat,
  AnalyticsOverview,
  DebateResult,
  LoanDetail,
  PipelineResponse,
  SimulationResult,
} from '../types/accord'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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
  params?: { status?: string; type?: string; search?: string; limit?: number; offset?: number },
): Promise<PipelineResponse> {
  const clean = Object.fromEntries(
    Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== ''),
  )
  const query = new URLSearchParams(clean as Record<string, string>).toString()
  return getJSON<PipelineResponse>(`/api/accord/pipeline${query ? `?${query}` : ''}`)
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

export function runSwarm() {
  return postJSON(`/api/accord/mirofish/swarm`, {})
}

// ── Analytics ────────────────────────────────────────────────────────

export function fetchAnalytics(): Promise<AnalyticsOverview> {
  return getJSON<AnalyticsOverview>(`/api/accord/analytics/overview`)
}

export function fetchAgents(): Promise<{ agents: AgentStat[] }> {
  return getJSON(`/api/accord/analytics/agents`)
}

export function fetchFunnel(): Promise<{ funnel: Array<Record<string, number>> }> {
  return getJSON(`/api/accord/analytics/funnel`)
}

export function fetchRisk(): Promise<Record<string, unknown>> {
  return getJSON(`/api/accord/analytics/risk`)
}

// ── Audit ────────────────────────────────────────────────────────────

export function fetchAudit(appId: string): Promise<Record<string, unknown>> {
  return getJSON(`/api/accord/audit/${encodeURIComponent(appId)}`)
}

export function fetchComplianceHealth(): Promise<Record<string, number>> {
  return getJSON(`/api/accord/audit/compliance-health`)
}
