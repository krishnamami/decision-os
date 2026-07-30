import { useState } from 'react'
import { BRAND } from './brand'
import { SecLabel, H2, Sub, Container, IconBox } from './primitives'
import { Icon, type IconName } from './Icon'
import VideoModal from './VideoModal'

const PRODUCTS: Array<{
  icon: IconName
  name: string
  tagline: string
  body: string
  video?: string
  videoTitle?: string
  link?: string
}> = [
  {
    icon: 'layout-list',
    name: 'Pipeline',
    tagline: 'See what AI found on every loan',
    body: "Review findings, take action, move on. AI tells you what's wrong, what's fine, and what to do next for every loan in your pipeline.",
    video: '/blog/clips/video24-FINAL.mp4',
    videoTitle: 'Pipeline — ARM loan walkthrough',
  },
  {
    icon: 'adjustments-horizontal',
    name: 'Simulation',
    tagline: "Ask 'what if' about anything",
    body: 'What if we tighten DTI? What if rates rise? Should this blocked loan be approved? Get answers with AI reasoning, not just numbers.',
    video: '/blog/clips/video17-FINAL.mp4',
    videoTitle: 'Simulation — Policy Simulator walkthrough',
  },
  {
    icon: 'chart-bar',
    name: 'Analytics',
    tagline: 'See exactly where your pipeline wins and where it leaks',
    body: 'Portfolio volume, approval rates, fallout by wave, and agent performance — all in one view. Spot where loans are dropping and where risk is concentrating.',
    video: '/blog/clips/accord_analytics.mp4',
    videoTitle: 'Analytics — Portfolio performance walkthrough',
  },
  {
    icon: 'clipboard-check',
    name: 'Audit',
    tagline: 'Pull the examiner package in one click',
    body: 'Every AI finding, every human action, every override — documented with reasoning. HMDA, fair lending, adverse action. Complete trail.',
    video: '/blog/clips/accord_audit.mp4',
    videoTitle: 'Audit — Examiner package walkthrough',
  },
]

export default function ProductsGrid() {
  const [activeVideo, setActiveVideo] = useState<{ src: string; title: string } | null>(null)

  return (
    <section id="products" className="py-20" style={{ backgroundColor: BRAND.offwhite }}>
      <Container>
        <div className="text-center">
          <SecLabel>Products</SecLabel>
          <H2 className="mx-auto">Four products. One platform.</H2>
          <Sub className="mx-auto mt-3">Start with Pipeline. Add more as you grow.</Sub>
        </div>
        <div className="mt-12 grid gap-5 md:grid-cols-2">
          {PRODUCTS.map((p) => (
            <div key={p.name} className="flex flex-col rounded-2xl border border-slate-200 bg-white p-6">
              <div className="flex items-center gap-3">
                <IconBox><Icon name={p.icon} size={20} /></IconBox>
                <div>
                  <div className="text-lg font-bold text-slate-900">{p.name}</div>
                  <div className="text-sm font-semibold" style={{ color: BRAND.dark }}>{p.tagline}</div>
                </div>
              </div>
              <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-600">{p.body}</p>
              {p.video ? (
                <button
                  onClick={() => setActiveVideo({ src: p.video!, title: p.videoTitle! })}
                  className="mt-4 text-left text-sm font-semibold hover:underline"
                  style={{ color: BRAND.dark }}
                >
                  ▶ Watch demo →
                </button>
              ) : p.link?.startsWith('/') ? (
                <a href={p.link} className="mt-4 text-sm font-semibold hover:underline" style={{ color: BRAND.dark }}>Learn more →</a>
              ) : (
                <a href={p.link} className="mt-4 text-sm font-semibold hover:underline" style={{ color: BRAND.dark }}>Learn more →</a>
              )}
            </div>
          ))}
        </div>
      </Container>

      {activeVideo && (
        <VideoModal
          src={activeVideo.src}
          title={activeVideo.title}
          onClose={() => setActiveVideo(null)}
        />
      )}
    </section>
  )
}
