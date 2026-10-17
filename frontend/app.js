
const video = document.querySelector('#cameraVideo');
const canvas = document.querySelector('#overlayCanvas');
const ctx = canvas.getContext('2d');
const startButton = document.querySelector('#startButton');
const voiceButton = document.querySelector('#voiceButton');
const testVoiceButton = document.querySelector('#testVoiceButton');
const voiceStatus = document.querySelector('#voiceStatus');
const manualCommandForm = document.querySelector('#manualCommandForm');
const manualCommandInput = document.querySelector('#manualCommandInput');
const destinationForm = document.querySelector('#destinationForm');
const destinationInput = document.querySelector('#destinationInput');

const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;

let recognition = null;
let listening = false;

const badge = document.querySelector('#connectionBadge');
const statusText = document.querySelector('#statusText');
const statsText = document.querySelector('#statsText');
const messageText = document.querySelector('#messageText');
const placeholder = document.querySelector('#cameraPlaceholder');

let stream = null;
let socket = null;
let running = false;
let navigationNoticeSpoken = false;
let speechAvailable = false;
let currentUtterance = null;
let currentSpeechPriority = 0;
let speechWatchdog = null;
let waitingForReply = false;
let framesSent = 0;
let lastFrameSentAt = 0;
let frameTimer = null;

// Spoken object-alert settings
const OBJECT_REAPPEAR_DELAY = 5000;
const OBJECT_SPEECH_COOLDOWN = 10000;

// Tracks each object category independently.
const objectSpeechState = new Map();
const speechQueue = [];
const queuedSpeechKeys = new Set();
const recentSpeechKeys = new Map();
let speechSequence = 0;
const MAX_SPEECH_QUEUE = 12;
const SPEECH_REPEAT_COOLDOWN = 2500;
const SPEECH_START_TIMEOUT = 8000;

function setVoiceStatus(text) {
  voiceStatus.textContent = text;
  voiceStatus.classList.toggle('unavailable', text === 'Voice unavailable');
}

function initializeSpeech() {
  speechAvailable = Boolean(
    window.speechSynthesis &&
    typeof window.speechSynthesis.speak === 'function' &&
    typeof window.SpeechSynthesisUtterance === 'function'
  );

  if (!speechAvailable) {
    setVoiceStatus('Voice unavailable');
    return false;
  }

  if (!currentUtterance) {
    setVoiceStatus('Voice ready');
  }
  return true;
}

function selectSpeechVoice() {
  let voices = [];
  try {
    voices = window.speechSynthesis.getVoices();
  } catch {
    return null;
  }
  return (
    voices.find(voice => voice.lang?.toLowerCase() === 'en-in') ||
    voices.find(voice => voice.lang?.toLowerCase().startsWith('en-')) ||
    voices.find(voice => voice.lang?.toLowerCase() === 'en') ||
    null
  );
}

function processSpeechQueue() {
  if (currentUtterance || speechQueue.length === 0) return;
  if (!initializeSpeech()) return;

  const item = speechQueue.shift();
  queuedSpeechKeys.delete(item.key);

  let utterance;
  try {
    utterance = new window.SpeechSynthesisUtterance(item.text);
  } catch (error) {
    setVoiceStatus('Voice unavailable');
    messageText.textContent =
      `Could not prepare voice output: ${error.message || String(error)}`;
    processSpeechQueue();
    return;
  }

  const voice = selectSpeechVoice();
  utterance.lang = voice?.lang || 'en-IN';
  if (voice) utterance.voice = voice;
  utterance.rate = 1;
  utterance.pitch = 1;

  currentUtterance = utterance;
  currentSpeechPriority = item.priority;
  utterance.onstart = () => {
    if (currentUtterance !== utterance) return;
    window.clearTimeout(speechWatchdog);
    speechWatchdog = window.setTimeout(
      () => failSpeech(utterance, 'speech timed out'),
      Math.min(60000, Math.max(10000, item.text.length * 120))
    );
    setVoiceStatus('Speaking');
  };
  utterance.onend = () => {
    if (currentUtterance !== utterance) return;
    window.clearTimeout(speechWatchdog);
    speechWatchdog = null;
    currentUtterance = null;
    currentSpeechPriority = 0;
    if (speechAvailable) setVoiceStatus('Voice ready');
    processSpeechQueue();
  };
  utterance.onerror = event => {
    failSpeech(utterance, event.error || 'unknown error');
  };

  speechWatchdog = window.setTimeout(
    () => failSpeech(utterance, 'speech did not start'),
    SPEECH_START_TIMEOUT
  );
  try {
    if (window.speechSynthesis.paused) {
      window.speechSynthesis.resume();
    }
    window.speechSynthesis.speak(utterance);
  } catch (error) {
    window.clearTimeout(speechWatchdog);
    speechWatchdog = null;
    currentUtterance = null;
    currentSpeechPriority = 0;
    setVoiceStatus('Voice unavailable');
    messageText.textContent =
      `Could not start voice output: ${error.message || String(error)}`;
    processSpeechQueue();
  }
}

