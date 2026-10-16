// ---------- Settings you can tune ----------
const MIN_ACCURACY_M = 40 // ignore GPS fixes less accurate than this
const OFF_ROUTE_M = 25 // how far from the route counts as "off route"
const OFF_ROUTE_SECONDS = 5 // must stay off route this long...
const OFF_ROUTE_FIXES = 3 // ...and for at least this many GPS readings
const MIN_REROUTE_GAP_S = 20 // wait at least this long between reroutes
const ANNOUNCE_FAR_M = 50 // "In 50 metres, turn left"
const ANNOUNCE_NOW_M = 20 // "Turn left now"

type Step = { text: string; distance: number; lat: number; lon: number }
type Route = {
    steps: Step[]
    coords: [number, number][] // [lat, lon] points along the route
    distance: number
    duration: number
}
type Place = { lat: number; lon: number; name: string }

// ---------- Voice and vibration ----------
function say(text: string) {
    // Cancels anything being spoken. Used for one-off messages.
    if (!('speechSynthesis' in window)) return
    speechSynthesis.cancel()
    speechSynthesis.speak(new SpeechSynthesisUtterance(text))
}

function speakQueued(text: string) {
    // Waits its turn, so it never cuts off an obstacle warning
    if (!('speechSynthesis' in window)) return
    speechSynthesis.speak(new SpeechSynthesisUtterance(text))
}

function buzz(pattern: number[]) {
    if ('vibrate' in navigator) navigator.vibrate(pattern)
}

// ---------- Text helpers ----------
function formatDistance(m: number): string {
    if (m < 1000) return `${Math.max(5, Math.round(m / 5) * 5)} metres`
    return `${(m / 1000).toFixed(1)} kilometres`
}

function describe(type: string, modifier: string | undefined, name: string): string {
    const onto = name ? ` onto ${name}` : ''
    if (type === 'depart') return 'Start walking'
    if (type === 'arrive') return 'You have arrived'
    if (modifier === 'straight') return `Continue straight${name ? ' on ' + name : ''}`
    if (type === 'turn' || type === 'end of road' || type === 'fork') {
        return `Turn ${modifier ?? 'ahead'}${onto}`
    }
    if (type === 'roundabout' || type === 'rotary') return 'Enter the roundabout'
    if (modifier) return `Go ${modifier}${onto}`
    return `Continue${onto}`
}

// ---------- Geometry ----------
function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6371000
    const toRad = (d: number) => (d * Math.PI) / 180
    const dLat = toRad(lat2 - lat1)
    const dLon = toRad(lon2 - lon1)
    const a =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
    return 2 * R * Math.asin(Math.sqrt(a))
}

// Shortest distance in metres from a point to the route line
function distanceToRoute(lat: number, lon: number, coords: [number, number][]): number {
    const kx = 111320 * Math.cos((lat * Math.PI) / 180)
    const ky = 110540
    let best = Infinity
    for (let i = 0; i < coords.length - 1; i++) {
        const ax = (coords[i][1] - lon) * kx
        const ay = (coords[i][0] - lat) * ky
        const bx = (coords[i + 1][1] - lon) * kx
        const by = (coords[i + 1][0] - lat) * ky
        const dx = bx - ax
        const dy = by - ay
        const len2 = dx * dx + dy * dy
        let t = len2 === 0 ? 0 : -(ax * dx + ay * dy) / len2
        t = Math.max(0, Math.min(1, t))
        best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy))
    }
    return best
}

// ---------- Network: location, place search, route ----------
function getPosition(): Promise<GeolocationPosition> {
    return new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 15000,
        })
    })
}

async function findPlace(query: string, lat: number, lon: number): Promise<Place | null> {
    const box = `${lon - 0.5},${lat + 0.5},${lon + 0.5},${lat - 0.5}`
    const url =
        'https://nominatim.openstreetmap.org/search?format=json&limit=1' +
        `&viewbox=${box}&q=${encodeURIComponent(query)}`
    const res = await fetch(url)
    const data = await res.json()
    if (!data.length) return null
    return {
        lat: parseFloat(data[0].lat),
        lon: parseFloat(data[0].lon),
        name: data[0].display_name as string,
    }
}

