import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchExaminerReport, fetchDocuments, type ExaminerReportData, type DocItem } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { resolveRule } from '../config/ruleLabels'
import { SOURCE_BY_TYPE, extractedValueText } from '../components/evidenceDoc'
import { deriveOFACStatus } from '../components/OFACBadge'
import type { DecisionDetail } from '../types/accord'

const LAYER_NAME: Record<string, string> = { federal: 'Federal', agency: 'Agency', lender: 'Your Policy', system: 'System' }
const OFAC_LABEL: Record<string, string> = { clear: 'Clear', match: 'MATCH — review required', review: 'Review', pending: 'Pending' }
const money = (v: number | null | undefined) => (v == null ? '—' : `$${Number(v).toLocaleString()}`)
const pct = (v: number | null | undefined) => (v == null ? '—' : `${Number(v).toFixed(1)}%`)
const fmtTs = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '—')
const titleCase = (s: string) => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
const sigVal = (d: DecisionDetail | undefined, re: RegExp) => d?.signals?.find((s) => re.test(s.key))?.value

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 break-inside-avoid">
      <h2 className="mb-2 border-b border-slate-300 pb-1 text-sm font-bold uppercase tracking-wide text-slate-700">{n}. {title}</h2>
      {children}
    </section>
  )
}
function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-2 py-0.5 text-sm">
      <span className="w-40 shrink-0 text-slate-500">{k}</span>
      <span className="font-medium text-slate-800">{v}</span>
    </div>
  )
}

