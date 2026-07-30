import { useEffect, useRef } from 'react'

interface Props {
  src: string
  title: string
  onClose: () => void
}

export default function VideoModal({ src, title, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    window.addEventListener('mousedown', handler)
    return () => window.removeEventListener('mousedown', handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4">
      <div ref={ref} className="relative w-full max-w-4xl">
        <button
          onClick={onClose}
          className="absolute -top-10 right-0 text-white/70 hover:text-white text-sm font-medium"
        >
          ✕ Close
        </button>
        <div className="text-center mb-3 text-white font-semibold text-lg">{title}</div>
        <video
          src={src}
          autoPlay
          controls
          className="w-full rounded-2xl shadow-2xl bg-black"
        />
      </div>
    </div>
  )
}
