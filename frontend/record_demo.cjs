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
    // ═══ INTRO (3.5s) ═══
    await card(page, 'accord', 'Every decision. In accord.')
    await sleep(3500)
    await clearCard(page)

    // ═══ BEAT 1: THE HOOK — Landing page hero (5s) ═══
    await beat(page, 'The biggest financial decision deserves the best underwriting.', { hold: 5000 })

    // ═══ BEAT 2: THE PAIN — Scroll landing page (6s) ═══
    await beat(page, 'Credit. Employment. Property. Title. Days to weeks.', { scrollY: 600, scrollMs: 3000, hold: 5500 })

    // ═══ BEAT 3: THE SOLUTION — Scroll to stats (5s) ═══
    await beat(page, 'Accord works like your best underwriter.', { scrollY: 1000, scrollMs: 2500, hold: 4500 })

    // ═══ BEAT 4: LOGIN → MY QUEUE (6s) ═══
    await login(page)
    await beat(page, 'Just the loans that need YOUR attention.', { url: '/pipeline', hold: 5500 })

    // ═══ BEAT 5: LOAN DETAIL — AI RECOMMENDATION (5s) ═══
    await beat(page, 'Every recommendation backed by evidence.', { url: '/pipeline/APP-SC02-004', hold: 5000 })

    // ═══ BEAT 6: EVIDENCE — WHY BLOCKED + WHAT PASSED (6s) ═══
    await beat(page, "Why it's blocked. What passed. One screen.", { scrollY: 600, scrollMs: 2500, hold: 5500 })

    // ═══ BEAT 7: COMPLIANCE — RULES + REGULATIONS (7s) ═══
    await beat(page, 'Three layers of rules. Federal. Agency. Yours. All visible.', { scrollY: 1000, scrollMs: 2500, hold: 6000 })

    // ═══ BEAT 8: DOCUMENT TRACING (5s) ═══
    await beat(page, 'Click any number. See the source document.', { scrollY: 1400, scrollMs: 2000, hold: 4500 })

    // ═══ BEAT 9: ACTION — ONE CLICK (4s) ═══
    await beat(page, 'One click to act. Complete audit trail.', { scrollY: 1800, scrollMs: 2000, hold: 3500 })

    // ═══ BEAT 10: SIMULATION (6s) ═══
    await beat(page, '"What if we tighten DTI?" See the impact before you commit.', { url: '/simulation#simulate', hold: 5500 })

    // ═══ BEAT 11: DEBATE (5s) ═══
    await beat(page, 'Debate complex cases. Communicate seamlessly.', { url: '/simulation#debate', hold: 4500 })

    // ═══ BEAT 12: AUDIT + COMPLIANCE (6s) ═══
    await beat(page, 'Examiner asks "why?" Answer in one click.', { url: '/audit', hold: 5500 })

    // ═══ BEAT 13: GOVERNANCE REPORTS (4s) ═══
    await beat(page, 'HMDA. Fair lending. Full examiner package.', { scrollY: 600, scrollMs: 2000, hold: 3500 })

    // ═══ CLOSING CARD (4s) ═══
    await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 60000 })
    await sleep(1200)
    await card(page, 'accord', 'Every decision. In accord.')
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
