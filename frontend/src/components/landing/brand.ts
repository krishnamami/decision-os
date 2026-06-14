// Landing-page brand tokens. These are intentionally scoped to the marketing
// landing components and applied via inline styles / arbitrary values, so the
// rest of the product (which uses the global `brand` Tailwind color #0F6E56)
// is left untouched. No other greens on the landing page.
export const BRAND = {
  dark: '#0F4D37',      // primary — buttons, headings, icons, all green text
  mid: '#34D399',       // logo accent only — do not use elsewhere in UI
  light: '#d1e8d8',     // icon backgrounds, active states, badges
  offwhite: '#F5F7FA',  // section backgrounds, screen mockups
  nearblack: '#0B1220', // h1, h2 headings
} as const

export const DEMO = 'mailto:demo@useaccord.com?subject=Accord%20demo%20request'
