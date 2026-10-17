"""FastAPI backend with YOLO object detection and alert engine over WebSocket."""

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from backend.alerts import AlertEngine
    from backend.describe import describe_scene
except ImportError:
    from alerts import AlertEngine
    from describe import describe_scene

logger = logging.getLogger(__name__)

app = FastAPI(title="Byte-Beginners / PathVoice Smart Navigation API", version="1.0.0")

INFERENCE_ENGINE = os.environ.get(
    "PATHVOICE_INFERENCE_ENGINE",
    "ultralytics",
).strip().lower()

MODEL_PATH = os.getenv("YOLO_MODEL", "yolo11n.pt")
CONFIDENCE = float(os.getenv("CONFIDENCE", "0.35"))

if INFERENCE_ENGINE == "onnx":
    try:
        from backend.detector_onnx import ONNXDetector
    except ImportError:
        from detector_onnx import ONNXDetector

    detector = ONNXDetector(
        os.environ.get("PATHVOICE_ONNX_MODEL", "yolo11n.onnx")
    )
    model = None
elif INFERENCE_ENGINE == "ultralytics":
    from ultralytics import YOLO

    # Load the model once when the server starts, not on every frame.
    model = YOLO(MODEL_PATH)
    detector = None
else:
    raise ValueError(
        "PATHVOICE_INFERENCE_ENGINE must be 'ultralytics' or 'onnx'"
    )

latest_frame: np.ndarray | None = None
latest_frame_lock = asyncio.Lock()


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "smart-navigation-backend",
        "engine": INFERENCE_ENGINE,
        "model": MODEL_PATH if model else "onnx",
    }


