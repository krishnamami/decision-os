// Records a captioned product walkthrough of the LIVE Accord app to an .mp4 — no
// Loom, no human voice. On-screen caption bars complement the ElevenLabs voiceover
// (merged in afterwards). It clicks through the real features (OFAC badge, QM,
// clickable metrics, evidence panel, decision-journey layer badges, examiner
// report, /data-health, rules lock) but never submits an action or runs an
// engine, so it does not mutate production data. Driven as admin@summit.com (the
// one role that can reach every page in the script).
const path = require('path')
const puppeteer = require('puppeteer-core')
const { PuppeteerScreenRecorder } = require('puppeteer-screen-recorder')
const ffmpegPath = require('@ffmpeg-installer/ffmpeg').path

const BASE = 'http://accord-alb-588286075.us-east-1.elb.amazonaws.com'
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const OUT = path.resolve(__dirname, '..', 'accord_demo.mp4')
const LOAN = 'APP-SC02-004' // OFAC Clear badge + rich decision journey + evidence
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

async function slowScrollTo(page, y, ms = 2000, steps = 26) {
  const cur = await page.evaluate(() => window.scrollY)
  for (let i = 1; i <= steps; i++) {
    await page.evaluate((v) => window.scrollTo(0, v), cur + (y - cur) * (i / steps))
    await sleep(ms / steps)
  }
}

async function go(page, url) {
  await page.goto(BASE + url, { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(1400)
}

// Click the first element (default: button) whose text matches `re`.
async function clickText(page, re, tag = 'button') {
  return page.evaluate((src, tag) => {
    const rx = new RegExp(src, 'i')
    const el = [...document.querySelectorAll(tag)].find((e) => rx.test(e.textContent || ''))
    if (el) { el.scrollIntoView({ block: 'center' }); el.click(); return true }
    return false
  }, re.source, tag)
}

// Close any open slide-over / popover (← Back, ✕, or click the overlay).
async function closePanel(page) {
  await page.evaluate(() => {
    const back = [...document.querySelectorAll('button')].find((b) => /←\s*Back/i.test(b.textContent || ''))
    const x = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').trim() === '✕')
    if (back) back.click()
    else if (x) x.click()
    else document.querySelector('.bg-black\\/30')?.click()
  })
  await sleep(700)
}

async function login(page, email) {
  await go(page, '/login')
  await caption(page, 'Log in. See exactly the loans that need your attention.')
  await page.evaluate((em) => {
    const ins = [...document.querySelectorAll('input')]
    const email = ins.find((i) => /email/i.test(i.type + i.name + i.placeholder)) || ins[0]
    const pass = ins.find((i) => i.type === 'password')
    const set = (el, v) => {
      Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set.call(el, v)
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    set(email, em)
    set(pass, 'accord2026')
  }, email)
  await sleep(1100)
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => /sign in|log in|continue/i.test(x.innerText))
    if (b) b.click()
  })
  await sleep(3500)
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
    fps: 25, ffmpeg_Path: ffmpegPath, videoFrame: { width: W, height: H }, aspectRatio: '16:9',
  })

  await go(page, '/')
  await recorder.start(OUT)

  try {
    // ═══ INTRO (3.5s) ═══
    await card(page, 'accord', 'Every lending decision, in accord.')
    await sleep(3500)
    await clearCard(page)

    // ═══ 1 — Landing hero ═══
    await caption(page, 'The biggest financial decision deserves the best underwriting.')
    await slowScrollTo(page, 600, 2500)
    await sleep(2500)

    // ═══ 2 — Login → pipeline ═══
    await login(page, 'admin@summit.com') // caption set inside login()
    await go(page, '/pipeline')
    await caption(page, 'Log in. See exactly the loans that need your attention.')
    await sleep(4500)

    // ═══ 3 — Loan header: OFAC + QM badges + clickable metrics ═══
    await go(page, '/pipeline/' + LOAN)
    await caption(page, 'Every data point on this loan is backed by a source document.')
    await sleep(5000)

    // ═══ 4 — Click credit score → evidence panel (top of page) ═══
    await caption(page, 'Click any number — see exactly where it came from.')
    await clickText(page, /Credit Score/)
    await sleep(5000)
    await closePanel(page)

    // ═══ 5 — Click OFAC badge → popover (still at top) ═══
    await caption(page, 'OFAC screening is automatic. The source document is right there.')
    await clickText(page, /OFAC/)
    await sleep(5000)
    await closePanel(page)

    // ═══ 6 — Decision Journey: three-layer rule badges (~y2780) ═══
    await caption(page, 'Every rule mapped to three layers. Federal law. Agency guidelines. Your policies.')
    await slowScrollTo(page, 2780, 3000)
    await page.evaluate(() => { document.querySelectorAll('button').forEach((b) => { if (/▼/.test(b.textContent || '')) b.click() }) })
    await sleep(900)
    await slowScrollTo(page, 3250, 1600) // a "Rule applied" row with its 🔒/📋/🔧 layer badge
    await sleep(5000)

    // ═══ 7 — Click an evidence document → extraction panel (same area) ═══
    await slowScrollTo(page, 2960, 1500)
    await caption(page, 'Click any evidence — see what Accord extracted, confidence, verified by whom.')
    await clickText(page, /📄.*indexed/) // an evidence row in the decision journey
    await sleep(5500)
    await closePanel(page)

    // ═══ 8 — Examiner report (full package) ═══
    await go(page, '/loans/' + LOAN + '/examiner-report')
    await caption(page, 'Examiners get the full package in one click.')
    await slowScrollTo(page, 500, 2500)
    await sleep(4000)

    // ═══ 9 — Data freshness ═══
    await go(page, '/data-health')
    await caption(page, 'Every data source. When it was last updated. Rule tests run automatically.')
    await slowScrollTo(page, 360, 2200)
    await sleep(4500)

    // ═══ 10 — Rules Dashboard: locked layers ═══
    await go(page, '/settings/rules')
    await caption(page, "You can't accidentally change a federal regulation.")
    await slowScrollTo(page, 1600, 3000)
    await sleep(5000)

    // ═══ CLOSING ═══
    await go(page, '/')
    await card(page, 'accord', 'Every lending decision, in accord.')
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
