from ultralytics import YOLO
import cv2
import pyttsx3
import threading
import queue
import time
import math

# ========== VOICE SYSTEM ==========

voice_queue = queue.Queue()
stop_speech = object()


def voice_worker():
    while True:
        message = voice_queue.get()

        try:
            if message is stop_speech:
                return

            print("SPEAKING:", message)

            # Fresh engine for every announcement
            engine = pyttsx3.init("sapi5")
            engine.setProperty("rate", 160)
            engine.setProperty("volume", 1.0)
            engine.say(message)
            engine.runAndWait()
            engine.stop()

        except Exception as error:
            print("Voice error:", error)

        finally:
            voice_queue.task_done()


voice_thread = threading.Thread(
    target=voice_worker,
    daemon=True
)
voice_thread.start()


def announce(message):
    # Don't queue the same message repeatedly
    if message not in pending_messages:
        pending_messages.add(message)
        voice_queue.put(message)


# ========== LOAD YOLO AND VIDEO ==========

model = YOLO("yolov8n.pt")
cap = cv2.VideoCapture("video.mp4")

if not cap.isOpened():
    print("ERROR: Cannot open video.mp4")
    voice_queue.put(stop_speech)
    voice_queue.join()
    voice_thread.join()
    raise SystemExit

# Supported COCO object names
allowed_objects = {
    "person", "car", "handbag", "bus", "truck",
    "bicycle", "motorcycle", "traffic light",
    "stop sign", "chair", "bench", "dog", "cat",
    "bottle", "backpack", "suitcase", "umbrella",
    "train", "bird", "cell phone", "cup", "laptop",
    "potted plant"
}

# Remember recently seen objects to avoid repeat announcements
object_memory = []
MATCH_DISTANCE = 100
MEMORY_SECONDS = 8

# Track queued and currently spoken messages
pending_messages = set()


# ========== OBJECT DETECTION AND TRACKING ==========

try:
    while True:
        success, frame = cap.read()

        if not success:
            print("Video finished")
            break

        results = model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            conf=0.25,
            verbose=False
        )

        result = results[0]
        now = time.time()

        # Remove old object memories
        object_memory = [
            item for item in object_memory
            if now - item["time"] < MEMORY_SECONDS
        ]

        # Display video without waiting for speech
        cv2.imshow(
            "AI Navigation Assistant",
            result.plot()
        )

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

        boxes = result.boxes

        if boxes is None or len(boxes) == 0:
            continue

        # Each object can match only one memory per frame
        matched_memories = set()

        for box in boxes:
            class_id = int(box.cls[0])
            object_name = model.names[class_id]

            if object_name not in allowed_objects:
                continue

            confidence = float(box.conf[0])

            # Ignore low-confidence detections
            if confidence < 0.25:
                continue

            x1, y1, x2, y2 = box.xyxy[0].cpu().tolist()
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2

            best_index = None
            best_distance = MATCH_DISTANCE

            # Match this detection to a recently seen object
            for index, item in enumerate(object_memory):
                if index in matched_memories:
                    continue

                if item["name"] != object_name:
                    continue

                distance = math.hypot(
                    center_x - item["x"],
                    center_y - item["y"]
                )

                if distance < best_distance:
                    best_distance = distance
                    best_index = index

            if best_index is not None:
                # Existing object: update its position
                item = object_memory[best_index]
                item["x"] = center_x
                item["y"] = center_y
                item["time"] = now
                matched_memories.add(best_index)

            else:
                # New object: remember and announce it
                object_memory.append({
                    "name": object_name,
                    "x": center_x,
                    "y": center_y,
                    "time": now
                })

                matched_memories.add(len(object_memory) - 1)

                message = f"{object_name} detected"
                print("NEW OBJECT:", message)
                announce(message)

finally:
    cap.release()
    cv2.destroyAllWindows()

    # Let queued announcements finish before exiting
    voice_queue.join()
    voice_queue.put(stop_speech)
    voice_queue.join()
    voice_thread.join()

    print("AI Navigation Assistant stopped")