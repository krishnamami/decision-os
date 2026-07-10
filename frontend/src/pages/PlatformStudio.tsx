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
const PLAN_OPTIONS = ['starter', 'professional', 'enterprise']
const PRODUCT_OPTIONS = ['pipeline', 'analytics', 'simulation', 'audit', 'platform_studio']

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
        <CreateTenantModal
          onClose={() => setShowCreate(false)}
          onCreated={(id, adminCreated) => {
            setShowCreate(false)
            notify(adminCreated ? `Created ${id} + admin ${adminCreated}` : `Created tenant ${id}`)
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

// ── Create tenant modal (super_admin only) ──
function CreateTenantModal({ onClose, onCreated }: {
  onClose: () => void
  onCreated: (id: string, adminCreated: string | null) => void
}) {
  const [form, setForm] = useState<CreateTenantInput>({
    tenant_id: '', name: '', plan: 'starter', products: ['pipeline'],
    admin_email: '', admin_name: '', admin_password: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const slug = useMemo(
    () => form.tenant_id.toLowerCase().replace(/[^a-z0-9_]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40),
    [form.tenant_id],
  )
  const set = <K extends keyof CreateTenantInput>(k: K, v: CreateTenantInput[K]) => setForm((f) => ({ ...f, [k]: v }))
  const toggleProduct = (p: string) =>
    setForm((f) => ({ ...f, products: f.products.includes(p) ? f.products.filter((x) => x !== p) : [...f.products, p] }))

  // Validation: id + name required; if any admin field is filled, email+password required.
  const wantsAdmin = !!(form.admin_email || form.admin_password || form.admin_name)
  const valid = !!slug && !!form.name.trim() && (!wantsAdmin || (!!form.admin_email && (form.admin_password?.length ?? 0) >= 6))

  async function submit() {
    if (!valid || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const body: CreateTenantInput = {
        tenant_id: slug, name: form.name.trim(), plan: form.plan,
        products: form.products.length ? form.products : ['pipeline'],
      }
      if (wantsAdmin) {
        body.admin_email = form.admin_email?.trim()
        body.admin_name = form.admin_name?.trim() || undefined
        body.admin_password = form.admin_password
      }
      const res = await createPlatformTenant(body)
      onCreated(res.tenant_id, res.admin_created)
    } catch (e) {
      setError(e instanceof Error ? e.message.replace(/^\d+\s+\w+\s+—\s+/, '') : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-bold text-slate-900">Create Tenant</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>

        <div className="space-y-3">
          <Field label="Tenant ID *" hint={slug && slug !== form.tenant_id ? `saved as: ${slug}` : 'lowercase, letters/numbers/underscore'}>
            <input value={form.tenant_id} onChange={(e) => set('tenant_id', e.target.value)}
              placeholder="e.g. capital_loans" className={inputCls} />
          </Field>
          <Field label="Name *">
            <input value={form.name} onChange={(e) => set('name', e.target.value)}
              placeholder="e.g. Capital Loans" className={inputCls} />
          </Field>
          <Field label="Plan">
            <select value={form.plan} onChange={(e) => set('plan', e.target.value)} className={inputCls}>
              {PLAN_OPTIONS.map((p) => <option key={p} value={p}>{pretty(p)}</option>)}
            </select>
          </Field>
          <Field label="Products">
            <div className="flex flex-wrap gap-2">
              {PRODUCT_OPTIONS.map((p) => (
                <button key={p} type="button" onClick={() => toggleProduct(p)}
                  className={`rounded-md border px-2.5 py-1 text-xs font-medium transition ${
                    form.products.includes(p)
                      ? 'border-[#14532d] bg-[#14532d]/5 text-[#14532d]'
                      : 'border-slate-200 text-slate-500 hover:bg-slate-50'}`}>{pretty(p)}</button>
              ))}
            </div>
          </Field>

          <div className="mt-2 border-t border-slate-100 pt-3">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">First Admin (optional)</div>
            <div className="space-y-3">
              <Field label="Admin email">
                <input value={form.admin_email} onChange={(e) => set('admin_email', e.target.value)}
                  placeholder="admin@tenant.com" className={inputCls} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Admin name">
                  <input value={form.admin_name} onChange={(e) => set('admin_name', e.target.value)}
                    placeholder="Jane Admin" className={inputCls} />
                </Field>
                <Field label="Password" hint="min 6 chars">
                  <input type="password" value={form.admin_password} onChange={(e) => set('admin_password', e.target.value)}
                    placeholder="••••••" className={inputCls} />
                </Field>
              </div>
            </div>
          </div>

          {error && <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">Cancel</button>
          <button onClick={submit} disabled={!valid || submitting}
            className="rounded-lg bg-[#14532d] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0f3d22] disabled:opacity-50">
            {submitting ? 'Creating…' : 'Create Tenant'}
          </button>
        </div>
      </div>
    </div>
  )
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
