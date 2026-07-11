import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  fetchPlatformTenants, fetchPlatformTenant, createPlatformTenant, updatePlatformTenant,
  fetchFieldMapperCanonical, suggestFieldMappings, saveFieldMappings, fetchSavedMappings,
  fetchPolicyRules, savePolicyRules, nlpExtractPolicy,
  fetchPlatformProducts, createPlatformProduct, updatePlatformProduct,
  type PlatformTenantList, type PlatformTenantDetail, type CreateTenantInput,
  type MappingSuggestion, type PolicyRule, type AssignmentRule, type ExtractedRule, type SavedMapping,
  type PlatformProduct, type PlatformProductInput,
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
  const [mapperTenant, setMapperTenant] = useState<{ id: string; name: string; losType?: string } | null>(null)
  const [policyTenant, setPolicyTenant] = useState<{ id: string; name: string } | null>(null)
  const [productsTenant, setProductsTenant] = useState<{ id: string; name: string } | null>(null)
  const [confirmationTenant, setConfirmationTenant] = useState<{ id: string; name: string } | null>(null)
  const [editTenant, setEditTenant] = useState<PlatformTenantDetail | null>(null)
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

  if (mapperTenant) {
    return (
      <div className="min-h-screen px-6 py-6" style={{ backgroundColor: '#f8f9fa' }}>
        <FieldMapper
          tenantId={mapperTenant.id}
          tenantName={mapperTenant.name}
          losType={mapperTenant.losType}
          onBack={() => { const id = mapperTenant.id; setMapperTenant(null); load(id) }}
        />
      </div>
    )
  }

  if (policyTenant) {
    return (
      <div className="min-h-screen px-6 py-6" style={{ backgroundColor: '#f8f9fa' }}>
        <PolicyRules
          tenantId={policyTenant.id}
          tenantName={policyTenant.name}
          onBack={() => { const id = policyTenant.id; setPolicyTenant(null); load(id) }}
        />
      </div>
    )
  }

  if (confirmationTenant) {
    return (
      <div className="min-h-screen px-6 py-6" style={{ backgroundColor: '#f8f9fa' }}>
        <OnboardingConfirmation
          tenantId={confirmationTenant.id}
          tenantName={confirmationTenant.name}
          onBack={() => { const id = confirmationTenant.id; setConfirmationTenant(null); load(id) }}
          onEditMapping={() => { const t = confirmationTenant; setConfirmationTenant(null); setMapperTenant({ id: t.id, name: t.name }) }}
          onEditPolicy={() => { const t = confirmationTenant; setConfirmationTenant(null); setPolicyTenant({ id: t.id, name: t.name }) }}
          onEditProducts={() => { const t = confirmationTenant; setConfirmationTenant(null); setProductsTenant({ id: t.id, name: t.name }) }}
        />
      </div>
    )
  }

  if (productsTenant) {
    return (
      <div className="min-h-screen px-6 py-6" style={{ backgroundColor: '#f8f9fa' }}>
        <Products
          tenantId={productsTenant.id}
          tenantName={productsTenant.name}
          onBack={() => { const id = productsTenant.id; setProductsTenant(null); load(id) }}
        />
      </div>
    )
  }

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
          {selected ? <TenantDetail tenantId={selected} onConfigureMapping={(id, name, losType) => setMapperTenant({ id, name, losType })} onConfigurePolicy={(id, name) => setPolicyTenant({ id, name })} onConfigureProducts={(id, name) => setProductsTenant({ id, name })} onGoLive={(id, name) => setConfirmationTenant({ id, name })} onEdit={(d) => setEditTenant(d)} /> : (
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
            if (goMapping) { setMapperTenant({ id, name: id }); return }
            notify(adminCreated ? `Created ${id} + admin ${adminCreated}` : `Created tenant ${id}`)
            load(id)
          }}
        />
      )}
      {editTenant && <EditTenantModal detail={editTenant} onClose={() => setEditTenant(null)} onSaved={() => { const id = editTenant.tenant_id; setEditTenant(null); load(id) }} />}

      {toast && (
        <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
    </div>
  )
}

