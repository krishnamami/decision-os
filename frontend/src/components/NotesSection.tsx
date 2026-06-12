import { useEffect, useState } from 'react'
import { addNote, fetchNotes, type LoanNote } from '../api/client'

export function relativeTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso).getTime()
  const mins = Math.round((Date.now() - d) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

export default function NotesSection({ appId }: { appId: string }) {
  const [notes, setNotes] = useState<LoanNote[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => fetchNotes(appId).then((d) => setNotes(d.notes)).catch(() => undefined)
  useEffect(() => {
    load()
  }, [appId])

  async function add() {
    if (!text.trim()) return
    setBusy(true)
    try {
      await addNote(appId, text.trim())
      setText('')
      await load()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 text-sm font-semibold text-slate-700">Notes ({notes.length})</div>
      <div className="mb-3 flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          placeholder="Add a note visible to everyone on this loan…"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-brand"
        />
        <button
          onClick={add}
          disabled={busy || !text.trim()}
          className="rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-40"
        >
          Add note
        </button>
      </div>
      <div className="space-y-3">
        {notes.length === 0 && <p className="text-sm text-slate-400">No notes yet.</p>}
        {notes.map((n) => (
          <div key={n.note_id} className="border-l-2 border-slate-200 pl-3">
            <div className="text-xs text-slate-500">
              <span className="font-medium text-slate-700">{n.author}</span> · {relativeTime(n.created_at)}
            </div>
            <p className="text-sm text-slate-700">{n.note}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