function failSpeech(utterance, reason) {
  if (currentUtterance !== utterance) return;
  window.clearTimeout(speechWatchdog);
  speechWatchdog = null;
  currentUtterance = null;
  currentSpeechPriority = 0;
  setVoiceStatus('Voice unavailable');
  messageText.textContent =
    `Voice output failed (${reason}). Check device volume and browser audio settings, then use Test Voice to retry.`;
  processSpeechQueue();
}

function speak(text, {
  priority = 1,
  dedupeKey,
  cooldown = SPEECH_REPEAT_COOLDOWN
} = {}) {
  const message = typeof text === 'string' ? text.trim() : '';
  if (!message) return;
  if (!initializeSpeech()) {
    messageText.textContent =
      'Voice output is unavailable in this browser. Check browser support and audio settings.';
    return;
  }

  const key = dedupeKey || message.toLowerCase();
  const now = Date.now();
  const lastQueued = recentSpeechKeys.get(key) || 0;
  if (now - lastQueued < cooldown || queuedSpeechKeys.has(key)) return;

  if (speechQueue.length >= MAX_SPEECH_QUEUE) {
    const lowestPriority = Math.min(
      ...speechQueue.map(item => item.priority)
    );
    const discardIndex = speechQueue.findIndex(
      item => item.priority === lowestPriority
    );
    if (priority <= lowestPriority || discardIndex < 0) return;
    const [discarded] = speechQueue.splice(discardIndex, 1);
    queuedSpeechKeys.delete(discarded.key);
  }

  speechQueue.push({
    text: message,
    key,
    priority,
    sequence: speechSequence++,
  });
  speechQueue.sort(
    (left, right) =>
      right.priority - left.priority ||
      left.sequence - right.sequence
  );
  queuedSpeechKeys.add(key);
  recentSpeechKeys.set(key, now);
  if (
    currentUtterance &&
    priority >= 3 &&
    currentSpeechPriority < 3
  ) {
    const interruptedUtterance = currentUtterance;
    currentUtterance = null;
    currentSpeechPriority = 0;
    window.clearTimeout(speechWatchdog);
    speechWatchdog = null;
    interruptedUtterance.onend = null;
    interruptedUtterance.onerror = null;
    try {
      window.speechSynthesis.cancel();
    } catch {
      setVoiceStatus('Voice unavailable');
    }
  }
  processSpeechQueue();
}

if (window.speechSynthesis?.addEventListener) {
  window.speechSynthesis.addEventListener('voiceschanged', () => {
    if (!currentUtterance && speechAvailable) {
      setVoiceStatus('Voice ready');
    }
  });
}
initializeSpeech();

// Announces eligible object categories without repeating
// continuously visible objects.
function announceDetections(detections) {
  if (!detections?.length) {
    return;
  }

  const now = Date.now();
  const visibleObjects = new Map();

  // Keep the highest-confidence detection for each category.
  for (const detection of detections) {
    const name = (
      detection.class_name || detection.label || ''
    ).trim().toLowerCase();

    if (!name) continue;

    const previous = visibleObjects.get(name);

    if (
      !previous ||
      (detection.confidence ?? 0) >
        (previous.confidence ?? 0)
    ) {
      visibleObjects.set(name, detection);
    }
  }

  // Find categories that are new or have reappeared.
  for (const [name] of visibleObjects) {
    let state = objectSpeechState.get(name);

    if (!state) {
      // First time this category has appeared.
      state = {
        lastSeen: now,
        lastSpoken: 0,
        pending: true
      };

      objectSpeechState.set(name, state);
      continue;
    }

    const disappearedFor = now - state.lastSeen;

    if (
      disappearedFor >= OBJECT_REAPPEAR_DELAY &&
      now - state.lastSpoken >= OBJECT_SPEECH_COOLDOWN
    ) {
      // Keep the announcement pending until it is spoken.
      state.pending = true;
    }

    state.lastSeen = now;
    objectSpeechState.set(name, state);
  }

  // Announce at most one category per frame response.
  // Remaining pending categories can be announced on
  // subsequent frames.
  const candidates = [...visibleObjects.entries()]
    .filter(([name]) => {
      const state = objectSpeechState.get(name);
      return state && state.pending;
    })
    .sort((a, b) =>
      (b[1].confidence ?? 0) - (a[1].confidence ?? 0)
    );

  if (candidates.length === 0) return;

  const [name, detection] = candidates[0];
  const state = objectSpeechState.get(name);

  state.pending = false;
  state.lastSpoken = now;

  const severity = detection.level === 'stop' ? 3 :
    detection.level === 'close' ? 2 : 1;
  speak(`${name} detected`, {
    priority: severity,
    dedupeKey: `object:${name}`,
    cooldown: OBJECT_SPEECH_COOLDOWN,
  });
}

