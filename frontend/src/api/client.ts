// Accord API client — thin fetch wrappers over the FastAPI backend.

import type {
  AdverseAction,
  AgentStat,
  AnalyticsOverview,
  AuditTrail,
  ComplianceHealth,
  DebateResult,
  FunnelStep,
  GovernedBy,
  LoanDetail,
  PipelineResponse,
  RainCheck,
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

async function patchJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
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
export type ActionPermissions = Record<string, boolean>
export async function fetchMe(): Promise<{ user: AuthUser; tenant: AuthTenant; permissions: string[]; action_permissions?: ActionPermissions }> {
  return getJSON('/api/accord/auth/me')
}

export interface DecideInput {
  action: 'approve' | 'deny' | 'override' | 'escalate' | 'snooze_pending_docs' | 'return_to_uw' | 'request_more_info' | 'recommend_approval'
    | 'mark_condition_received' | 'advance_to_underwriting'
  decision_id?: string
  override_reason?: string
  override_outcome?: 'approve' | 'deny' | 'clear_block' | 'waive_condition'
  feedback_message?: string
  feedback_category?: string
  reasoning?: string
  conditions?: string
  denial_code?: string
  denial_reason?: string
  note?: string
  condition_id?: string
}
export function decideLoan(appId: string, body: DecideInput): Promise<{ ok: boolean; title: string }> {
  return postJSON('/api/accord/pipeline/decide', { application_id: appId, ...body })
}

// ── My Queue / Team (role-based landing) ─────────────────────────────
export interface QueueCard {
  application_id: string
  borrower_name: string
  loan_amount: number | null
  loan_type: string | null
  loan_program?: string | null
  status: string
  stage: string
  queue_type: 'action_needed' | 'internal_request' | 'returned' | 'escalated' | 'direct_assignment'
  category?: 'clean' | 'fraud' | 'income' | 'compliance' | 'other'
  days_in_queue: number | null
  sla_days?: number
  rate_lock_days: number | null
  urgency: 'urgent' | 'normal'
  ai_finding: string
  ai_data_sources: string
  ai_recommendation: string
  senior_review?: boolean
  attention_request: { request_id: string; from: string; message: string; priority: string; category?: string | null; source?: string | null } | null
  requesting?: string[]
  sent?: string | null
  due_date?: string | null
  recipient_email?: string | null
  // Pending Response sub-type: waiting on borrower docs vs the senior UW decision.
  awaiting?: 'borrower' | 'senior'
  senior_name?: string | null
  requested_by_name?: string | null
}
export interface ResolvedReply {
  request_id: string
  application_id: string
  borrower_name: string
  loan_amount: number | null
  loan_type: string | null
  from: string
  message: string
  response: string
  resolved_at: string | null
}
export interface ProcessorCard {
  application_id: string
  borrower_name: string
  loan_amount: number | null
  loan_program?: string | null
  outstanding_count: number
  received_count: number
  days_in_verify: number | null
  status_pill: string
}
export interface ProcessorQueue {
  needs_action: ProcessorCard[]
  waiting_on_borrower: ProcessorCard[]
  ready_to_advance: ProcessorCard[]
}
export interface MyQueueResponse {
  user: { name: string; role: string }
  counts: { active: number; pending: number; decided: number }
  active: QueueCard[]
  pending: QueueCard[]
  decided: QueueCard[]
  recently_resolved?: ResolvedReply[]
  processor_queue?: ProcessorQueue | null
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
export function resolveAttentionRequest(appId: string, requestId: string, reply?: string): Promise<{ ok: boolean }> {
  return postJSON(
    `/api/accord/loans/${encodeURIComponent(appId)}/attention-requests/${encodeURIComponent(requestId)}/resolve`,
    reply ? { reply } : {},
  )
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

// ── Assignment rules (admin) ─────────────────────────────────────────
export interface AssignmentRule {
  rule_id: string
  rule_name: string
  priority: number
  min_loan_amount: number | null
  max_loan_amount: number | null
  loan_type: string | null
  min_fraud_score: number | null
  min_ltv: number | null
  assign_to_role: string
  assign_to_user_id: string | null
  is_active: boolean
  created_at: string | null
}
export type NewAssignmentRule = Omit<AssignmentRule, 'rule_id' | 'is_active' | 'created_at'>
export function fetchAssignmentRules(): Promise<{ rules: AssignmentRule[] }> {
  return getJSON('/api/accord/pipeline/assignment-rules')
}
export function createAssignmentRule(body: NewAssignmentRule): Promise<{ rule_id: string; ok: boolean }> {
  return postJSON('/api/accord/pipeline/assignment-rules', body)
}
export function toggleAssignmentRule(ruleId: string, isActive: boolean): Promise<{ ok: boolean }> {
  return patchJSON(`/api/accord/pipeline/assignment-rules/${encodeURIComponent(ruleId)}`, { is_active: isActive })
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

// ── Platform Studio (admin + super_admin) ────────────────────────────
export interface PlatformTenant {
  tenant_id: string
  name: string
  plan: string
  is_active: boolean
  products: string[]
  user_count: number
  created_at: string | null
}
export interface PlatformTenantList {
  is_super_admin: boolean
  own_tenant: string
  tenants: PlatformTenant[]
}
export interface PlatformTenantDetail extends PlatformTenant {
  los_type: string | null
  programs: string[]
  licensed_states: string[]
  channels: string[]
  contact_email: string | null
  users: { email: string; name: string; role: string }[]
  mapping_count: number
  loan_count: number
  rules: { regulatory: number; agency_guidelines: number; scope: string }
}
export interface CreateTenantInput {
  tenant_id: string
  name: string
  contact_email: string
  los_type: string
  programs: string[]
  licensed_states: string[]
  channels: string[]
  plan: string
  products: string[]
  admin_email?: string
  admin_name?: string
  admin_password?: string
}
export interface CreateTenantResult {
  ok: boolean
  tenant_id: string
  admin_created: string | null
  integration_endpoint_created: boolean
  tenant_rules_seeded: boolean
  overlay_rules_seeded: number
}
export function fetchPlatformTenants(): Promise<PlatformTenantList> {
  return getJSON<PlatformTenantList>('/api/accord/platform-studio/tenants')
}
export function fetchPlatformTenant(id: string): Promise<PlatformTenantDetail> {
  return getJSON<PlatformTenantDetail>(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}`)
}
export function updatePlatformTenant(id: string, body: Partial<CreateTenantInput>): Promise<{ status: string }> {
  return patchJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}`, body)
}
export function createPlatformTenant(body: CreateTenantInput): Promise<CreateTenantResult> {
  return postJSON('/api/accord/platform-studio/tenants', body)
}

// ── Field Mapper (Section 2) ─────────────────────────────────────────
export interface FieldMapperCanonical { entities: Record<string, string[]>; total: number }
export interface MappingSuggestion {
  source_field: string
  canonical_entity: string | null
  canonical_column: string | null
  confidence: number
  reasoning: string
}
export interface SuggestResult { suggestions: MappingSuggestion[]; method: 'claude' | 'heuristic'; model: string }
export function fetchFieldMapperCanonical(id: string): Promise<FieldMapperCanonical> {
  return getJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/field-mapper/canonical`)
}

export interface SavedMapping {
  source_system: string
  source_field: string
  canonical_entity: string
  canonical_column: string
  transform_rule: string
  notes: string | null
}
export interface SavedMappingsResult {
  tenant_id: string
  count: number
  mappings: SavedMapping[]
}
export function fetchSavedMappings(id: string): Promise<SavedMappingsResult> {
  return getJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/field-mappings`)
}
export function suggestFieldMappings(id: string, body: { source_system: string; input_type: string; raw_input: string }): Promise<SuggestResult> {
  return postJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/field-mapper/suggest`, body)
}
export function saveFieldMappings(id: string, body: { source_system: string; mappings: Array<{ source_field: string; canonical_entity: string; canonical_column: string; transform_rule: string; notes?: string }> }): Promise<{ saved: number; skipped: number }> {
  return postJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/field-mapper/save`, body)
}

// ── Policy Rules (Section 3A) ────────────────────────────────────────
export interface PolicyRule {
  rule_key: string; category: string; label: string
  overlay_value: number | null; agency_default: number | null
  agency_name: string; citation: string; description: string; is_stricter: boolean
}
export interface AssignmentRule {
  rule_id: string; rule_name: string; priority: number
  min_loan_amount: number | null; max_loan_amount: number | null; loan_type: string | null
  min_fraud_score: number | null; min_ltv: number | null; assign_to_role: string; is_active: boolean
}
export interface PolicyRulesData { rules: PolicyRule[]; assignment_rules: AssignmentRule[] }
export function fetchPolicyRules(id: string): Promise<PolicyRulesData> {
  return getJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/policy-rules`)
}
export function savePolicyRules(id: string, body: { rules: Array<{ rule_key: string; rule_type: string; overlay_value: number | null; direction: string }> }): Promise<{ saved_rules: number }> {
  return postJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/policy-rules`, body)
}
export interface ExtractedRule {
  rule_key: string; extracted_value: number; confidence: number
  reasoning: string; is_stricter: boolean
  agency_default: number | null; label: string; unit: string
}
export interface NlpExtractResult { extracted: ExtractedRule[]; method: 'claude' | 'heuristic'; model: string }
export function nlpExtractPolicy(id: string, policy_text: string): Promise<NlpExtractResult> {
  return postJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/policy-rules/nlp-extract`, { policy_text })
}

// ── Platform Studio Products (Section 4) — distinct from the catalogue Product ──
export interface PlatformProduct {
  product_id: string; product_name: string; loan_type: string; loan_purpose: string | null
  max_loan_amount: number | null; min_credit_score: number | null
  max_dti: number | null; max_ltv: number | null; is_active: boolean; created_at: string | null
}
export interface PlatformProductInput {
  product_name: string; loan_type: string; loan_purpose?: string | null
  max_loan_amount?: number | null; min_credit_score?: number | null
  max_dti?: number | null; max_ltv?: number | null; is_active: boolean
}
export function fetchPlatformProducts(id: string): Promise<{ products: PlatformProduct[] }> {
  return getJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/products`)
}
export function createPlatformProduct(id: string, body: PlatformProductInput): Promise<{ product_id: string; status: string }> {
  return postJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/products`, body)
}
export function updatePlatformProduct(id: string, productId: string, body: Partial<PlatformProductInput>): Promise<{ product_id: string; status: string }> {
  return patchJSON(`/api/accord/platform-studio/tenants/${encodeURIComponent(id)}/products/${encodeURIComponent(productId)}`, body)
}

// Exam-ready PDF export (CN-EX). Fetches the PDF blob with the Bearer header
// (a plain <a href> can't carry it) and triggers a browser download.
export async function exportExamReady(appId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/accord/loans/${encodeURIComponent(appId)}/export/exam-ready`,
    { method: 'POST', headers: authHeaders() },
  )
  if (res.status === 401) handle401('/export/exam-ready')
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — export failed`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `exam-ready-${appId}.pdf`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function fetchConditions(appId: string) {
  return getJSON<any[]>(
    `/api/accord/conditions/${encodeURIComponent(appId)}`
  )
}

export function fetchConditionsSummary(appId: string) {
  return getJSON<any>(
    `/api/accord/conditions/${encodeURIComponent(appId)}/summary`
  )
}

export function satisfyCondition(
  conditionId: string,
  body: { document_id: string; reviewed_by: string; review_notes?: string }
) {
  return patchJSON(
    `/api/accord/conditions/${encodeURIComponent(conditionId)}/satisfy`,
    body
  )
}

// ── Admin/Manager dashboard ──
export function fetchDashboardSummary() {
  return getJSON<any>('/api/accord/dashboard/summary')
}
export function fetchDashboardTeam() {
  return getJSON<any>('/api/accord/dashboard/team-performance')
}
export function fetchDashboardAttention(limit = 12) {
  return getJSON<any>(`/api/accord/dashboard/attention?limit=${limit}`)
}

export interface RuleVersionApplied {
  version: number
  effective_from: string | null
  effective_to: string | null
  decision_count: number
  changes_summary: string | null
}
export interface ExaminerReportData {
  generated_at: string
  generated_by: string
  application_id: string
  tenant_id: string
  loan_type: string | null
  rain_check?: RainCheck
  governing_regulations?: Array<{ decision_id: string; outcome: string; governed_by: GovernedBy[] }>
  rule_versions_applied?: RuleVersionApplied[]
  loan: LoanDetail
}
export function fetchExaminerReport(appId: string): Promise<ExaminerReportData> {
  return getJSON<ExaminerReportData>(`/api/accord/loans/${encodeURIComponent(appId)}/examiner-report`)
}

// ── Workbench: documented human actions + similar cases ──
export interface LoanAction {
  id: string; application_id: string; action_type: string; reason_category: string | null
  reason_text: string; performed_by: string; performed_at: string | null
  related_decision_id: string | null; visible_to: string[]
}
export interface LoanActionInput {
  action_type: string; reason_category?: string | null; reason_text: string
  related_decision_id?: string | null; visible_to?: string[]
}
export interface SimilarCase {
  application_id: string; loan_amount: number | null; fraud_score: number | null; loan_type: string | null
  outcome: string; action_type: string; reason_text: string; reason_category: string | null
  related_decision_id: string | null; resolved_days: number | null
}
export function fetchLoanActions(appId: string): Promise<{ actions: LoanAction[] }> {
  return getJSON(`/api/accord/loans/${encodeURIComponent(appId)}/actions`)
}
export function createLoanAction(appId: string, body: LoanActionInput): Promise<LoanAction> {
  return postJSON(`/api/accord/loans/${encodeURIComponent(appId)}/actions`, body)
}
export function fetchSimilarCases(appId: string): Promise<{ cases: SimilarCase[]; based_on: { fraud_score: number | null; loan_type: string | null } }> {
  return getJSON(`/api/accord/loans/${encodeURIComponent(appId)}/similar-cases`)
}

export interface DataSourceHealth {
  source: string
  category: 'federal' | 'agency' | 'system' | 'external'
  last_updated: string | null
  next_refresh: string
  status: 'current' | 'stale' | 'unknown' | 'failing'
  regulation?: string | null
  record_count?: number | null
  tests_total?: number | null
  tests_passed?: number | null
  tests_failed?: number | null
  error?: string | null
}
export interface DataHealthResponse { sources: DataSourceHealth[]; as_of: string }
export function fetchDataHealth(): Promise<DataHealthResponse> {
  return getJSON<DataHealthResponse>('/api/accord/data-health')
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

export interface HmdaIncompleteLoan { application_id: string; borrower_name: string; missing_fields: string[]; missing_count: number }
export interface HmdaIncompleteResponse {
  filing_deadline: string; total: number; complete: number; incomplete: number; pct: number; note: string
  loans: HmdaIncompleteLoan[]
}
export function fetchHmdaIncomplete(): Promise<HmdaIncompleteResponse> {
  return getJSON<HmdaIncompleteResponse>('/api/accord/audit/hmda-incomplete')
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
  change_type?: string | null; scheduled_for?: string | null; expires_at?: string | null
  rolled_back_from?: number | null; pipeline_policy?: string | null
  ratified_by?: string | null; ratified_at?: string | null; emergency_type?: string | null
}
export interface DataSource {
  source_id: string; source_name: string; source_url: string | null; last_download: string | null
  last_success: string | null; record_count: number | null; status: string
  next_scheduled: string | null; error_message: string | null
}
export interface ExpiringWaiverItem { name: string; field: string; value: number; normal: number; expires: string; days_remaining: number; severity: string }
export interface RulesResponse {
  regulatory: RegulatoryRule[]; agency: AgencyGuideline[]; tenant: TenantVersion | null
  data_freshness: DataSource[]
  validation: { all_above_regulatory: boolean; errors: string[]; warnings: string[] }
  scheduled?: TenantVersion[]; shadow?: TenantVersion | null
  examination?: { active: boolean; examiner?: string; reason?: string; started_at?: string }
  expiring?: ExpiringWaiverItem[]
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

// ── Policy Studio redesign: products, pipeline protection, field impacts ──
export interface Product {
  product_id: string; product_name: string; active_indicator: boolean
  rate_type: string | null; governing_authority: string | null
}
export function fetchProducts(): Promise<{ products: Product[]; active_count: number }> {
  return getJSON('/api/accord/products')
}
export interface PipelineProtection {
  has_history: boolean; total_locked: number; pinned: number; pinned_pct: number
  current_version: number | null; protected: Array<{ pinned_version: number; count: number }>
}
export function fetchPipelineProtection(): Promise<PipelineProtection> {
  return getJSON('/api/accord/rules/pipeline-protection')
}
export interface FieldImpact { count: number; label: string }
export function fetchFieldImpacts(): Promise<{ impacts: Record<string, FieldImpact>; active_loans: number }> {
  return getJSON('/api/accord/rules/overlay/field-impacts')
}
export interface PolicyProposal {
  proposal_id: string; decision_id: string; boundary_rule: string
  override_count: number; pattern_summary: string; proposed_change: string
  status: string; created_at: string | null
}
export function fetchPolicyProposals(): Promise<{ proposals: PolicyProposal[]; count: number }> {
  return getJSON('/api/accord/rules/policy-proposals')
}
export function actOnProposal(proposalId: string, action: 'accept' | 'dismiss'): Promise<{ status: string; action: string }> {
  return postJSON(`/api/accord/rules/policy-proposals/${proposalId}/action`, { action })
}

// ── Rules versioning (advanced) ───────────────────────────────────
export interface ScheduledVersion extends TenantVersion {}
export interface ExpiringWaiver { name: string; field: string; value: number; normal: number; expires: string; days_remaining: number; severity: string }
export interface ExaminationState { active: boolean; examiner?: string; reason?: string; started_at?: string }

export function rollbackRules(version: number, reason: string): Promise<{ version: number; message: string; affected_pipeline_loans: number; examples: Array<{ name: string; reason: string }> }> {
  return postJSON('/api/accord/rules/rollback', { rollback_to_version: version, reason })
}
export function scheduleRules(rules: Record<string, unknown>, scheduled_for: string, reason: string): Promise<{ version: number; status: string; activates: string }> {
  return postJSON('/api/accord/rules/schedule', { rules, scheduled_for, reason })
}
export function startShadow(rules: Record<string, unknown>, shadow_duration_days: number, reason: string): Promise<{ shadow_version: number; loans_evaluated: number; differences: number }> {
  return postJSON('/api/accord/rules/shadow', { rules, shadow_duration_days, reason })
}
export function fetchShadowReport(): Promise<any> {
  return getJSON('/api/accord/rules/shadow-report')
}
export function emergencyChange(rules: Record<string, unknown>, reason: string, emergency_type: string): Promise<any> {
  return postJSON('/api/accord/rules/emergency', { rules, reason, emergency_type })
}
export function ratifyEmergency(version: number, ratified: boolean, reason?: string): Promise<any> {
  return postJSON(`/api/accord/rules/emergency/${version}/ratify`, { ratified, reason })
}
export function examinationMode(action: 'start' | 'end', examiner?: string, reason?: string): Promise<any> {
  return postJSON('/api/accord/rules/examination-mode', { action, examiner, reason })
}
export function runRetrospective(date_range_start: string, date_range_end: string, simulate_version: number): Promise<any> {
  return postJSON('/api/accord/rules/retrospective', { date_range_start, date_range_end, simulate_version })
}
export function reconstructDecision(date: string, application_id: string): Promise<any> {
  return getJSON(`/api/accord/rules/reconstruct?date=${encodeURIComponent(date)}&application_id=${encodeURIComponent(application_id)}`)
}
export function setPipelinePolicy(policy: string, cutoff_date?: string): Promise<any> {
  return putJSON('/api/accord/rules/pipeline-policy', { policy, cutoff_date })
}
export function fetchRuleImpact(rules: Record<string, unknown>): Promise<{ count: number; examples: Array<{ application_id: string; name: string; reason: string }> }> {
  return postJSON('/api/accord/rules/impact', { rules })
}
export function fetchLoanRulesNote(applicationId: string): Promise<{ show: boolean; application_date?: string; applied_version?: number; applied_effective?: string; current_version?: number; current_effective?: string; differences?: Array<{ field: string; pinned: number; current: number }> }> {
  return getJSON(`/api/accord/rules/loan-note?application_id=${encodeURIComponent(applicationId)}`)
}

// ── Document viewer ───────────────────────────────────────────────
export interface DocItem {
  document_id: string; document_type: string; document_category?: string | null; display_name: string; status: string
  indexed_at: string | null; extraction_method: string | null; confidence: number | null
  key_value: string | null; key_field: string | null; extracted_data: Record<string, any>; file_path: string | null
}
export interface MissingDoc { document_type: string; display_name: string; required: boolean; reason: string }
export interface DocsResponse {
  application_id: string; documents: DocItem[]; missing_documents: MissingDoc[]
  summary: { total_on_file: number; total_missing: number; total_required_missing: number }
}
export interface SourceField {
  field_name: string; value: any; display_value: string | null; source_document: string | null
  source_field: string | null; document_id: string | null; confidence: number | null; status: string
}
export interface VerificationCategory {
  category: string; fields: SourceField[]
  discrepancy: { exists: boolean; description?: string; severity?: string; ai_used?: string }
}
export interface SourceMatchResponse { application_id: string; verifications: VerificationCategory[] }

export function fetchDocuments(appId: string): Promise<DocsResponse> {
  return getJSON(`/api/accord/documents/${encodeURIComponent(appId)}`)
}
export function fetchSourceMatch(appId: string): Promise<SourceMatchResponse> {
  return getJSON(`/api/accord/documents/${encodeURIComponent(appId)}/source-match`)
}

// ── Rule validation suite ─────────────────────────────────────────
export interface ValidationTest { id: string; category: string; description: string; input: Record<string, any>; expected: string; actual: string; passed: boolean; flags: string[] }
export interface ValidationReport {
  tenant_id: string; rule_version: number | null; total_tests: number; passed: number; failed: number
  duration_ms: number; run_at: string
  categories: Record<string, { total: number; passed: number; failed: number }>
  warnings: Array<{ id: string; severity: string; description: string }>
  tests: ValidationTest[]
}
export function runValidation(): Promise<ValidationReport> { return postJSON('/api/accord/rules/validate', {}) }
export function fetchValidationReport(): Promise<ValidationReport> { return getJSON('/api/accord/rules/validation-report') }

// ── Comparison Mode ───────────────────────────────────────────────
export interface ComparisonDetail { application_id: string; borrower: string; description: string | null; accord_decision: string; manual_decision: string; resolution: string | null }
export interface ComparisonRow { application_id: string; borrower: string; accord_outcome: string; manual_outcome: string; agreement: string }
export interface ComparisonReport {
  active: boolean; ended?: boolean
  period?: { started: string; ends: string; day: number; duration: number }
  summary?: { total_loans: number; agree: number; accord_stricter: number; accord_looser: number; disagree: number; agreement_rate: number }
  accord_caught?: ComparisonDetail[]; manual_caught?: ComparisonDetail[]; disagreements?: ComparisonDetail[]
  weekly_trend?: Array<{ week: number; loans: number; agreement: number }>
  all_comparisons?: ComparisonRow[]
}
export function startComparison(duration_days: number): Promise<{ period_id: string; ends_at: string }> { return postJSON('/api/accord/comparison/start', { duration_days }) }
export function recordManual(application_id: string, manual_outcome: string, manual_reasoning: string): Promise<{ ok: boolean; accord_outcome: string; manual_outcome: string; agreement: string; label: string }> { return postJSON('/api/accord/comparison/record-manual', { application_id, manual_outcome, manual_reasoning }) }
export function fetchComparisonReport(): Promise<ComparisonReport> { return getJSON('/api/accord/comparison/report') }
export function fetchComparisonStatus(applicationId?: string): Promise<{ active: boolean; ends_at: string | null; existing: { accord_outcome: string; manual_outcome: string; agreement: string } | null }> { return getJSON(`/api/accord/comparison/status${applicationId ? `?application_id=${encodeURIComponent(applicationId)}` : ''}`) }
export function completeComparison(): Promise<{ ok: boolean }> { return postJSON('/api/accord/comparison/complete', {}) }

// ── Onboarding / CSV import ───────────────────────────────────────
export interface ImportValidation {
  valid: boolean; row_count: number; valid_count: number
  errors: Array<{ row: number; error: string }>; warnings: string[]
  preview: Array<{ loan_number: string; borrower: string; amount: number | null; type?: string; status: string; error?: string }>
  headers: string[]; needs_mapping: boolean
  auto_mapping?: Record<string, string | null>; mapping_stats?: { auto: number; skipped: number; total: number }
}
export interface ImportResult {
  imported: number; skipped: number; errors: Array<{ row: number; error: string }>; warnings: string[]
  summary: { total_loans: number; by_type: Record<string, number>; by_status: Record<string, number>; avg_amount: number; avg_score: number; assignments: Record<string, number> }
  evaluation?: Record<string, number>; next_steps: string[]
}
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: authHeaders(), body: form })
  if (res.status === 401) handle401(path)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* */ }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}
export async function downloadImportTemplate(): Promise<void> {
  const res = await fetch(`${API_BASE}/api/accord/onboarding/template`, { headers: authHeaders() })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = 'accord_import_template.csv'
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function validateImport(file: File, mapping?: Record<string, string | null>): Promise<ImportValidation> {
  const f = new FormData(); f.append('file', file); if (mapping) f.append('mapping', JSON.stringify(mapping))
  return postForm('/api/accord/onboarding/validate', f)
}
export function importLoans(file: File, mapping?: Record<string, string | null>): Promise<ImportResult> {
  const f = new FormData(); f.append('file', file); if (mapping) f.append('mapping', JSON.stringify(mapping))
  return postForm('/api/accord/onboarding/import', f)
}
export const IMPORT_FIELDS = [
  'loan_number', 'application_date', 'loan_purpose', 'loan_type', 'channel', 'borrower_first_name', 'borrower_last_name',
  'borrower_email', 'borrower_phone', 'borrower_dob', 'borrower_ssn_last4', 'borrower_citizenship', 'employer_name',
  'employment_type', 'employment_years', 'employer_phone', 'stated_annual_income', 'verified_annual_income', 'monthly_income',
  'other_income', 'income_source', 'credit_score_experian', 'credit_score_transunion', 'credit_score_equifax', 'mid_credit_score',
  'monthly_debt_payments', 'monthly_housing_payment', 'property_address', 'property_type', 'property_state', 'property_county',
  'property_zip', 'occupancy', 'purchase_price', 'appraised_value', 'estimated_value', 'loan_amount', 'interest_rate',
  'loan_term_months', 'amortization_type', 'ltv', 'dti_front', 'dti_back', 'coborrower_first_name', 'coborrower_last_name',
  'coborrower_income', 'coborrower_credit_score', 'loan_status', 'assigned_to_email',
]

// ── Regulation transparency (admin/compliance) ──────────────────────────────
export interface RegulationRule {
  layer: 'federal' | 'agency' | 'state'
  state_code: string | null
  source: string
  rule_name: string
  display_value: string | null
  description: string | null
  citation: string | null
  effective_date: string | null
  last_refreshed: string | null
  verified_by: string | null
  is_active: boolean
  category: string | null
  regulation_id: string
}
export interface LenderRuleVersion {
  rule_version_id: string
  version: number
  status: string
  rules: Record<string, unknown>
  changes_summary: string | null
  change_reason: string | null
  effective_from: string | null
  approved_at: string | null
  pipeline_cutoff_date: string | null
  change_type: string | null
  scheduled_for: string | null
}
export interface RegulationTransparency {
  layers: { federal: RegulationRule[]; agency: RegulationRule[]; state: RegulationRule[]; lender: LenderRuleVersion[] }
  summary: {
    federal_count: number; agency_count: number; state_count: number; lender_versions: number
    states_covered: string[]; last_federal_refresh: string | null; last_agency_refresh: string | null
  }
  pipeline_protection: {
    total_locked: number; pinned: number; unpinned: number
    current_version: number | null; current_effective: string | null; note: string
  }
}
export function fetchRegulationTransparency(params?: { layer?: string; state_code?: string; category?: string }): Promise<RegulationTransparency> {
  const q = new URLSearchParams()
  if (params?.layer) q.set('layer', params.layer)
  if (params?.state_code) q.set('state_code', params.state_code)
  if (params?.category) q.set('category', params.category)
  const qs = q.toString()
  return getJSON<RegulationTransparency>(`/api/accord/rules/regulations/transparency${qs ? `?${qs}` : ''}`)
}

// ── Policy Studio backend (PROMPT E) ────────────────────────────────────────
export interface ImpactByDecision {
  decision_id: string
  threshold: number
  newly_blocked: number
  newly_allowed: number
  samples: Array<{ application_id: string; name: string; value: number; change: string }>
}
export interface PreviewImpactResult {
  total_loans_affected: number
  active_loans_evaluated: number
  impact_by_decision: ImpactByDecision[]
  recommendation: string
}
export function previewOverlayImpact(rules: Record<string, unknown>): Promise<PreviewImpactResult> {
  return postJSON('/api/accord/rules/overlay/preview-impact', { rules })
}

export interface RateSheetUploadResult {
  uploaded: number
  rows_in_file: number
  errors: string[]
  effective_dates: string[]
  uploaded_at: string
}
export async function uploadRateSheet(file: File): Promise<RateSheetUploadResult> {
  const path = '/api/accord/rules/rate-sheet/upload'
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: authHeaders(), body: fd })
  if (res.status === 401) handle401(path)
  if (!res.ok) {
    let m = `${res.status} ${res.statusText}`
    try { const j = await res.json(); if (j && typeof j.detail === 'string') m = j.detail } catch { /* non-JSON */ }
    throw new Error(m)
  }
  return res.json() as Promise<RateSheetUploadResult>
}
export interface RateSheetStatus {
  last_upload: string | null
  last_uploaded_by: string | null
  last_record_count: number | null
  total_entries: number
  recent: Array<{ product_id: string; credit_band: string; ltv_max: number; base_rate: number; llpa_adjustment: number; effective_date: string; uploaded_at: string; uploaded_by?: string | null }>
}
export function fetchRateSheetStatus(): Promise<RateSheetStatus> {
  return getJSON('/api/accord/rules/rate-sheet/status')
}
