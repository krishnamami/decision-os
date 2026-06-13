import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { changeUserRole, deactivateUser, fetchTeammates, inviteUser, type TeammateLite } from '../api/client'
import { relativeTime } from '../components/NotesSection'
import RulesSettings from './RulesSettings'

const ROLES = ['admin', 'manager', 'processor', 'underwriter', 'senior_uw', 'closer', 'compliance', 'viewer']
const prettyRole = (r: string) => r.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      {subtitle && <p className="mb-3 text-sm text-slate-500">{subtitle}</p>}
      <div className={subtitle ? '' : 'mt-3'}>{children}</div>
    </section>
  )
}

export default function Settings() {
  const { user, tenant, impersonate } = useAuth()
  const navigate = useNavigate()
  const [users, setUsers] = useState<TeammateLite[]>([])
  const [toast, setToast] = useState<string | null>(null)
  const [inv, setInv] = useState({ email: '', name: '', role: 'processor' })
  const [target, setTarget] = useState('')
  const [tab, setTab] = useState<'general' | 'rules'>('general')

  const load = () => fetchTeammates().then((d) => setUsers(d.users)).catch(() => undefined)
  useEffect(() => {
    load()
  }, [])

  const fire = (m: string) => {
    setToast(m)
    setTimeout(() => setToast(null), 2500)
  }

  if (user && user.role !== 'admin') {
    return <div className="p-12 text-center text-slate-400">Settings is available to admins only.</div>
  }

  async function invite() {
    if (!inv.email.trim() || !inv.name.trim()) return
    try {
      await inviteUser(inv.email.trim(), inv.name.trim(), inv.role)
      setInv({ email: '', name: '', role: 'processor' })
      fire(`Invited ${inv.email} (password: accord2026)`)
      load()
    } catch {
      fire('Could not invite — email may already exist')
    }
  }
  async function setRole(uid: string, role: string) {
    await changeUserRole(uid, role)
    fire('Role updated')
    load()
  }
  async function deactivate(uid: string, name: string) {
    await deactivateUser(uid)
    fire(`${name} deactivated`)
    load()
  }
  function doImpersonate() {
    const u = users.find((x) => x.user_id === target)
    if (!u) return
    impersonate({ user_id: u.user_id, name: u.name, role: u.role })
    navigate('/pipeline')
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-6 py-6">
      <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <div className="flex gap-6">
          {([['general', 'General'], ['rules', 'Decision Rules']] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={`-mb-px border-b-2 py-2.5 text-sm font-medium transition ${tab === k ? 'border-brand text-brand' : 'border-transparent text-slate-500 hover:text-slate-800'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'rules' && <RulesSettings />}

      {tab === 'general' && <>
      {/* A. Company info */}
      <Section title="Company info">
        <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          <div><dt className="text-slate-500">Tenant name</dt><dd className="font-medium text-slate-900">{tenant?.name}</dd></div>
          <div><dt className="text-slate-500">Plan</dt><dd className="font-medium capitalize text-slate-900">{tenant?.plan}</dd></div>
          <div className="sm:col-span-2">
            <dt className="text-slate-500">Products</dt>
            <dd className="mt-1 flex flex-wrap gap-2">
              {['pipeline', 'analytics', 'simulation', 'audit'].map((p) => {
                const on = tenant?.products?.includes(p)
                return (
                  <span key={p} className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${on ? 'bg-green-100 text-green-800' : 'bg-slate-100 text-slate-400'}`}>
                    {on ? '✅' : '—'} {p}
                  </span>
                )
              })}
            </dd>
          </div>
        </dl>
      </Section>

      {/* A2. Import loans */}
      <Section title="Import loans" subtitle="Bring your pipeline into Accord from any LOS export (Encompass, ICE, or a generic CSV).">
        <button onClick={() => navigate('/settings/import')} className="rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white hover:bg-brand-dark">📥 Import loans from CSV</button>
      </Section>

      {/* B. User management */}
      <Section title="User management" subtitle={`${users.filter((u) => u.is_active !== false).length} active users in ${tenant?.name}`}>
        <div className="mb-3 flex flex-wrap items-end gap-2 rounded-lg bg-slate-50 p-3">
          <div className="flex-1">
            <label className="mb-0.5 block text-xs text-slate-500">Email</label>
            <input value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} placeholder="name@summit.com" className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm outline-none focus:border-brand" />
          </div>
          <div className="flex-1">
            <label className="mb-0.5 block text-xs text-slate-500">Name</label>
            <input value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} placeholder="Full name" className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="mb-0.5 block text-xs text-slate-500">Role</label>
            <select value={inv.role} onChange={(e) => setInv({ ...inv, role: e.target.value })} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm outline-none focus:border-brand">
              {ROLES.map((r) => <option key={r} value={r}>{prettyRole(r)}</option>)}
            </select>
          </div>
          <button onClick={invite} className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark">Invite user</button>
        </div>

        <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left">Name</th>
                <th className="px-3 py-2 text-left">Email</th>
                <th className="px-3 py-2 text-left">Role</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Last login</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((u) => (
                <tr key={u.user_id} className={u.is_active === false ? 'opacity-50' : ''}>
                  <td className="px-3 py-2 font-medium text-slate-800">{u.name}</td>
                  <td className="px-3 py-2 text-slate-500">{u.email}</td>
                  <td className="px-3 py-2">
                    <select
                      value={u.role}
                      onChange={(e) => setRole(u.user_id, e.target.value)}
                      disabled={u.user_id === user?.user_id}
                      className="rounded-md border border-slate-200 px-1.5 py-0.5 text-xs capitalize outline-none focus:border-brand disabled:opacity-60"
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{prettyRole(r)}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${u.is_active === false ? 'bg-slate-100 text-slate-500' : 'bg-green-100 text-green-800'}`}>
                      {u.is_active === false ? 'Inactive' : 'Active'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-500">{u.last_login ? relativeTime(u.last_login) : 'Never'}</td>
                  <td className="px-3 py-2 text-right">
                    {u.user_id !== user?.user_id && u.is_active !== false && (
                      <button onClick={() => deactivate(u.user_id, u.name)} className="text-xs font-medium text-red-600 hover:underline">Deactivate</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* D. Impersonate */}
      <Section title="Impersonate user" subtitle="View Accord exactly as another team member sees it — their queue, their role. Useful for support + debugging.">
        <div className="flex flex-wrap items-center gap-2">
          <select value={target} onChange={(e) => setTarget(e.target.value)} className="min-w-56 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand">
            <option value="">— Select a team member —</option>
            {users.filter((u) => u.user_id !== user?.user_id && u.is_active !== false).map((u) => (
              <option key={u.user_id} value={u.user_id}>{u.name} ({prettyRole(u.role)})</option>
            ))}
          </select>
          <button onClick={doImpersonate} disabled={!target} className="rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40">Impersonate</button>
        </div>
      </Section>
      </>}

      {toast && (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
    </div>
  )
}
