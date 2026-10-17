"""CPU inference for a YOLO11n COCO ONNX export using OpenCV DNN."""

from pathlib import Path

import cv2
import numpy as np

IMAGE_SIZE = 640
CLASS_NAMES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
)
OUTPUT_CHANNELS = 4 + len(CLASS_NAMES)
CONFIDENCE_THRESHOLD = 0.35
NMS_THRESHOLD = 0.45


class ONNXDetector:
    """Run a fixed-size YOLO11n COCO ONNX model with OpenCV's CPU backend."""

    def __init__(self, model_path: str | Path) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"ONNX model not found: {self.model_path}. "
                "Set PATHVOICE_ONNX_MODEL to an exported YOLO11n COCO "
                "ONNX model with 640x640 input."
            )

        self.net = cv2.dnn.readNetFromONNX(str(self.model_path))

    def detect(self, frame: np.ndarray) -> list[dict[str, object]]:
        """Return normalized boxes in the same shape as the Ultralytics path."""
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Expected a three-channel BGR image")

        height, width = frame.shape[:2]
        if width < 1 or height < 1:
            raise ValueError("Expected a non-empty BGR image")
        input_image, scale, pad_left, pad_top = self._letterbox(frame)
        blob = cv2.dnn.blobFromImage(
            input_image,
            scalefactor=1.0 / 255.0,
            size=(IMAGE_SIZE, IMAGE_SIZE),
            swapRB=True,
            crop=False,
        )
        self.net.setInput(blob)
        output = self.net.forward()

        return self._parse_output(
            output,
            width,
            height,
            scale,
            pad_left,
            pad_top,
        )

    @staticmethod
    def _letterbox(
        frame: np.ndarray,
    ) -> tuple[np.ndarray, float, int, int]:
        height, width = frame.shape[:2]
        scale = min(IMAGE_SIZE / width, IMAGE_SIZE / height)
        resized_width = int(round(width * scale))
        resized_height = int(round(height * scale))
        resized = cv2.resize(
            frame,
            (resized_width, resized_height),
            interpolation=cv2.INTER_LINEAR,
        )

        pad_width = IMAGE_SIZE - resized_width
        pad_height = IMAGE_SIZE - resized_height
        pad_left = int(round(pad_width / 2 - 0.1))
        pad_right = pad_width - pad_left
        pad_top = int(round(pad_height / 2 - 0.1))
        pad_bottom = pad_height - pad_top
        padded = cv2.copyMakeBorder(
            resized,
            pad_top,
            pad_bottom,
            pad_left,
            pad_right,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )

        return padded, scale, pad_left, pad_top

    @staticmethod
    def _parse_output(
        output: object,
        original_width: int,
        original_height: int,
        scale: float,
        pad_left: int,
        pad_top: int,
    ) -> list[dict[str, object]]:
        """Parse raw YOLO11 COCO output shaped [1,84,N] or [1,N,84]."""
        predictions = output.tolist() if hasattr(output, "tolist") else output
        if not isinstance(predictions, (list, tuple)):
            raise ValueError(
                "Expected a nested YOLO output array"
            )

        if (
            len(predictions) == 1
            and isinstance(predictions[0], (list, tuple))
            and predictions[0]
            and isinstance(predictions[0][0], (list, tuple))
        ):
            predictions = predictions[0]

        if not predictions or not isinstance(predictions[0], (list, tuple)):
            raise ValueError("Expected a 2D YOLO output after batch removal")

        first_row_length = len(predictions[0])
        if len(predictions) == OUTPUT_CHANNELS and first_row_length != OUTPUT_CHANNELS:
            predictions = [list(row) for row in zip(*predictions)]
        elif first_row_length != OUTPUT_CHANNELS:
            raise ValueError(
                "Expected raw YOLO11 COCO output with 84 channels "
                "(4 box values + 80 class scores)"
            )

        boxes: list[list[int]] = []
        scores: list[float] = []
        class_ids: list[int] = []
        normalized_boxes: list[list[float]] = []

        for row in predictions:
            class_scores = row[4:]
            class_id = max(
                range(len(class_scores)),
                key=class_scores.__getitem__,
            )
            confidence = float(class_scores[class_id])
            if confidence < CONFIDENCE_THRESHOLD:
                continue

            center_x, center_y, box_width, box_height = (
                float(value) for value in row[:4]
            )
            x1 = (center_x - box_width / 2 - pad_left) / scale
            y1 = (center_y - box_height / 2 - pad_top) / scale
            x2 = (center_x + box_width / 2 - pad_left) / scale
            y2 = (center_y + box_height / 2 - pad_top) / scale

            x1 = min(max(x1, 0.0), float(original_width))
            y1 = min(max(y1, 0.0), float(original_height))
            x2 = min(max(x2, 0.0), float(original_width))
            y2 = min(max(y2, 0.0), float(original_height))
            if x2 <= x1 or y2 <= y1:
                continue

            boxes.append([
                round(x1),
                round(y1),
                round(x2 - x1),
                round(y2 - y1),
            ])
            scores.append(confidence)
            class_ids.append(class_id)
            normalized_boxes.append([
                x1 / original_width,
                y1 / original_height,
                (x2 - x1) / original_width,
                (y2 - y1) / original_height,
            ])

        kept: list[int] = []
        for class_id in set(class_ids):
            class_indices = [
                index for index, candidate_class in enumerate(class_ids)
                if candidate_class == class_id
            ]
            local_indices = cv2.dnn.NMSBoxes(
                [boxes[index] for index in class_indices],
                [scores[index] for index in class_indices],
                CONFIDENCE_THRESHOLD,
                NMS_THRESHOLD,
            )
            kept.extend(
                class_indices[index]
                for index in ONNXDetector._flatten_indices(local_indices)
            )

        detections = []
        for index in kept:
            class_name = CLASS_NAMES[class_ids[index]]
            confidence = scores[index]
            detections.append({
                "label": f"{class_name} {confidence:.0%}",
                "class_name": class_name,
                "confidence": round(confidence, 3),
                "box": [round(value, 4) for value in normalized_boxes[index]],
                "level": "normal",
            })

        detections.sort(key=lambda detection: detection["confidence"], reverse=True)
        return detections

    @staticmethod
    def _flatten_indices(indices: object) -> list[int]:
        if indices is None:
            return []
        if hasattr(indices, "tolist"):
            indices = indices.tolist()
        if isinstance(indices, (list, tuple)):
            flattened: list[int] = []
            for index in indices:
                flattened.extend(ONNXDetector._flatten_indices(index))
            return flattened
        if hasattr(indices, "item"):
            indices = indices.item()
        return [int(indices)]
