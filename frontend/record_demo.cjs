// Records a ~60s captioned product walkthrough of the LIVE Accord app to an .mp4
// (silent — the ElevenLabs voiceover is muxed in afterwards). No intro card: the
// recorder starts on the already-loaded /login page so frame 0 is real content,
// no black opening. It clicks through the real features (clickable metrics →
// evidence panels, decision-journey layer badges, examiner report) but never
// submits an action, so it does not mutate production data.
//
// Scenes (target ~60s, to mux onto a ~55-65s voiceover with a plain -c:v copy):
//   1  login (underwriter) → pipeline
//   2  loan header — OFAC + QM badges + 4 clickable metrics
//   2a click credit score → evidence panel (bureau pull)
//   2b click DTI → evidence panel (income document)
//   2c Decision Journey — Federal / Agency / Your-Policy rule badges + citation
//   3  re-login (compliance) → examiner report + slow scroll
//   4  back to /pipeline
const path = require('path')
const puppeteer = require('puppeteer-core')
const { PuppeteerScreenRecorder } = require('puppeteer-screen-recorder')
const ffmpegPath = require('@ffmpeg-installer/ffmpeg').path

const BASE = 'http://accord-alb-588286075.us-east-1.elb.amazonaws.com'
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const OUT = path.resolve(__dirname, '..', 'accord_demo.mp4')
const LOAN = 'APP-SC30-004' // Wayne Hart — OFAC + QM badges, all 4 metrics, full journey
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

async function go(page, url) {
  await page.goto(BASE + url, { waitUntil: 'networkidle2', timeout: 60000 })
  await sleep(1300)
}

// ── existing login pattern (unchanged) ──
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

// ── action helpers ──
async function clickMetric(page, label) {
  return page.evaluate((label) => {
    const rx = new RegExp('^\\s*' + label, 'i')
    const b = [...document.querySelectorAll('button')].find((x) => rx.test((x.textContent || '').trim()) && /↗/.test(x.textContent || ''))
    if (b) { b.scrollIntoView({ block: 'center' }); b.click(); return true }
    return false
  }, label)
}
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
async function scrollToDecisionJourney(page) {
  await page.evaluate(() => {
    const dj = [...document.querySelectorAll('div')].find((e) => (e.textContent || '').trim() === 'Decision Journey')
    if (dj) dj.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
  await sleep(900)
}
async function clickFirstRule(page) {
  // expand the first collapsed decision to reveal its Rule-applied layer badge
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => /▼/.test(x.textContent || ''))
    if (b) { b.scrollIntoView({ block: 'center' }); b.click() }
  })
  await sleep(900)
  await page.evaluate(() => {
    const ra = [...document.querySelectorAll('div')].find((e) => (e.textContent || '').trim() === 'Rule applied')
    if (ra) ra.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
  await sleep(700)
}
// The examiner button opens a new tab (window.open) the recorder can't follow —
// navigate the same page to the report URL instead (renders the same view).
async function openExaminerReport(page, loan) {
  await go(page, '/loans/' + loan + '/examiner-report')
}
async function slowScrollReport(page) {
  for (let i = 0; i < 3; i++) {
    await page.evaluate(() => window.scrollBy({ top: 400, behavior: 'smooth' }))
    await sleep(1500)
  }
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

  // Land on /login first so frame 0 is real content (no black opening).
  await go(page, '/login')
  await recorder.start(OUT)

  try {
    // ═══ SCENE 1 — Queue (login → pipeline) ═══
    await login(page, 'underwriter@summit.com')
    await go(page, '/pipeline')
    await caption(page, 'Just the loans that need your attention.')
    await sleep(3000)

    // ═══ SCENE 2 — Loan header ═══
    await go(page, '/pipeline/' + LOAN)
    await caption(page, 'Every number on this screen is sourced.')
    await sleep(5000)

    // ═══ 2a — Click credit score → evidence panel ═══
    await caption(page, "Click the credit score — there's the bureau pull.")
    await clickMetric(page, 'Credit Score')
    await sleep(5000)
    await closePanel(page)

    // ═══ 2b — Click DTI → evidence panel ═══
    await caption(page, "Click the DTI — there's the income document.")
    await clickMetric(page, 'DTI')
    await sleep(5000)
    await closePanel(page)

    // ═══ 2c — Decision Journey: layer badges + rule citation ═══
    await caption(page, 'Every rule — federal law, agency guidelines, or your own policy.')
    await scrollToDecisionJourney(page)
    await sleep(3500)
    await clickFirstRule(page)
    await caption(page, 'Click any rule — see the regulation it came from.')
    await sleep(4000)

    // ═══ SCENE 3 — Examiner report (as compliance) ═══
    // Sign out first — an authenticated session redirects /login to the dashboard.
    await page.evaluate(() => { try { localStorage.clear() } catch (e) {} })
    await login(page, 'compliance@summit.com')
    await go(page, '/pipeline/' + LOAN)
    await caption(page, 'Examiner asks why? The full package — one click.')
    await sleep(2500)
    await openExaminerReport(page, LOAN)
    await sleep(1800)
    await slowScrollReport(page)
    await sleep(2500)

    // ═══ SCENE 4 — Close ═══
    await go(page, '/pipeline')
    await caption(page, 'Every lending decision — in accord.')
    await sleep(6000)
  } catch (e) {
    console.error('BEAT ERROR:', e.message)
  } finally {
    await recorder.stop()
    await browser.close()
  }
  console.log('Saved →', OUT)
}

main()
