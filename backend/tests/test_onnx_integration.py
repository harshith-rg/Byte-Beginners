import os
import importlib.util
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
SAMPLE_IMAGE = BACKEND_DIR / "bus.jpg"
MODEL_PATH = Path(
    os.environ.get(
        "PATHVOICE_ONNX_MODEL",
        str(BACKEND_DIR / "yolo11n.onnx"),
    )
)
INTEGRATION_READY = (
    MODEL_PATH.is_file()
    and importlib.util.find_spec("cv2") is not None
    and importlib.util.find_spec("numpy") is not None
)


class OnnxSampleImageInferenceTests(unittest.TestCase):
    @unittest.skipUnless(
        INTEGRATION_READY,
        "Requires cv2, NumPy, and an exported ONNX model at "
        "PATHVOICE_ONNX_MODEL or backend/yolo11n.onnx.",
    )
    def test_bus_image_produces_real_detections(self):
        import cv2

        from detector_onnx import ONNXDetector

        frame = cv2.imread(str(SAMPLE_IMAGE))
        self.assertIsNotNone(frame, "Could not read backend/bus.jpg")

        detector = ONNXDetector(MODEL_PATH)
        detections = detector.detect(frame)

        self.assertTrue(
            detections,
            "ONNX inference returned no detections for backend/bus.jpg",
        )
        self.assertIn(
            "bus",
            {detection["class_name"] for detection in detections},
            "Expected the sample bus image to include a bus detection.",
        )
        for detection in detections:
            with self.subTest(detection=detection["class_name"]):
                self.assertEqual(
                    set(detection),
                    {"label", "class_name", "confidence", "box", "level"},
                )
                self.assertIsInstance(detection["class_name"], str)
                self.assertTrue(detection["class_name"])
                self.assertGreaterEqual(detection["confidence"], 0.0)
                self.assertLessEqual(detection["confidence"], 1.0)
                self.assertTrue(detection["label"].startswith(
                    f'{detection["class_name"]} '
                ))
                box = detection["box"]
                self.assertEqual(len(box), 4)
                x, y, width, height = box
                self.assertTrue(
                    all(0.0 <= coordinate <= 1.0 for coordinate in box),
                    "Detection boxes must be normalized to 0..1.",
                )
                self.assertGreater(width, 0.0)
                self.assertGreater(height, 0.0)
                self.assertLessEqual(x + width, 1.0001)
                self.assertLessEqual(y + height, 1.0001)


if __name__ == "__main__":
    unittest.main()
