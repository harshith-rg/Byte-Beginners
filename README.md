# PathVoice — IBM Z Datathon starter

PathVoice serves a phone-friendly frontend from FastAPI. The browser sends 320 px-wide JPEG camera frames to the backend over a WebSocket; the backend runs YOLO object detection and returns normalized detections for display and spoken alerts. Turn-by-turn routing, watsonx.ai scene descriptions, and full SOS contact settings are not implemented.

The default inference engine is Ultralytics using `backend/yolo11n.pt`. An
experimental OpenCV DNN ONNX engine is available only when explicitly selected
with `PATHVOICE_INFERENCE_ENGINE=onnx`; it expects a YOLO11 COCO ONNX export
with 640-by-640 input. The checked-in repository does not include that ONNX
export, and its LinuxONE inference path has not been validated on the VM.

The **Describe scene** action uses the latest successfully processed frame's
object-detection labels to produce a cautious local text description. **What
is around me?** gives a compact count of those labels. These are not
watsonx.ai or full scene-understanding features: they cannot establish exact
distances, safe paths, or details the detector did not recognize.

Voice commands use the browser's Web Speech recognition service when
available; this browser feature may require internet access and is not
guaranteed to work offline. If recognition is unsupported, denied, or reports
a network error, use the on-page text command field instead. Navigate accepts
a typed destination, but PathVoice does not calculate routes or provide
turn-by-turn directions. PathVoice displays this safety notice when you use
Navigate: “PathVoice does not provide turn-by-turn directions. Use a dedicated
navigation app for route guidance. PathVoice has not verified your route or
its safety.”

Spoken output uses the browser's native speech synthesis, independently from
voice-command recognition. Use **Test Voice** to check output without starting
the camera. The page reports voice readiness or failure; check the browser's
audio output and device volume if speech does not play.

## Requirements
- Python 3.10+
- Dependencies from `backend/requirements.txt`
- `backend/yolo11n.pt` for default Ultralytics mode, or a generated
  `backend/yolo11n.onnx` for the opt-in LinuxONE mode
- A modern browser; Android Chrome is the recommended first demo target
- For phone camera/GPS access, use HTTPS (a tunnel) rather than plain HTTP

## Run locally

From the project root:

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` on the same computer and check `http://localhost:8000/health`. To test on a phone, expose port 8000 through Cloudflare Tunnel or ngrok and open its HTTPS URL. Start the camera and verify that the frame counter increases.

The frontend sends one frame at a time and waits for its response before
sending another. The selected inference engine and its model load during
backend startup, so those dependencies and model files must be available before
the health endpoint can respond.

For IBM LinuxONE deployment notes, including the opt-in ONNX path and its
compatibility and inference checks, see [DEPLOY_LINUXONE.md](./DEPLOY_LINUXONE.md).

## Team file ownership
- M1: integration, deployment, voice commands
- M2: `backend/detector.py` and detector tests
- M3: `backend/main.py`, `backend/alerts.py`, `backend/describe.py`
- M4: `backend/navigation.py` and frontend navigation/SOS modules
- M5: `frontend/index.html`, `frontend/app.js` and camera/WebSocket behaviour
- M6: `frontend/style.css`, tests/log, README, pitch and demo assets

Keep secrets in `.env`, never commit them, and do not use this prototype as a sole mobility aid.
