// Minimal inline-SVG icon set covering the Tabler icons the landing spec names
// (ti-brain, ti-shield-check, …). Stroke-based, inherits `color` via
// currentColor, sized by the `size` prop (default 20px to match the spec).
import type { CSSProperties } from 'react'

type IconName =
  | 'brain' | 'shield-check' | 'file-check' | 'clipboard-list' | 'users' | 'chart-line'
  | 'building-bank' | 'eye' | 'refresh' | 'layout-list' | 'adjustments-horizontal'
  | 'chart-bar' | 'clipboard-check' | 'certificate' | 'circle-check' | 'chevron-down'

const PATHS: Record<IconName, JSX.Element> = {
  brain: (
    <>
      <path d="M12 5a2.5 2.5 0 0 0-5 0 2.5 2.5 0 0 0-1.6 4.4A2.5 2.5 0 0 0 6.5 14 2.5 2.5 0 0 0 9 16.5 2.5 2.5 0 0 0 12 19" />
      <path d="M12 5a2.5 2.5 0 0 1 5 0 2.5 2.5 0 0 1 1.6 4.4A2.5 2.5 0 0 1 17.5 14 2.5 2.5 0 0 1 15 16.5 2.5 2.5 0 0 1 12 19" />
      <path d="M12 5v14" />
    </>
  ),
  'shield-check': (
    <>
      <path d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  'file-check': (
    <>
      <path d="M14 3v4a1 1 0 0 0 1 1h4" />
      <path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z" />
      <path d="M9 15l2 2 4-4" />
    </>
  ),
  'clipboard-list': (
    <>
      <rect x="8" y="3" width="8" height="4" rx="1" />
      <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
      <path d="M9 12h6M9 16h6" />
      <path d="M7.5 12h.01M7.5 16h.01" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20c0-3 3-5 6-5s6 2 6 5" />
      <path d="M16 5.5a3 3 0 0 1 0 5.8" />
      <path d="M17 15.2c2 .6 4 2 4 4.8" />
    </>
  ),
  'chart-line': (
    <>
      <path d="M4 4v16h16" />
      <path d="M7 14l3-3 3 2 5-6" />
    </>
  ),
  'building-bank': (
    <>
      <path d="M3 9l9-5 9 5" />
      <path d="M4 9h16" />
      <path d="M6 9v8M10 9v8M14 9v8M18 9v8" />
      <path d="M3 20h18" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 0 0-14-4l-2 2" />
      <path d="M4 13a8 8 0 0 0 14 4l2-2" />
      <path d="M4 5v4h4M20 19v-4h-4" />
    </>
  ),
  'layout-list': (
    <>
      <rect x="4" y="5" width="16" height="6" rx="1" />
      <rect x="4" y="14" width="16" height="5" rx="1" />
    </>
  ),
  'adjustments-horizontal': (
    <>
      <path d="M4 7h10M18 7h2" />
      <path d="M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </>
  ),
  'chart-bar': (
    <>
      <path d="M4 4v16h16" />
      <rect x="7" y="11" width="3" height="6" />
      <rect x="12" y="8" width="3" height="9" />
      <rect x="17" y="13" width="3" height="4" />
    </>
  ),
  'clipboard-check': (
    <>
      <rect x="8" y="3" width="8" height="4" rx="1" />
      <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
      <path d="M9 14l2 2 4-4" />
    </>
  ),
  certificate: (
    <>
      <circle cx="12" cy="10" r="5" />
      <path d="M9 14l-1 6 4-2 4 2-1-6" />
      <path d="M10 10l1.5 1.5L14 9" />
    </>
  ),
  'circle-check': (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8.5 12l2.5 2.5 4.5-5" />
    </>
  ),
  'chevron-down': <path d="M6 9l6 6 6-6" />,
}

export function Icon({ name, size = 20, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  )
}

export type { IconName }
