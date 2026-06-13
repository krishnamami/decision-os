// Records a ~2-minute captioned product walkthrough of the LIVE Accord app to
// an .mp4 — no Loom, no human voice. On-screen caption bars carry the narration
// from docs/DEMO_SCRIPT.md. It only NAVIGATES and scrolls; it never submits an
// action or runs an engine, so it does not mutate production data.
const path = require('path')
const puppeteer = require('puppeteer-core')
const { PuppeteerScreenRecorder } = require('puppeteer-screen-recorder')
const ffmpegPath = require('@ffmpeg-installer/ffmpeg').path

const BASE = 'http://accord-alb-588286075.us-east-1.elb.amazonaws.com'
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const OUT = path.resolve(__dirname, '..', 'accord_demo.mp4')
const W = 1280, H = 720
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Caption bar pinned to the bottom of the viewport (survives scrolling).
async function caption(page, text) {
  await page.evaluate((t) => {
    let el = document.getElementById('__cap__')
    if (!el) {
      el = document.createElement('div')
      el.id = '__cap__'
      el.style.cssText =
        'position:fixed;left:50%;bottom:34px;transform:translateX(-50%);z-index:2147483647;' +
        'max-width:78%;background:rgba(15,23,42,.93);color:#fff;padding:14px 24px;border-radius:12px;' +
        'font:600 19px/1.5 system-ui,Segoe UI,sans-serif;text-align:center;box-shadow:0 10px 34px rgba(0,0,0,.4)'
      document.body.appendChild(el)
    }
    el.textContent = t
  }, text)
}

// Full-screen brand card for the intro / outro.
async function card(page, title, sub) {
  await page.evaluate(({ title, sub }) => {
    const el = document.createElement('div')
    el.id = '__card__'
    el.style.cssText =
      'position:fixed;inset:0;z-index:2147483647;background:#0F6E56;color:#fff;display:flex;' +
      'flex-direction:column;align-items:center;justify-content:center;gap:14px;font-family:system-ui,Segoe UI,sans-serif'
    el.innerHTML =
      '<div style="font-size:54px;font-weight:800;letter-spacing:-1px">' + title + '</div>' +
      '<div style="font-size:22px;opacity:.85">' + sub + '</div>'
    document.body.appendChild(el)
  }, { title, sub })
}
const clearCard = (page) => page.evaluate(() => document.getElementById('__card__')?.remove())

async function slowScrollTo(page, y, ms = 2400, steps = 30) {
  const cur = await page.evaluate(() => window.scrollY)
  for (let i = 1; i <= steps; i++) {
    await page.evaluate((v) => window.scrollTo(0, v), cur + (y - cur) * (i / steps))
    await sleep(ms / steps)
  }
}

async function login(page) {
  await page.goto(BASE + '/login', { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(700)
  await caption(page, 'A loan officer signs in to their workbench…')
  await page.evaluate(() => {
    const ins = [...document.querySelectorAll('input')]
    const email = ins.find((i) => /email/i.test(i.type + i.name + i.placeholder)) || ins[0]
    const pass = ins.find((i) => i.type === 'password')
    const set = (el, v) => {
      Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set.call(el, v)
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    set(email, 'senioruw@summit.com')
    set(pass, 'accord2026')
  })
  await sleep(1200)
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => /sign in|log in|continue/i.test(x.innerText))
    if (b) b.click()
  })
  await sleep(3500)
}

// A beat: optional navigate, set caption, optional slow-scroll, then hold.
async function beat(page, text, opts = {}) {
  const { url, scrollY = 0, hold = 4500, scrollMs = 2400, preHold = 900 } = opts
  if (url) {
    await page.goto(BASE + url, { waitUntil: 'networkidle2', timeout: 60000 })
    await sleep(1300)
  }
  await caption(page, text)
  await sleep(preHold)
  if (scrollY) await slowScrollTo(page, scrollY, scrollMs)
  await sleep(hold)
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    defaultViewport: { width: W, height: H },
    args: ['--no-sandbox', `--window-size=${W},${H}`],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: W, height: H })
  const recorder = new PuppeteerScreenRecorder(page, {
    fps: 25,
    ffmpeg_Path: ffmpegPath,
    videoFrame: { width: W, height: H },
    aspectRatio: '16:9',
  })

  // Land first so there's a body to draw the intro card on.
  await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(800)
  await recorder.start(OUT)

  try {
    // 0 — Intro
    await card(page, 'accord', 'AI-powered lending decisions — a 2-minute tour')
    await sleep(3000)
    await clearCard(page)

    // 1 — Landing / hero
    await beat(page, 'Accord turns a loan into an audited decision — with the AI shown working.', { hold: 4500 })
    await slowScrollTo(page, 520, 2600)
    await beat(page, 'Eight checks run on every loan: credit, fraud, income, collateral, DTI, compliance…', { hold: 4000 })

    // 2 — Login → queue
    await login(page)
    await beat(page, 'After login, an officer sees just the loans that need them — their queue.', { url: '/pipeline', hold: 5000 })

    // 3 — Blocked loan
    await beat(page, 'This loan is blocked — and the AI shows exactly why, scored finding by finding.', {
      url: '/pipeline/APP-SC02-004', hold: 4500,
    })
    await beat(page, 'Identity flagged a watchlist match at 95% confidence — every check itemized, not a black box.', {
      scrollY: 600, scrollMs: 2600, hold: 4500,
    })
    await beat(page, 'From here it is one click to the right team — with a full, timestamped audit trail.', {
      scrollY: 1100, scrollMs: 2400, hold: 4500,
    })

    // 4 — MiroFish debate
    await beat(page, 'MiroFish: 12 AI agents debate a loan across 3 rounds and reach consensus.', {
      url: '/simulation#debate', hold: 5200,
    })

    // 5 — Policy simulator
    await beat(page, 'Policy Simulator: change a rule and see exactly who is affected — before you ship it.', {
      url: '/simulation#simulate', hold: 5000,
    })

    // 6 — Health check / swarm
    await beat(page, 'Portfolio Health Check scans every loan for hidden risk and concentration patterns.', {
      url: '/simulation#swarm', hold: 5000,
    })

    // 7 — Audit
    await beat(page, 'Every decision is documented. Every action is traced. Examiner-ready.', {
      url: '/audit', hold: 4800,
    })

    // 8 — Close on the landing page
    await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 60000 })
    await sleep(1200)
    await card(page, 'accord', 'Every decision, in accord.')
    await sleep(4000)
  } catch (e) {
    console.error('BEAT ERROR:', e.message)
  } finally {
    await recorder.stop()
    await browser.close()
  }
  console.log('Saved →', OUT)
}

main()
