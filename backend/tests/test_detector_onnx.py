import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
DETECTOR_PATH = BACKEND_DIR / "detector_onnx.py"


class FakeImage:
    def __init__(self, height, width, channels=3):
        self.shape = (height, width, channels)
        self.ndim = 3


class FakeDnn:
    @staticmethod
    def NMSBoxes(boxes, scores, score_threshold, nms_threshold):
        return list(range(len(boxes)))


fake_cv2 = types.ModuleType("cv2")
fake_cv2.dnn = FakeDnn()
fake_cv2.INTER_LINEAR = 1
fake_cv2.BORDER_CONSTANT = 0
fake_cv2.resize = lambda frame, size, interpolation: FakeImage(
    size[1],
    size[0],
    frame.shape[2],
)
fake_cv2.copyMakeBorder = lambda frame, top, bottom, left, right, border, value: FakeImage(
    frame.shape[0] + top + bottom,
    frame.shape[1] + left + right,
    frame.shape[2],
)

spec = importlib.util.spec_from_file_location("detector_onnx_under_test", DETECTOR_PATH)
detector_module = importlib.util.module_from_spec(spec)
missing_module = object()
previous_cv2 = sys.modules.get("cv2", missing_module)
sys.modules["cv2"] = fake_cv2
try:
    spec.loader.exec_module(detector_module)
finally:
    if previous_cv2 is missing_module:
        sys.modules.pop("cv2", None)
    else:
        sys.modules["cv2"] = previous_cv2


class OnnxOutputParsingTests(unittest.TestCase):
    def make_output(self, orientation):
        predictions = []
        for coordinates, class_id, confidence in (
            ([320, 320, 160, 160], 5, 0.9),
            ([160, 160, 80, 80], 0, 0.8),
        ):
            row = [0.0] * 84
            row[:4] = coordinates
            row[4 + class_id] = confidence
            predictions.append(row)

        if orientation == "channels_first":
            predictions = [list(column) for column in zip(*predictions)]
        return [predictions]

    def test_letterboxes_and_records_padding_for_landscape_frame(self):
        image, scale, pad_left, pad_top = (
            detector_module.ONNXDetector._letterbox(FakeImage(320, 640))
        )
        self.assertEqual(image.shape, (640, 640, 3))
        self.assertEqual(scale, 1.0)
        self.assertEqual(pad_left, 0)
        self.assertEqual(pad_top, 160)

    def test_detect_uses_rgb_normalized_blob_and_forwards_model(self):
        class FakeNet:
            def __init__(self, output):
                self.output = output
                self.input_blob = None

            def setInput(self, blob):
                self.input_blob = blob

            def forward(self):
                return self.output

        row = [0.0] * 84
        row[:4] = [320, 320, 160, 160]
        row[4 + 5] = 0.9
        net = FakeNet([[row]])
        detector = detector_module.ONNXDetector.__new__(
            detector_module.ONNXDetector
        )
        detector.net = net
        blob_options = {}

        def fake_blob(image, **kwargs):
            blob_options.update(kwargs)
            return "prepared-input"

        with patch.object(
            fake_cv2.dnn,
            "blobFromImage",
            side_effect=fake_blob,
            create=True,
        ):
            detections = detector.detect(FakeImage(640, 640))

        self.assertEqual(net.input_blob, "prepared-input")
        self.assertEqual(
            blob_options,
            {
                "scalefactor": 1.0 / 255.0,
                "size": (640, 640),
                "swapRB": True,
                "crop": False,
            },
        )
        self.assertEqual(detections[0]["class_name"], "bus")

    def test_parses_channels_first_yolo11_output_into_contract(self):
        detections = detector_module.ONNXDetector._parse_output(
            self.make_output("channels_first"),
            original_width=640,
            original_height=640,
            scale=1.0,
            pad_left=0,
            pad_top=0,
        )
        self.assertEqual(
            [item["class_name"] for item in detections],
            ["bus", "person"],
        )
        self.assertEqual(detections[0]["box"], [0.375, 0.375, 0.25, 0.25])
        self.assertEqual(
            set(detections[0]),
            {"label", "class_name", "confidence", "box", "level"},
        )

    def test_parses_channels_last_output(self):
        detections = detector_module.ONNXDetector._parse_output(
            self.make_output("channels_last"),
            original_width=640,
            original_height=640,
            scale=1.0,
            pad_left=0,
            pad_top=0,
        )
        self.assertEqual(len(detections), 2)
        self.assertEqual(detections[0]["class_name"], "bus")

    def test_reverses_letterbox_padding_and_clips_boxes(self):
        row = [0.0] * 84
        row[:4] = [320, 320, 640, 640]
        row[4 + 5] = 0.9
        output = [[list(column) for column in zip(row)]]
        detections = detector_module.ONNXDetector._parse_output(
            output,
            original_width=640,
            original_height=320,
            scale=1.0,
            pad_left=0,
            pad_top=160,
        )
        self.assertEqual(detections[0]["box"], [0.0, 0.0, 1.0, 1.0])

    def test_rejects_unrecognized_output_channels(self):
        with self.assertRaisesRegex(ValueError, "84 channels"):
            detector_module.ONNXDetector._parse_output(
                [[[0.0] * 10 for _ in range(85)]],
                original_width=640,
                original_height=640,
                scale=1.0,
                pad_left=0,
                pad_top=0,
            )

    def test_filters_low_confidence_rows(self):
        row = [0.0] * 84
        row[:4] = [320, 320, 100, 100]
        row[4 + 5] = 0.2
        output = [[list(column) for column in zip(row)]]
        self.assertEqual(
            detector_module.ONNXDetector._parse_output(
                output,
                original_width=640,
                original_height=640,
                scale=1.0,
                pad_left=0,
                pad_top=0,
            ),
            [],
        )

    def test_flattens_opencv_nms_return_shapes(self):
        self.assertEqual(
            detector_module.ONNXDetector._flatten_indices([[0], [2]]),
            [0, 2],
        )


if __name__ == "__main__":
    unittest.main()