export default function ExaminerReport() {
  const { id = '' } = useParams()
  const { tenant } = useAuth()
  const [rep, setRep] = useState<ExaminerReportData | null>(null)
  const [docs, setDocs] = useState<DocItem[]>([])
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetchExaminerReport(id)
      .then((r) => alive && setRep(r))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : 'Failed to load examiner report'))
    fetchDocuments(id).then((d) => alive && setDocs(d.documents)).catch(() => undefined)
    return () => { alive = false }
  }, [id])

  if (err) return <div className="p-10 text-center text-sm text-red-600">{err}</div>
  if (!rep) return <div className="p-10 text-center text-sm text-slate-400">Generating examiner report…</div>

  const loan = rep.loan
  const m = loan.metrics
  const decisions = [...(loan.decisions || [])].sort((a, b) => a.wave - b.wave || a.decision_id.localeCompare(b.decision_id))
  const ofacStatus = deriveOFACStatus(loan.decisions || [])
  const ofacDoc = docs.find((d) => d.document_type === 'OFAC_CHECK')
  const ofacChecked = ofacDoc?.extracted_data?.checked_at as string | undefined
  const comp = (loan.decisions || []).find((d) => d.decision_id === 'compliance_check')
  const hmda = sigVal(comp, /hmda/i)
  const fairLending = sigVal(comp, /fair.?lending violation/i) ?? sigVal(comp, /fair.?lending/i)
  const missingDisc = sigVal(comp, /missing disclosures/i)
  const anyBlock = (loan.decisions || []).some((d) => d.outcome === 'block')
  const activity = (loan as unknown as { activity?: Array<{ actor: string; action: string; at: string; detail?: { note?: string } }> }).activity || []

  return (
    <div className="mx-auto max-w-3xl bg-white px-8 py-8 text-slate-800">
      <style>{`@media print { .no-print { display: none !important } body { background: #fff } @page { margin: 18mm } }`}</style>

      <div className="no-print mb-5 flex items-center justify-between">
        <Link to={`/pipeline/${rep.application_id}`} className="text-sm font-medium text-brand hover:underline">← Back to loan</Link>
        <button onClick={() => window.print()} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark">🖨 Print / Save as PDF</button>
      </div>

      {/* Title block */}
      <div className="border-b-2 border-slate-800 pb-3">
        <h1 className="text-xl font-bold tracking-tight">ACCORD — LOAN EXAMINATION REPORT</h1>
        <p className="mt-1 text-xs text-slate-500">
          Generated {fmtTs(rep.generated_at)} by {rep.generated_by} · Application {rep.application_id} · Tenant {tenant?.name || rep.tenant_id}
        </p>
      </div>

      {/* 1. Borrower summary */}
      <Section n={1} title="Borrower summary">
        <Row k="Name" v={loan.borrower.name} />
        <Row k="Loan amount" v={money(m.loan_amount)} />
        <Row k="LTV" v={pct(m.ltv)} />
        <Row k="DTI" v={pct(m.dti)} />
        <Row k="Credit score" v={m.credit_score ?? '—'} />
        <Row k="Loan type" v={rep.loan_type ? titleCase(rep.loan_type) : '—'} />
        <Row k="QM status" v={loan.qm ? `${loan.qm.determination} (${loan.qm.citation})` : '—'} />
        <Row k="OFAC status" v={`${OFAC_LABEL[ofacStatus] || ofacStatus}${ofacChecked ? ` — SDN list checked ${fmtTs(ofacChecked)}` : ''}`} />
      </Section>

      {/* 2. Decision trail */}
      <Section n={2} title="Decision trail">
        {decisions.length === 0 && <p className="text-sm text-slate-400">No decisions recorded.</p>}
        {decisions.map((d) => {
          const info = resolveRule(d.rule || '')
          return (
            <div key={d.decision_id} className="mt-3 break-inside-avoid border-l-2 border-slate-200 pl-3">
              <div className="text-sm font-semibold text-slate-900">
                {d.persona_name} <span className="text-xs font-normal text-slate-400">({d.decision_id} · wave {d.wave})</span>
              </div>
              <Row k="Outcome" v={d.outcome.toUpperCase()} />
              <Row k="Rule" v={info.label} />
              <Row k="Layer" v={`${LAYER_NAME[info.layer] || info.layer}${info.citation ? ` (${info.citation})` : ''}`} />
              <Row k="Confidence" v={d.confidence != null ? `${Math.round(d.confidence * 100)}%` : '—'} />
              <Row k="Decided at" v={d.reviewed_at ? fmtTs(d.reviewed_at) : d.reviewed ? 'reviewed' : 'pending'} />
              {d.reviewer && <Row k="Reviewer" v={d.reviewer} />}
              {d.evidence?.length > 0 && <Row k="Evidence" v={d.evidence.map((e) => `${e.document} — ${e.detail}`).join('; ')} />}
            </div>
          )
        })}
      </Section>

      {/* 3. Evidence documents */}
      <Section n={3} title="Evidence documents">
        {docs.length === 0 && <p className="text-sm text-slate-400">No indexed documents.</p>}
        {docs.map((doc) => (
          <div key={doc.document_id} className="mt-3 break-inside-avoid border-l-2 border-slate-200 pl-3">
            <div className="text-sm font-semibold text-slate-900">
              {doc.display_name} <span className="text-xs font-normal text-slate-400">({titleCase(doc.document_category || doc.document_type)})</span>
            </div>
            <Row k="Extracted" v={extractedValueText(doc) || '—'} />
            <Row k="Confidence" v={doc.confidence != null ? `${Math.round(doc.confidence * 100)}%` : '—'} />
            <Row k="Source" v={SOURCE_BY_TYPE[doc.document_type] || 'Lender upload'} />
          </div>
        ))}
      </Section>

      {/* 4. Audit log */}
      <Section n={4} title="Audit log">
        {activity.length === 0 && <p className="text-sm text-slate-400">No audit-log entries.</p>}
        <ul>
          {activity.map((a, i) => (
            <li key={i} className="border-b border-slate-100 py-1 text-sm">
              <span className="font-mono text-xs text-slate-500">{fmtTs(a.at)}</span> · <span className="font-medium text-slate-800">{a.actor}</span> · {a.action}
              {a.detail?.note ? ` — "${a.detail.note}"` : ''}
            </li>
          ))}
        </ul>
      </Section>

      {/* 5. Compliance checks */}
      <Section n={5} title="Compliance checks">
        <Row k="HMDA fields" v={hmda ? (/yes/i.test(hmda) ? 'Complete' : 'Incomplete — review missing fields') : '—'} />
        <Row k="Fair lending" v={fairLending ? (/no/i.test(fairLending) ? 'No flags' : 'Flags — review') : '—'} />
        <Row k="Missing disclosures" v={missingDisc ? (/no/i.test(missingDisc) ? 'None' : 'Missing — review') : '—'} />
        <Row k="OFAC" v={`${OFAC_LABEL[ofacStatus] || ofacStatus}${ofacChecked ? ` — SDN / Consolidated checked ${fmtTs(ofacChecked)}` : ''}`} />
        <Row k="Adverse action" v={anyBlock ? 'Review required — a check is blocked / declined' : 'None pending'} />
      </Section>

      {/* 6. Rule versions applied */}
      <Section n={6} title="Rule versions applied">
        {(!rep.rule_versions_applied || rep.rule_versions_applied.length === 0) && (
          <p className="text-sm text-slate-400">No versioned rule set recorded for this loan's decisions.</p>
        )}
        {(rep.rule_versions_applied || []).map((rv) => (
          <div key={rv.version} className="mt-3 break-inside-avoid border-l-2 border-slate-200 pl-3">
            <div className="text-sm font-semibold text-slate-900">
              Rule v{rv.version} <span className="text-xs font-normal text-slate-400">({rv.decision_count} decision{rv.decision_count === 1 ? '' : 's'})</span>
            </div>
            <Row
              k="In force"
              v={`${rv.effective_from ? new Date(rv.effective_from).toLocaleDateString() : '—'} → ${rv.effective_to ? new Date(rv.effective_to).toLocaleDateString() : 'present'}`}
            />
            {rv.changes_summary && <Row k="Changes" v={rv.changes_summary} />}
          </div>
        ))}
      </Section>

      {/* 7. Rain check — pipeline protection */}
      {rep.rain_check && (
        <Section n={7} title="Rain check — pipeline protection">
          <Row k="Rate locked" v={rep.rain_check.rate_locked ? 'Yes' : 'No'} />
          <Row
            k="Evaluated under"
            v={rep.rain_check.pinned_version_number != null
              ? `Rule v${rep.rain_check.pinned_version_number}${rep.rain_check.pinned_at ? ` (pinned ${new Date(rep.rain_check.pinned_at).toLocaleDateString()})` : ''}`
              : 'Current active rules'}
          />
          <Row k="Current rule version" v={rep.rain_check.current_version_number != null ? `Rule v${rep.rain_check.current_version_number}` : '—'} />
          {rep.rain_check.application_date && <Row k="Application date" v={new Date(rep.rain_check.application_date).toLocaleDateString()} />}
          <Row k="Protected" v={rep.rain_check.protected ? 'Yes — pinned version differs from current' : 'No'} />
          <p className="mt-2 text-sm text-slate-600">{rep.rain_check.protection_reason}</p>
        </Section>
      )}

      {/* 8. Governing regulations */}
      {rep.governing_regulations && rep.governing_regulations.length > 0 && (
        <Section n={8} title="Governing regulations">
          {rep.governing_regulations.map((gr) => (
            <div key={gr.decision_id} className="mt-2 break-inside-avoid border-l-2 border-slate-200 pl-3 text-sm">
              <div className="font-semibold text-slate-900">{titleCase(gr.decision_id)} <span className="text-xs font-normal uppercase text-slate-400">{gr.outcome}</span></div>
              {gr.governed_by.map((g, i) => (
                <div key={i} className="text-slate-600">
                  {g.citation ? <span className="font-medium">{g.citation}</span> : g.rule_name}
                  {g.rule_name && g.citation ? ` — ${g.rule_name}` : ''}
                  {(g.source || g.type) ? ` (${(g.source || g.type)!.replace(/_/g, ' ')})` : ''}
                </div>
              ))}
            </div>
          ))}
        </Section>
      )}

      <p className="mt-8 border-t border-slate-200 pt-3 text-xs text-slate-400">
        Generated by Accord · CFPB ECOA/Reg B · HMDA · TILA · OCC / FDIC compliance examination procedures.
      </p>
    </div>
  )
}
