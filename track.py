import os
import sys
import math
import time
import queue
import threading
import cv2
from ultralytics import YOLO

# ========== PATH CONFIGURATION ==========

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "yolov8n.pt")
VIDEO_PATH = os.path.join(SCRIPT_DIR, "video.mp4")

# Fallback to local relative names if absolute paths are not found
if not os.path.exists(MODEL_PATH):
    MODEL_PATH = "yolov8n.pt"
if not os.path.exists(VIDEO_PATH):
    VIDEO_PATH = "video.mp4"

# ========== VOICE SYSTEM ==========

voice_queue = queue.Queue()
stop_speech = object()
pending_messages = set()
pending_lock = threading.Lock()


def voice_worker():
    # Initialize COM for Windows SAPI in this worker thread
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass

    try:
        import pyttsx3
        try:
            engine = pyttsx3.init("sapi5")
        except Exception:
            engine = pyttsx3.init()
    except Exception as error:
        print("Voice engine init error:", error)
        engine = None

    if engine is not None:
        try:
            engine.setProperty("rate", 160)
            engine.setProperty("volume", 1.0)
        except Exception as error:
            print("Voice property error:", error)

    while True:
        message = voice_queue.get()

        try:
            if message is stop_speech:
                return

            print("SPEAKING:", message)

            if engine is not None:
                engine.say(message)
                engine.runAndWait()

        except Exception as error:
            print("Voice error:", error)

        finally:
            with pending_lock:
                if message is not stop_speech:
                    pending_messages.discard(message)
            voice_queue.task_done()


def announce(message):
    # Don't queue the same message repeatedly while it is pending or speaking
    with pending_lock:
        if message not in pending_messages:
            pending_messages.add(message)
            voice_queue.put(message)


# ========== MAIN OBJECT DETECTION AND TRACKING ==========

def main():
    # Parse source from CLI arguments or use default VIDEO_PATH
    source = sys.argv[1] if len(sys.argv) > 1 else VIDEO_PATH
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    # Start speech worker thread
    voice_thread = threading.Thread(
        target=voice_worker,
        daemon=True
    )
    voice_thread.start()

    # Load YOLO model
    print(f"Loading YOLO model from: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)

    # Open video capture
    print(f"Opening video source: {source}")
    cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"ERROR: Cannot open video source: {source}")
        if voice_thread.is_alive():
            voice_queue.put(stop_speech)
            voice_thread.join()
        sys.exit(1)

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
    # For confirmed tracks with ByteTrack IDs:
    tracked_objects = {}  # track_id -> {"name": str, "last_seen": float}

    # Fallback for untracked detections where box.id is None:
    untracked_memory = []
    MATCH_DISTANCE = 100
    MEMORY_SECONDS = 8
    user_quit = False

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

            # Remove old object memories (tracked objects and untracked fallback)
            tracked_objects = {
                tid: info for tid, info in tracked_objects.items()
                if now - info["last_seen"] < MEMORY_SECONDS
            }
            untracked_memory = [
                item for item in untracked_memory
                if now - item["time"] < MEMORY_SECONDS
            ]

            # Display video without waiting for speech
            try:
                cv2.imshow(
                    "AI Navigation Assistant",
                    result.plot()
                )
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    user_quit = True
                    break
            except cv2.error:
                # If running in a headless environment without GUI support
                pass

            boxes = result.boxes

            if boxes is None or len(boxes) == 0:
                continue

            # Each untracked detection can match only one memory per frame
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

                # 1. Native ByteTrack tracking via box.id
                if box.id is not None:
                    track_id = int(box.id[0])

                    if track_id not in tracked_objects:
                        # New tracked object: record and announce
                        tracked_objects[track_id] = {
                            "name": object_name,
                            "last_seen": now
                        }
                        message = f"{object_name} detected"
                        print(f"NEW OBJECT (track {track_id}):", message)
                        announce(message)
                    else:
                        # Existing tracked object: refresh last_seen timestamp
                        tracked_objects[track_id]["last_seen"] = now

                # 2. Centroid-matching fallback for detections without a track ID
                else:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().tolist()
                    center_x = (x1 + x2) / 2
                    center_y = (y1 + y2) / 2

                    best_index = None
                    best_distance = MATCH_DISTANCE

                    for index, item in enumerate(untracked_memory):
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
                        # Existing object: update position and timestamp
                        item = untracked_memory[best_index]
                        item["x"] = center_x
                        item["y"] = center_y
                        item["time"] = now
                        matched_memories.add(best_index)
                    else:
                        # New object: remember and announce
                        untracked_memory.append({
                            "name": object_name,
                            "x": center_x,
                            "y": center_y,
                            "time": now
                        })
                        matched_memories.add(len(untracked_memory) - 1)

                        message = f"{object_name} detected"
                        print("NEW OBJECT:", message)
                        announce(message)

    finally:
        cap.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass

        if user_quit:
            # User pressed 'q': discard remaining audio queue to exit immediately
            while not voice_queue.empty():
                try:
                    voice_queue.get_nowait()
                    voice_queue.task_done()
                except queue.Empty:
                    break
        else:
            # Video finished: let queued announcements finish
            voice_queue.join()

        # Safely signal and stop worker thread
        if voice_thread.is_alive():
            voice_queue.put(stop_speech)
            voice_thread.join()

        print("AI Navigation Assistant stopped")


if __name__ == "__main__":
    main()