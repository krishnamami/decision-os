import { useState } from 'react'
import { requestInfo } from '../../api/client'
import { useAuth } from '../../context/AuthContext'

// Sends a document request to the borrower via POST /communications (request_info)
// — it does NOT escalate or record an audit note. The catalogue of askable
// documents is presentation data; the backend stores whatever labels we submit
// as items_requested. Shared by the loan workbench and the UW queue cards, so it
// takes plain props (application_id + borrower_name), not a full LoanDetail.
const DOC_TYPES = [
  'W-2s (last 2 years)',
  'Pay stubs (last 30 days)',
  'Bank statements (last 2 months)',
  'Tax returns (last 2 years)',
  'Employment verification letter',
  'Government-issued photo ID',
  'Proof of insurance',
]

function addBusinessDays(start: Date, n: number): Date {
  const d = new Date(start)
  let added = 0
  while (added < n) {
    d.setDate(d.getDate() + 1)
    const wd = d.getDay()
    if (wd !== 0 && wd !== 6) added += 1
  }
  return d
}
// Local-date ISO (yyyy-mm-dd) without UTC drift — drives the <input type=date>.
function isoDate(d: Date): string {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}
// "2026-07-07" → "Monday, July 7" for the email body (parse as local, no TZ drift).
function prettyDueDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(`${iso}T00:00:00`)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
}

