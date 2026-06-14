import { Link } from 'react-router-dom'
import { BRAND, DEMO } from './brand'

// Sticky top nav. Logo image already contains the wordmark — no text beside it.
export default function LandingNav() {
  return (
    <header className="sticky top-0 z-40 bg-white" style={{ borderBottom: '0.5px solid #E5E7EB' }}>
      <div className="mx-auto flex max-w-[1200px] items-center px-6" style={{ paddingTop: '18px', paddingBottom: '18px' }}>
        <a href="#top" className="flex items-center" style={{ gap: '6px' }}>
          <img src="/accord_logo.png" alt="Accord" style={{ height: '28px' }} />
          <span style={{ fontSize: '22px', fontWeight: 700, color: BRAND.nearblack, letterSpacing: '-0.5px', lineHeight: 1 }}>accord</span>
        </a>
        <nav className="ml-10 hidden items-center md:flex" style={{ gap: '32px', fontSize: '16px', fontWeight: 400, color: BRAND.nearblack }}>
          <a href="#products" className="hover:opacity-70">Product</a>
          <a href="#pricing" className="hover:opacity-70">Pricing</a>
          <a href="#faq" className="hover:opacity-70">Docs</a>
          <a href="#" className="hover:opacity-70">Blog</a>
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <Link to="/login" className="hover:opacity-70" style={{ fontSize: '16px', fontWeight: 400, color: BRAND.nearblack }}>Log in</Link>
          <a
            href={DEMO}
            className="px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110"
            style={{ backgroundColor: BRAND.dark, borderRadius: '8px' }}
          >
            Request a demo
          </a>
        </div>
      </div>
    </header>
  )
}
