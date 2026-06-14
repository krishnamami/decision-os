import { Link } from 'react-router-dom'
import { BRAND, DEMO } from './brand'

export default function CTASection() {
  return (
    <section className="px-6 py-16">
      <div className="mx-auto max-w-[1100px] rounded-3xl px-8 py-14 text-center" style={{ backgroundColor: BRAND.dark }}>
        <h2 className="text-[28px] font-bold text-white md:text-[32px]">Ready to see Accord in action?</h2>
        <p className="mx-auto mt-3 max-w-2xl text-base text-white/80">
          See how AI evaluates your loans — with full audit trail. Book a personalized demo and see how Accord helps
          lenders make better decisions — every day.
        </p>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <a href={DEMO} className="rounded-lg bg-white px-6 py-3 text-sm font-semibold transition hover:bg-white/90" style={{ color: BRAND.dark }}>
            Request a demo
          </a>
          <Link to="/login" className="rounded-lg border border-white px-6 py-3 text-sm font-semibold text-white transition hover:bg-white/10">
            Or log in to your account
          </Link>
        </div>
      </div>
    </section>
  )
}