// ── Read-only per-tenant detail panel ──
function TenantDetail({ tenantId, onConfigureMapping, onConfigurePolicy, onConfigureProducts, onGoLive, onEdit }: { tenantId: string; onConfigureMapping: (id: string, name: string, losType?: string) => void; onConfigurePolicy: (id: string, name: string) => void; onConfigureProducts: (id: string, name: string) => void; onGoLive: (id: string, name: string) => void; onEdit: (d: PlatformTenantDetail) => void }) {
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
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            <button
              onClick={() => onConfigureProducts(detail.tenant_id, detail.name)}
            className="rounded-lg border border-[#14532d] px-3 py-1.5 text-xs font-semibold text-[#14532d] hover:bg-[#14532d]/5"
            >Loan Products →</button>
            <button onClick={() => onEdit(detail)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">Edit Tenant</button>
            <button
              onClick={() => onConfigurePolicy(detail.tenant_id, detail.name)}
              className="rounded-lg border border-[#14532d] px-3 py-1.5 text-xs font-semibold text-[#14532d] hover:bg-[#14532d]/5"
            >Credit Policy →</button>
            <button
              onClick={() => onConfigureMapping(detail.tenant_id, detail.name, detail.los_type ?? undefined)}
              className="rounded-lg bg-[#14532d] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0f3d22]"
            >Map Your Fields →</button>
            <button
              onClick={() => onGoLive(detail.tenant_id, detail.name)}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
            >Go Live ✓</button>
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
    name: '', tenant_id: '', idEdited: false, contact_email: '', los_type: 'encompass', plan: 'starter',
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
        licensed_states: form.licensed_states, plan: form.plan || 'starter', products: ['pipeline'],
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

  const STATE_NAME_MAP: Record<string, string> = {
    AL:'Alabama',AK:'Alaska',AZ:'Arizona',AR:'Arkansas',CA:'California',
    CO:'Colorado',CT:'Connecticut',DE:'Delaware',DC:'Washington D.C.',FL:'Florida',
    GA:'Georgia',HI:'Hawaii',ID:'Idaho',IL:'Illinois',IN:'Indiana',IA:'Iowa',
    KS:'Kansas',KY:'Kentucky',LA:'Louisiana',ME:'Maine',MD:'Maryland',
    MA:'Massachusetts',MI:'Michigan',MN:'Minnesota',MS:'Mississippi',MO:'Missouri',
    MT:'Montana',NE:'Nebraska',NV:'Nevada',NH:'New Hampshire',NJ:'New Jersey',
    NM:'New Mexico',NY:'New York',NC:'North Carolina',ND:'North Dakota',OH:'Ohio',
    OK:'Oklahoma',OR:'Oregon',PA:'Pennsylvania',RI:'Rhode Island',SC:'South Carolina',
    SD:'South Dakota',TN:'Tennessee',TX:'Texas',UT:'Utah',VT:'Vermont',
    VA:'Virginia',WA:'Washington',WV:'West Virginia',WI:'Wisconsin',WY:'Wyoming',
  }
  const filteredStates = US_STATES.filter((s) => {
    if (form.licensed_states.includes(s)) return false
    const q = stateSearch.toLowerCase()
    if (!q) return true
    return s.toLowerCase().includes(q) || (STATE_NAME_MAP[s] ?? '').toLowerCase().includes(q)
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        {done ? (
          <div className="py-6 text-center">
            <div className="text-3xl">✅</div>
            <h3 className="mt-2 text-xl font-bold text-slate-900">{done.name} is now live!</h3>
            {done.admin && <p className="mt-1 text-sm text-slate-500">{done.admin} has been created</p>}
            <div className="mt-6 flex justify-center gap-3">
              <button onClick={() => onCreated(done.id, done.admin, true)} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22]">Map Your Fields →</button>
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
              <Field label="Plan *">
                <select value={form.plan || 'starter'} onChange={(e) => set({ plan: e.target.value })} className={inputCls}>
                  <option value="starter">Starter</option>
                  <option value="growth">Growth</option>
                  <option value="business">Business</option>
                  <option value="enterprise">Enterprise</option>
                </select>
              </Field>
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

// ── Field Mapper (Section 2) — NLP source->canonical mapping ──
const SOURCE_SYSTEMS = ['encompass', 'bytepro', 'openclose', 'custom']
const TRANSFORMS = ['direct', 'enum', 'date', 'encrypt']
type MapRow = MappingSuggestion & { keep: boolean; transform_rule: string }
const confBadge = (c: number) => c > 0.85
  ? { t: 'High', cls: 'bg-emerald-50 text-emerald-700' }
  : c >= 0.6 ? { t: 'Medium', cls: 'bg-amber-50 text-amber-700' }
             : { t: 'Review', cls: 'bg-red-50 text-red-700' }

function FieldMapper({ tenantId, tenantName, losType, onBack }: { tenantId: string; tenantName: string; losType?: string; onBack: () => void }) {
  const [sourceSystem, setSourceSystem] = useState(losType?.toLowerCase() ?? 'encompass')
  const [tab, setTab] = useState<'upload' | 'paste'>('paste')
  const [raw, setRaw] = useState('')
  const [fileType, setFileType] = useState<string | null>(null)
  const [canonical, setCanonical] = useState<Record<string, string[]>>({})
  const [rows, setRows] = useState<MapRow[] | null>(null)
  const [method, setMethod] = useState(''); const [model, setModel] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<{ saved: number } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [existingMappings, setExistingMappings] = useState<SavedMapping[]>([])
  const [showExisting, setShowExisting] = useState(false)

  useEffect(() => {
    setRows(null); setSaved(null); setErr(null)
    fetchFieldMapperCanonical(tenantId).then((d) => setCanonical(d.entities)).catch(() => {})
    fetchSavedMappings(tenantId).then((d) => {
      setExistingMappings(d.mappings)
      if (d.count > 0) {
        setShowExisting(true)
        setRaw(d.mappings.map((m) => m.source_field).join(', '))
      }
    }).catch(() => {})
  }, [tenantId])
  const options = useMemo(() => Object.entries(canonical).flatMap(([e, cols]) => cols.map((c) => `${e}.${c}`)), [canonical])

  const detectType = (t: string) => fileType ?? (/^\s*[[{]/.test(t) ? 'json_keys' : 'paste')
  async function onFile(f: File) {
    setRaw(await f.text())
    const n = f.name.toLowerCase()
    setFileType(n.endsWith('.json') ? 'json_keys' : n.endsWith('.csv') ? 'csv_headers' : null)
  }
  async function suggest() {
    if (!raw.trim() || loading) return
    setLoading(true); setErr(null)
    try {
      const res = await suggestFieldMappings(tenantId, { source_system: sourceSystem, input_type: detectType(raw), raw_input: raw })
      setRows(res.suggestions.map((s) => ({ ...s, keep: !!s.canonical_column, transform_rule: 'direct' })))
      setMethod(res.method); setModel(res.model)
    } catch (e) { setErr(e instanceof Error ? e.message.replace(/^\d+\s+\w+\s+—\s+/, '') : String(e)) }
    finally { setLoading(false) }
  }
  const upd = (i: number, patch: Partial<MapRow>) => setRows((rs) => rs!.map((r, k) => k === i ? { ...r, ...patch } : r))
  const acceptHighConf = () => setRows((rs) => rs!.map((r) => r.confidence > 0.85 && r.canonical_column ? { ...r, keep: true } : r))
  async function save() {
    if (!rows || saving) return
    const keep = rows.filter((r) => r.keep && r.canonical_entity && r.canonical_column)
    if (!keep.length) { setErr('Nothing to save — keep at least one mapping.'); return }
    setSaving(true); setErr(null)
    try {
      const res = await saveFieldMappings(tenantId, {
        source_system: sourceSystem,
        mappings: keep.map((r) => ({ source_field: r.source_field, canonical_entity: r.canonical_entity!, canonical_column: r.canonical_column!, transform_rule: r.transform_rule, notes: r.reasoning })),
      })
      setSaved({ saved: res.saved })
    } catch (e) { setErr(e instanceof Error ? e.message.replace(/^\d+\s+\w+\s+—\s+/, '') : String(e)) }
    finally { setSaving(false) }
  }

  const mappedCount = rows?.filter((r) => r.keep && r.canonical_column).length ?? 0
  const reviewCount = (rows?.length ?? 0) - mappedCount

  return (
    <div>
      <button onClick={onBack} className="mb-3 text-sm text-slate-500 hover:text-slate-800">← Back to tenants</button>
      <h1 className="text-2xl font-semibold text-slate-900">Map Your Fields — {tenantName}</h1>
      <p className="mb-4 text-sm text-slate-500">Map your LOS fields to canonical mortgage fields</p>
      {existingMappings.length > 0 && (
        <div className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50">
          <button
            onClick={() => setShowExisting(v => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-sm font-semibold text-emerald-800"
          >
            <span>✓ {existingMappings.length} saved mappings — click to view/edit</span>
            <span className="text-emerald-600">{showExisting ? '▲' : '▼'}</span>
          </button>
          {showExisting && (
            <div className="border-t border-emerald-200 px-4 py-3 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-emerald-200 text-[10px] uppercase tracking-wide text-emerald-600">
                    <th className="py-1.5 pr-4">Source Field</th>
                    <th className="py-1.5 pr-4">Canonical Mapping</th>
                    <th className="py-1.5 pr-4">Transform</th>
                    <th className="py-1.5">Source System</th>
                  </tr>
                </thead>
                <tbody>
                  {existingMappings.map((m, i) => (
                    <tr key={i} className="border-b border-emerald-100 last:border-0">
                      <td className="py-1.5 pr-4 font-mono text-slate-700">{m.source_field}</td>
                      <td className="py-1.5 pr-4 font-medium text-emerald-700">{m.canonical_entity}.{m.canonical_column}</td>
                      <td className="py-1.5 pr-4 text-slate-500">{m.transform_rule}</td>
                      <td className="py-1.5 text-slate-400">{m.source_system}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {saved ? (
        <Card>
          <div className="py-6 text-center">
            <div className="text-3xl">✅</div>
            <h3 className="mt-2 text-lg font-bold text-slate-900">{saved.saved} field mappings saved for {tenantName}</h3>
            <button onClick={onBack} className="mt-4 text-sm font-medium text-blue-600 hover:underline">View in tenant detail →</button>
          </div>
        </Card>
      ) : !rows ? (
        <Card>
          <Field label="Source system">
            <div className="flex flex-wrap gap-2">
              {SOURCE_SYSTEMS.map((s) => {
                const isActive = sourceSystem === s
                const isDisabled = !!losType && s !== losType.toLowerCase() && s !== 'custom'
                return (
                  <button key={s}
                    onClick={() => !isDisabled && setSourceSystem(s)}
                    title={isDisabled ? `This tenant uses ${losType}` : undefined}
                    className={`rounded-md border px-3 py-1.5 text-xs font-medium transition
                      ${isActive ? 'border-[#14532d] bg-[#14532d]/5 text-[#14532d]' : 'border-slate-200 text-slate-500 hover:bg-slate-50'}`}
                    style={isDisabled ? { opacity: 0.25, cursor: 'not-allowed', pointerEvents: 'none' } : {}}>
                    {pretty(s)}
                  </button>
                )
              })}
            </div>
          </Field>
          <div className="mt-3 flex gap-2 border-b border-slate-100">
            {(['upload', 'paste'] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`border-b-2 px-3 py-2 text-sm font-medium ${tab === t ? 'border-[#14532d] text-[#14532d]' : 'border-transparent text-slate-400'}`}>{t === 'upload' ? 'Upload File' : 'Paste Fields'}</button>
            ))}
          </div>
          {tab === 'upload' ? (
            <label className="mt-3 flex h-32 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-200 text-sm text-slate-400 hover:bg-slate-50">
              <input type="file" accept=".csv,.json,text/csv,application/json" className="hidden"
                onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
              {raw ? `Loaded ${raw.length} chars${fileType ? ` (${fileType})` : ''}` : 'Drop your Encompass export header row or field list here'}
            </label>
          ) : (
            <textarea value={raw} onChange={(e) => { setRaw(e.target.value); setFileType(null) }} rows={6}
              placeholder={'Paste field names, one per line or comma-separated\ne.g. loan_amt, fico_score, borrower_name, dti_ratio'}
              className="mt-3 w-full rounded-md border border-slate-200 p-3 text-sm focus:border-[#14532d] focus:outline-none" />
          )}
          {err && <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
          <button onClick={suggest} disabled={!raw.trim() || loading}
            className="mt-4 rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">
            {loading ? 'Asking Claude…' : 'Suggest Mappings'}
          </button>
        </Card>
      ) : (
        <Card>
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm text-slate-600"><span className="font-semibold text-slate-800">{mappedCount}</span> mapped, <span className="font-semibold text-amber-600">{reviewCount}</span> need review</div>
            <button onClick={acceptHighConf} className="rounded-md border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50">Accept All High Confidence</button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12px]">
              <thead><tr className="border-b border-slate-100 text-[9px] uppercase tracking-wide text-slate-400">
                <th className="px-2 py-2">Source Field</th><th className="px-2 py-2">Suggested Canonical</th>
                <th className="px-2 py-2">Confidence</th><th className="px-2 py-2">Transform</th><th className="px-2 py-2">Keep</th>
              </tr></thead>
              <tbody>
                {rows.map((r, i) => {
                  const b = confBadge(r.confidence)
                  return (
                    <tr key={r.source_field} className={`border-b border-slate-50 ${r.keep ? '' : 'opacity-50'}`}>
                      <td className="px-2 py-2"><span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">{r.source_field}</span></td>
                      <td className="px-2 py-2">
                        <select value={r.canonical_entity && r.canonical_column ? `${r.canonical_entity}.${r.canonical_column}` : ''}
                          onChange={(e) => { const v = e.target.value; const parts = v ? v.split('.') : [null, null]; upd(i, { canonical_entity: parts[0], canonical_column: parts[1], keep: !!v }) }}
                          className="w-full rounded border border-slate-200 px-1.5 py-1 text-[11px]">
                          <option value="">— skip —</option>
                          {options.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-2"><span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${b.cls}`} title={r.reasoning}>{b.t} {Math.round(r.confidence * 100)}%</span></td>
                      <td className="px-2 py-2">
                        <select value={r.transform_rule} onChange={(e) => upd(i, { transform_rule: e.target.value })} className="rounded border border-slate-200 px-1.5 py-1 text-[11px]">
                          {TRANSFORMS.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-2"><input type="checkbox" checked={r.keep} onChange={(e) => upd(i, { keep: e.target.checked })} /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {err && <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
          <div className="mt-4 flex items-center justify-between">
            <span className="text-[11px] text-slate-400">{method === 'claude' ? `🤖 Mapped by Claude ${model}` : '🔧 Mapped by fuzzy matching (no AI key)'}</span>
            <div className="flex gap-2">
              <button onClick={() => setRows(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">← New input</button>
              <button onClick={save} disabled={saving || mappedCount === 0} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">{saving ? 'Saving…' : `Save Field Mappings (${mappedCount})`}</button>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}

// ── Policy Rules (Section 3A) — overlay thresholds vs agency defaults ──
const CAT_LABEL: Record<string, string> = { dti: 'DTI', credit: 'Credit', ltv: 'LTV', fraud: 'Fraud', income: 'Income', reserves: 'Reserves' }
const HIGHER_STRICTER = new Set(['credit_min_score', 'reserves_months_required', 'reserves_months_jumbo', 'income_min_confidence'])
function sliderCfg(cat: string) {
  if (cat === 'dti') return { min: 36, max: 57, step: 0.5, unit: '%' }
  if (cat === 'credit') return { min: 500, max: 800, step: 5, unit: '' }
  if (cat === 'ltv') return { min: 60, max: 97, step: 0.5, unit: '%' }
  if (cat === 'fraud' || cat === 'income') return { min: 0.50, max: 0.95, step: 0.01, unit: '' }
  if (cat === 'reserves') return { min: 1, max: 24, step: 1, unit: ' mo' }
  return { min: 0, max: 100, step: 1, unit: '' }
}
function stricterState(rk: string, val: number, def: number | null): 'stricter' | 'looser' | 'same' {
  if (def == null || val === def) return 'same'
  return (HIGHER_STRICTER.has(rk) ? val > def : val < def) ? 'stricter' : 'looser'
}

function PolicyRules({ tenantId, tenantName, onBack }: { tenantId: string; tenantName: string; onBack: () => void }) {
  const [rules, setRules] = useState<PolicyRule[] | null>(null)
  const [assigns, setAssigns] = useState<AssignmentRule[]>([])
  const [values, setValues] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [savedSummary, setSavedSummary] = useState<{count: number; rules: Array<{label: string; value: number; unit: string}>} | null>(null)
  // Mode B (plain-English NLP)
  const [mode, setMode] = useState<'form' | 'nlp'>('form')
  const [policyText, setPolicyText] = useState('')
  const [extracted, setExtracted] = useState<(ExtractedRule & { apply: boolean })[] | null>(null)
  const [extMethod, setExtMethod] = useState(''); const [extModel, setExtModel] = useState('')
  const [extracting, setExtracting] = useState(false)

  useEffect(() => {
    let alive = true
    fetchPolicyRules(tenantId).then((d) => {
      if (!alive) return
      setRules(d.rules); setAssigns(d.assignment_rules)
      const init: Record<string, number> = {}
      d.rules.forEach((r) => {
        const cfg = sliderCfg(r.category)
        init[r.rule_key] = r.overlay_value ?? r.agency_default ?? (cfg.min + cfg.max) / 2
      })
      setValues(init); setErr(null)
      // Pre-populate plain English textarea with existing overlay values
      const hasOverlays = d.rules.some((r) => r.overlay_value !== null)
      if (hasOverlays) {
        const lines = d.rules
          .filter((r) => r.overlay_value !== null)
          .map((r) => {
            const cfg = sliderCfg(r.category)
            return `${r.label}: ${r.overlay_value}${cfg.unit}`
          })
        setPolicyText(lines.join('\n'))
        // Also show saved summary immediately on load
        setSavedSummary({ count: d.rules.filter(r => r.overlay_value !== null).length,
          rules: d.rules.filter(r => r.overlay_value !== null).map(r => {
            const cfg = sliderCfg(r.category)
            return { label: r.label, value: r.overlay_value ?? 0, unit: cfg.unit }
          })})
      }
    }).catch((e) => setErr(e instanceof Error ? e.message : String(e))).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [tenantId])

  async function save() {
    if (!rules || saving) return
    setSaving(true); setErr(null)
    try {
      const body = {
        rules: rules.map((r) => {
          const v = values[r.rule_key]
          return { rule_key: r.rule_key, rule_type: r.rule_key, overlay_value: v,
                   direction: stricterState(r.rule_key, v, r.agency_default) === 'looser' ? 'looser' : 'stricter' }
        }),
      }
      const res = await savePolicyRules(tenantId, body)
      const summary = (rules ?? []).map((r) => {
        const cfg = sliderCfg(r.category)
        return { label: r.label, value: values[r.rule_key] ?? r.agency_default ?? 0, unit: cfg.unit }
      })
      setSavedSummary({ count: res.saved_rules, rules: summary })
      setToast(`Credit policy saved — ${res.saved_rules} rules active`)
      window.setTimeout(() => setToast(null), 2600)
    } catch (e) { setErr(e instanceof Error ? e.message.replace(/^\d+\s+\w+\s+—\s+/, '') : String(e)) }
    finally { setSaving(false) }
  }

  async function extract() {
    if (!policyText.trim() || extracting) return
    setExtracting(true); setErr(null)
    try {
      const res = await nlpExtractPolicy(tenantId, policyText)
      setExtracted(res.extracted.map((e) => ({ ...e, apply: true })))
      setExtMethod(res.method); setExtModel(res.model)
    } catch (e) { setErr(e instanceof Error ? e.message.replace(/^\d+\s+\w+\s+—\s+/, '') : String(e)) }
    finally { setExtracting(false) }
  }
  async function applyExtracted() {
    if (!extracted || saving) return
    const chosen = extracted.filter((e) => e.apply)
    if (!chosen.length) { setErr('Select at least one rule to apply.'); return }
    setValues((p) => { const n = { ...p }; chosen.forEach((e) => { n[e.rule_key] = e.extracted_value }); return n })
    setSaving(true); setErr(null)
    try {
      const res = await savePolicyRules(tenantId, {
        rules: chosen.map((e) => ({ rule_key: e.rule_key, rule_type: e.rule_key,
          overlay_value: e.extracted_value, direction: e.is_stricter ? 'stricter' : 'looser' })),
      })
      const summary = (rules ?? []).map((r) => {
        const cfg = sliderCfg(r.category)
        return { label: r.label, value: values[r.rule_key] ?? r.agency_default ?? 0, unit: cfg.unit }
      })
      setSavedSummary({ count: res.saved_rules, rules: summary })
      setToast(`Credit policy saved — ${res.saved_rules} rules active`)
      window.setTimeout(() => setToast(null), 2600)
      setExtracted(null); setPolicyText('')
    } catch (e) { setErr(e instanceof Error ? e.message.replace(/^\d+\s+\w+\s+—\s+/, '') : String(e)) }
    finally { setSaving(false) }
  }

  if (loading) return <div className="p-12 text-center text-slate-400">Loading policy rules…</div>
  if (err && !rules) return <Card><div className="py-8 text-center text-sm text-red-600">{err}</div></Card>
  if (!rules) return null

  const byCat: Record<string, PolicyRule[]> = {}
  rules.forEach((r) => { (byCat[r.category] ??= []).push(r) })

  return (
    <div className="pb-24">
      <button onClick={onBack} className="mb-3 text-sm text-slate-500 hover:text-slate-800">← Back to tenants</button>
      <h1 className="text-2xl font-semibold text-slate-900">Credit Policy — {tenantName}</h1>
      <p className="mb-4 text-sm text-slate-500">Set tenant overlays against agency defaults. Stricter overlays tighten eligibility.</p>

      <div className="mb-4 inline-flex rounded-lg border border-slate-200 bg-white p-1">
        {([['form', '📋 Structured Form'], ['nlp', '💬 Plain English']] as const).map(([m, label]) => (
          <button key={m} onClick={() => setMode(m)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium ${mode === m ? 'bg-[#14532d] text-white' : 'text-slate-500 hover:text-slate-700'}`}>{label}</button>
        ))}
      </div>

      {mode === 'form' ? (<>
      {Object.entries(byCat).map(([cat, rs]) => (
        <Card key={cat} title={CAT_LABEL[cat] ?? pretty(cat)} className="mb-4">
          <div className="space-y-5">
            {rs.map((r) => {
              const cfg = sliderCfg(r.category)
              const v = values[r.rule_key] ?? cfg.min
              const st = stricterState(r.rule_key, v, r.agency_default)
              const yoursCls = st === 'stricter' ? 'bg-emerald-50 text-emerald-700' : st === 'looser' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-600'
              return (
                <div key={r.rule_key}>
                  <div className="text-sm font-semibold text-slate-800">{r.label}</div>
                  <div className="mb-1 text-[11px] text-slate-400">{r.citation}</div>
                  <input type="range" min={cfg.min} max={cfg.max} step={cfg.step} value={v}
                    onChange={(e) => setValues((p) => ({ ...p, [r.rule_key]: parseFloat(e.target.value) }))}
                    className="w-full accent-[#14532d]" />
                  <div className="mt-1 flex gap-2 text-[11px]">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-500" title={r.agency_name}>
                      Agency: {r.agency_default != null ? `${r.agency_default}${cfg.unit}` : 'n/a'}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 font-semibold ${yoursCls}`}>Yours: {v}{cfg.unit}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      ))}

      <Card title="Routing Rules (view only — managed in Settings)" className="mb-4">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12px]">
            <thead><tr className="border-b border-slate-100 text-[9px] uppercase tracking-wide text-slate-400">
              <th className="px-2 py-2">Rule Name</th><th className="px-2 py-2">Condition</th><th className="px-2 py-2">Assignee</th><th className="px-2 py-2">Active</th>
            </tr></thead>
            <tbody>
              {assigns.length === 0 && <tr><td colSpan={4} className="px-2 py-4 text-center text-slate-400">No routing rules.</td></tr>}
              {assigns.map((a) => {
                const cond = [a.min_loan_amount != null && `loan ≥ $${Math.round(a.min_loan_amount / 1000)}k`,
                  a.max_loan_amount != null && `loan ≤ $${Math.round(a.max_loan_amount / 1000)}k`,
                  a.min_fraud_score != null && `fraud ≥ ${a.min_fraud_score}`,
                  a.min_ltv != null && `ltv ≥ ${a.min_ltv}`, a.loan_type && `type=${a.loan_type}`].filter(Boolean).join(', ') || '—'
                return (
                  <tr key={a.rule_id} className="border-b border-slate-50">
                    <td className="px-2 py-2 font-medium text-slate-800">{a.rule_name}</td>
                    <td className="px-2 py-2 text-slate-600">{cond}</td>
                    <td className="px-2 py-2"><span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{pretty(a.assign_to_role)}</span></td>
                    <td className="px-2 py-2">{a.is_active ? '✓' : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {err && <div className="mb-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
      {savedSummary && (
        <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm font-semibold text-emerald-800">&#10003; {savedSummary.count} credit policy rules saved</div>
            <button onClick={() => setSavedSummary(null)} className="text-xs text-emerald-600 hover:text-emerald-800 underline">Edit rules</button>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {savedSummary.rules.map((r, i) => (
              <div key={i} className="rounded-lg bg-white border border-emerald-100 px-3 py-2">
                <div className="text-[10px] text-slate-400 uppercase tracking-wide">{r.label}</div>
                <div className="text-sm font-bold text-slate-800">{r.value}{r.unit}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="fixed bottom-0 left-0 right-0 border-t border-slate-200 bg-white px-6 py-3 shadow-[0_-2px_8px_rgba(0,0,0,0.05)]">
        <div className="mx-auto flex max-w-5xl justify-end">
          <button onClick={save} disabled={saving} className="rounded-lg bg-[#14532d] px-5 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">{saving ? 'Saving…' : 'Save Credit Policy'}</button>
        </div>
      </div>
      </>) : (<>
        {!extracted ? (
          <Card>
            <div className="mb-2 text-sm font-semibold text-slate-700">Describe your credit policy in plain English. I'll extract the rules automatically.</div>
            <textarea value={policyText} onChange={(e) => setPolicyText(e.target.value)} rows={7}
              placeholder={"We don't lend below 640 FICO.\nOur DTI cap is 45% back-end.\nWe require 3 months reserves.\nFraud scores above 0.70 go to senior review.\nMaximum LTV on purchases is 95%."}
              className="w-full rounded-md border border-slate-200 p-3 text-sm focus:border-[#14532d] focus:outline-none" />
            {err && <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
            <button onClick={extract} disabled={!policyText.trim() || extracting}
              className="mt-4 rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">
              {extracting ? 'Asking Claude…' : 'Extract Rules'}</button>
          </Card>
        ) : (
          <Card>
            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm text-slate-700">Extracted <span className="font-semibold">{extracted.length}</span> rule{extracted.length === 1 ? '' : 's'}</div>
              <span className="text-[11px] text-slate-400">{extMethod === 'claude' ? `🤖 Claude ${extModel}` : '🔧 Regex extraction'}</span>
            </div>
            {extracted.length === 0 ? (
              <div className="py-6 text-center text-sm text-slate-400">No rules found in that text. Try again with explicit thresholds.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[12px]">
                  <thead><tr className="border-b border-slate-100 text-[9px] uppercase tracking-wide text-slate-400">
                    <th className="px-2 py-2">Rule</th><th className="px-2 py-2">Value</th><th className="px-2 py-2">Conf</th><th className="px-2 py-2">Stricter?</th><th className="px-2 py-2">Apply</th>
                  </tr></thead>
                  <tbody>
                    {extracted.map((e, i) => (
                      <tr key={e.rule_key} className={`border-b border-slate-50 ${e.apply ? '' : 'opacity-50'}`}>
                        <td className="px-2 py-2 font-medium text-slate-800">{e.label}<div className="text-[10px] text-slate-400" title={e.reasoning}>{e.reasoning.slice(0, 40)}</div></td>
                        <td className="px-2 py-2 font-semibold text-slate-700">{e.extracted_value}{e.unit}</td>
                        <td className="px-2 py-2">{Math.round(e.confidence * 100)}%</td>
                        <td className="px-2 py-2">{e.is_stricter ? <span className="text-emerald-700">✓ Yes</span> : <span className="text-amber-600">Looser</span>}</td>
                        <td className="px-2 py-2"><input type="checkbox" checked={e.apply}
                          onChange={(ev) => setExtracted((rs) => rs!.map((r, k) => k === i ? { ...r, apply: ev.target.checked } : r))} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {err && <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
            <div className="mt-4 flex justify-between">
              <button onClick={() => { setExtracted(null); setPolicyText('') }} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">← Try again</button>
              <button onClick={applyExtracted} disabled={saving || extracted.filter((e) => e.apply).length === 0}
                className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">
                {saving ? 'Saving…' : `Apply Selected Rules (${extracted.filter((e) => e.apply).length})`}</button>
            </div>
          </Card>
        )}
      </>)}
      {toast && <div className="fixed bottom-16 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">{toast}</div>}
    </div>
  )
}

// ── Products (Section 4) — add/edit loan products ──
const LOAN_TYPES = ['Conventional', 'FHA', 'VA', 'Jumbo', 'NonQM']
const LOAN_PURPOSES = ['purchase', 'refinance', 'cash_out_refinance']
const money = (v: number | null) => v == null ? '—' : `$${Math.round(v / 1000)}k`

function Products({ tenantId, tenantName, onBack }: { tenantId: string; tenantName: string; onBack: () => void }) {
  const [products, setProducts] = useState<PlatformProduct[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState<PlatformProduct | 'new' | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try { const d = await fetchPlatformProducts(tenantId); setProducts(d.products); setErr(null) }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [tenantId])   // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="p-12 text-center text-slate-400">Loading products…</div>
  if (err && !products) return <Card><div className="py-8 text-center text-sm text-red-600">{err}</div></Card>
  if (!products) return null

  return (
    <div>
      <button onClick={onBack} className="mb-3 text-sm text-slate-500 hover:text-slate-800">← Back to tenants</button>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Products — {tenantName}</h1>
          <p className="text-sm text-slate-500">Add or edit loan products. Changes take effect immediately — no deploy.</p>
        </div>
        <button onClick={() => setEditing('new')} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22]">+ Add Product</button>
      </div>
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12px]">
            <thead><tr className="border-b border-slate-100 text-[9px] uppercase tracking-wide text-slate-400">
              <th className="px-2 py-2">Product Name</th><th className="px-2 py-2">Type</th><th className="px-2 py-2">Purpose</th>
              <th className="px-2 py-2">Max Loan</th><th className="px-2 py-2">Max DTI</th><th className="px-2 py-2">Max LTV</th>
              <th className="px-2 py-2">Min FICO</th><th className="px-2 py-2">Active</th><th className="px-2 py-2"></th>
            </tr></thead>
            <tbody>
              {products.length === 0 && <tr><td colSpan={9} className="px-2 py-6 text-center text-slate-400">No products yet.</td></tr>}
              {products.map((p) => (
                <tr key={p.product_id} className={`border-b border-slate-50 ${p.is_active ? '' : 'opacity-50'}`}>
                  <td className="px-2 py-2 font-medium text-slate-800">{p.product_name}</td>
                  <td className="px-2 py-2">{p.loan_type}</td>
                  <td className="px-2 py-2 text-slate-500">{pretty(p.loan_purpose)}</td>
                  <td className="px-2 py-2">{money(p.max_loan_amount)}</td>
                  <td className="px-2 py-2">{p.max_dti != null ? `${p.max_dti}%` : '—'}</td>
                  <td className="px-2 py-2">{p.max_ltv != null ? `${p.max_ltv}%` : '—'}</td>
                  <td className="px-2 py-2">{p.min_credit_score ?? '—'}</td>
                  <td className="px-2 py-2">{p.is_active ? <span className="text-emerald-700">✓</span> : <span className="text-slate-400">—</span>}</td>
                  <td className="px-2 py-2"><button onClick={() => setEditing(p)} className="rounded border border-slate-200 px-2 py-1 text-[10px] font-medium text-slate-600 hover:bg-slate-50">Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {editing && <ProductModal tenantId={tenantId} product={editing}
        onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); setToast('Product saved'); window.setTimeout(() => setToast(null), 2400); load() }} />}
      {toast && <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">{toast}</div>}
    </div>
  )
}

function ProductModal({ tenantId, product, onClose, onSaved }: {
  tenantId: string; product: PlatformProduct | 'new'; onClose: () => void; onSaved: () => void
}) {
  const isNew = product === 'new'
  const [form, setForm] = useState<PlatformProductInput>(isNew
    ? { product_name: '', loan_type: 'Conventional', loan_purpose: 'purchase', max_loan_amount: null, min_credit_score: null, max_dti: null, max_ltv: null, is_active: true }
    : { product_name: product.product_name, loan_type: product.loan_type, loan_purpose: product.loan_purpose ?? 'purchase',
        max_loan_amount: product.max_loan_amount, min_credit_score: product.min_credit_score, max_dti: product.max_dti, max_ltv: product.max_ltv, is_active: product.is_active })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = (patch: Partial<PlatformProductInput>) => setForm((f) => ({ ...f, ...patch }))
  const num = (v: string): number | null => v === '' ? null : parseFloat(v)
  const valid = form.product_name.trim() !== '' && form.loan_type !== ''

  async function submit() {
    if (!valid || saving) return
    setSaving(true); setError(null)
    try {
      if (isNew) await createPlatformProduct(tenantId, form)
      else await updatePlatformProduct(tenantId, product.product_id, form)
      onSaved()
    } catch (e) { setError(e instanceof Error ? e.message.replace(/^\d+\s+\w+\s+—\s+/, '') : String(e)) }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-bold text-slate-900">{isNew ? 'Add Product' : 'Edit Product'}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>
        <div className="space-y-3">
          <Field label="Product name *"><input value={form.product_name} onChange={(e) => set({ product_name: e.target.value })} placeholder="CL-CONV-30" className={inputCls} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Loan type *">
              <select value={form.loan_type} onChange={(e) => set({ loan_type: e.target.value })} className={inputCls}>
                {LOAN_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="Loan purpose">
              <select value={form.loan_purpose ?? 'purchase'} onChange={(e) => set({ loan_purpose: e.target.value })} className={inputCls}>
                {LOAN_PURPOSES.map((p) => <option key={p} value={p}>{pretty(p)}</option>)}
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Max loan amount ($)"><input type="number" value={form.max_loan_amount ?? ''} onChange={(e) => set({ max_loan_amount: num(e.target.value) })} step={1000} min={0} className={inputCls} /></Field>
            <Field label="Min credit score"><input type="number" value={form.min_credit_score ?? ''} onChange={(e) => set({ min_credit_score: num(e.target.value) })} min={500} max={800} step={5} className={inputCls} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Max DTI (%)"><input type="number" value={form.max_dti ?? ''} onChange={(e) => set({ max_dti: num(e.target.value) })} min={0} max={57} step={0.5} className={inputCls} /></Field>
            <Field label="Max LTV (%)"><input type="number" value={form.max_ltv ?? ''} onChange={(e) => set({ max_ltv: num(e.target.value) })} min={0} max={100} step={0.5} className={inputCls} /></Field>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={form.is_active} onChange={(e) => set({ is_active: e.target.checked })} /> Active
          </label>
          {error && <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">Cancel</button>
          <button onClick={submit} disabled={!valid || saving} className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </div>
  )
}

// ── small components ──
const inputCls = 'w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-[#14532d] focus:outline-none'

function Card({ title, className = '', children }: { title?: string; className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-lg border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
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

// ── Onboarding Confirmation (Section 5 / P19) ────────────────────────────────

type SectionStatus = { complete: boolean; detail: string }
type OnboardingSummary = {
  tenant_id: string
  is_active: boolean
  ready_for_go_live: boolean
  sections: {
    tenant_setup: SectionStatus
    field_mapper: SectionStatus
    policy_rules: SectionStatus
    product_config: SectionStatus
  }
}
type ImportResult = {
  mapped_count: number
  unmatched_count: number
  mapped: Record<string, { value: unknown; source_field: string; transform_rule: string }>
  unmatched: string[]
}

const BASE = import.meta.env.VITE_API_URL ?? ""

function OnboardingConfirmation({ tenantId, tenantName, onBack, onEditMapping, onEditPolicy, onEditProducts }: { tenantId: string; tenantName: string; onBack: () => void; onEditMapping?: () => void; onEditPolicy?: () => void; onEditProducts?: () => void }) {
  const [summary, setSummary] = useState<OnboardingSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [goingLive, setGoingLive] = useState(false)
  const [liveMsg, setLiveMsg] = useState<string | null>(null)
  const [savedMaps, setSavedMaps] = useState<SavedMapping[]>([])
  const [savedRules, setSavedRules] = useState<PolicyRule[]>([])
  const [savedProducts, setSavedProducts] = useState<PlatformProduct[]>([])
  const [expandSection, setExpandSection] = useState<string | null>(null)
  const [importJson, setImportJson] = useState('{\n  "loan_amt": 425000,\n  "fico_score": 720,\n  "dti_ratio": 38.5,\n  "ltv_ratio": 85.0\n}')
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importErr, setImportErr] = useState<string | null>(null)
  const [importLoading, setImportLoading] = useState(false)
  const [showImport, setShowImport] = useState(false)

  const tok = () => localStorage.getItem('accord_token') ?? ''

  useEffect(() => {
    fetch(`${BASE}/api/accord/platform-studio/tenants/${tenantId}/onboarding-summary`, {
      headers: { Authorization: `Bearer ${tok()}` },
    })
      .then((r) => r.json())
      .then((d) => setSummary(d))
      .catch(() => {})
      .finally(() => setLoading(false))
    fetchSavedMappings(tenantId).then((d) => {
      setSavedMaps(d.mappings)
      // Auto-build dry-run payload from tenant's actual source fields
      if (d.mappings.length > 0) {
        const SAMPLE_VALUES: Record<string, unknown> = {
          loan_amount: 425000, loan_amt: 425000, amount: 425000,
          fico_score: 720, credit_score: 720, mid_score: 720, score: 720,
          back_end_dti: 38.5, dti: 38.5, dti_ratio: 38.5, dti_back: 38.5,
          front_end_dti: 24.0, dti_front: 24.0,
          ltv: 85.0, ltv_ratio: 85.0, loan_to_value: 85.0,
          first_name: 'John', last_name: 'Smith',
          annual_income: 95000, base_salary: 95000, income: 95000,
          monthly_income: 7917, qualifying_income: 7917,
          purchase_price: 500000, appraised_value: 510000,
          loan_type: 'Conventional', loan_purpose: 'purchase',
          property_state: 'CA', property_zip: '90210', property_type: 'SFR',
          occupancy_type: 'primary_residence', occupancy: 'primary_residence',
          employer_name: 'Acme Corp', years_employed: 5,
          aus_recommendation: 'APPROVE/ELIGIBLE',
          interest_rate: 6.875, amortization_type: 'fixed',
        }
        const payload: Record<string, unknown> = {}
        d.mappings.slice(0, 15).forEach((m) => {
          const sf = m.source_field
          payload[sf] = SAMPLE_VALUES[sf] ?? SAMPLE_VALUES[sf.toLowerCase()] ?? `sample_${sf}`
        })
        setImportJson(JSON.stringify(payload, null, 2))
      }
    }).catch(() => {})
    fetchPolicyRules(tenantId).then((d) => setSavedRules(d.rules.filter(r => r.overlay_value !== null))).catch(() => {})
    fetchPlatformProducts(tenantId).then((d) => setSavedProducts(d.products)).catch(() => {})
  }, [tenantId])

  async function handleGoLive() {
    if (!summary?.ready_for_go_live) return
    setGoingLive(true)
    try {
      const r = await fetch(`${BASE}/api/accord/platform-studio/tenants/${tenantId}/go-live`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok()}` },
      })
      const d = await r.json()
      setLiveMsg(d.status === 'live' ? '🎉 Tenant is now live!' : JSON.stringify(d))
      setSummary((prev) => prev ? { ...prev, is_active: true } : prev)
    } catch (e) {
      setLiveMsg('Error going live')
    } finally {
      setGoingLive(false)
    }
  }

  async function handleImportTest() {
    setImportLoading(true)
    setImportErr(null)
    setImportResult(null)
    try {
      const raw = JSON.parse(importJson)
      const r = await fetch(`${BASE}/api/accord/platform-studio/tenants/${tenantId}/import-test`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw }),
      })
      const d = await r.json()
      setImportResult(d)
    } catch (e) {
      setImportErr(e instanceof Error ? e.message : 'Parse or network error')
    } finally {
      setImportLoading(false)
    }
  }

  const SECTION_LABELS: Record<string, string> = {
    tenant_setup: '1 · Tenant Setup',
    field_mapper: '2 · Map Your Fields',
    policy_rules: '3 · Credit Policy',
    product_config: '4 · Product Config',
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-xs text-slate-400 hover:text-slate-700">← Back</button>
        <div>
          <h2 className="text-xl font-bold text-slate-900">{tenantName} — Onboarding Review</h2>
          <p className="text-xs text-slate-400">{tenantId}</p>
        </div>
      </div>

      {loading ? (
        <div className="py-12 text-center text-sm text-slate-400">Loading summary…</div>
      ) : summary ? (
        <>
          <div className="space-y-3">
            {Object.entries(summary.sections).map(([key, sec]) => (
              <div key={key} className={`rounded-xl border ${sec.complete ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'}`}>
                <button
                  onClick={() => setExpandSection(expandSection === key ? null : key)}
                  className="flex w-full items-center justify-between px-4 py-3"
                >
                  <div className="flex items-center gap-2">
                    <span className={`text-lg ${sec.complete ? 'text-emerald-600' : 'text-amber-500'}`}>{sec.complete ? '✓' : '○'}</span>
                    <span className="text-sm font-semibold text-slate-800">{SECTION_LABELS[key]}</span>
                    <span className="text-xs text-slate-400">{sec.detail}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {key === 'field_mapper' && onEditMapping && <button onClick={(e) => { e.stopPropagation(); onEditMapping() }} className="text-xs text-emerald-700 hover:underline">Edit →</button>}
                    {key === 'policy_rules' && onEditPolicy && <button onClick={(e) => { e.stopPropagation(); onEditPolicy() }} className="text-xs text-emerald-700 hover:underline">Edit →</button>}
                    {key === 'product_config' && onEditProducts && <button onClick={(e) => { e.stopPropagation(); onEditProducts() }} className="text-xs text-emerald-700 hover:underline">Edit →</button>}
                    <span className="text-slate-400 text-xs">{expandSection === key ? '▲' : '▼'}</span>
                  </div>
                </button>
                {expandSection === key && (
                  <div className="border-t border-emerald-100 px-4 py-3">
                    {key === 'field_mapper' && savedMaps.length > 0 && (
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead><tr className="text-[10px] uppercase text-emerald-600 border-b border-emerald-200">
                            <th className="py-1 pr-3 text-left">Source Field</th>
                            <th className="py-1 pr-3 text-left">Canonical</th>
                            <th className="py-1 text-left">System</th>
                          </tr></thead>
                          <tbody>{savedMaps.slice(0,10).map((m,i) => (
                            <tr key={i} className="border-b border-emerald-50">
                              <td className="py-1 pr-3 font-mono text-slate-600">{m.source_field}</td>
                              <td className="py-1 pr-3 text-emerald-700 font-medium">{m.canonical_entity}.{m.canonical_column}</td>
                              <td className="py-1 text-slate-400">{m.source_system}</td>
                            </tr>
                          ))}</tbody>
                        </table>
                        {savedMaps.length > 10 && <p className="mt-1 text-xs text-slate-400">+{savedMaps.length - 10} more mappings</p>}
                      </div>
                    )}
                    {key === 'policy_rules' && savedRules.length > 0 && (
                      <div className="grid grid-cols-2 gap-2">
                        {savedRules.map((r,i) => (
                          <div key={i} className="rounded-lg bg-white border border-emerald-100 px-3 py-2">
                            <div className="text-[10px] text-slate-400">{r.label}</div>
                            <div className="text-sm font-bold text-slate-800">{r.overlay_value}{r.category === 'credit' ? '' : r.category === 'fraud' || r.category === 'income' ? '' : '%'}</div>
                          </div>
                        ))}
                      </div>
                    )}
                    {key === 'product_config' && savedProducts.length > 0 && (
                      <table className="w-full text-xs">
                        <thead><tr className="text-[10px] uppercase text-emerald-600 border-b border-emerald-200">
                          <th className="py-1 pr-3 text-left">Product</th>
                          <th className="py-1 pr-3 text-left">Type</th>
                          <th className="py-1 pr-3 text-left">Max LTV</th>
                          <th className="py-1 text-left">Min FICO</th>
                        </tr></thead>
                        <tbody>{savedProducts.map((p,i) => (
                          <tr key={i} className="border-b border-emerald-50">
                            <td className="py-1 pr-3 font-medium text-slate-700">{p.product_name}</td>
                            <td className="py-1 pr-3 text-slate-500">{p.loan_type}</td>
                            <td className="py-1 pr-3 text-slate-500">{p.max_ltv ? `${p.max_ltv}%` : '—'}</td>
                            <td className="py-1 text-slate-500">{p.min_credit_score ?? '—'}</td>
                          </tr>
                        ))}</tbody>
                      </table>
                    )}
                    {key === 'tenant_setup' && (
                      <p className="text-xs text-slate-500">Tenant configured with {sec.detail}. Use Edit Tenant to modify.</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-slate-800">Ready to go live?</div>
                <div className="text-xs text-slate-400 mt-0.5">
                  {summary.ready_for_go_live ? 'All sections complete — tenant can be activated.' : 'Complete all sections before activating.'}
                </div>
              </div>
              <button
                onClick={handleGoLive}
                disabled={!summary.ready_for_go_live || goingLive || summary.is_active}
                className="rounded-lg px-5 py-2 text-sm font-semibold text-white disabled:opacity-40 bg-indigo-600 hover:bg-indigo-700 disabled:cursor-not-allowed"
              >
                {summary.is_active ? 'Already Live ✓' : goingLive ? 'Activating…' : 'Go Live'}
              </button>
            </div>
            {liveMsg && <div className="mt-3 text-sm font-medium text-emerald-700">{liveMsg}</div>}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white">
            <button
              onClick={() => setShowImport((v) => !v)}
              className="flex w-full items-center justify-between px-5 py-3 text-sm font-semibold text-slate-700"
            >
              <span>Validate Field Mappings</span>
              <span className="text-slate-400">{showImport ? '▲' : '▼'}</span>
            </button>
            {showImport && (
              <div className="border-t border-slate-100 px-5 py-4 space-y-3">
                <p className="text-xs text-slate-400">Paste a sample LOS JSON row. Fields are matched against your field mappings — no data is written.</p>
                <textarea
                  className="w-full rounded-lg border border-slate-200 p-3 font-mono text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-300"
                  rows={6}
                  value={importJson}
                  onChange={(e) => setImportJson(e.target.value)}
                />
                <button
                  onClick={handleImportTest}
                  disabled={importLoading}
                  className="rounded-lg bg-slate-800 px-4 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-40"
                >
                  {importLoading ? 'Running…' : 'Run Dry-Run Import'}
                </button>
                {importErr && <div className="text-xs text-red-600">{importErr}</div>}
                {importResult && (
                  <div className="space-y-2">
                    <div className="flex gap-4 text-xs font-semibold">
                      <span className="text-emerald-700">✓ {importResult.mapped_count} mapped</span>
                      {importResult.unmatched_count > 0 && (
                        <span className="text-amber-600">⚠ {importResult.unmatched_count} unmatched</span>
                      )}
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-600 overflow-x-auto">
                      {Object.entries(importResult.mapped).map(([canon, v]) => (
                        <div key={canon}><span className="text-emerald-700">{canon}</span> ← <span className="text-slate-400">{v.source_field}</span> = <span className="text-slate-800">{String(v.value)}</span></div>
                      ))}
                      {importResult.unmatched.map((u) => (
                        <div key={u} className="text-amber-600">? {u} (no mapping)</div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="text-sm text-red-600">Failed to load onboarding summary.</div>
      )}
    </div>
  )
}

// ── Edit Tenant Modal ─────────────────────────────────────────────────────────
const PLANS = ['starter', 'growth', 'business', 'enterprise']
const LOS_TYPE_IDS = ['encompass', 'bytepro', 'openclose', 'custom']
const ALL_PROGRAMS = ['CONVENTIONAL', 'FHA', 'VA', 'JUMBO', 'NON_QM']
const ALL_CHANNELS = ['retail', 'wholesale', 'correspondent', 'consumer_direct']
const ALL_STATES = [
  'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
  'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
  'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
  'VA','WA','WV','WI','WY','DC',
]
const STATE_NAMES: Record<string, string> = {
  AL:'Alabama',AK:'Alaska',AZ:'Arizona',AR:'Arkansas',CA:'California',
  CO:'Colorado',CT:'Connecticut',DE:'Delaware',FL:'Florida',GA:'Georgia',
  HI:'Hawaii',ID:'Idaho',IL:'Illinois',IN:'Indiana',IA:'Iowa',KS:'Kansas',
  KY:'Kentucky',LA:'Louisiana',ME:'Maine',MD:'Maryland',MA:'Massachusetts',
  MI:'Michigan',MN:'Minnesota',MS:'Mississippi',MO:'Missouri',MT:'Montana',
  NE:'Nebraska',NV:'Nevada',NH:'New Hampshire',NJ:'New Jersey',NM:'New Mexico',
  NY:'New York',NC:'North Carolina',ND:'North Dakota',OH:'Ohio',OK:'Oklahoma',
  OR:'Oregon',PA:'Pennsylvania',RI:'Rhode Island',SC:'South Carolina',
  SD:'South Dakota',TN:'Tennessee',TX:'Texas',UT:'Utah',VT:'Vermont',
  VA:'Virginia',WA:'Washington',WV:'West Virginia',WI:'Wisconsin',WY:'Wyoming',DC:'D.C.',
}

function EditTenantModal({ detail, onClose, onSaved }: {
  detail: PlatformTenantDetail
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState({
    name: detail.name,
    plan: detail.plan,
    contact_email: detail.contact_email ?? '',
    los_type: detail.los_type ?? 'encompass',
    programs: [...detail.programs],
    licensed_states: [...detail.licensed_states],
    channels: [...detail.channels],
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [stateSearch, setStateSearch] = useState('')

  const set = (p: Partial<typeof form>) => setForm((f) => ({ ...f, ...p }))
  const toggle = (arr: string[], v: string) =>
    arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]

  const filteredStates = ALL_STATES.filter((s) => {
    const q = stateSearch.toLowerCase()
    return s.toLowerCase().includes(q) || (STATE_NAMES[s] ?? '').toLowerCase().includes(q)
  })

  async function save() {
    if (!form.name.trim()) { setErr('Lender name is required'); return }
    setSaving(true); setErr(null)
    try {
      await updatePlatformTenant(detail.tenant_id, {
        name: form.name.trim(),
        plan: form.plan,
        contact_email: form.contact_email,
        los_type: form.los_type,
        programs: form.programs,
        licensed_states: form.licensed_states,
        channels: form.channels,
      })
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-xl overflow-y-auto max-h-[90vh]">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h3 className="text-lg font-bold text-slate-900">Edit Tenant — {detail.tenant_id}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>
        <div className="px-6 py-5 space-y-4">
          {/* Name + Plan */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-semibold text-slate-600">Lender Name *</label>
              <input value={form.name} onChange={(e) => set({ name: e.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#14532d]/30" />
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-600">Plan</label>
              <select value={form.plan} onChange={(e) => set({ plan: e.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#14532d]/30">
                {PLANS.map((p) => <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
              </select>
            </div>
          </div>
          {/* Contact + LOS */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-semibold text-slate-600">Contact Email</label>
              <input value={form.contact_email} onChange={(e) => set({ contact_email: e.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#14532d]/30" />
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-600">LOS Type</label>
              <select value={form.los_type} onChange={(e) => set({ los_type: e.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#14532d]/30">
                {LOS_TYPE_IDS.map((l) => <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>)}
              </select>
            </div>
          </div>
          {/* Programs */}
          <div>
            <label className="text-xs font-semibold text-slate-600">Loan Programs</label>
            <div className="mt-2 flex flex-wrap gap-2">
              {ALL_PROGRAMS.map((p) => (
                <label key={p} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input type="checkbox" checked={form.programs.includes(p)}
                    onChange={() => set({ programs: toggle(form.programs, p) })} />
                  {p.replace('_', ' ')}
                </label>
              ))}
            </div>
          </div>
          {/* Channels */}
          <div>
            <label className="text-xs font-semibold text-slate-600">Channels</label>
            <div className="mt-2 flex flex-wrap gap-2">
              {ALL_CHANNELS.map((c) => (
                <label key={c} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input type="checkbox" checked={form.channels.includes(c)}
                    onChange={() => set({ channels: toggle(form.channels, c) })} />
                  {c.replace('_', ' ')}
                </label>
              ))}
            </div>
          </div>
          {/* States */}
          <div>
            <label className="text-xs font-semibold text-slate-600">Licensed States ({form.licensed_states.length})</label>
            <input value={stateSearch} onChange={(e) => setStateSearch(e.target.value)}
              placeholder="Search by state name or abbreviation…"
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#14532d]/30" />
            <div className="mt-2 grid grid-cols-6 gap-1 max-h-40 overflow-y-auto">
              {filteredStates.map((s) => (
                <label key={s} className="flex items-center gap-1 text-xs cursor-pointer">
                  <input type="checkbox" checked={form.licensed_states.includes(s)}
                    onChange={() => set({ licensed_states: toggle(form.licensed_states, s) })} />
                  <span title={STATE_NAMES[s]}>{s}</span>
                </label>
              ))}
            </div>
          </div>
          {err && <div className="text-sm text-red-600">{err}</div>}
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">Cancel</button>
          <button onClick={save} disabled={saving}
            className="rounded-lg bg-[#14532d] px-5 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-40">
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
