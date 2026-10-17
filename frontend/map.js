// ============================================================================
// PathVoice Smart Navigation (frontend/map.js)
// Ported from src/nav.ts: geocoding, walking routes, step announcements,
// and off-route rerouting (30 m off route for 3 fixes).
// ============================================================================

// ---------- Settings ----------
const MIN_ACCURACY_M = 40;   // ignore GPS fixes less accurate than this
const OFF_ROUTE_M = 30;      // 30 m off route triggers off-route count
const OFF_ROUTE_FIXES = 3;   // reroute after 3 fixes off route
const MIN_REROUTE_GAP_S = 20;// wait at least 20s between reroutes
const ANNOUNCE_FAR_M = 50;   // "In 50 metres, turn left"
const ANNOUNCE_NOW_M = 20;   // "Turn left now"

// ---------- State ----------
let navRoute = null;
let navDest = null;
let navWatchId = null;
let navWakeLock = null;
let nextIndex = 1;
let farDoneFor = -1;
let gaveFirst = false;
let offSince = null;
let offFixes = 0;
let lastRerouteAt = 0;
let rerouting = false;
let isNavigating = false;

// ---------- Speech and Vibration ----------
function navBuzz(pattern) {
  if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
    try {
      navigator.vibrate(pattern);
    } catch {
      // Vibration not permitted or supported
    }
  }
}

function navSay(text) {
  if (typeof window.speak === 'function') {
    window.speak(text, { priority: 2, dedupeKey: `nav:${text}`, cooldown: 1000 });
  } else if (typeof speak === 'function') {
    speak(text, { priority: 2, dedupeKey: `nav:${text}`, cooldown: 1000 });
  } else if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }
}

function navSpeakQueued(text) {
  if (typeof window.speak === 'function') {
    window.speak(text, { priority: 2 });
  } else if (typeof speak === 'function') {
    speak(text, { priority: 2 });
  } else if ('speechSynthesis' in window) {
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }
}

// ---------- Text Helpers ----------
function formatDistance(m) {
  if (m < 1000) return `${Math.max(5, Math.round(m / 5) * 5)} metres`;
  return `${(m / 1000).toFixed(1)} kilometres`;
}

function describe(type, modifier, name) {
  const onto = name ? ` onto ${name}` : '';
  if (type === 'depart') return 'Start walking';
  if (type === 'arrive') return 'You have arrived';
  if (modifier === 'straight') return `Continue straight${name ? ' on ' + name : ''}`;
  if (type === 'turn' || type === 'end of road' || type === 'fork') {
    return `Turn ${modifier || 'ahead'}${onto}`;
  }
  if (type === 'roundabout' || type === 'rotary') return 'Enter the roundabout';
  if (modifier) return `Go ${modifier}${onto}`;
  return `Continue${onto}`;
}

// ---------- Geometry ----------
function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = d => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// Shortest distance in metres from a point to the route line
function distanceToRoute(lat, lon, coords) {
  if (!coords || coords.length === 0) return 0;
  if (coords.length === 1) return haversine(lat, lon, coords[0][0], coords[0][1]);

  const kx = 111320 * Math.cos((lat * Math.PI) / 180);
  const ky = 110540;
  let best = Infinity;

  for (let i = 0; i < coords.length - 1; i++) {
    const ax = (coords[i][1] - lon) * kx;
    const ay = (coords[i][0] - lat) * ky;
    const bx = (coords[i + 1][1] - lon) * kx;
    const by = (coords[i + 1][0] - lat) * ky;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    let t = len2 === 0 ? 0 : -(ax * dx + ay * dy) / len2;
    t = Math.max(0, Math.min(1, t));
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return best;
}

// ---------- Geolocation & Network ----------
function getPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Geolocation is not supported by your browser.'));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      timeout: 15000,
    });
  });
}

async function findPlace(query, lat, lon) {
  const box = `${lon - 0.5},${lat + 0.5},${lon + 0.5},${lat - 0.5}`;
  const urlLocal =
    'https://nominatim.openstreetmap.org/search?format=json&limit=1' +
    `&viewbox=${box}&q=${encodeURIComponent(query)}`;

  try {
    const res = await fetch(urlLocal);
    const data = await res.json();
    if (data && data.length > 0) {
      return {
        lat: parseFloat(data[0].lat),
        lon: parseFloat(data[0].lon),
        name: data[0].display_name,
      };
    }
  } catch (err) {
    console.warn('Local Nominatim search failed, trying global search:', err);
  }

  // Fallback if place is outside the local 0.5 deg viewbox
  const urlGlobal =
    'https://nominatim.openstreetmap.org/search?format=json&limit=1' +
    `&q=${encodeURIComponent(query)}`;
  const res = await fetch(urlGlobal);
  const data = await res.json();
  if (!data || data.length === 0) return null;
  return {
    lat: parseFloat(data[0].lat),
    lon: parseFloat(data[0].lon),
    name: data[0].display_name,
  };
}

