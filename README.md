# Byte-Beginners — PathVoice & AI Navigation Assistant

Byte-Beginners is an accessibility-focused AI navigation and obstacle-awareness system developed for the IBM Z Datathon. It combines phone-friendly live camera streaming with WebSocket-driven object detection, audio/voice guidance, tracking, and IBM LinuxONE deployment support.

## Overview

The repository integrates contributions from across the project milestones:
- **M1 (Lakshman)**: LinuxONE deployment (`DEPLOY_LINUXONE.md`), ONNX inference engine (`backend/detector_onnx.py`), test suite, and integration.
- **M2 (John)**: YOLOv8 object detection, ByteTrack object tracking (`track.py`), and speech tests.
- **M3 (Ani)**: Alert engine (`backend/alerts.py`), scene description (`backend/describe.py`), and WebSocket backend.
- **M4 (Harish)**: Navigation and route mapping services.
- **M5 (Harshith)**: Frontend UI and client applications.
- **M6**: Presentation, pitch, and demo assets.

---

## 1. PathVoice Web Application (FastAPI + WebSocket)

PathVoice serves a phone-friendly frontend from FastAPI. The browser sends 320 px-wide JPEG camera frames over a WebSocket; the backend runs YOLO object detection and returns normalized detections for display and spoken alerts.

### Requirements
- Python 3.10+
- Dependencies from `backend/requirements.txt`
- `backend/yolo11n.pt` for default Ultralytics mode, or `backend/yolo11n.onnx` for opt-in LinuxONE mode
- A modern browser (Chrome recommended)

### Run PathVoice Locally

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` in your browser. Check health at `http://localhost:8000/health`.

For IBM LinuxONE deployment notes, including the ONNX path, see [DEPLOY_LINUXONE.md](./DEPLOY_LINUXONE.md).

---

## 2. Standalone Video Tracking & Voice Assistant (M2)

An accessibility prototype that detects and tracks everyday objects in video, announcing newly observed objects with text-to-speech.

### Run Tracker
```bash
python track.py
```

### Other Scripts
| Command | Purpose |
| --- | --- |
| `python detech.py` | Runs YOLOv8 detection on sample bus image |
| `python backend/detector.py` | Runs detection on local `bus.jpg` image |
| `python voice_test.py` | Checks basic text-to-speech output |
| `python voice_test2.py` | Checks sequential Windows SAPI5 announcements |

---

## Team File Ownership

- **M1 (Lakshman)**: `DEPLOY_LINUXONE.md`, `backend/detector_onnx.py`, `backend/yolo11n.onnx`, tests
- **M2 (John)**: `backend/detector.py`, `track.py`, `detech.py`, `voice_test*.py`
- **M3 (Ani)**: `backend/alerts.py`, `backend/describe.py`, `backend/main.py`
- **M4 (Harish)**: `backend/navigation.py`, navigation frontend
- **M5 (Harshith)**: `frontend/index.html`, `frontend/app.js`, web client
- **M6**: `frontend/style.css`, demo assets, pitch deck

> **Notice**: Prototype only. This system is not a replacement for a white cane, guide dog, or established mobility support.
