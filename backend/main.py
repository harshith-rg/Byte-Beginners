import asyncio
import base64
import os
import time

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from ultralytics import YOLO

from backend.alerts import AlertEngine
from backend.describe import describe_scene

app = FastAPI(title="VisionGuide AI", version="1.0.0")

MODEL_PATH = os.getenv("YOLO_MODEL", "yolo26n.pt")
CONFIDENCE = float(os.getenv("CONFIDENCE", "0.40"))
MAX_FRAME_BYTES = 5 * 1024 * 1024
MIN_FRAME_INTERVAL = 0.10  # Maximum 10 accepted frames/second per connection.

# Load once at startup. Set YOLO_MODEL to your trained model path if applicable.
model = YOLO(MODEL_PATH)

latest_frame = None
latest_frame_lock = asyncio.Lock()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "VisionGuide AI",
        "detector": MODEL_PATH,
        "description_fallback": "local detector",
    }


def decode_frame(encoded):
    if not isinstance(encoded, str):
        raise ValueError("image must be a base64 string")
    if encoded.startswith("data:"):
        parts = encoded.split(",", 1)
        if len(parts) != 2:
            raise ValueError("Invalid data URL")
        encoded = parts[1]

    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 image") from exc

    if not raw:
        raise ValueError("Empty image")
    if len(raw) > MAX_FRAME_BYTES:
        raise ValueError("Frame exceeds 5 MB limit")

    array = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid JPEG/PNG image")
    return image


def detect_objects(image):
    height, width = image.shape[:2]
    result = model.predict(
        source=image,
        conf=CONFIDENCE,
        imgsz=640,
        verbose=False,
    )[0]

    detections = []
    if result.boxes is None:
        return detections

    for box in result.boxes:
        class_id = int(box.cls.item())
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        detections.append({
            "label": result.names[class_id],
            "confidence": float(box.conf.item()),
            "box": [round(x1, 1), round(y1, 1),
                    round(x2, 1), round(y2, 1)],
        })
    return detections, width, height


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    engine = AlertEngine(cooldown=3.0)
    last_frame_time = 0.0

    try:
        while True:
            message = await ws.receive_json()
            msg_type = message.get("type")

            if msg_type == "navigation":
                engine.update_navigation(message)
                await ws.send_json({
                    "type": "navigation_ack",
                    "instruction": engine.navigation["instruction"],
                    "direction": engine.navigation["direction"],
                    "active": engine.navigation["active"],
                })
                continue

            if msg_type != "frame":
                await ws.send_json({
                    "type": "error",
                    "message": "Expected type 'frame' or 'navigation'.",
                })
                continue

            now = time.monotonic()
            if now - last_frame_time < MIN_FRAME_INTERVAL:
                await ws.send_json({
                    "type": "skipped",
                    "reason": "frame_rate_limit",
                })
                continue
            last_frame_time = now

            try:
                image = decode_frame(message.get("image"))
            except ValueError as exc:
                await ws.send_json({
                    "type": "error",
                    "message": str(exc),
                })
                continue

            started = time.perf_counter()
            try:
                # Inference runs outside the asyncio event loop.
                result = await asyncio.to_thread(detect_objects, image)
                detections, width, height = result
                alert = engine.process(detections, width, height)
            except Exception:
                await ws.send_json({
                    "type": "error",
                    "message": "Detection failed for this frame.",
                })
                continue

            async with latest_frame_lock:
                global latest_frame
                latest_frame = image.copy()

            await ws.send_json({
                "type": "result",
                "detections": [
                    {**d, "frame_width": width, "frame_height": height}
                    for d in detections
                ],
                "alert": alert,
                "latency_ms": round(
                    (time.perf_counter() - started) * 1000, 1
                ),
                "latency_scope": "backend decode, inference and alert logic",
            })

    except WebSocketDisconnect:
        pass


class DescribeRequest(BaseModel):
    question: str = Field(
        default="What is around me?",
        max_length=300,
    )


@app.post("/describe")
async def describe(request: DescribeRequest):
    async with latest_frame_lock:
        image = latest_frame.copy() if latest_frame is not None else None

    if image is None:
        return {
            "text": "No camera frame is available yet.",
            "source": "fallback",
        }

    try:
        text, source = await asyncio.to_thread(
            describe_scene, image, request.question, model
        )
        return {"text": text, "source": source}
    except Exception:
        return {
            "text": (
                "I could not describe the scene right now. "
                "Please pause and use your usual mobility aid."
            ),
            "source": "fallback",
        }
            