async function getRoute(
    fromLat: number,
    fromLon: number,
    toLat: number,
    toLon: number
): Promise<Route | null> {
    const url =
        'https://routing.openstreetmap.de/routed-foot/route/v1/foot/' +
        `${fromLon},${fromLat};${toLon},${toLat}` +
        '?overview=full&geometries=geojson&steps=true'
    const res = await fetch(url)
    const data = await res.json()
    if (data.code !== 'Ok') return null
    const r = data.routes[0]
    const steps: Step[] = r.legs[0].steps.map((s: any) => ({
        text: describe(s.maneuver.type, s.maneuver.modifier, s.name),
        distance: s.distance,
        lat: s.maneuver.location[1],
        lon: s.maneuver.location[0],
    }))
    const coords: [number, number][] = r.geometry.coordinates.map((c: number[]) => [
        c[1],
        c[0],
    ])
    return { steps, coords, distance: r.distance, duration: r.duration }
}

// ---------- The navigation panel ----------
export function setupNavigation() {
    const box = document.querySelector<HTMLDivElement>('#nav')!
    box.innerHTML = `
    <input id="dest" placeholder="Where to? e.g. Cubbon Park"
      style="font-size:20px;padding:10px;width:65%">
    <button id="go" style="font-size:20px;padding:10px">Get route</button>
    <div style="margin:8px 0">
      <button id="guide" style="display:none;font-size:22px;padding:14px">Start guidance</button>
      <button id="stop" style="display:none;font-size:22px;padding:14px">Stop guidance</button>
    </div>
    <p id="navmsg"></p>
    <p id="live" style="font-size:20px;font-weight:bold"></p>
    <ol id="steps" style="text-align:left"></ol>
  `
    const input = document.querySelector<HTMLInputElement>('#dest')!
    const go = document.querySelector<HTMLButtonElement>('#go')!
    const guideBtn = document.querySelector<HTMLButtonElement>('#guide')!
    const stopBtn = document.querySelector<HTMLButtonElement>('#stop')!
    const navmsg = document.querySelector<HTMLParagraphElement>('#navmsg')!
    const live = document.querySelector<HTMLParagraphElement>('#live')!
    const stepsEl = document.querySelector<HTMLOListElement>('#steps')!

    // State
    let route: Route | null = null
    let dest: Place | null = null
    let watchId: number | null = null
    let wakeLock: any = null
    let nextIndex = 1 // index of the next turn to announce
    let farDoneFor = -1
    let gaveFirst = false
    let offSince: number | null = null
    let offFixes = 0
    let lastRerouteAt = 0
    let rerouting = false

    function renderSteps() {
        if (!route) return
        stepsEl.innerHTML = route.steps
            .map((s) => `<li>${s.text} (${formatDistance(s.distance)})</li>`)
            .join('')
    }

    function resetProgress() {
        nextIndex = 1
        farDoneFor = -1
        gaveFirst = false
        offSince = null
        offFixes = 0
    }

    function stopGuidance() {
        if (watchId !== null) navigator.geolocation.clearWatch(watchId)
        watchId = null
        if (wakeLock) {
            try {
                wakeLock.release()
            } catch {
                /* ignore */
            }
            wakeLock = null
        }
        stopBtn.style.display = 'none'
        if (route) guideBtn.style.display = 'inline-block'
    }

    function arrive() {
        speakQueued('You have arrived')
        buzz([300, 150, 300, 150, 300])
        live.textContent = 'You have arrived.'
        stopGuidance()
    }

    // Decide whether we are truly off route (not just GPS noise)
    function shouldReroute(offDistance: number): boolean {
        const now = Date.now()
        if (offDistance <= OFF_ROUTE_M) {
            offSince = null
            offFixes = 0
            return false
        }
        if (offSince === null) offSince = now
        offFixes++
        const longEnough = now - offSince >= OFF_ROUTE_SECONDS * 1000
        const enoughFixes = offFixes >= OFF_ROUTE_FIXES
        const gapOk = now - lastRerouteAt >= MIN_REROUTE_GAP_S * 1000
        if (longEnough && enoughFixes && gapOk && !rerouting) {
            lastRerouteAt = now
            return true
        }
        return false
    }

    async function doReroute(lat: number, lon: number) {
        if (!dest) return
        rerouting = true
        speakQueued('You are off route. Finding a new way.')
        try {
            const r = await getRoute(lat, lon, dest.lat, dest.lon)
            if (r) {
                route = r
                resetProgress()
                renderSteps()
                speakQueued('New route found.')
            } else {
                speakQueued('Could not find a new route.')
            }
        } catch {
            speakQueued('Could not find a new route.')
        } finally {
            rerouting = false
        }
    }

    async function onFix(pos: GeolocationPosition) {
        if (!route || rerouting) return
        const { latitude: lat, longitude: lon, accuracy } = pos.coords

        if (accuracy > MIN_ACCURACY_M) {
            live.textContent = `Waiting for better GPS (accuracy ${Math.round(accuracy)} m)...`
            return
        }

        // 1. Are we off the route?
        const off = distanceToRoute(lat, lon, route.coords)
        if (shouldReroute(off)) {
            await doReroute(lat, lon)
            return
        }

        // 2. Progress along the route
        const step = route.steps[nextIndex]
        if (!step) {
            arrive()
            return
        }
        const d = haversine(lat, lon, step.lat, step.lon)
        const isLast = nextIndex === route.steps.length - 1
        live.textContent =
            `Next: ${step.text} in ${Math.round(d)} m | off route: ${Math.round(off)} m | ` +
            `GPS +/-${Math.round(accuracy)} m`

        if (!gaveFirst) {
            gaveFirst = true
            if (d > ANNOUNCE_FAR_M) {
                speakQueued(`Walk ${formatDistance(d)}, then ${step.text}`)
            }
        }

        if (d <= ANNOUNCE_NOW_M) {
            if (isLast) {
                arrive()
                return
            }
            speakQueued(`${step.text} now`)
            buzz([200, 100, 200])
            nextIndex++
        } else if (d <= ANNOUNCE_FAR_M && farDoneFor !== nextIndex) {
            farDoneFor = nextIndex
            if (isLast) {
                speakQueued('Your destination is close')
            } else {
                speakQueued(`In ${formatDistance(d)}, ${step.text}`)
            }
            buzz([100])
        }
    }

    async function keepScreenOn() {
        try {
            wakeLock = await (navigator as any).wakeLock?.request('screen')
        } catch {
            wakeLock = null
        }
    }

    // ----- Buttons -----
    go.addEventListener('click', async () => {
        const query = input.value.trim()
        if (!query) {
            navmsg.textContent = 'Type a destination first.'
            return
        }
        stopGuidance()
        say('Finding route') // also unlocks speech on iPhone
        go.disabled = true
        guideBtn.style.display = 'none'
        stepsEl.innerHTML = ''
        live.textContent = ''
        route = null
        try {
            navmsg.textContent = 'Getting your location...'
            const pos = await getPosition()
            const { latitude, longitude } = pos.coords

            navmsg.textContent = 'Searching for the place...'
            const place = await findPlace(query, latitude, longitude)
            if (!place) {
                navmsg.textContent = 'Place not found. Try a more specific name.'
                say('Place not found')
                return
            }

            navmsg.textContent = 'Getting walking route...'
            const r = await getRoute(latitude, longitude, place.lat, place.lon)
            if (!r) {
                navmsg.textContent = 'No walking route found.'
                say('No walking route found')
                return
            }

            route = r
            dest = place
            resetProgress()
            const mins = Math.max(1, Math.round(r.duration / 60))
            navmsg.textContent =
                `To: ${place.name} | ${formatDistance(r.distance)}, about ${mins} min`
            renderSteps()
            guideBtn.style.display = 'inline-block'
            say(
                `Route found. ${formatDistance(r.distance)}, about ${mins} minutes. ` +
                'Press Start guidance when you are ready.'
            )
        } catch (err) {
            navmsg.textContent = 'Error: ' + err
        } finally {
            go.disabled = false
        }
    })

    guideBtn.addEventListener('click', async () => {
        if (!route) return
        speakQueued('Starting guidance') // unlocks speech from a button press
        resetProgress()
        guideBtn.style.display = 'none'
        stopBtn.style.display = 'inline-block'
        live.textContent = 'Getting GPS signal...'
        await keepScreenOn()
        watchId = navigator.geolocation.watchPosition(
            (pos) => {
                void onFix(pos)
            },
            (err) => {
                live.textContent = 'Location error: ' + err.message
            },
            { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 }
        )
    })

    stopBtn.addEventListener('click', () => {
        stopGuidance()
        live.textContent = 'Guidance stopped.'
        say('Guidance stopped')
    })
}