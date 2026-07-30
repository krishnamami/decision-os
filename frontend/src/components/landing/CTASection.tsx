import { BRAND } from './brand'

interface Props {
  onDemo?: () => void
}

export default function CTASection({ onDemo }: Props) {
  return (
    <section className="py-20 text-center" style={{ backgroundColor: BRAND.dark }}>
      <div className="mx-auto max-w-2xl px-6">
        <h2 className="text-[28px] font-bold leading-[1.2] tracking-[-0.02em] text-white md:text-[36px]">
          See Accord on your own pipeline
        </h2>
        <p className="mt-4 text-white/70">No slides. Real product. Your loans.</p>
        <button
          onClick={onDemo}
          className="mt-8 rounded-lg bg-white px-6 py-3 text-sm font-semibold transition hover:bg-white/90"
          style={{ color: BRAND.dark }}
        >
          Request a demo
        </button>
      </div>
    </section>
  )
}
