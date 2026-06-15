import { useEffect, useState } from 'react'
import { BRAND } from './brand'
import { SecLabel, H2, Sub } from './primitives'

const VIDEO_SRC = '/accord_demo.mp4'
const POSTER = '/accord_demo_poster.jpg'

export default function VideoSection() {
  // Render the real <video> only if the file is actually deployed — show the
  // placeholder otherwise. The SPA server returns index.html (200, text/html)
  // for unknown paths, so we must confirm the response is really a video, not
  // just that the request succeeded. (Drop the MP4 at public/accord_demo.mp4.)
  const [hasVideo, setHasVideo] = useState(false)
  useEffect(() => {
    let alive = true
    fetch(VIDEO_SRC, { method: 'HEAD' })
      .then((r) => {
        const ct = r.headers.get('content-type') || ''
        if (alive && r.ok && ct.startsWith('video')) setHasVideo(true)
      })
      .catch(() => undefined)
    return () => { alive = false }
  }, [])

  return (
    <section id="video" className="mx-auto max-w-[1000px] scroll-mt-24 px-6 py-16 text-center">
      <SecLabel>See it in action</SecLabel>
      <H2 className="mx-auto">Watch Accord review a loan</H2>
      <Sub className="mx-auto mt-3 max-w-xl">
        From file landing in the queue to an audited, documented decision — in under two minutes.
      </Sub>

      {hasVideo ? (
        <video
          src={VIDEO_SRC}
          controls
          poster={POSTER}
          className="mx-auto mt-8 aspect-video w-full max-w-3xl rounded-2xl bg-black shadow-lg"
        />
      ) : (
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
      )}
    </section>
  )
}
