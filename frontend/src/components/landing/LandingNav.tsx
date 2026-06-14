import { Link } from 'react-router-dom'
import { BRAND, DEMO } from './brand'

// Sticky top nav. Logo image already contains the wordmark — no text beside it.
export default function LandingNav() {
  return (
    <header className="sticky top-0 z-40 bg-white" style={{ borderBottom: '0.5px solid #E5E7EB' }}>
      <div className="mx-auto flex max-w-[1200px] items-center px-6" style={{ height: 64 }}>
        <a href="#top" className="flex items-center" style={{ gap: '12px' }}>
          <img src="/accord_logo.png" alt="Accord" style={{ height: '28px' }} />
          <span style={{ fontSize: '20px', fontWeight: 700, color: BRAND.nearblack, letterSpacing: '-0.3px', lineHeight: 1 }}>accord</span>
        </a>
        <nav className="ml-10 hidden items-center gap-7 md:flex" style={{ fontSize: '15px', fontWeight: 400, color: BRAND.nearblack }}>
          <a href="#products" className="hover:opacity-70">Product</a>
          <a href="#pricing" className="hover:opacity-70">Pricing</a>
          <a href="#faq" className="hover:opacity-70">Docs</a>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <Link to="/login" className="text-sm hover:opacity-70" style={{ fontWeight: 400, color: BRAND.nearblack }}>Log in</Link>
          <a
            href={DEMO}
            className="rounded-lg px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110"
            style={{ backgroundColor: BRAND.dark }}
          >
            Request a demo
          </a>
        </div>
      </div>
    </header>
  )
}
