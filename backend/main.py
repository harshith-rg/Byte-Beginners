
"""FastAPI backend with YOLO object detection over WebSocket."""

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

logger = logging.getLogger(__name__)

app = FastAPI(title="IBM Z Datathon Smart Navigation API")

INFERENCE_ENGINE = os.environ.get(
    "PATHVOICE_INFERENCE_ENGINE",
    "ultralytics",
).strip().lower()

if INFERENCE_ENGINE == "onnx":
    from detector_onnx import ONNXDetector

    detector = ONNXDetector(
        os.environ.get("PATHVOICE_ONNX_MODEL", "yolo11n.onnx")
    )
    model = None
elif INFERENCE_ENGINE == "ultralytics":
    from ultralytics import YOLO

    # Load the model once when the server starts, not on every frame.
    model = YOLO("yolo11n.pt")
    detector = None
else:
    raise ValueError(
        "PATHVOICE_INFERENCE_ENGINE must be 'ultralytics' or 'onnx'"
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "smart-navigation-backend",
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
        conf=0.35,
        verbose=False,
    )

    detections = []

    for result in results:
        if result.boxes is None:
            continue

        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            class_id = int(box.cls[0].item())
            confidence = float(box.conf[0].item())
            label = model.names[class_id]

            # Convert pixel coordinates to 0..1 normalized coordinates.
            x = max(0.0, min(1.0, x1 / width))
            y = max(0.0, min(1.0, y1 / height))
            box_width = max(0.0, min(1.0 - x, (x2 - x1) / width))
            box_height = max(0.0, min(1.0 - y, (y2 - y1) / height))

            detections.append({
                "label": f"{label} {confidence:.0%}",
                "class_name": label,
                "confidence": round(confidence, 3),
                "box": [
                    round(x, 4),
                    round(y, 4),
                    round(box_width, 4),
                    round(box_height, 4),
                ],
                "level": "normal",
            })

    return detections


def _detection_counts(
    detections: list[dict[str, Any]],
) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for detection in detections:
        name = str(detection.get("class_name") or "unknown object")
        counts[name] = counts.get(name, 0) + 1
    return list(counts.items())


def _summary_text(detections: list[dict[str, Any]]) -> str:
    if not detections:
        return (
            "No recognizable objects were detected in the latest processed "
            "frame. This does not mean the area is clear; the detector can "
            "miss objects."
        )

    counts = "; ".join(
        f"{name}: {count} detection{'s' if count != 1 else ''}"
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    latest_detections: list[dict[str, Any]] | None = None
    navigation_disclaimer_sent = False

    try:
        while True:
            started = time.perf_counter()
            raw = await websocket.receive_text()

            try:
                message: dict[str, Any] = json.loads(raw)
                kind = message.get("type")

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

                    latest_detections = [
                        {
                            **detection,
                            "box": list(detection["box"]),
                        }
                        for detection in detections
                    ]

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
                        "alert": "",
                        "nav": {
                            "instruction": "",
                            "distance_to_turn": None,
                            "bearing": None,
                            "off_route": False,
                            "speak": False,
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
app.mount(
    "/",
    StaticFiles(directory="../frontend", html=True),
    name="frontend",
)
