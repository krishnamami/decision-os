import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationsResponse,
} from '../api/client'
import { relativeTime } from './NotesSection'

export default function NotificationBell() {
  const [data, setData] = useState<NotificationsResponse | null>(null)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const load = () => fetchNotifications().then(setData).catch(() => undefined)
  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (open && ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  function openMenu() {
    setOpen((v) => !v)
    if (!open) load()
  }
  function clickNotif(id: string, appId: string | null) {
    markNotificationRead(id).then(load)
    setOpen(false)
    if (appId) navigate(`/pipeline/${appId}`)
  }
  function readAll() {
    markAllNotificationsRead().then(load)
  }

  const unread = data?.unread_count ?? 0
  const list = data?.notifications ?? []

  return (
    <div ref={ref} className="relative">
      <button onClick={openMenu} className="relative flex h-8 w-8 items-center justify-center rounded-full hover:bg-slate-100" aria-label="Notifications">
        <span className="text-lg">🔔</span>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
            <span className="text-sm font-semibold text-slate-900">Notifications</span>
            {unread > 0 && (
              <button onClick={readAll} className="text-xs font-medium text-brand hover:underline">Mark all read</button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {list.length === 0 && <div className="px-4 py-6 text-center text-sm text-slate-400">You're all caught up.</div>}
            {list.map((n) => (
              <button
                key={n.notification_id}
                onClick={() => clickNotif(n.notification_id, n.application_id)}
                className={`flex w-full items-start gap-2 border-b border-slate-50 px-4 py-2.5 text-left hover:bg-slate-50 ${n.is_read ? '' : 'bg-brand-light/30'}`}
              >
                {!n.is_read && <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />}
                <span className={n.is_read ? 'pl-3.5' : ''}>
                  <span className="block text-sm text-slate-800">{n.title}</span>
                  <span className="block text-xs text-slate-400">{relativeTime(n.created_at)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
