import { useState } from 'react'
import { BRAND } from './brand'

interface Props {
  onClose: () => void
}

export default function DemoModal({ onClose }: Props) {
  const [status, setStatus] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setStatus('submitting')
    const form = e.currentTarget
    const data = new FormData(form)
    try {
      const res = await fetch('https://formspree.io/f/mgogboaz', {
        method: 'POST',
        body: data,
        headers: { Accept: 'application/json' },
      })
      if (res.ok) {
        setStatus('success')
      } else {
        setStatus('error')
      }
    } catch {
      setStatus('error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className="relative w-full max-w-lg rounded-2xl bg-white p-8 shadow-2xl">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-slate-400 hover:text-slate-600 text-xl font-bold"
        >
          ✕
        </button>

        {status === 'success' ? (
          <div className="text-center py-8">
            <div className="text-4xl mb-4">✅</div>
            <h2 className="text-2xl font-bold mb-2" style={{ color: BRAND.nearblack }}>Request received</h2>
            <p className="text-slate-500 mb-6">We'll be in touch within one business day to schedule your demo.</p>
            <button
              onClick={onClose}
              className="rounded-lg px-6 py-2.5 text-sm font-semibold text-white"
              style={{ backgroundColor: BRAND.dark }}
            >
              Close
            </button>
          </div>
        ) : (
          <>
            <h2 className="text-2xl font-bold mb-1" style={{ color: BRAND.nearblack }}>Request a demo</h2>
            <p className="text-sm text-slate-500 mb-6">We'll show you Accord on your own pipeline — no slides, real product.</p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">First name *</label>
                  <input
                    name="first_name"
                    required
                    className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:border-transparent"
                    style={{ '--tw-ring-color': BRAND.dark } as React.CSSProperties}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Last name *</label>
                  <input
                    name="last_name"
                    required
                    className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:border-transparent"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Company *</label>
                <input
                  name="company"
                  required
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Work email *</label>
                <input
                  name="email"
                  type="email"
                  required
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Phone</label>
                <input
                  name="phone"
                  type="tel"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">What are you looking to solve?</label>
                <textarea
                  name="message"
                  rows={3}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:border-transparent resize-none"
                />
              </div>

              {status === 'error' && (
                <p className="text-sm text-red-500">Something went wrong. Please email us at demo@accordlend.com</p>
              )}

              <button
                type="submit"
                disabled={status === 'submitting'}
                className="w-full rounded-lg py-3 text-sm font-semibold text-white disabled:opacity-60"
                style={{ backgroundColor: BRAND.dark }}
              >
                {status === 'submitting' ? 'Sending...' : 'Request demo →'}
              </button>

              <p className="text-center text-xs text-slate-400">We'll respond within one business day.</p>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
