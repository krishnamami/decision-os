import { useState } from 'react'
import { Link } from 'react-router-dom'
import { BRAND } from './brand'
import { AccordLogo } from './primitives'
import DemoModal from './DemoModal'

export default function LandingNav() {
  const [showDemo, setShowDemo] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  const scrollTo = (id: string) => {
    setMenuOpen(false)
    const el = document.getElementById(id)
    if (el) el.scrollIntoView({ behavior: 'smooth' })
    else window.location.href = `/?scroll=${id}`
  }

  return (
    <>
      <header className="sticky top-0 z-40 bg-white" style={{ borderBottom: '0.5px solid #E5E7EB' }}>
        <div className="mx-auto flex max-w-[1200px] items-center px-6" style={{ paddingTop: '18px', paddingBottom: '18px' }}>

          {/* Logo */}
          <a href="/" className="flex items-center"><AccordLogo /></a>

          {/* Desktop nav */}
          <nav className="ml-10 hidden items-center md:flex" style={{ gap: '32px', fontSize: '15px', fontWeight: 400, color: BRAND.nearblack }}>
            <a href="/#products" onClick={(e) => { e.preventDefault(); scrollTo('products') }} className="flex items-center gap-1 hover:opacity-70">Products <span className="text-[10px]">▾</span></a>
            <a href="/#pricing" onClick={(e) => { e.preventDefault(); scrollTo('pricing') }} className="hover:opacity-70">Pricing</a>
            <Link to="/docs" className="hover:opacity-70">Docs</Link>
            <Link to="/blog" className="hover:opacity-70">Blog</Link>
          </nav>

          {/* Desktop right side */}
          <div className="ml-auto hidden items-center gap-4 md:flex">
            <Link to="/login" className="hover:opacity-70" style={{ fontSize: '15px', fontWeight: 400, color: BRAND.nearblack }}>Log in</Link>
            <button
              onClick={() => setShowDemo(true)}
              className="px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110"
              style={{ backgroundColor: BRAND.dark, borderRadius: '8px' }}
            >
              Request a demo
            </button>
          </div>

          {/* Mobile right side */}
          <div className="ml-auto flex items-center gap-3 md:hidden">
            <button
              onClick={() => setShowDemo(true)}
              className="px-3 py-1.5 text-xs font-semibold text-white transition hover:brightness-110"
              style={{ backgroundColor: BRAND.dark, borderRadius: '8px' }}
            >
              Request a demo
            </button>
            {/* Hamburger */}
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="flex flex-col items-center justify-center gap-1.5 p-1"
              aria-label="Toggle menu"
            >
              <span className={`block h-0.5 w-6 bg-slate-700 transition-all ${menuOpen ? 'translate-y-2 rotate-45' : ''}`} />
              <span className={`block h-0.5 w-6 bg-slate-700 transition-all ${menuOpen ? 'opacity-0' : ''}`} />
              <span className={`block h-0.5 w-6 bg-slate-700 transition-all ${menuOpen ? '-translate-y-2 -rotate-45' : ''}`} />
            </button>
          </div>
        </div>

        {/* Mobile menu dropdown */}
        {menuOpen && (
          <div className="border-t border-slate-100 bg-white px-6 py-4 md:hidden">
            <nav className="flex flex-col gap-4" style={{ fontSize: '15px', fontWeight: 400, color: BRAND.nearblack }}>
              <a href="/#products" onClick={(e) => { e.preventDefault(); scrollTo('products') }} className="hover:opacity-70">Products</a>
              <a href="/#pricing" onClick={(e) => { e.preventDefault(); scrollTo('pricing') }} className="hover:opacity-70">Pricing</a>
              <Link to="/docs" onClick={() => setMenuOpen(false)} className="hover:opacity-70">Docs</Link>
              <Link to="/blog" onClick={() => setMenuOpen(false)} className="hover:opacity-70">Blog</Link>
              <div className="border-t border-slate-100 pt-4">
                <Link to="/login" onClick={() => setMenuOpen(false)} className="hover:opacity-70">Log in</Link>
              </div>
            </nav>
          </div>
        )}
      </header>

      {showDemo && <DemoModal onClose={() => setShowDemo(false)} />}
    </>
  )
}
