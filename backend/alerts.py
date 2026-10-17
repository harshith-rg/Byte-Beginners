import time
from collections import defaultdict, deque
from math import hypot


# Baseline COCO classes plus common labels from custom accessibility models.
BASE_PRIORITY = {
    "car": 5, "truck": 5, "bus": 5, "motorcycle": 5,
    "bicycle": 3, "person": 3, "dog": 3,
    "chair": 2, "bench": 2, "potted plant": 1,
    "stairs": 5, "stair": 5, "pothole": 5, "curb": 4,
    "traffic light": 2, "stop sign": 2, "door": 1,
}


def classify_direction(box, frame_width):
    x1, _, x2, _ = box
    center_x = ((x1 + x2) / 2) / max(1, frame_width)
    if center_x < 0.35:
        return "left"
    if center_x > 0.65:
        return "right"
    return "ahead"


def image_proximity(box, frame_width, frame_height):
    """
    Heuristic based on bounding-box height and image position.
    This is NOT a physical distance measurement.
    """
    x1, y1, x2, y2 = box
    box_h = max(0.0, y2 - y1) / max(1, frame_height)
    bottom = y2 / max(1, frame_height)

    # Large objects low in the image are treated as more visually prominent.
    if box_h >= 0.55 or (box_h >= 0.38 and bottom >= 0.85):
        return "near"
    if box_h >= 0.24 or bottom >= 0.90:
        return "medium"
    return "far"


class AlertEngine:
    """
    Per-client alert engine.

    Navigation message example:
      {"type":"navigation", "instruction":"Turn left at the next street",
       "direction":"left", "active":true}

    The route direction is used as context only; it is not a safe-path guarantee.
    """

    def __init__(self, cooldown=3.0, tracking_window=5):
        self.cooldown = cooldown
        self.last_alert = defaultdict(float)
        self.history = defaultdict(lambda: deque(maxlen=tracking_window))
        self.navigation = {
            "instruction": "",
            "direction": None,
            "active": False,
        }

    def update_navigation(self, message):
        direction = message.get("direction")
        if direction not in (None, "left", "ahead", "right"):
            direction = None
        self.navigation = {
            "instruction": str(message.get("instruction", ""))[:200],
            "direction": direction,
            "active": bool(message.get("active", True)),
        }

    def _approach_trend(self, key, box_height, now):
        hist = self.history[key]
        hist.append((now, box_height))
        if len(hist) < 3:
            return "unknown"

        # Compare recent average with older average, with a minimum time span.
        old = hist[0]
        new = hist[-1]
        if new[0] - old[0] < 0.25:
            return "unknown"

        delta = new[1] - old[1]
        if delta > 0.06:
            return "possibly_approaching"
        if delta < -0.06:
            return "possibly_receding"
        return "stable"

    def process(self, detections, frame_width, frame_height):
        now = time.monotonic()
        candidates = []

        for obj in detections:
            label = str(obj.get("label", "unknown")).lower()
            confidence = float(obj.get("confidence", 0))
            if confidence < 0.40:
                continue

            box = obj.get("box", [])
            if len(box) != 4:
                continue
            x1, y1, x2, y2 = map(float, box)
            if x2 <= x1 or y2 <= y1:
                continue

            direction = classify_direction(box, frame_width)
            proximity = image_proximity(box, frame_width, frame_height)
            box_height = (y2 - y1) / max(1, frame_height)

            # Key by class and region, not a true object identity tracker.
            key = (label, direction)
            trend = self._approach_trend(key, box_height, now)

            priority = BASE_PRIORITY.get(label, 1)
            if proximity == "near":
                priority += 3
            elif proximity == "medium":
                priority += 1

            if trend == "possibly_approaching":
                priority += 2

            # If route guidance indicates a direction, objects in that image
            # region receive a modest boost. Camera orientation must be calibrated.
            nav = self.navigation
            if nav["active"] and nav["direction"] == direction:
                priority += 2

            # Ignore tiny distant detections for these ordinary classes.
            if proximity == "far" and label in {
                "person", "chair", "bench", "dog", "bicycle"
            }:
                continue

            if now - self.last_alert[key] < self.cooldown:
                continue

            sentence = self.make_sentence(label, direction, proximity, trend)
            candidates.append({
                "priority": priority,
                "key": key,
                "text": sentence,
                "object": label,
                "direction": direction,
                "proximity_estimate": proximity,
                "trend_estimate": trend,
                "confidence": round(confidence, 3),
                "navigation_context": nav["instruction"] if nav["active"] else "",
            })

        if not candidates:
            return None

        best = max(candidates, key=lambda item: item["priority"])
        self.last_alert[best["key"]] = now
        best["type"] = "alert"
        return best

    @staticmethod
    def make_sentence(label, direction, proximity, trend):
        if proximity == "near":
            return f"Caution. Possible nearby obstacle {direction}: {label}."
        if trend == "possibly_approaching":
            return f"Caution. {label} ahead on your {direction}, may be getting closer."
        if proximity == "medium":
            return f"{label.capitalize()} {direction}."
        return f"{label.capitalize()} detected {direction}."
