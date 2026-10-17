type Target = { lat: number; lon: number; toLat: number; toLon: number; at: number }

let target: Target | null = null
let heading: number | null = null

const toRad = (d: number) => (d * Math.PI) / 180
const toDeg = (r: number) => (r * 180) / Math.PI

// Direction from point 1 to point 2, in degrees from north
function bearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const dLon = toRad(lon2 - lon1)
    const y = Math.sin(dLon) * Math.cos(toRad(lat2))
    const x =
        Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
        Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(dLon)
    return (toDeg(Math.atan2(y, x)) + 360) % 360
}

// Android: compass direction the back of the phone is facing
function compassHeading(alpha: number, beta: number, gamma: number): number {
    const x = toRad(beta || 0)
    const y = toRad(gamma || 0)
    const z = toRad(alpha || 0)
    const cY = Math.cos(y)
    const cZ = Math.cos(z)
    const sX = Math.sin(x)
    const sY = Math.sin(y)
    const sZ = Math.sin(z)
    const vx = -cZ * sY - sZ * sX * cY
    const vy = -sZ * sY + cZ * sX * cY
    let h = Math.atan(vx / vy)
    if (vy < 0) h += Math.PI
    else if (vx < 0) h += 2 * Math.PI
    return toDeg(h)
}

// Smooths the shaky compass reading
function smooth(prev: number, next: number): number {
    const diff = ((next - prev + 540) % 360) - 180
    return (prev + diff * 0.2 + 360) % 360
}

export function setupCompass() {
    document.body.insertAdjacentHTML(
        'beforeend',
        `<div id="arrow" style="position:fixed;top:12px;right:12px;width:110px;
        background:rgba(0,0,0,0.7);color:white;border-radius:16px;padding:8px;
        text-align:center;display:none;z-index:1000">
       <div id="arrowIcon" style="font-size:64px;line-height:70px">&#8593;</div>
       <div id="arrowHint" style="font-size:18px"></div>
     </div>`
    )
    const arrow = document.querySelector<HTMLDivElement>('#arrow')!
    const icon = document.querySelector<HTMLDivElement>('#arrowIcon')!
    const hint = document.querySelector<HTMLDivElement>('#arrowHint')!

    function update(h: number) {
        heading = heading === null ? h : smooth(heading, h)
    }

    function refresh() {
        if (!target || heading === null || Date.now() - target.at > 5000) {
            arrow.style.display = 'none'
            return
        }
        const brg = bearing(target.lat, target.lon, target.toLat, target.toLon)
        const rel = ((brg - heading + 540) % 360) - 180 // -180 to 180
        arrow.style.display = 'block'
        icon.style.transform = `rotate(${rel}deg)`
        hint.textContent = Math.abs(rel) < 20 ? 'Straight' : rel > 0 ? 'Turn right' : 'Turn left'
    }

    // Position updates sent by the navigation code
    window.addEventListener('nav-target', (e: Event) => {
        const d = (e as CustomEvent).detail
        target = { lat: d.lat, lon: d.lon, toLat: d.toLat, toLon: d.toLon, at: Date.now() }
        refresh()
    })

    // Compass readings
    window.addEventListener('deviceorientationabsolute', (e: any) => {
        if (e.alpha == null) return
        update(compassHeading(e.alpha, e.beta, e.gamma))
        refresh()
    })
    window.addEventListener('deviceorientation', (e: any) => {
        if (typeof e.webkitCompassHeading === 'number') {
            update(e.webkitCompassHeading) // iPhone
            refresh()
        }
    })

    // iPhone asks for permission, and only after a tap
    document.addEventListener(
        'click',
        () => {
            const req = (DeviceOrientationEvent as any).requestPermission
            if (typeof req === 'function') {
                req.call(DeviceOrientationEvent).catch(() => { })
            }
        },
        { once: true }
    )

    setInterval(refresh, 500)
}