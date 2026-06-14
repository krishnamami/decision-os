// Small shared building blocks for the landing sections — keeps the brand
// colors and typography consistent without a CSS framework change.
import type { ReactNode } from 'react'
import { BRAND } from './brand'

export function SecLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-3 text-xs font-bold uppercase tracking-[0.14em]" style={{ color: BRAND.dark }}>
      {children}
    </div>
  )
}

export function H2({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <h2 className={`text-[28px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[32px] ${className}`} style={{ color: BRAND.nearblack }}>
      {children}
    </h2>
  )
}

export function Sub({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <p className={`text-[16px] leading-relaxed text-slate-500 ${className}`}>{children}</p>
}

export function PrimaryButton({ children, href, className = '' }: { children: ReactNode; href: string; className?: string }) {
  return (
    <a
      href={href}
      className={`inline-flex items-center justify-center rounded-lg px-6 py-3 text-sm font-semibold text-white transition hover:brightness-110 ${className}`}
      style={{ backgroundColor: BRAND.dark }}
    >
      {children}
    </a>
  )
}

// Ghost button that matches the primary green outline/text (spec: "See it in
// action" must be the same green as "Request a demo").
export function GreenGhostButton({ children, onClick, href, className = '' }: { children: ReactNode; onClick?: () => void; href?: string; className?: string }) {
  const cls = `inline-flex items-center justify-center gap-2 rounded-lg border px-6 py-3 text-sm font-semibold transition hover:bg-[#d1e8d8]/40 ${className}`
  const style = { color: BRAND.dark, borderColor: BRAND.dark } as const
  if (href) return <a href={href} className={cls} style={style}>{children}</a>
  return <button type="button" onClick={onClick} className={cls} style={style}>{children}</button>
}

export function IconBox({ children, size = 40 }: { children: ReactNode; size?: number }) {
  return (
    <span
      className="flex flex-shrink-0 items-center justify-center rounded-xl"
      style={{ width: size, height: size, backgroundColor: BRAND.light, color: BRAND.dark }}
    >
      {children}
    </span>
  )
}

export function Container({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto max-w-[1200px] px-6 ${className}`}>{children}</div>
}

// Brand mark — solid green rounded square with a white "A". Rendered in code
// (not the logo image) so it stays crisp at any size.
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <span
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.25),
        backgroundColor: BRAND.dark,
        color: '#fff',
        fontSize: Math.round(size * 0.58),
        fontWeight: 700,
        lineHeight: 1,
      }}
    >
      A
    </span>
  )
}
