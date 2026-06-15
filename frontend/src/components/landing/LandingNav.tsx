import { Link } from 'react-router-dom'
import { BRAND, DEMO } from './brand'
import { AccordLogo } from './primitives'

// Sticky top nav. Logo copied from the app nav (Header.tsx) for an exact match.
export default function LandingNav() {
  return (
    <header className="sticky top-0 z-40 bg-white" style={{ borderBottom: '0.5px solid #E5E7EB' }}>
      <div className="mx-auto flex max-w-[1200px] items-center px-6" style={{ paddingTop: '18px', paddingBottom: '18px' }}>
        <a href="#top" className="flex items-center"><AccordLogo /></a>
        <nav className="ml-10 hidden items-center md:flex" style={{ gap: '32px', fontSize: '15px', fontWeight: 400, color: BRAND.nearblack }}>
          <a href="#products" className="flex items-center gap-1 hover:opacity-70">Products <span className="text-[10px]">▾</span></a>
          <a href="#pricing" className="hover:opacity-70">Pricing</a>
          <a href="#faq" className="hover:opacity-70">Docs</a>
          <a href="#" className="hover:opacity-70">Blog</a>
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <Link to="/login" className="hover:opacity-70" style={{ fontSize: '15px', fontWeight: 400, color: BRAND.nearblack }}>Log in</Link>
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