function setStatus(text) {
  statusText.textContent = text;
}

function setConnection(online) {
  badge.textContent = online ? 'Connected' : 'Offline';
  badge.classList.toggle('online', online);
}

function websocketUrl() {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${location.host}/ws`;
}

function connectSocket() {
  return new Promise((resolve, reject) => {
    socket = new WebSocket(websocketUrl());

    socket.onopen = () => {
      setConnection(true);
      resolve();
    };

    socket.onerror = () => {
      reject(new Error('Could not connect to the server.'));
    };

    socket.onclose = () => {
      setConnection(false);
      waitingForReply = false;

      if (running) {
        setStatus('Connection lost. Stop and restart to reconnect.');
      }
    };

    socket.onmessage = event => {
      waitingForReply = false;

      let data;

      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }

      if (data.type === 'result') {
        framesSent++;

        const latency = data.stats?.latency_ms;

        statsText.textContent =
          `Frames ${framesSent} · server ${latency ?? '—'} ms`;

        const detections = data.detections || [];

        drawDetections(detections);
        announceDetections(detections);

        if (data.alert) {
          speak(data.alert, {
            priority: 3,
            dedupeKey: `alert:${data.alert}`,
            cooldown: OBJECT_SPEECH_COOLDOWN,
          });
        }

      } else if (data.type === 'describe_result') {
        messageText.textContent = data.text;
        if (data.text.startsWith('Destination entered: ')) {
          if (!navigationNoticeSpoken) {
            navigationNoticeSpoken = true;
            speak(data.text, {
              priority: 3,
              dedupeKey: 'navigation-warning',
              cooldown: Infinity,
            });
          }
        } else {
          speak(data.text, {
            priority: 2,
            dedupeKey: `response:${data.text}`,
          });
        }

      } else if (data.type === 'error') {
        messageText.textContent = data.message;
        speak(data.message, {
          priority: 3,
          dedupeKey: `error:${data.message}`,
          cooldown: 5000,
        });
      }
    };
  });
}

function drawDetections(detections) {
  const w = video.videoWidth;
  const h = video.videoHeight;

  if (!w || !h) return;

  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }

  ctx.clearRect(0, 0, w, h);

  for (const d of detections) {
    if (!Array.isArray(d.box) || d.box.length !== 4) continue;

    const [x, y, bw, bh] = d.box;

    ctx.lineWidth = Math.max(2, w / 180);

    ctx.strokeStyle =
      d.level === 'stop' ? '#ff525e' :
      d.level === 'close' ? '#ffbd4a' :
      '#62f0cf';

    ctx.strokeRect(x * w, y * h, bw * w, bh * h);

    const label =
      `${d.label || 'object'}${d.direction ? ` · ${d.direction}` : ''}`;

    ctx.font = `bold ${Math.max(14, w / 32)}px system-ui`;

    const tw = ctx.measureText(label).width;

    ctx.fillStyle = ctx.strokeStyle;

    ctx.fillRect(
      x * w,
      Math.max(0, y * h - 28),
      tw + 14,
      27
    );

    ctx.fillStyle = '#07131b';

    ctx.fillText(
      label,
      x * w + 7,
      Math.max(18, y * h - 9)
    );
  }
}

async function sendFrame() {
  if (
    !running ||
    waitingForReply ||
    !socket ||
    socket.readyState !== WebSocket.OPEN ||
    video.readyState < 2
  ) {
    return;
  }

  const sourceWidth = video.videoWidth;
  const sourceHeight = video.videoHeight;

  if (!sourceWidth || !sourceHeight) return;

  const targetWidth = 320;
  const targetHeight = Math.round(
    sourceHeight * targetWidth / sourceWidth
  );

  const frameCanvas = document.createElement('canvas');

  frameCanvas.width = targetWidth;
  frameCanvas.height = targetHeight;

  frameCanvas
    .getContext('2d')
    .drawImage(video, 0, 0, targetWidth, targetHeight);

  const jpegDataUrl = frameCanvas.toDataURL('image/jpeg', 0.6);
  const image = jpegDataUrl.split(',', 2)[1];

  const message = {
    type: 'frame',
    image,
    ts: Date.now(),
    lat: null,
    lng: null,
    accuracy: null,
    heading: null
  };

  waitingForReply = true;
  lastFrameSentAt = performance.now();

  socket.send(JSON.stringify(message));

  // Recover if a server response is lost.
  window.setTimeout(() => {
    if (
      waitingForReply &&
      performance.now() - lastFrameSentAt > 2500
    ) {
      waitingForReply = false;
    }
  }, 2600);
}

async function start() {
  startButton.disabled = true;

  try {
    if (
      !window.isSecureContext &&
      location.hostname !== 'localhost'
    ) {
      throw new Error(
        'Camera access requires HTTPS. Open the secure tunnel URL.'
      );
    }

    speak(
      'PathVoice is starting. This prototype does not replace your mobility aid.'
    );

    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 640 }
      },
      audio: false
    });

    video.srcObject = stream;
    await video.play();

    placeholder.hidden = true;

    await connectSocket();

    running = true;

    startButton.textContent = 'Stop camera and alerts';
    startButton.disabled = false;

    setStatus(
      'Camera active · object detection and voice alerts enabled'
    );

    messageText.textContent =
      'Connected. Object detection and spoken announcements are active.';

    frameTimer = window.setInterval(sendFrame, 180);

  } catch (error) {
    startButton.disabled = false;

    setStatus('Could not start');

    messageText.textContent = error.message || String(error);
    speak(error.message || 'Camera could not start.', {
      priority: 3,
      dedupeKey: 'camera-start-error',
      cooldown: 5000,
    });

    if (stream) {
      stream.getTracks().forEach(track => track.stop());
    }

    stream = null;

    if (socket) {
      socket.close();
    }
  }
}

function stop() {
  running = false;

  if (frameTimer) {
    window.clearInterval(frameTimer);
  }

  frameTimer = null;

  if (stream) {
    stream.getTracks().forEach(track => track.stop());
  }

  stream = null;

  if (socket) {
    socket.close();
  }

  socket = null;
  waitingForReply = false;
  video.srcObject = null;

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  placeholder.hidden = false;

  startButton.textContent = 'Start camera and alerts';

  setStatus('Stopped');

  speak('Camera stopped.', { priority: 1 });
}

startButton.addEventListener('click', () => {
  running ? stop() : start();
});

testVoiceButton.addEventListener('click', () => {
  if (!initializeSpeech()) {
    messageText.textContent =
      'Voice output is not supported by this browser. Try a current browser with speech synthesis enabled.';
    return;
  }

  speak('PathVoice voice output is working.', {
    priority: 4,
    dedupeKey: `test-voice:${Date.now()}`,
    cooldown: 0,
  });
});

document.querySelector('#summaryButton').addEventListener('click', () => {
  sendCommand({ type: 'summary' });
});

document.querySelector('#describeButton').addEventListener('click', () => {
  sendCommand({ type: 'describe' });
});

document.querySelector('#navigateButton').addEventListener('click', () => {
  destinationForm.hidden = false;
  destinationInput.focus();
});

destinationForm.addEventListener('submit', event => {
  event.preventDefault();
  submitDestination(destinationInput.value);
});

manualCommandForm.addEventListener('submit', event => {
  event.preventDefault();
  const command = manualCommandInput.value.trim();

  if (!command) return;

  manualCommandInput.value = '';
  handleVoiceCommand(command, 'Typed command');
});

document.querySelector('#sosButton').addEventListener('click', () => {
  if (!confirm('Open an emergency message with your current location?')) {
    return;
  }

  if (!navigator.geolocation) {
    messageText.textContent =
      'Location is not available in this browser.';
    return;
  }

  navigator.geolocation.getCurrentPosition(
    position => {
      const { latitude, longitude } = position.coords;

      const text =
        `I need help. My location: https://maps.google.com/?q=${latitude},${longitude}`;

      window.open(
        `https://wa.me/?text=${encodeURIComponent(text)}`,
        '_blank',
        'noopener'
      );
    },
    () => {
      messageText.textContent =
        'Could not get location. Check location permission and try again.';
    },
    {
      enableHighAccuracy: true,
      timeout: 10000
    }
  );
});