async function getRoute(fromLat, fromLon, toLat, toLon) {
  const url =
    'https://routing.openstreetmap.de/routed-foot/route/v1/foot/' +
    `${fromLon},${fromLat};${toLon},${toLat}` +
    '?overview=full&geometries=geojson&steps=true';
  const res = await fetch(url);
  const data = await res.json();
  if (data.code !== 'Ok' || !data.routes || data.routes.length === 0) return null;

  const r = data.routes[0];
  const steps = r.legs[0].steps.map(s => ({
    text: describe(s.maneuver.type, s.maneuver.modifier, s.name),
    distance: s.distance,
    lat: s.maneuver.location[1],
    lon: s.maneuver.location[0],
  }));
  const coords = r.geometry.coordinates.map(c => [c[1], c[0]]);
  return { steps, coords, distance: r.distance, duration: r.duration };
}

// ---------- UI Updating ----------
function getUiElements() {
  return {
    navmsg: document.querySelector('#navmsg'),
    navLive: document.querySelector('#navLive'),
    navSteps: document.querySelector('#navSteps'),
    navDetails: document.querySelector('#navDetails'),
    navActiveControls: document.querySelector('#navActiveControls'),
    messageText: document.querySelector('#messageText'),
  };
}

function renderSteps() {
  const { navSteps } = getUiElements();
  if (!navSteps || !navRoute) return;
  navSteps.innerHTML = navRoute.steps
    .map(s => `<li>${s.text} (${formatDistance(s.distance)})</li>`)
    .join('');
}

function setLiveText(text) {
  const { navLive, messageText } = getUiElements();
  if (navLive) navLive.textContent = text;
  if (messageText) messageText.textContent = text;
}

function setNavMsg(text) {
  const { navmsg } = getUiElements();
  if (navmsg) navmsg.textContent = text;
}

function resetProgress() {
  nextIndex = 1;
  farDoneFor = -1;
  gaveFirst = false;
  offSince = null;
  offFixes = 0;
}

async function keepScreenOn() {
  try {
    if ('wakeLock' in navigator) {
      navWakeLock = await navigator.wakeLock.request('screen');
    }
  } catch {
    navWakeLock = null;
  }
}

// ---------- Off-Route & Rerouting ----------
function shouldReroute(offDistance) {
  const now = Date.now();
  if (offDistance <= OFF_ROUTE_M) {
    offSince = null;
    offFixes = 0;
    return false;
  }

  if (offSince === null) offSince = now;
  offFixes++;

  const enoughFixes = offFixes >= OFF_ROUTE_FIXES;
  const gapOk = now - lastRerouteAt >= MIN_REROUTE_GAP_S * 1000;

  if (enoughFixes && gapOk && !rerouting) {
    lastRerouteAt = now;
    return true;
  }
  return false;
}

async function doReroute(lat, lon) {
  if (!navDest) return;
  rerouting = true;
  navSpeakQueued('You are off route. Finding a new way.');
  setLiveText('Off route (30 m+). Calculating new walking route…');

  try {
    const r = await getRoute(lat, lon, navDest.lat, navDest.lon);
    if (r) {
      navRoute = r;
      resetProgress();
      renderSteps();
      navSpeakQueued('New route found.');
      setLiveText('New route found. Continuing guidance…');
    } else {
      navSpeakQueued('Could not find a new route.');
      setLiveText('Could not find a new route.');
    }
  } catch {
    navSpeakQueued('Could not find a new route.');
    setLiveText('Error finding a new route.');
  } finally {
    rerouting = false;
  }
}

// ---------- GPS Fix Handler ----------
async function onFix(pos) {
  if (!navRoute || rerouting) return;
  const { latitude: lat, longitude: lon, accuracy } = pos.coords;

  if (accuracy > MIN_ACCURACY_M) {
    setLiveText(`Waiting for better GPS (accuracy ${Math.round(accuracy)} m)…`);
    return;
  }

  // 1. Off-route check
  const off = distanceToRoute(lat, lon, navRoute.coords);
  if (shouldReroute(off)) {
    await doReroute(lat, lon);
    return;
  }

  // 2. Progress along the route
  const step = navRoute.steps[nextIndex];
  if (!step) {
    arrive();
    return;
  }

  const d = haversine(lat, lon, step.lat, step.lon);
  const isLast = nextIndex === navRoute.steps.length - 1;

  setLiveText(
    `Next: ${step.text} in ${Math.round(d)} m | off route: ${Math.round(off)} m | GPS ±${Math.round(accuracy)} m`
  );

  if (!gaveFirst) {
    gaveFirst = true;
    if (d > ANNOUNCE_FAR_M) {
      navSpeakQueued(`Walk ${formatDistance(d)}, then ${step.text}`);
    }
  }

  if (d <= ANNOUNCE_NOW_M) {
    if (isLast) {
      arrive();
      return;
    }
    navSpeakQueued(`${step.text} now`);
    navBuzz([200, 100, 200]);
    nextIndex++;
  } else if (d <= ANNOUNCE_FAR_M && farDoneFor !== nextIndex) {
    farDoneFor = nextIndex;
    if (isLast) {
      navSpeakQueued('Your destination is close');
    } else {
      navSpeakQueued(`In ${formatDistance(d)}, ${step.text}`);
    }
    navBuzz([100]);
  }
}

