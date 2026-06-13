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

// ── Token storage (shared with AuthContext) ──────────────────────────
const TOKEN_KEY = 'accord_token'
export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY)
export const setToken = (t: string): void => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY)

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const t = getToken()
  return { ...(extra || {}), ...(t ? { Authorization: `Bearer ${t}` } : {}) }
}

// A 401 on a non-auth route means the session is gone → clear + signal the app.
function handle401(path: string): void {
  if (path.includes('/auth/login') || path.includes('/auth/signup')) return
  clearToken()
  window.dispatchEvent(new Event('accord:unauthorized'))
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() })
  if (res.status === 401) handle401(path)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`)
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  })
  if (res.status === 401) handle401(path)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`)
  return res.json() as Promise<T>
}

// Like postJSON but for PUT, and it surfaces the FastAPI `detail` message
// (e.g. a rule-validation rejection) instead of a generic status string.
async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  })
  if (res.status === 401) handle401(path)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (j && typeof j.detail === 'string') detail = j.detail
    } catch {
      /* non-JSON body */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

// ── Auth ─────────────────────────────────────────────────────────────
export interface AuthUser {
  user_id: string
  tenant_id: string
  email: string
  name: string
  role: string
  is_active?: boolean
}
export interface AuthTenant {
  tenant_id: string
  name: string
  plan: string
  products: string[]
  settings?: Record<string, unknown>
  logo_url?: string | null
}
export interface AuthSession {
  access_token: string
  token_type: string
  user: AuthUser
  tenant: AuthTenant
}

export async function loginRequest(email: string, password: string): Promise<AuthSession> {
  return postJSON<AuthSession>('/api/accord/auth/login', { email, password })
}
export async function signupRequest(
  tenant_name: string, email: string, password: string, name: string,
): Promise<AuthSession> {
  return postJSON<AuthSession>('/api/accord/auth/signup', { tenant_name, email, password, name })
}
export async function fetchMe(): Promise<{ user: AuthUser; tenant: AuthTenant; permissions: string[] }> {
  return getJSON('/api/accord/auth/me')
}

// ── My Queue / Team (role-based landing) ─────────────────────────────
export interface QueueCard {
  application_id: string
  borrower_name: string
  loan_amount: number | null
  loan_type: string | null
  status: string
  stage: string
  queue_type: 'action_needed' | 'internal_request' | 'returned'
  category?: 'clean' | 'fraud' | 'income' | 'compliance' | 'other'
  days_in_queue: number | null
  sla_days?: number
  rate_lock_days: number | null
  urgency: 'urgent' | 'normal'
  ai_finding: string
  ai_data_sources: string
  ai_recommendation: string
  attention_request: { from: string; message: string; priority: string } | null
  requesting?: string[]
  sent?: string | null
  due_date?: string | null
  recipient_email?: string | null
}
export interface MyQueueResponse {
  user: { name: string; role: string }
  counts: { active: number; pending: number; decided: number }
  active: QueueCard[]
  pending: QueueCard[]
  decided: QueueCard[]
}
export interface TeamMember {
  user_id: string
  name: string
  role: string
  active: number
  pending: number
  decided: number
  oldest_days: number
  loans: Array<{
    application_id: string
    borrower_name: string
    loan_amount: number | null
    loan_status: string
    stage: string
    days_in_queue: number | null
  }>
}
export interface TeamResponse {
  members: TeamMember[]
  totals: { active: number; pending: number; decided: number; avg_days: number }
}
export interface TeamPerformanceMember {
  name: string
  role: string
  active: number
  decided: number
  avg_days: number
  overrides: number
}
export interface TeamPerformanceResponse {
  members: TeamPerformanceMember[]
  avg_overrides: number
}
export interface ReportData {
  report_id: string
  columns: string[]
  rows: Array<Array<string | number | null>>
  count: number
}

export function fetchMyQueue(userId?: string): Promise<MyQueueResponse> {
  return getJSON(`/api/accord/pipeline/my-queue${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`)
}
export function fetchTeam(): Promise<TeamResponse> {
  return getJSON('/api/accord/pipeline/team')
}
export function reassignLoans(application_ids: string[], to_user_id: string): Promise<{ transferred: number; to_name: string }> {
  return postJSON('/api/accord/pipeline/reassign', { application_ids, to_user_id })
}
export function decideLoan(application_id: string, action: 'approve' | 'deny' | 'escalate', note?: string): Promise<{ ok: boolean; title: string }> {
  return postJSON('/api/accord/pipeline/decide', { application_id, action, note })
}
export function fetchTeamPerformance(): Promise<TeamPerformanceResponse> {
  return getJSON('/api/accord/analytics/team-performance')
}
export function fetchReportData(reportId: string): Promise<ReportData> {
  return getJSON(`/api/accord/audit/reports/${encodeURIComponent(reportId)}/data`)
}

// ── Communications / attention / notes / notifications ───────────────
export interface Notification {
  notification_id: string
  type: string
  title: string
  body: string | null
  application_id: string | null
  is_read: boolean
  created_at: string | null
}
export interface NotificationsResponse {
  unread_count: number
  notifications: Notification[]
}
export interface LoanNote {
  note_id: string
  note: string
  note_type: string
  author: string
  created_at: string | null
}
export interface TeammateLite {
  user_id: string
  name: string
  role: string
  email?: string
  is_active?: boolean
  last_login?: string | null
}

export function requestInfo(body: {
  application_id: string
  recipient_email?: string
  items: string[]
  note?: string
  due_date?: string
}): Promise<{ ok: boolean }> {
  return postJSON('/api/accord/communications', body)
}
export function simulateResponse(application_id: string, items?: string[]): Promise<{ ok: boolean }> {
  return postJSON('/api/accord/communications/simulate-response', { application_id, items: items ?? [] })
}
export function inviteUser(email: string, name: string, role: string): Promise<{ user_id: string; ok: boolean }> {
  return postJSON('/api/accord/users/invite', { email, name, role })
}
export function changeUserRole(userId: string, role: string): Promise<{ ok: boolean }> {
  return postJSON(`/api/accord/users/${encodeURIComponent(userId)}/role`, { role })
}
export function deactivateUser(userId: string): Promise<{ ok: boolean }> {
  return postJSON(`/api/accord/users/${encodeURIComponent(userId)}/deactivate`, {})
}
export function createAttentionRequest(body: {
  application_id: string
  decision_id?: string
  to_user_id: string
  message: string
  priority: string
}): Promise<{ ok: boolean }> {
  return postJSON('/api/accord/attention-requests', body)
}
export function fetchNotes(appId: string): Promise<{ notes: LoanNote[] }> {
  return getJSON(`/api/accord/loans/${encodeURIComponent(appId)}/notes`)
}
export function addNote(appId: string, note: string): Promise<{ ok: boolean }> {
  return postJSON(`/api/accord/loans/${encodeURIComponent(appId)}/notes`, { note })
}
export function fetchNotifications(): Promise<NotificationsResponse> {
  return getJSON('/api/accord/notifications')
}
export function markNotificationRead(id: string): Promise<{ ok: boolean }> {
  return postJSON(`/api/accord/notifications/${encodeURIComponent(id)}/read`, {})
}
export function markAllNotificationsRead(): Promise<{ ok: boolean }> {
  return postJSON('/api/accord/notifications/read-all', {})
}
export function fetchTeammates(): Promise<{ users: TeammateLite[] }> {
  return getJSON('/api/accord/users')
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

// ── Rules Dashboard ───────────────────────────────────────────────
export interface RegulatoryRule {
  rule_id: string; authority: string; state_code: string | null; category: string
  rule_name: string; rule_value: Record<string, unknown>; display_value: string | null
  description: string; citation: string | null; source_url: string | null; effective_date: string | null
}
export interface AgencyGuideline {
  guideline_id: string; agency: string; category: string; guideline_name: string
  guideline_value: Record<string, unknown>; display_value: string | null; description: string
  conditions: string | null; citation: string | null; source_url: string | null
  effective_date: string | null; last_verified: string | null; verified_by: string | null
}
export interface TenantVersion {
  rule_version_id: string; version: number; status: string; rules: Record<string, any>
  programs: string[]; changes_summary: string | null; change_reason: string | null
  created_by: string | null; approved_by: string | null; effective_from: string | null
  effective_to: string | null; created_at: string | null; approved_at: string | null
}
export interface DataSource {
  source_id: string; source_name: string; source_url: string | null; last_download: string | null
  last_success: string | null; record_count: number | null; status: string
  next_scheduled: string | null; error_message: string | null
}
export interface RulesResponse {
  regulatory: RegulatoryRule[]; agency: AgencyGuideline[]; tenant: TenantVersion | null
  data_freshness: DataSource[]
  validation: { all_above_regulatory: boolean; errors: string[]; warnings: string[] }
}
export interface RuleAlert {
  alert_id: string; source: string; title: string; description: string | null
  url: string | null; published_date: string | null; status: string
}

export function fetchRules(): Promise<RulesResponse> {
  return getJSON('/api/accord/rules')
}
export function fetchRulesHistory(): Promise<{ versions: TenantVersion[] }> {
  return getJSON('/api/accord/rules/history')
}
export function updateRules(body: { rules: Record<string, unknown>; change_reason: string; changes_summary?: string; programs?: string[] }): Promise<{ version: number; status: string; warnings: string[] }> {
  return putJSON('/api/accord/rules', body)
}
export function approveRules(): Promise<{ ok: boolean; version: number; status: string }> {
  return postJSON('/api/accord/rules/approve', {})
}
export function lookupRules(date: string): Promise<{ found: boolean; date: string; version?: number; rules?: TenantVersion; message?: string }> {
  return getJSON(`/api/accord/rules/lookup?date=${encodeURIComponent(date)}`)
}
export function fetchDataFreshness(): Promise<{ sources: DataSource[]; all_ok: boolean; stale: DataSource[] }> {
  return getJSON('/api/accord/rules/data-freshness')
}
export function fetchRuleAlerts(): Promise<{ alerts: RuleAlert[]; new_count: number }> {
  return getJSON('/api/accord/rules/alerts')
}
