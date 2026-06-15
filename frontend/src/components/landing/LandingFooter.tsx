import { Link } from 'react-router-dom'
import { AccordLogo, Container } from './primitives'

const PRODUCT = ['Overview', 'Pipeline', 'Analytics', 'Simulation', 'Audit']
const COMPANY = ['Docs', 'Pricing', 'Security', 'Contact us']

export default function LandingFooter() {
  return (
    <footer className="border-t border-slate-200 bg-white py-14">
      <Container>
        <div className="grid gap-10 md:grid-cols-[2fr_1fr_1fr]">
          {/* Col 1 */}
          <div>
            <AccordLogo />
            <p style={{ fontSize: '11px', color: '#6B7280', marginTop: '4px' }}>Decision Intelligence for Lending</p>
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-slate-500">
              accordlend.com is built by Accord — where policy, evidence, and human judgment come together to create
              trusted lending decisions. Accord is the holding company behind accordlend.com and accordpreauth.com.
            </p>
          </div>
          {/* Col 2 */}
          <div>
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Product</div>
            <ul className="mt-3 space-y-2 text-sm text-slate-600">
              {PRODUCT.map((l) => <li key={l}><a href="#products" className="hover:text-slate-900">{l}</a></li>)}
            </ul>
          </div>
          {/* Col 3 */}
          <div>
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Company</div>
            <ul className="mt-3 space-y-2 text-sm text-slate-600">
              {COMPANY.map((l) => (
                <li key={l}>
                  {l === 'Security'
                    ? <Link to="/security" className="hover:text-slate-900">{l}</Link>
                    : l === 'Pricing'
                      ? <a href="#pricing" className="hover:text-slate-900">{l}</a>
                      : <a href="#faq" className="hover:text-slate-900">{l}</a>}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-6 text-xs text-slate-500">
          <span>© 2026 Accord. All rights reserved.</span>
          <Link to="/" className="hover:text-slate-900">accordlend.com</Link>
          <span className="flex flex-wrap gap-x-5">
            <a href="#faq" className="hover:text-slate-900">Privacy Policy</a>
            <a href="#faq" className="hover:text-slate-900">Terms of Service</a>
            <Link to="/security" className="hover:text-slate-900">Security</Link>
          </span>
        </div>
      </Container>
    </footer>
  )
}
