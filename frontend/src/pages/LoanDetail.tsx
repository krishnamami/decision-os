import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  fetchLoan, fetchDocuments, fetchLoanActions, fetchSimilarCases,
  type DocItem, type LoanAction, type SimilarCase,
} from '../api/client'
import type { LoanDetail as LoanDetailT } from '../types/accord'
import { EvidenceDocumentPanel } from '../components/EvidenceDocumentPanel'
import { panelPropsFromDoc } from '../components/evidenceDoc'
import PersonaAccordion from '../components/PersonaAccordion'
import Briefing from '../components/workbench/Briefing'
import DecisionSnapshot from '../components/workbench/DecisionSnapshot'
import AttentionItems from '../components/workbench/AttentionItems'
import ActionPanel from '../components/workbench/ActionPanel'
import EvidenceTab from '../components/workbench/EvidenceTab'
import NotesTab from '../components/workbench/NotesTab'
import AuditTab from '../components/workbench/AuditTab'
import AuditStrip from '../components/workbench/AuditStrip'
import AdvancedSection from '../components/workbench/AdvancedSection'

const TABS = [
  { key: 'checks', label: 'Checks' },
  { key: 'evidence', label: 'Evidence' },
  { key: 'notes', label: 'Notes' },
  { key: 'audit', label: 'Audit' },
] as const
type Tab = (typeof TABS)[number]['key']

export default function LoanDetail() {
  const { appId = '' } = useParams()
  const { effectiveUser } = useAuth()
  const role = effectiveUser?.role ?? 'viewer'

  const [loan, setLoan] = useState<LoanDetailT | null>(null)
  const [docs, setDocs] = useState<DocItem[]>([])
  const [actions, setActions] = useState<LoanAction[]>([])
  const [similar, setSimilar] = useState<SimilarCase[]>([])
  const [similarLoading, setSimilarLoading] = useState(true)
  const [ofac, setOfac] = useState<{ checkedAt?: string; listDate?: string }>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('checks')
  const [openDoc, setOpenDoc] = useState<DocItem | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true); setError(null); setSimilarLoading(true)
    fetchLoan(appId)
      .then((d) => alive && setLoan(d))
      .catch((e) => alive && setError(e instanceof Error ? e.message : 'Failed to load loan'))
      .finally(() => alive && setLoading(false))
    fetchDocuments(appId).then((d) => {
      if (!alive) return
      setDocs(d.documents)
      const o = d.documents.find((x) => x.document_type === 'OFAC_CHECK')
      if (o) setOfac({ checkedAt: o.extracted_data?.checked_at as string, listDate: o.extracted_data?.list_date as string })
    }).catch(() => undefined)
    fetchLoanActions(appId).then((d) => alive && setActions(d.actions)).catch(() => undefined)
    fetchSimilarCases(appId).then((d) => alive && setSimilar(d.cases)).catch(() => undefined).finally(() => alive && setSimilarLoading(false))
    return () => { alive = false }
  }, [appId])

  function onActionDone(a: LoanAction) {
    setActions((prev) => [a, ...prev])
    setToast('Recorded — added to the file.')
    setTimeout(() => setToast(null), 2500)
    fetchLoan(appId).then(setLoan).catch(() => undefined) // refresh examiner_readiness
  }

  if (loading) return <div className="p-12 text-center text-sm text-slate-400">Loading {appId}…</div>
  if (error) return <div className="p-12 text-center text-red-600">{error}</div>
  if (!loan) return null

  const canExaminer = ['compliance', 'admin', 'super_admin'].includes(role)
  const teamCount = new Set(actions.map((a) => a.performed_by)).size

  return (
    <div className="mx-auto max-w-7xl px-6 py-6 pb-20">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <Link to="/pipeline" className="text-sm font-medium text-brand hover:underline">← Back to queue</Link>
        {canExaminer && (
          <button
            onClick={() => window.open(`/loans/${loan.application_id}/examiner-report`, '_blank')}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            📋 Examiner report
          </button>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Left column — 2/3 */}
        <div className="space-y-5 lg:col-span-2">
          <Briefing loan={loan} ofac={ofac} docs={docs} onOpenDoc={setOpenDoc} />
          <DecisionSnapshot loan={loan} />
          <AttentionItems loan={loan} />

          <section className="rounded-xl border border-slate-200 bg-white">
            <div className="flex gap-1 border-b border-slate-200 px-3">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`-mb-px border-b-2 px-3 py-2.5 text-sm font-medium transition ${tab === t.key ? 'border-brand text-brand' : 'border-transparent text-slate-500 hover:text-slate-800'}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="p-5">
              {tab === 'checks' && <PersonaAccordion decisions={loan.decisions} applicationId={loan.application_id} actions={actions} />}
              {tab === 'evidence' && <EvidenceTab docs={docs} />}
              {tab === 'notes' && <NotesTab appId={loan.application_id} actions={actions} activity={(loan as unknown as { activity?: [] }).activity ?? []} onActionDone={onActionDone} />}
              {tab === 'audit' && <AuditTab loan={loan} docs={docs} actions={actions} />}
            </div>
          </section>

          <AdvancedSection loan={loan} />
        </div>

        {/* Right column — sticky action panel */}
        <div className="lg:col-span-1">
          <div className="lg:sticky lg:top-4">
            <ActionPanel loan={loan} role={role} similar={similar} similarLoading={similarLoading} onActionDone={onActionDone} />
          </div>
        </div>
      </div>

      <AuditStrip loan={loan} docsCount={docs.length} teamCount={teamCount} />

      {openDoc && <EvidenceDocumentPanel {...panelPropsFromDoc(openDoc)} showEdms={false} onClose={() => setOpenDoc(null)} />}
      {toast && (
        <div className="fixed bottom-16 left-1/2 z-40 -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
    </div>
  )
}
