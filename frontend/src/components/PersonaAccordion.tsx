import { useEffect, useState } from 'react'
import type { DecisionDetail, Evidence } from '../types/accord'
import { fetchDocuments, type DocItem } from '../api/client'
import { resolveRule } from '../config/ruleLabels'
import { RuleLayerBadge } from './RuleLayerBadge'
import DecisionPill, { outcomeMeta } from './DecisionPill'
import ExtractionDetail from './ExtractionDetail'

const SIGNAL_DOT: Record<string, string> = {
  pass: 'bg-green-500',
  fail: 'bg-red-500',
  warn: 'bg-amber-500',
  no_data: 'bg-slate-300',
  info: 'bg-slate-400',
}

// Match a free-text evidence name to an indexed document.
function matchDoc(name: string, docs: DocItem[]): DocItem | undefined {
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '')
  const n = norm(name)
  if (!n) return undefined
  return docs.find((d) => {
    const dn = norm(d.display_name)
    const dt = norm(d.document_type)
    return dn === n || dt === n || dn.includes(n) || n.includes(dn) || (!!dt && (dt.includes(n) || n.includes(dt)))
  })
}

// The 5 lifecycle stages, keyed by the `wave` each decision already carries.
const STAGES = [
  { wave: 1, label: 'VERIFY' },
  { wave: 2, label: 'UNDERWRITE' },
  { wave: 3, label: 'ELIGIBILITY' },
  { wave: 4, label: 'DECIDE' },
  { wave: 5, label: 'CLOSE' },
]

function overall(ds: DecisionDetail[]): { label: string; cls: string } {
  if (!ds.length) return { label: 'Pending', cls: 'bg-gray-100 text-gray-400' }
  if (ds.some((d) => d.outcome === 'block')) return { label: 'Blocked', cls: 'bg-red-100 text-red-800' }
  if (ds.some((d) => d.outcome === 'escalate' || d.outcome === 'recommend'))
    return { label: 'Review', cls: 'bg-amber-100 text-amber-800' }
  if (ds.every((d) => d.outcome === 'allow')) return { label: 'Passed', cls: 'bg-green-100 text-green-800' }
  return { label: 'Pending', cls: 'bg-gray-100 text-gray-400' }
}

