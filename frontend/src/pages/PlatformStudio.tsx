import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  fetchPlatformTenants, fetchPlatformTenant, createPlatformTenant,
  type PlatformTenantList, type PlatformTenantDetail, type CreateTenantInput,
} from '../api/client'

const PLAN_BADGE: Record<string, string> = {
  starter: 'bg-slate-100 text-slate-600',
  professional: 'bg-blue-50 text-blue-700',
  enterprise: 'bg-emerald-50 text-emerald-700',
}
const LOS_TYPES = [
  { id: 'encompass', label: 'Encompass', icon: '📋' },
  { id: 'bytepro', label: 'BytePro', icon: '📄' },
  { id: 'openclose', label: 'OpenClose', icon: '🔧' },
  { id: 'custom', label: 'Custom', icon: '⚙️' },
]
const PROGRAM_OPTIONS = ['CONVENTIONAL', 'FHA', 'VA', 'JUMBO', 'NON_QM', 'USDA']
const CHANNEL_OPTIONS = ['retail', 'wholesale', 'correspondent', 'consumer_direct']
const US_STATES = ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY']
const slugify = (s: string) => s.toLowerCase().replace(/[^a-z0-9_]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)

function pretty(s?: string | null): string {
  return s ? String(s).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : ''
}

export default function PlatformStudio() {
  const [data, setData] = useState<PlatformTenantList | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const notify = (m: string) => { setToast(m); window.setTimeout(() => setToast(null), 2600) }

  async function load(selAfter?: string) {
    setLoading(true)
    try {
      const d = await fetchPlatformTenants()
      setData(d)
      setErr(null)
      setSelected((prev) => selAfter ?? prev ?? (d.tenants[0]?.tenant_id ?? null))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="p-12 text-center text-slate-400">Loading Platform Studio…</div>
  if (err) return (
    <div className="mx-auto mt-16 max-w-md rounded-lg border border-dashed border-red-200 bg-white p-8 text-center">
      <div className="text-sm font-semibold text-red-600">Couldn't load Platform Studio</div>
      <div className="mt-1 text-xs text-slate-400">{err}</div>
    </div>
  )
  if (!data) return null

  const isSuper = data.is_super_admin

  return (
    <div className="min-h-screen px-6 py-6" style={{ backgroundColor: '#f8f9fa' }}>
      {/* header */}
      <div className="mb-5 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Platform Studio</h1>
          <p className="text-sm text-slate-500">
            {isSuper
              ? `Managing ${data.tenants.length} tenant${data.tenants.length === 1 ? '' : 's'} · super admin`
              : `Your tenant · ${data.own_tenant}`}
          </p>
        </div>
        {isSuper && (
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22]"
          >+ Create Tenant</button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]">
        {/* ── left: tenant list ── */}
        <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
            {isSuper ? 'All Tenants' : 'Your Tenant'}
          </div>
          <div className="max-h-[70vh] overflow-y-auto">
            {data.tenants.length === 0 && (
              <div className="p-6 text-center text-sm text-slate-400">No tenants.</div>
            )}
            {data.tenants.map((t) => {
              const active = selected === t.tenant_id
              return (
                <button
                  key={t.tenant_id}
                  onClick={() => setSelected(t.tenant_id)}
                  className={`flex w-full items-center justify-between border-l-2 px-4 py-3 text-left transition ${
                    active ? 'border-[#14532d] bg-[#14532d]/5' : 'border-transparent hover:bg-slate-50'
                  }`}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${t.is_active ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                      <span className="truncate text-sm font-semibold text-slate-800">{t.name}</span>
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-slate-400">{t.tenant_id} · {t.user_count} user{t.user_count === 1 ? '' : 's'}</div>
                  </div>
                  <span className={`ml-2 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${PLAN_BADGE[t.plan] ?? 'bg-slate-100 text-slate-600'}`}>{t.plan}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* ── right: tenant detail ── */}
        <div className="min-w-0">
          {selected ? <TenantDetail tenantId={selected} /> : (
            <div className="flex h-full min-h-[40vh] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white text-sm text-slate-400">
              Select a tenant to view details.
            </div>
          )}
        </div>
      </div>

      {showCreate && isSuper && (
        <CreateTenantWizard
          onClose={() => setShowCreate(false)}
          onCreated={(id, adminCreated, goMapping) => {
            setShowCreate(false)
            notify(goMapping
              ? 'Field mapping — arriving in Section 2'
              : (adminCreated ? `Created ${id} + admin ${adminCreated}` : `Created tenant ${id}`))
            load(id)
          }}
        />
      )}

      {toast && (
        <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
    </div>
  )
}

// ── Read-only per-tenant detail panel ──
function TenantDetail({ tenantId }: { tenantId: string }) {
  const [detail, setDetail] = useState<PlatformTenantDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setDetail(null)
    fetchPlatformTenant(tenantId)
      .then((d) => { if (alive) { setDetail(d); setErr(null) } })
      .catch((e) => { if (alive) setErr(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [tenantId])

  if (loading) return <Card><div className="py-10 text-center text-sm text-slate-400">Loading tenant…</div></Card>
  if (err) return <Card><div className="py-10 text-center text-sm text-red-600">{err}</div></Card>
  if (!detail) return null

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900">{detail.name}</h2>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${detail.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                {detail.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
            <div className="mt-0.5 text-xs text-slate-400">
              {detail.tenant_id} · {pretty(detail.plan)} plan
              {detail.created_at ? ` · created ${detail.created_at.slice(0, 10)}` : ''}
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {detail.products.length === 0 && <span className="text-xs text-slate-400">No products</span>}
          {detail.products.map((p) => (
            <span key={p} className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">{pretty(p)}</span>
          ))}
        </div>
      </Card>

      {(detail.los_type || detail.programs.length > 0 || detail.contact_email) && (
        <Card title="Configuration">
          <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
            <div><span className="text-slate-400">LOS Type: </span><span className="font-medium text-slate-700">{pretty(detail.los_type) || '—'}</span></div>
            <div><span className="text-slate-400">Contact: </span><span className="font-medium text-slate-700">{detail.contact_email || '—'}</span></div>
            <div><span className="text-slate-400">Programs: </span><span className="text-slate-700">{detail.programs.map(pretty).join(', ') || '—'}</span></div>
            <div><span className="text-slate-400">Channels: </span><span className="text-slate-700">{detail.channels.map(pretty).join(', ') || '—'}</span></div>
            <div className="sm:col-span-2"><span className="text-slate-400">Licensed States: </span><span className="text-slate-700">{detail.licensed_states.join(', ') || '—'}</span></div>
          </div>
        </Card>
      )}

      {/* stat tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Users" value={detail.user_count} />
        <Stat label="Loans" value={detail.loan_count} />
        <Stat label="Field Mappings" value={detail.mapping_count} />
        <Stat label="Rules (shared)" value={detail.rules.regulatory + detail.rules.agency_guidelines} />
      </div>

      <Card title="Users">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-slate-100 text-[9px] uppercase tracking-wide text-slate-400">
                <th className="px-2 py-2 font-semibold">Name</th>
                <th className="px-2 py-2 font-semibold">Email</th>
                <th className="px-2 py-2 font-semibold">Role</th>
              </tr>
            </thead>
            <tbody>
              {detail.users.length === 0 && (
                <tr><td colSpan={3} className="px-2 py-4 text-center text-slate-400">No users.</td></tr>
              )}
              {detail.users.map((u) => (
                <tr key={u.email} className="border-b border-slate-50">
                  <td className="px-2 py-2 font-medium text-slate-800">{u.name}</td>
                  <td className="px-2 py-2 text-slate-500">{u.email}</td>
                  <td className="px-2 py-2"><span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{pretty(u.role)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Rules Catalogue (shared across all tenants)">
        <div className="flex gap-6 text-sm">
          <div><span className="font-semibold text-slate-800">{detail.rules.regulatory}</span> <span className="text-slate-500">regulatory rules</span></div>
          <div><span className="font-semibold text-slate-800">{detail.rules.agency_guidelines}</span> <span className="text-slate-500">agency guidelines</span></div>
        </div>
        <p className="mt-2 text-[11px] text-slate-400">Rules are a global catalogue — not tenant-scoped. Per-tenant rule overrides arrive in a later release.</p>
      </Card>
    </div>
  )
}

// ── Create tenant wizard (3 steps, super_admin only) ──
function CreateTenantWizard({ onClose, onCreated }: {
  onClose: () => void
  onCreated: (id: string, adminCreated: string | null, goMapping: boolean) => void
}) {
  const [step, setStep] = useState(1)
  const [form, setForm] = useState({
    name: '', tenant_id: '', idEdited: false, contact_email: '', los_type: 'encompass',
    programs: ['CONVENTIONAL'] as string[], channels: ['retail'] as string[],
    licensed_states: [] as string[],
    admin_email: '', admin_name: '', admin_password: '', admin_confirm: '',
  })
  const [stateSearch, setStateSearch] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ id: string; name: string; admin: string | null } | null>(null)

  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const slug = useMemo(() => slugify(form.idEdited ? form.tenant_id : form.name), [form.idEdited, form.tenant_id, form.name])
  const emailOk = (e: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)
  const toggle = (arr: string[], v: string) => arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]

  const step1Valid = !!form.name.trim() && !!slug && emailOk(form.contact_email) && !!form.los_type
  const step2Valid = form.programs.length > 0 && form.channels.length > 0
  const wantsAdmin = !!(form.admin_email || form.admin_password || form.admin_name)
  const step3Valid = !wantsAdmin || (emailOk(form.admin_email) && form.admin_password.length >= 6 && form.admin_password === form.admin_confirm)
  const stepValid = step === 1 ? step1Valid : step === 2 ? step2Valid : step3Valid

  async function submit() {
    if (!step3Valid || submitting) return
    setSubmitting(true); setError(null)
    try {
      const body: CreateTenantInput = {
        tenant_id: slug, name: form.name.trim(), contact_email: form.contact_email.trim(),
        los_type: form.los_type, programs: form.programs, channels: form.channels,
        licensed_states: form.licensed_states, plan: 'starter', products: ['pipeline'],
      }
      if (wantsAdmin) {
        body.admin_email = form.admin_email.trim()
        body.admin_name = form.admin_name.trim() || undefined
        body.admin_password = form.admin_password
      }
      const res = await createPlatformTenant(body)
      setDone({ id: res.tenant_id, name: form.name.trim(), admin: res.admin_created })
    } catch (e) {
      setError(e instanceof Error ? e.message.replace(/^\d+\s+\w+\s+—\s+/, '') : String(e))
    } finally { setSubmitting(false) }
  }

  const filteredStates = US_STATES.filter((s) => !form.licensed_states.includes(s) && s.includes(stateSearch.toUpperCase()))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        {done ? (
          <div className="py-6 text-center">
            <div className="text-3xl">✅</div>
            <h3 className="mt-2 text-xl font-bold text-slate-900">{done.name} is now live!</h3>
            {done.admin && <p className="mt-1 text-sm text-slate-500">{done.admin} has been created</p>}
            <div className="mt-6 flex justify-center gap-3">
              <button onClick={() => onCreated(done.id, done.admin, true)} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22]">Configure Field Mapping →</button>
              <button onClick={() => onCreated(done.id, done.admin, false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">View in Tenant List</button>
            </div>
          </div>
        ) : (<>
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-lg font-bold text-slate-900">New Lender — Step {step} of 3</h3>
            <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
          </div>
          <div className="mb-5 flex items-center gap-2">
            {[1, 2, 3].map((n) => (
              <div key={n} className="flex flex-1 items-center gap-2">
                <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${step >= n ? 'bg-[#14532d] text-white' : 'bg-slate-100 text-slate-400'}`}>{n}</span>
                {n < 3 && <div className={`h-0.5 flex-1 ${step > n ? 'bg-[#14532d]' : 'bg-slate-100'}`} />}
              </div>
            ))}
          </div>

          {step === 1 && (
            <div className="space-y-3">
              <Field label="Lender name *"><input value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="Capital Loans Mortgage" className={inputCls} /></Field>
              <Field label="Tenant ID *" hint={`preview: ${slug || '—'}`}><input value={form.idEdited ? form.tenant_id : slug} onChange={(e) => set({ tenant_id: e.target.value, idEdited: true })} className={inputCls} /></Field>
              <Field label="Contact email *"><input value={form.contact_email} onChange={(e) => set({ contact_email: e.target.value })} placeholder="ops@capitalloans.com" className={inputCls} /></Field>
              <Field label="LOS type *">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {LOS_TYPES.map((l) => (
                    <button key={l.id} type="button" onClick={() => set({ los_type: l.id })}
                      className={`rounded-lg border px-2 py-3 text-center text-xs font-medium ${form.los_type === l.id ? 'border-[#14532d] bg-[#14532d]/5 text-[#14532d]' : 'border-slate-200 text-slate-500 hover:bg-slate-50'}`}>
                      <div className="text-lg">{l.icon}</div>{l.label}
                    </button>
                  ))}
                </div>
              </Field>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <Field label="Programs">
                <div className="grid grid-cols-2 gap-2">
                  {PROGRAM_OPTIONS.map((p) => (
                    <label key={p} className="flex items-center gap-2 rounded-md border border-slate-200 px-2 py-1.5 text-sm">
                      <input type="checkbox" checked={form.programs.includes(p)} onChange={() => set({ programs: toggle(form.programs, p) })} />
                      {pretty(p)}
                    </label>
                  ))}
                </div>
              </Field>
              <Field label="Channels">
                <div className="grid grid-cols-2 gap-2">
                  {CHANNEL_OPTIONS.map((c) => (
                    <label key={c} className="flex items-center gap-2 rounded-md border border-slate-200 px-2 py-1.5 text-sm">
                      <input type="checkbox" checked={form.channels.includes(c)} onChange={() => set({ channels: toggle(form.channels, c) })} />
                      {pretty(c)}
                    </label>
                  ))}
                </div>
              </Field>
              <Field label="Licensed states">
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {form.licensed_states.map((s) => (
                    <span key={s} className="flex items-center gap-1 rounded bg-[#14532d]/10 px-2 py-0.5 text-xs font-medium text-[#14532d]">
                      {s} <button type="button" onClick={() => set({ licensed_states: form.licensed_states.filter((x) => x !== s) })}>×</button>
                    </span>
                  ))}
                  {form.licensed_states.length === 0 && <span className="text-xs text-slate-400">None selected</span>}
                </div>
                <input value={stateSearch} onChange={(e) => setStateSearch(e.target.value)} placeholder="Search states…" className={inputCls} />
                {stateSearch && (
                  <div className="mt-1 max-h-32 overflow-y-auto rounded-md border border-slate-200">
                    {filteredStates.slice(0, 12).map((s) => (
                      <button key={s} type="button" onClick={() => { set({ licensed_states: [...form.licensed_states, s] }); setStateSearch('') }}
                        className="block w-full px-3 py-1.5 text-left text-sm hover:bg-slate-50">{s}</button>
                    ))}
                    {filteredStates.length === 0 && <div className="px-3 py-1.5 text-xs text-slate-400">No match</div>}
                  </div>
                )}
              </Field>
            </div>
          )}

          {step === 3 && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Admin User (optional)</div>
                <Field label="Admin email"><input value={form.admin_email} onChange={(e) => set({ admin_email: e.target.value })} className={inputCls} /></Field>
                <Field label="Admin name"><input value={form.admin_name} onChange={(e) => set({ admin_name: e.target.value })} className={inputCls} /></Field>
                <Field label="Password" hint="min 6 chars"><input type="password" value={form.admin_password} onChange={(e) => set({ admin_password: e.target.value })} className={inputCls} /></Field>
                <Field label="Confirm password"><input type="password" value={form.admin_confirm} onChange={(e) => set({ admin_confirm: e.target.value })} className={inputCls} /></Field>
                {wantsAdmin && form.admin_password !== form.admin_confirm && <p className="text-xs text-red-600">Passwords don't match</p>}
                <p className="text-[11px] text-slate-400">Leave blank to add users later via Settings.</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="mb-2 font-semibold text-slate-700">Summary</div>
                <Row k="Lender" v={form.name} /><Row k="Tenant ID" v={slug} /><Row k="Contact" v={form.contact_email} />
                <Row k="LOS" v={pretty(form.los_type)} /><Row k="Programs" v={form.programs.map(pretty).join(', ')} />
                <Row k="Channels" v={form.channels.map(pretty).join(', ')} /><Row k="States" v={form.licensed_states.join(', ') || '—'} />
              </div>
            </div>
          )}

          {error && <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}

          <div className="mt-5 flex justify-between">
            <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">Cancel</button>
            <div className="flex gap-2">
              {step > 1 && <button onClick={() => setStep(step - 1)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">← Back</button>}
              {step < 3 && <button onClick={() => stepValid && setStep(step + 1)} disabled={!stepValid} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">Next →</button>}
              {step === 3 && <button onClick={submit} disabled={!step3Valid || submitting} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">{submitting ? 'Creating…' : 'Create Lender'}</button>}
            </div>
          </div>
        </>)}
      </div>
    </div>
  )
}
function Row({ k, v }: { k: string; v: string }) {
  return <div className="mb-1 flex gap-2"><span className="w-16 shrink-0 text-slate-400">{k}</span><span className="text-slate-700">{v || '—'}</span></div>
}

// ── small components ──
const inputCls = 'w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-[#14532d] focus:outline-none'

function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {title && <div className="mb-2 text-xs font-semibold text-slate-700">{title}</div>}
      {children}
    </div>
  )
}
function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-bold text-slate-900">{value}</div>
    </div>
  )
}
function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-slate-600">{label}</span>
        {hint && <span className="text-[10px] text-slate-400">{hint}</span>}
      </div>
      {children}
    </label>
  )
}
