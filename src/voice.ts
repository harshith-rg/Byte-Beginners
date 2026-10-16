function speakQueued(text: string) {
    if (!('speechSynthesis' in window)) return
    speechSynthesis.speak(new SpeechSynthesisUtterance(text))
}

function clickWhenVisible(selector: string, timeoutMs: number) {
    // Waits for a button to appear (for example Start guidance), then presses it
    const started = Date.now()
    const timer = setInterval(() => {
        const el = document.querySelector<HTMLButtonElement>(selector)
        if (el && el.style.display !== 'none') {
            clearInterval(timer)
            el.click()
        } else if (Date.now() - started > timeoutMs) {
            clearInterval(timer)
        }
    }, 500)
}

function handleCommand(raw: string) {
    const text = raw.toLowerCase().trim()

    // "navigate to X", "take me to X", "go to X" ...
    const m = text.match(/^(?:navigate to|take me to|go to|directions to|walk to)\s+(.+)$/)
    if (m) {
        const input = document.querySelector<HTMLInputElement>('#dest')!
        input.value = m[1]
        document.querySelector<HTMLButtonElement>('#go')!.click()
        clickWhenVisible('#guide', 30000) // start guidance automatically
        return
    }

    if (/^(start|begin)/.test(text)) {
        const guide = document.querySelector<HTMLButtonElement>('#guide')
        if (guide && guide.style.display !== 'none') {
            guide.click()
        } else {
            speakQueued('There is no route yet. Say navigate to, and a place.')
        }
        return
    }

    if (/^(stop|cancel|end)/.test(text)) {
        const stop = document.querySelector<HTMLButtonElement>('#stop')
        if (stop && stop.style.display !== 'none') stop.click()
        else speakQueued('Guidance is not running.')
        return
    }

    if (/^(repeat|again|where|status)/.test(text)) {
        const live = document.querySelector<HTMLParagraphElement>('#live')!
        speakQueued(live.textContent || 'No guidance running.')
        return
    }

    speakQueued(`Sorry, I heard ${raw}. Say navigate to, start, stop, or repeat.`)
}

export function setupVoice() {
    const nav = document.querySelector<HTMLDivElement>('#nav')!
    nav.insertAdjacentHTML(
        'afterbegin',
        `<button id="mic" style="width:100%;font-size:28px;padding:28px;margin-bottom:12px">
       Tap and speak
     </button>
     <p id="heard"></p>`
    )
    const mic = document.querySelector<HTMLButtonElement>('#mic')!
    const heard = document.querySelector<HTMLParagraphElement>('#heard')!

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) {
        heard.textContent = 'Voice input is not supported in this browser. Type the destination instead.'
        mic.disabled = true
        return
    }

    const rec = new SR()
    rec.lang = 'en-IN'
    rec.interimResults = false
    rec.maxAlternatives = 1
    let listening = false

    rec.onresult = (e: any) => {
        const text: string = e.results[0][0].transcript
        heard.textContent = 'Heard: ' + text
        handleCommand(text)
    }
    rec.onerror = (e: any) => {
        heard.textContent = 'Voice error: ' + e.error
    }
    rec.onend = () => {
        listening = false
        mic.textContent = 'Tap and speak'
    }

    mic.addEventListener('click', () => {
        if (listening) {
            rec.stop()
            return
        }
        if ('speechSynthesis' in window) speechSynthesis.cancel()
        try {
            rec.start()
            listening = true
            mic.textContent = 'Listening... (tap to cancel)'
        } catch {
            heard.textContent = 'Could not start the microphone.'
        }
    })
}