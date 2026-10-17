import { setupVoice } from './voice'
import { setupNavigation } from './nav'
import { setupCompass } from './compass'
import '@tensorflow/tfjs'
import * as cocoSsd from '@tensorflow-models/coco-ssd'

// ---------- Settings you can tune ----------
const DANGER_M = 1.5
const WARNING_M = 3
const COOLDOWN_MS = 4000

const REAL_HEIGHT_M: Record<string, number> = {
  person: 1.7,
  chair: 0.9,
  bench: 0.9,
  couch: 0.9,
  bicycle: 1.0,
  motorcycle: 1.1,
  car: 1.5,
  bus: 3.0,
  truck: 3.0,
  dog: 0.5,
  bottle: 0.25,
  'cell phone': 0.15,
  laptop: 0.25,
  tv: 0.5,
  backpack: 0.45,
  'potted plant': 0.5,
  'dining table': 0.75,
}

// ---------- Position and distance ----------
function zoneOf(centerX: number, frameWidth: number): string {
  const r = centerX / frameWidth
  if (r < 0.35) return 'left'
  if (r > 0.65) return 'right'
  return 'ahead'
}

function distanceM(
  label: string,
  boxHeightPx: number,
  frameW: number,
  frameH: number
): number | null {
  const real = REAL_HEIGHT_M[label]
  if (!real || boxHeightPx <= 0) return null
  const focalPx = 0.73 * Math.max(frameW, frameH)
  const d = (real * focalPx) / boxHeightPx
  return Math.min(Math.max(d, 0.3), 20)
}

// ---------- Alerts: voice, vibration, beeps ----------
type Band = 'danger' | 'warning'

function bandOf(d: number): Band | null {
  if (d < DANGER_M) return 'danger'
  if (d < WARNING_M) return 'warning'
  return null
}

let audioCtx: AudioContext | null = null

function unlockAudio() {
  // Must be called from a button click so phones allow sound
  try {
    audioCtx = new AudioContext()
  } catch {
    audioCtx = null
  }
  if ('speechSynthesis' in window) {
    speechSynthesis.speak(new SpeechSynthesisUtterance('Starting SightPath'))
  }
}

function speak(text: string, urgent: boolean) {
  if (!('speechSynthesis' in window)) return
  if (urgent) speechSynthesis.cancel()
  else if (speechSynthesis.speaking) return
  speechSynthesis.speak(new SpeechSynthesisUtterance(text))
}

function beep(times: number) {
  if (!audioCtx) return
  for (let i = 0; i < times; i++) {
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    osc.frequency.value = 880
    gain.gain.value = 0.2
    osc.connect(gain)
    gain.connect(audioCtx.destination)
    const t = audioCtx.currentTime + i * 0.25
    osc.start(t)
    osc.stop(t + 0.12)
  }
}

function buzz(band: Band) {
  const pattern = band === 'danger' ? [200, 100, 200, 100, 200] : [150, 100, 150]
  if ('vibrate' in navigator) {
    navigator.vibrate(pattern)
  } else {
    beep(band === 'danger' ? 3 : 2)
  }
}

const lastAlert = new Map<string, { time: number; band: Band }>()

type Item = { label: string; zone: string; d: number }

function maybeAlert(items: Item[]) {
  // Look at the nearest object that is close enough to matter
  const near = items
    .filter((i) => bandOf(i.d) !== null)
    .sort((a, b) => a.d - b.d)[0]
  if (!near) return

  const band = bandOf(near.d)!
  const key = near.label + '-' + near.zone
  const last = lastAlert.get(key)
  const now = Date.now()
  const worse = last && last.band === 'warning' && band === 'danger'

  if (last && now - last.time < COOLDOWN_MS && !worse) return

  lastAlert.set(key, { time: now, band })
  const where = near.zone === 'ahead' ? 'ahead' : 'on your ' + near.zone
  const metres = Math.round(near.d * 10) / 10
  speak(`${near.label} ${where}, ${metres} metres`, band === 'danger')
  buzz(band)
}

// ---------- Page ----------
const app = document.querySelector<HTMLDivElement>('#app')!

app.innerHTML = `
  <h1>SightPath</h1>
  <div id="nav"></div>
  <button id="start" style="font-size:24px;padding:16px">Start camera</button>
  <p id="msg"></p>
  <div style="position:relative;width:100%;max-width:640px">
    <video id="video" autoplay playsinline muted style="width:100%;display:block"></video>
    <canvas id="overlay" style="position:absolute;left:0;top:0;width:100%;height:100%"></canvas>
  </div>
  <pre id="list" style="font-size:20px;text-align:left"></pre>
`

const button = document.querySelector<HTMLButtonElement>('#start')!
const video = document.querySelector<HTMLVideoElement>('#video')!
const canvas = document.querySelector<HTMLCanvasElement>('#overlay')!
const msg = document.querySelector<HTMLParagraphElement>('#msg')!
const list = document.querySelector<HTMLPreElement>('#list')!
const ctx = canvas.getContext('2d')!

async function start() {
  button.disabled = true
  unlockAudio()
  try {
    msg.textContent = 'Starting camera...'
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' },
      audio: false,
    })
    video.srcObject = stream
    await video.play()

    msg.textContent = 'Loading AI model (first time takes a few seconds)...'
    const model = await cocoSsd.load()
    msg.textContent = 'Detecting objects...'

    canvas.width = video.videoWidth
    canvas.height = video.videoHeight

    const loop = async () => {
      const predictions = await model.detect(video)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.lineWidth = 4
      ctx.font = '24px sans-serif'

      const items: Item[] = []
      const lines: { d: number; text: string }[] = []

      for (const p of predictions) {
        const [x, y, w, h] = p.bbox
        const zone = zoneOf(x + w / 2, canvas.width)
        const d = distanceM(p.class, h, canvas.width, canvas.height)
        const distText = d === null ? '' : ` ${d.toFixed(1)}m`
        const label = `${p.class} ${zone}${distText}`

        const band = d === null ? null : bandOf(d)
        const color = band === 'danger' ? 'red' : band === 'warning' ? 'orange' : 'lime'
        ctx.strokeStyle = color
        ctx.strokeRect(x, y, w, h)
        ctx.fillStyle = color
        ctx.fillText(label, x + 4, y > 28 ? y - 6 : y + 24)

        lines.push({ d: d ?? 99, text: label })
        if (d !== null) items.push({ label: p.class, zone, d })
      }

      lines.sort((a, b) => a.d - b.d)
      list.textContent = lines.map((l) => l.text).join('\n')

      maybeAlert(items)
      requestAnimationFrame(loop)
    }
    loop()
  } catch (err) {
    msg.textContent = 'Error: ' + err
    button.disabled = false
  }
}

button.addEventListener('click', start)
setupNavigation()
setupVoice()
setupCompass()