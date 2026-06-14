import { BRAND } from './brand'
import { SecLabel, H2, Sub } from './primitives'

// Placeholder per spec. When the final cut lands, swap the placeholder block
// for: <video src="/accord_demo_final.mp4" controls poster="/video_poster.png" />
export default function VideoSection() {
  return (
    <section id="video" className="mx-auto max-w-[1000px] scroll-mt-24 px-6 py-16 text-center">
      <SecLabel>See it in action</SecLabel>
      <H2 className="mx-auto">Watch Accord review a loan</H2>
      <Sub className="mx-auto mt-3 max-w-xl">
        From file landing in the queue to an audited, documented decision — in under two minutes.
      </Sub>

      <div
        className="mx-auto mt-8 flex aspect-video w-full max-w-3xl flex-col items-center justify-center gap-4 rounded-2xl"
        style={{ backgroundColor: BRAND.offwhite }}
      >
        <span className="flex h-20 w-20 items-center justify-center rounded-full shadow-lg" style={{ backgroundColor: BRAND.dark }}>
          <span
            style={{
              width: 0,
              height: 0,
              borderTop: '10px solid transparent',
              borderBottom: '10px solid transparent',
              borderLeft: '16px solid white',
              marginLeft: '3px',
            }}
          />
        </span>
        <div>
          <div className="text-base font-semibold" style={{ color: BRAND.nearblack }}>Accord demo — underwriter walkthrough</div>
          <div className="mt-1 text-sm text-slate-500">60 seconds · Real product</div>
        </div>
      </div>
    </section>
  )
}