function sendCommand(command) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    if (command.type === 'set_destination') {
      showNavigationUnavailable(command.query);
      return;
    }

    const message = 'Start the camera and connect first.';
    messageText.textContent = message;
    speak(message, {
      priority: 2,
      dedupeKey: 'websocket-not-connected',
      cooldown: 5000,
    });
    return;
  }

  socket.send(JSON.stringify(command));
}

function submitDestination(value) {
  const destination = value.trim();

  if (!destination) {
    messageText.textContent = 'Enter a destination name first.';
    destinationInput.focus();
    return;
  }

  destinationInput.value = '';
  sendCommand({
    type: 'set_destination',
    query: destination
  });
}

function showNavigationUnavailable(destination) {
  const firstNotice = !navigationNoticeSpoken;
  const disclaimer = firstNotice
    ? 'PathVoice does not provide turn-by-turn directions. Use a dedicated ' +
      'navigation app for route guidance. PathVoice has not verified your ' +
      'route or its safety.'
    : 'Turn-by-turn navigation is not available.';
  const message = `Destination entered: ${destination}. ${disclaimer}`;
  messageText.textContent = message;
  if (firstNotice) {
    navigationNoticeSpoken = true;
    speak(message, {
      priority: 3,
      dedupeKey: 'navigation-warning',
      cooldown: Infinity,
    });
  }
}