def decode_jpeg_data_url(value: str) -> np.ndarray:
    """Decode a base64 JPEG image received from the frontend."""
    if not isinstance(value, str) or not value:
        raise ValueError("No image data was supplied")

    if "," in value and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]

    raw = base64.b64decode(value, validate=True)
    image = cv2.imdecode(
        np.frombuffer(raw, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise ValueError("The supplied image is not a valid JPEG image")

    return image


def detect_objects(frame: np.ndarray) -> list[dict[str, Any]]:
    """Run the selected detector and return normalized frontend boxes."""
    if detector is not None:
        return detector.detect(frame)

    height, width = frame.shape[:2]

    results = model.predict(
        source=frame,
        imgsz=320,
        conf=CONFIDENCE,
        verbose=False,
    )

    detections = []

    for result in results:
        if result.boxes is None:
            continue

        for box in result.boxes:
            class_id = int(box.cls.item())
            name = result.names[class_id]
            conf = float(box.conf.item())

            # Convert xyxy pixel coordinates to normalized 0-1 values.
            x1, y1, x2, y2 = box.xyxy[0].tolist()

            detections.append({
                "label": name,
                "confidence": round(conf, 2),
                "box": [
                    round(max(0.0, min(1.0, x1 / width)), 4),
                    round(max(0.0, min(1.0, y1 / height)), 4),
                    round(max(0.0, min(1.0, x2 / width)), 4),
                    round(max(0.0, min(1.0, y2 / height)), 4),
                ],
            })

    return detections


def _detection_counts(detections: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for detection in detections:
        label = str(detection.get("label", "unknown"))
        counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _summary_text(detections: list[dict[str, Any]]) -> str:
    if not detections:
        return (
            "No objects are detected in the latest frame. Keep moving "
            "slowly and rely on your regular mobility aid."
        )

    counts = ", ".join(
        f"{name}: {count}"
        for name, count in _detection_counts(detections)
    )
    return (
        f"Latest frame object-count summary: {counts}. "
        "These are detector labels only; distance and route safety are "
        "not assessed."
    )


def _description_text(detections: list[dict[str, Any]]) -> str:
    if not detections:
        return (
            "The detector found no recognizable objects in the latest "
            "processed frame. This does not mean the area is clear; the "
            "detector can miss objects."
        )

    labels = "; ".join(
        f"{name} ({count} detection{'s' if count != 1 else ''})"
        for name, count in _detection_counts(detections)
    )
    return (
        f"In the latest processed frame, the detector labeled: {labels}. "
        "This local description is based only on model labels; it cannot "
        "determine exact distances, whether a path is safe, or details the "
        "detector did not recognize."
    )


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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    latest_detections: list[dict[str, Any]] | None = None
    navigation_disclaimer_sent = False
    alert_engine = AlertEngine(cooldown=3.0)

    try:
        while True:
            started = time.perf_counter()
            raw = await websocket.receive_text()

            try:
                message: dict[str, Any] = json.loads(raw)
                kind = message.get("type")

                if kind == "navigation":
                    alert_engine.update_navigation(message)
                    await websocket.send_json({
                        "type": "navigation_ack",
                        "instruction": alert_engine.navigation["instruction"],
                        "direction": alert_engine.navigation["direction"],
                        "active": alert_engine.navigation["active"],
                    })
                    continue

                if kind == "frame":
                    frame = decode_jpeg_data_url(
                        message.get("image", "")
                    )
                    height, width = frame.shape[:2]
                    latest_detections = None

                    try:
                        detections = detect_objects(frame)
                    except (
                        cv2.error,
                        RuntimeError,
                        ValueError,
                        TypeError,
                        OSError,
                    ):
                        logger.exception(
                            "Object detection failed for a WebSocket frame"
                        )
                        await websocket.send_json({
                            "type": "error",
                            "message": (
                                "Object detection failed for the latest "
                                "frame. Wait for another frame and try again."
                            ),
                        })
                        continue

                    # Update global latest frame for /describe endpoint
                    async with latest_frame_lock:
                        global latest_frame
                        latest_frame = frame.copy()

                    latest_detections = [
                        {
                            **detection,
                            "box": list(detection["box"]),
                        }
                        for detection in detections
                    ]

                    # Compute alert using M3 AlertEngine
                    pixel_detections = [
                        {
                            **d,
                            "box": [
                                d["box"][0] * width,
                                d["box"][1] * height,
                                d["box"][2] * width,
                                d["box"][3] * height,
                            ],
                        }
                        for d in detections
                    ]
                    alert_text = alert_engine.process(pixel_detections, width, height) or ""

                    latency_ms = round(
                        (time.perf_counter() - started) * 1000,
                        1,
                    )

                    reply = {
                        "type": "result",
                        "ts": message.get(
                            "ts",
                            int(time.time() * 1000),
                        ),
                        "detections": detections,
                        "alert": alert_text,
                        "nav": {
                            "instruction": alert_engine.navigation["instruction"],
                            "distance_to_turn": None,
                            "bearing": None,
                            "off_route": False,
                            "speak": bool(alert_text),
                        },
                        "stats": {
                            "latency_ms": latency_ms,
                            "fps": (
                                round(1000 / latency_ms, 1)
                                if latency_ms > 0
                                else None
                            ),
                            "frame_width": width,
                            "frame_height": height,
                        },
                    }

                    await websocket.send_json(reply)

                elif kind in {"summary", "describe"}:
                    if latest_detections is None:
                        text = (
                            "No successfully analyzed camera frame is "
                            "available on this connection yet. Start the "
                            "camera and wait for a frame before requesting "
                            "a summary or description."
                        )
                    elif kind == "summary":
                        text = _summary_text(latest_detections)
                    else:
                        text = _description_text(latest_detections)

                    await websocket.send_json({
                        "type": "describe_result",
                        "text": text,
                    })

                elif kind == "set_destination":
                    destination = str(
                        message.get("query", "")
                    ).strip()

                    if destination:
                        if navigation_disclaimer_sent:
                            navigation_notice = (
                                "Turn-by-turn navigation is not available."
                            )
                        else:
                            navigation_notice = (
                                "PathVoice does not provide turn-by-turn "
                                "directions. Use a dedicated navigation app "
                                "for route guidance. PathVoice has not "
                                "verified your route or its safety."
                            )
                            navigation_disclaimer_sent = True

                        await websocket.send_json({
                            "type": "describe_result",
                            "text": (
                                f"Destination entered: {destination}. "
                                f"{navigation_notice}"
                            ),
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Please enter a destination first.",
                        })

                elif kind == "sos":
                    await websocket.send_json({
                        "type": "error",
                        "message": (
                            "Use the frontend SOS button for the "
                            "current WhatsApp message-draft workflow."
                        ),
                    })

                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Unsupported message type.",
                    })

            except (
                ValueError,
                TypeError,
                json.JSONDecodeError,
                cv2.error,
            ) as exc:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Invalid message: {exc}",
                })

    except WebSocketDisconnect:
        pass


# Mount the frontend last.
if os.path.exists("../frontend"):
    app.mount(
        "/",
        StaticFiles(directory="../frontend", html=True),
        name="frontend",
    )