export default function PersonaAccordion({ decisions, applicationId }: { decisions: DecisionDetail[]; applicationId?: string }) {
  // One open decision per stage. Default: open the first blocking/escalating one.
  const [openByWave, setOpenByWave] = useState<Record<number, string | null>>(() => {
    const blocker = decisions.find((d) => d.outcome === 'block' || d.outcome === 'escalate')
    return blocker ? { [blocker.wave]: blocker.decision_id } : {}
  })
  // Indexed documents, so evidence rows can open the real extraction.
  const [docs, setDocs] = useState<DocItem[]>([])
  useEffect(() => {
    if (!applicationId) return
    let alive = true
    fetchDocuments(applicationId).then((d) => alive && setDocs(d.documents)).catch(() => undefined)
    return () => { alive = false }
  }, [applicationId])

  return (
    <div>
      <div className="mb-1 text-base font-semibold text-slate-900">Decision Journey</div>
      <p className="mb-3 text-sm text-slate-500">Click any decision to see the AI's reasoning.</p>

      <div className="space-y-3">
        {STAGES.map((stage) => {
          const ds = decisions.filter((d) => d.wave === stage.wave)
          const ov = overall(ds)
          return (
            <div key={stage.wave} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="flex items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-5 py-3">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-bold tracking-wide text-slate-800">{stage.label}</span>
                  <span className="text-xs text-slate-400">Wave {stage.wave}</span>
                </div>
                <span className="flex items-center gap-1.5 text-xs text-slate-500">
                  Overall:
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${ov.cls}`}>{ov.label}</span>
                </span>
              </div>

              {ds.length === 0 ? (
                <div className="px-5 py-3 text-sm text-slate-400">No data available.</div>
              ) : (
                <div className="divide-y divide-slate-100">
                  {ds.map((d) => (
                    <DecisionRow
                      key={d.decision_id}
                      d={d}
                      docs={docs}
                      open={openByWave[stage.wave] === d.decision_id}
                      onToggle={() =>
                        setOpenByWave((s) => ({
                          ...s,
                          [stage.wave]: s[stage.wave] === d.decision_id ? null : d.decision_id,
                        }))
                      }
                    />
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DecisionRow({ d, docs, open, onToggle }: { d: DecisionDetail; docs: DocItem[]; open: boolean; onToggle: () => void }) {
  const m = outcomeMeta(d.outcome)
  const [openEv, setOpenEv] = useState<{ ev: Evidence; doc: DocItem | null } | null>(null)
  const ruleStr = (d.rule || '').trim()
  const isDefaultEscalate = ruleStr.toLowerCase() === 'default escalate'

  return (
    <div>
      <button onClick={onToggle} className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-slate-50">
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${m.pill}`}>
          {m.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-800">{d.persona_name}</span>
            {d.stale && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">stale</span>
            )}
          </div>
          <div className="truncate text-xs text-slate-500">{(d.explanation || '').split('. ')[0]}</div>
        </div>
        <span className="hidden shrink-0 text-xs text-slate-400 sm:block">
          {d.reviewed ? `✓ Reviewed${d.reviewer ? ` by ${d.reviewer}` : ''}` : '⏳ Pending'}
        </span>
        <DecisionPill outcome={d.outcome} compact />
        <span className="shrink-0 text-slate-400">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-slate-100 bg-slate-50/60 px-5 py-4">
          {/* AI explanation */}
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">🧠 AI Explanation</div>
            <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-700">
              {d.explanation || 'No explanation available.'}
            </div>
          </div>

          {/* Signals */}
          {d.signals.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Signals</div>
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {d.signals.map((s, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${SIGNAL_DOT[s.status] || 'bg-slate-400'}`} />
                    <span className="text-slate-600">{s.key}</span>
                    <span className="ml-auto font-medium text-slate-900">{s.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Rule applied */}
          {d.rule && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">Rule applied</div>
              {isDefaultEscalate ? (
                <div className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex items-start">
                    <RuleLayerBadge layer="system" />
                    <div>
                      <p className="text-[15px] leading-relaxed text-slate-700">
                        No specific rule matched for this check. The system escalated to a human reviewer because the
                        data didn&apos;t clearly pass or fail any defined threshold.
                      </p>
                      <p className="mt-2 text-sm leading-relaxed text-slate-500">
                        This typically means: missing data, edge case values, or a scenario not covered by current rules.
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                (() => {
                  const def = resolveRule(ruleStr)
                  return (
                    <div className="rounded-lg border border-slate-200 bg-white p-4">
                      <div className="flex items-start">
                        <RuleLayerBadge layer={def.layer} />
                        <div>
                          <p className="text-[15px] font-medium text-[#374151]">{def.label}</p>
                          {def.citation && <p className="mt-0.5 text-xs text-slate-500">Citation: {def.citation}</p>}
                        </div>
                      </div>
                      <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 px-3 py-2 font-mono text-[12px] leading-relaxed text-slate-100">
                        {ruleStr} → {d.outcome}
                      </pre>
                    </div>
                  )
                })()
              )}
            </div>
          )}

          {/* Evidence — each document is clickable */}
          {d.evidence.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Evidence</div>
              <ul className="space-y-1">
                {d.evidence.map((e, i) => {
                  const doc = matchDoc(e.document, docs)
                  return (
                    <li key={i}>
                      <button
                        onClick={() => setOpenEv({ ev: e, doc: doc ?? null })}
                        title="View extracted data"
                        className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-white hover:shadow-sm"
                      >
                        <span className="text-slate-400">📄</span>
                        <span className="font-medium text-slate-700">{e.document}</span>
                        <span className="text-brand">↗</span>
                        <span className="text-slate-400">— {e.detail}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {/* Metadata: Confidence · Reviewer · Timestamp */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-200 pt-3 text-xs text-slate-400">
            <span>
              Confidence:{' '}
              <span className="font-medium text-slate-600">
                {d.confidence != null ? `${Math.round(d.confidence * 100)}%` : '—'}
              </span>
            </span>
            <span>Mode: <span className="font-medium text-slate-600">{d.mode}</span></span>
            <span>Reviewer: <span className="font-medium text-slate-600">{d.reviewer ?? 'System'}</span></span>
            {d.reviewed_at && <span>{new Date(d.reviewed_at).toLocaleString()}</span>}
          </div>

          {/* Evidence document detail (slide-over) */}
          {openEv && (
            openEv.doc && openEv.doc.extracted_data && Object.keys(openEv.doc.extracted_data).length > 0 ? (
              <ExtractionDetail
                doc={openEv.doc}
                allDocs={docs}
                onClose={() => setOpenEv(null)}
                onOpenDoc={(id) => setOpenEv({ ev: openEv.ev, doc: docs.find((x) => x.document_id === id) ?? null })}
              />
            ) : (
              <EvidenceComingSoon ev={openEv.ev} doc={openEv.doc} onClose={() => setOpenEv(null)} />
            )
          )}
        </div>
      )}
    </div>
  )
}

// Fallback slide-over when an evidence document has no structured extraction yet.
function EvidenceComingSoon({ ev, doc, onClose }: { ev: Evidence; doc: DocItem | null; onClose: () => void }) {
  const confMatch = /(\d+)\s*%/.exec(ev.detail || '')
  const conf = doc?.confidence != null ? `${Math.round(doc.confidence * 100)}%` : confMatch ? `${confMatch[1]}%` : null
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="flex-1 bg-black/30" />
      <div className="w-[420px] max-w-full animate-[slideIn_.2s_ease] overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <style>{`@keyframes slideIn{from{transform:translateX(40px);opacity:.6}to{transform:none;opacity:1}}`}</style>
        <div className="border-b border-slate-100 p-5">
          <button onClick={onClose} className="mb-3 text-sm font-medium text-brand hover:underline">← Back</button>
          <h2 className="text-lg font-bold text-slate-900">📄 {ev.document}</h2>
          {ev.detail && <p className="text-sm text-slate-500">{ev.detail}</p>}
        </div>
        <div className="p-5">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-600">
            Document indexed{conf ? ` at ${conf} confidence` : ''}. Detailed extraction view coming soon.
          </div>
        </div>
      </div>
    </div>
  )
}