window.addEventListener('beforeunload', () => {
  if (stream) {
    stream.getTracks().forEach(track => track.stop());
  }
});

function handleVoiceCommand(transcript, source = 'Voice command') {
  const command = transcript.toLowerCase().trim();

  messageText.textContent = `${source}: "${transcript}"`;

  if (
    command.includes('start detection') ||
    command.includes('start camera')
  ) {
    if (!running) {
      start();
    } else {
      speak('Camera and detection flow are already running.');
    }

    return;
  }

  if (
    command.includes('stop detection') ||
    command.includes('stop camera')
  ) {
    if (running) {
      stop();
    } else {
      speak('Camera is already stopped.');
    }

    return;
  }

  if (
    command.includes('describe scene') ||
    command.includes('describe surroundings')
  ) {
    sendCommand({ type: 'describe' });
    speak('Requesting a scene description.');
    return;
  }

  if (
    command.includes('what is around me') ||
    command.includes('summarize surroundings')
  ) {
    sendCommand({ type: 'summary' });
    return;
  }

  if (command.startsWith('navigate to ')) {
    const destination =
      command.slice('navigate to '.length).trim();

    if (destination) {
      sendCommand({
        type: 'set_destination',
        query: destination
      });
    }

    return;
  }

  if (
    command.includes('emergency') ||
    command.includes('sos')
  ) {
    speak(
      'Emergency command heard. Please tap the SOS button and confirm.'
    );

    return;
  }

  speak('Command not recognized. Please try again.');
}

function startVoiceCommands() {
  if (!SpeechRecognition) {
    const message =
      'Speech recognition is not supported in this browser. Type a command below instead.';
    messageText.textContent = message;
    speak(message, { priority: 2, dedupeKey: 'recognition-unsupported' });
    return;
  }

  if (listening) {
    recognition.stop();
    return;
  }

  recognition = new SpeechRecognition();

  recognition.lang = 'en-IN';
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    listening = true;
    voiceButton.textContent = 'Stop listening';
    messageText.textContent = 'Listening for a voice command…';
  };

  recognition.onresult = event => {
    const transcript = event.results[0][0].transcript;
    handleVoiceCommand(transcript);
  };

  recognition.onerror = event => {
    const errorMessages = {
      'not-allowed':
        'Microphone or speech-recognition permission was denied. Allow access in browser settings, or type a command below.',
      'service-not-allowed':
        'The browser blocked its speech-recognition service. Check browser permissions, or type a command below.',
      network:
        'Browser speech recognition could not reach its recognition service. It may require internet access and is not guaranteed to work offline. Type a command below instead.',
      'audio-capture':
        'No usable microphone was found. Check your microphone, or type a command below.',
      'no-speech':
        'No speech was detected. Try again or type a command below.',
      aborted: 'Voice recognition was stopped.'
    };
    const message = errorMessages[event.error] ||
      `Voice recognition failed (${event.error}). Type a command below instead.`;
    messageText.textContent = message;
    speak(message, {
      priority: 2,
      dedupeKey: `recognition-error:${event.error}`,
      cooldown: 5000,
    });
  };

  recognition.onend = () => {
    listening = false;
    voiceButton.textContent = 'Start voice commands';
  };

  try {
    recognition.start();
  } catch (error) {
    messageText.textContent =
      `Could not start voice recognition: ${error.message}`;
  }
}

voiceButton.addEventListener('click', startVoiceCommands);