function arrive() {
  navSpeakQueued('You have arrived');
  navBuzz([300, 150, 300, 150, 300]);
  setLiveText('You have arrived.');
  stopNavigation();
}

// ---------- Public Navigation API ----------
function stopNavigation() {
  if (navWatchId !== null) {
    navigator.geolocation.clearWatch(navWatchId);
    navWatchId = null;
  }
  if (navWakeLock) {
    try {
      navWakeLock.release();
    } catch {
      // ignore
    }
    navWakeLock = null;
  }

  isNavigating = false;
  const { navActiveControls, navDetails } = getUiElements();
  if (navActiveControls) navActiveControls.style.display = 'none';

  setLiveText('Guidance stopped.');
  navSay('Guidance stopped');
}

async function startGuidance() {
  if (!navRoute) return;
  navSpeakQueued('Starting guidance');
  resetProgress();

  const { navActiveControls, navDetails } = getUiElements();
  if (navActiveControls) navActiveControls.style.display = 'block';
  if (navDetails) navDetails.hidden = false;

  setLiveText('Getting GPS signal…');
  await keepScreenOn();

  navWatchId = navigator.geolocation.watchPosition(
    pos => {
      void onFix(pos);
    },
    err => {
      setLiveText('Location error: ' + err.message);
    },
    { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 }
  );
}

async function startNavigation(query) {
  const destinationQuery = (query || '').trim();
  if (!destinationQuery) {
    setLiveText('Enter a destination first.');
    navSay('Enter a destination first.');
    return;
  }

  stopNavigation();
  navSay('Finding route');
  isNavigating = true;

  const { navDetails, navSteps, navActiveControls, messageText } = getUiElements();
  if (navSteps) navSteps.innerHTML = '';
  if (navDetails) navDetails.hidden = false;
  if (navActiveControls) navActiveControls.style.display = 'block';

  navRoute = null;
  navDest = null;

  try {
    setNavMsg('Getting your location…');
    setLiveText('Getting your location…');
    const pos = await getPosition();
    const { latitude, longitude } = pos.coords;

    setNavMsg('Searching for destination…');
    setLiveText('Searching for destination…');
    const place = await findPlace(destinationQuery, latitude, longitude);

    if (!place) {
      setNavMsg('Place not found. Try a more specific name.');
      setLiveText('Place not found. Try a more specific name.');
      navSay('Place not found');
      isNavigating = false;
      if (navActiveControls) navActiveControls.style.display = 'none';
      return;
    }

    setNavMsg(`Found ${place.name}. Getting walking route…`);
    setLiveText('Getting walking route…');
    const r = await getRoute(latitude, longitude, place.lat, place.lon);

    if (!r) {
      setNavMsg('No walking route found.');
      setLiveText('No walking route found.');
      navSay('No walking route found');
      isNavigating = false;
      if (navActiveControls) navActiveControls.style.display = 'none';
      return;
    }

    navRoute = r;
    navDest = place;
    resetProgress();

    const mins = Math.max(1, Math.round(r.duration / 60));
    setNavMsg(`To: ${place.name} | ${formatDistance(r.distance)}, ~${mins} min`);
    renderSteps();

    navSay(`Route found. ${formatDistance(r.distance)}, about ${mins} minutes. Starting guidance.`);
    await startGuidance();

  } catch (err) {
    const errorMsg = 'Navigation error: ' + (err.message || String(err));
    setNavMsg(errorMsg);
    setLiveText(errorMsg);
    navSay('Could not complete navigation');
    isNavigating = false;
    if (navActiveControls) navActiveControls.style.display = 'none';
  }
}

function bindNavControls() {
  const stopBtn = document.querySelector('#stopNavBtn');
  if (stopBtn && !stopBtn.dataset.bound) {
    stopBtn.dataset.bound = 'true';
    stopBtn.addEventListener('click', stopNavigation);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bindNavControls);
} else {
  bindNavControls();
}

// Export to window for app.js and global usage
window.startNavigation = startNavigation;
window.stopNavigation = stopNavigation;
window.isNavigating = () => isNavigating;