export default function RequestDocsModal({
  applicationId, borrowerName = null, borrowerEmail = null, coBorrowerEmail = null, onClose, onDone,
}: {
  applicationId: string
  borrowerName?: string | null
  borrowerEmail?: string | null
  coBorrowerEmail?: string | null
  onClose: () => void
  onDone: (msg: string) => void
}) {
  const { effectiveUser, tenant } = useAuth()
  const [step, setStep] = useState<1 | 2>(1)
  const [docs, setDocs] = useState<Set<string>>(new Set())
  const [otherChecked, setOtherChecked] = useState(false)
  const [otherText, setOtherText] = useState('')
  const [sendBorrower, setSendBorrower] = useState(true)
  const [sendCo, setSendCo] = useState(false)
  const [sendLO, setSendLO] = useState(false)
  const [message, setMessage] = useState('')
  const [dueDate, setDueDate] = useState(() => isoDate(addBusinessDays(new Date(), 5)))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  function toggleDoc(d: string) {
    setDocs((prev) => { const n = new Set(prev); n.has(d) ? n.delete(d) : n.add(d); return n })
  }

  const items = [...docs, ...(otherChecked && otherText.trim() ? [otherText.trim()] : [])]
  const ready = items.length > 0 && (!otherChecked || otherText.trim().length > 0) && !busy

  // Email-preview values — all derived from the form + auth/props context.
  const borrowerFirstName = (borrowerName ?? '').trim().split(/\s+/)[0] || 'there'
  const underwriterName = effectiveUser?.name ?? 'your underwriter'
  const tenantName = tenant?.name ?? 'your lender'

  async function submit() {
    if (!ready) return
    setBusy(true); setErr(null)
    // request_info takes a single recipient_email; preserve the full send-to
    // selection in the note so nothing the underwriter chose is lost.
    const recipients: string[] = []
    if (sendBorrower) recipients.push('Borrower')
    if (sendCo && coBorrowerEmail) recipients.push('Co-borrower')
    if (sendLO) recipients.push('Loan officer')
    const note = [
      message.trim() || undefined,
      recipients.length ? `Send to: ${recipients.join(', ')}` : undefined,
    ].filter(Boolean).join('\n\n') || undefined
    try {
      await requestInfo({
        application_id: applicationId,
        recipient_email: sendBorrower && borrowerEmail ? borrowerEmail : undefined,
        items,
        note,
        due_date: dueDate || undefined,
      })
      onDone('Document request sent — borrower notified.')
    } catch {
      setErr('Could not send the request — please try again.')
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        {/* Header + step indicator */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-base font-bold text-slate-900">Request documents</div>
            <div className="mt-1 text-[12px] text-slate-500">
              {step === 1
                ? <>Ask {borrowerName ?? 'the borrower'} to upload the documents you need to clear conditions.</>
                : <>Review the email {borrowerName ?? 'the borrower'} will receive before sending.</>}
            </div>
          </div>
          <StepIndicator step={step} />
        </div>

        {step === 1 ? (
          <>
            <div className="mt-4">
              <div className="mb-1.5 text-xs font-semibold text-slate-600">Document types</div>
              <div className="space-y-1.5">
                {DOC_TYPES.map((d) => (
                  <label key={d} className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={docs.has(d)} onChange={() => toggleDoc(d)} className="accent-[#14532d]" />
                    {d}
                  </label>
                ))}
                <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={otherChecked} onChange={() => setOtherChecked((v) => !v)} className="accent-[#14532d]" />
                  Other
                </label>
                {otherChecked && (
                  <input
                    value={otherText}
                    onChange={(e) => setOtherText(e.target.value)}
                    placeholder="Describe the document…"
                    className="ml-6 w-[calc(100%-1.5rem)] rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm outline-none focus:border-[#14532d]"
                  />
                )}
              </div>
            </div>

            <div className="mt-4">
              <div className="mb-1.5 text-xs font-semibold text-slate-600">Send to</div>
              <div className="space-y-1.5">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={sendBorrower} onChange={() => setSendBorrower((v) => !v)} className="accent-[#14532d]" />
                  Borrower{borrowerEmail ? ` (${borrowerEmail})` : ''}
                </label>
                {coBorrowerEmail && (
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={sendCo} onChange={() => setSendCo((v) => !v)} className="accent-[#14532d]" />
                    Co-borrower ({coBorrowerEmail})
                  </label>
                )}
                <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={sendLO} onChange={() => setSendLO((v) => !v)} className="accent-[#14532d]" />
                  Loan officer
                </label>
              </div>
            </div>

            <div className="mt-4">
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-slate-600">Message to borrower (optional)</span>
                <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-[#14532d]" />
              </label>
            </div>

            <div className="mt-4">
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-slate-600">Due date</span>
                <span className="flex items-center gap-2">
                  <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-[#14532d]" />
                  <span className="text-[11px] text-slate-400">Default: 5 business days</span>
                </span>
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
              <button onClick={() => setStep(2)} disabled={!ready} title={items.length === 0 ? 'Select at least one document' : undefined} className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-40">
                Preview email →
              </button>
            </div>
          </>
        ) : (
          <>
            <EmailPreview
              borrowerFirstName={borrowerFirstName}
              borrowerEmail={borrowerEmail}
              appId={applicationId}
              items={items}
              message={message.trim()}
              dueDatePretty={prettyDueDate(dueDate)}
              underwriterName={underwriterName}
              tenantName={tenantName}
            />

            {err && <p className="mt-3 text-sm font-medium text-red-600">{err}</p>}

            <div className="mt-5 flex items-center justify-between gap-2">
              <button onClick={() => { setErr(null); setStep(1) }} disabled={busy} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40">← Back</button>
              <button onClick={submit} disabled={!ready} className="rounded-lg bg-green-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-green-500 disabled:opacity-40">
                {busy ? 'Sending…' : 'Send request'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// Two-dot progress indicator + "Step N of 2" label.
function StepIndicator({ step }: { step: 1 | 2 }) {
  return (
    <div className="flex shrink-0 flex-col items-end gap-1">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Step {step} of 2</span>
      <div className="flex items-center gap-1">
        <span className={`h-2 w-2 rounded-full ${step >= 1 ? 'bg-blue-600' : 'bg-slate-300'}`} />
        <span className={`h-0.5 w-4 ${step >= 2 ? 'bg-blue-600' : 'bg-slate-300'}`} />
        <span className={`h-2 w-2 rounded-full ${step >= 2 ? 'bg-blue-600' : 'bg-slate-300'}`} />
      </div>
    </div>
  )
}

// Realistic rendering of the email the borrower will receive — visual only.
function EmailPreview({ borrowerFirstName, borrowerEmail, appId, items, message, dueDatePretty, underwriterName, tenantName }: {
  borrowerFirstName: string; borrowerEmail: string | null; appId: string; items: string[]
  message: string; dueDatePretty: string; underwriterName: string; tenantName: string
}) {
  return (
    <div className="mt-4">
      <div className="overflow-hidden rounded-lg border border-slate-200 shadow-sm">
        {/* Email header bar */}
        <div className="space-y-0.5 border-b border-slate-200 bg-slate-50 px-4 py-2.5 text-[11px] text-slate-500">
          <div><span className="inline-block w-12 text-slate-400">From:</span><span className="text-slate-700">noreply@useaccord.com</span></div>
          <div><span className="inline-block w-12 text-slate-400">To:</span><span className="text-slate-700">{borrowerEmail ?? 'borrower'}</span></div>
          <div><span className="inline-block w-12 align-top text-slate-400">Subject:</span><span className="font-medium text-slate-800">Action required — documents needed for your loan application</span></div>
        </div>

        {/* Email body */}
        <div className="bg-white px-5 py-4 text-[13px] leading-relaxed text-slate-700">
          <div className="mb-3 text-sm font-bold tracking-tight text-[#14532d]">accord</div>

          <p>Hi {borrowerFirstName},</p>
          <p className="mt-2">
            Your underwriter has reviewed your loan application (<span className="font-mono text-[12px]">{appId}</span>) and needs the following documents to continue:
          </p>

          <ul className="mt-2 list-disc space-y-0.5 pl-5">
            {items.map((it) => <li key={it}>{it}</li>)}
          </ul>

          {message && <p className="mt-3 whitespace-pre-line italic text-slate-600">{message}</p>}

          {dueDatePretty && (
            <p className="mt-3">Please upload these documents by <span className="font-semibold">{dueDatePretty}</span>.</p>
          )}

          <div className="mt-4">
            <span className="inline-block cursor-default rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white">Upload documents →</span>
          </div>

          <p className="mt-4 text-[12px] text-slate-500">
            If you have questions, contact your underwriter at {underwriterName}, {tenantName}.
          </p>
          <p className="mt-3 text-[12px] text-slate-500">— The {tenantName} team</p>
        </div>
      </div>

      <p className="mt-2 text-center text-[10px] uppercase tracking-wide text-slate-400">Preview only — not yet sent</p>
    </div>
  )
}
