# Byte-Beginners — AI Navigation Assistant

An accessibility-focused computer-vision prototype that detects and tracks everyday objects in video, then announces newly detected objects with text-to-speech. It uses YOLOv8 for object detection and ByteTrack for tracking.

## Features

- Detects common objects such as people, cars, buses, bicycles, traffic lights, bags, and animals.
- Tracks objects between video frames to reduce repeated announcements.
- Announces newly detected objects through the system's text-to-speech engine.
- Shows a live annotated video window.
- Includes simple image-detection and speech-test scripts.

## Tech stack

- Python
- [Ultralytics YOLOv8](https://docs.ultralytics.com/)
- OpenCV
- pyttsx3 (offline text-to-speech)
- ByteTrack (provided through Ultralytics)

## Prerequisites

- Python 3.9 or later
- A webcam/video-capable environment
- Windows is recommended for the included `sapi5` speech-engine setting

## Installation

1. Clone the repository and move into it.

   ```bash
   git clone <your-repository-url>
   cd hackathon
   ```

2. Create and activate a virtual environment (recommended).

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Install the dependencies.

   ```bash
   pip install ultralytics opencv-python pyttsx3
   ```

4. Keep `yolov8n.pt` and `video.mp4` in the project root. The project already includes sample copies; if the model file is missing, Ultralytics can download it automatically when the script runs.

## Run the navigation assistant

```bash
python track.py
```

The program opens an annotated video window and speaks a message such as `person detected` when it finds a newly observed supported object. Press `q` in the video window to stop it.

## Other scripts

| Command | Purpose |
| --- | --- |
| `python detech.py` | Runs YOLOv8 detection on Ultralytics' sample bus image. |
| `python backend/detector.py` | Runs detection on the local `bus.jpg` image. |
| `python voice_test.py` | Checks basic text-to-speech output. |
| `python voice_test2.py` | Checks sequential speech announcements with the Windows SAPI5 engine. |

Detection outputs are saved under `runs/detect/`.

## How it works

1. YOLOv8 analyzes each frame from `video.mp4`.
2. ByteTrack maintains identities for objects across frames.
3. The app filters detections to relevant everyday objects and ignores low-confidence results.
4. Recently seen objects are remembered for eight seconds; new objects are added to a speech queue.
5. A background thread speaks announcements without pausing the video display.

## Project structure

```text
.
├── track.py              # Main detection, tracking, and voice-assistant program
├── detech.py             # Sample remote-image detection script
├── backend/detector.py   # Local image detection script
├── voice_test.py         # Basic speech test
├── voice_test2.py        # Windows SAPI5 speech test
├── video.mp4             # Sample input video
├── bus.jpg               # Sample input image
└── yolov8n.pt            # YOLOv8 Nano model weights
```

## Notes

- This is a prototype and should not be relied on as a sole navigation or safety aid.
- To use another video, replace `video.mp4` or change the source path in `track.py`.
- For a GitHub upload, it is usually best to exclude generated `runs/` output and large model/video files unless they are intentionally part of the demo.

## Team

Byte-Beginners
