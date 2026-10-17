import asyncio
import base64
import importlib
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
_MISSING_MODULE = object()


def install_modules(replacements):
    originals = {
        name: sys.modules.get(name, _MISSING_MODULE)
        for name in replacements
    }
    sys.modules.update(replacements)
    return originals


def restore_modules(originals):
    for name, module in originals.items():
        if module is _MISSING_MODULE:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class FakeWebSocketDisconnect(Exception):
    pass


class FakeOpenCVError(Exception):
    pass


class FakeFastAPI:
    def __init__(self, title):
        self.title = title
        self.http_routes = {}
        self.websocket_routes = {}
        self.mounts = []

    def get(self, path):
        return lambda function: self.http_routes.setdefault(path, function)

    def websocket(self, path):
        return lambda function: self.websocket_routes.setdefault(path, function)

    def mount(self, path, application, name):
        self.mounts.append((path, application, name))


class FakeStaticFiles:
    def __init__(self, directory, html):
        self.directory = directory
        self.html = html


class FakeDetector:
    def __init__(self, model_path):
        self.model_path = model_path

    def detect(self, frame):
        return [{
            "label": "bus 90%",
            "class_name": "bus",
            "confidence": 0.9,
            "box": [0.1, 0.2, 0.3, 0.4],
            "level": "normal",
        }]


class FakeFrame:
    shape = (24, 32, 3)


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = [messages] if isinstance(messages, str) else messages
        self.accepted = False
        self.replies = []
        self.receive_count = 0

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        self.receive_count += 1
        if self.receive_count <= len(self.messages):
            return self.messages[self.receive_count - 1]
        raise FakeWebSocketDisconnect()

    async def send_json(self, reply):
        self.replies.append(reply)


class BackendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.IMREAD_COLOR = 1
        fake_cv2.error = FakeOpenCVError
        fake_cv2.imdecode = lambda buffer, flag: (
            None if buffer.tobytes() == b"invalid-image" else FakeFrame()
        )

        fake_detector_module = types.ModuleType("detector_onnx")
        fake_detector_module.ONNXDetector = FakeDetector

        fake_fastapi = types.ModuleType("fastapi")
        fake_fastapi.FastAPI = FakeFastAPI
        fake_fastapi.WebSocket = object
        fake_fastapi.WebSocketDisconnect = FakeWebSocketDisconnect
        fake_fastapi.staticfiles = types.ModuleType("fastapi.staticfiles")
        fake_fastapi.staticfiles.StaticFiles = FakeStaticFiles

        cls.original_modules = install_modules({
            "cv2": fake_cv2,
            "detector_onnx": fake_detector_module,
            "fastapi": fake_fastapi,
            "fastapi.staticfiles": fake_fastapi.staticfiles,
        })
        cls.env_patch = patch.dict(
            os.environ,
            {"PATHVOICE_INFERENCE_ENGINE": "onnx"},
        )
        cls.env_patch.start()
        sys.path.insert(0, str(BACKEND_DIR))
        cls.previous_cwd = Path.cwd()
        os.chdir(BACKEND_DIR)
        sys.modules.pop("main", None)
        try:
            cls.app_module = importlib.import_module("main")
        except Exception:
            cls._cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    @classmethod
    def _cleanup(cls):
        sys.modules.pop("main", None)
        if hasattr(cls, "previous_cwd"):
            os.chdir(cls.previous_cwd)
        if str(BACKEND_DIR) in sys.path:
            sys.path.remove(str(BACKEND_DIR))
        if hasattr(cls, "env_patch"):
            cls.env_patch.stop()
        if hasattr(cls, "original_modules"):
            restore_modules(cls.original_modules)

    def test_health_handler_payload(self):
        payload = asyncio.run(self.app_module.health())
        self.assertEqual(
            payload,
            {
                "status": "ok",
                "service": "smart-navigation-backend",
            },
        )
        self.assertIn("/health", self.app_module.app.http_routes)

    def test_default_engine_remains_ultralytics(self):
        fake_ultralytics = types.ModuleType("ultralytics")
        fake_model = object()
        fake_ultralytics.YOLO = lambda model_path: fake_model
        onnx_module = self.app_module
        sys.modules.pop("main", None)
        original_modules = install_modules({
            "ultralytics": fake_ultralytics,
        })
        try:
            with patch.dict(os.environ, {}, clear=True):
                default_module = importlib.import_module("main")
                self.assertEqual(
                    default_module.INFERENCE_ENGINE,
                    "ultralytics",
                )
                self.assertIs(default_module.model, fake_model)
                self.assertIsNone(default_module.detector                )
        finally:
            restore_modules(original_modules)
            sys.modules.pop("main", None)
            sys.modules["main"] = onnx_module

    def test_unknown_engine_fails_instead_of_silently_falling_back(self):
        onnx_module = self.app_module
        sys.modules.pop("main", None)
        try:
            with patch.dict(
                os.environ,
                {"PATHVOICE_INFERENCE_ENGINE": "unknown"},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "must be 'ultralytics' or 'onnx'",
                ):
                    importlib.import_module("main")
        finally:
            sys.modules.pop("main", None)
            sys.modules["main"] = onnx_module

    def test_websocket_frame_response_contract(self):
        websocket = FakeWebSocket(json.dumps({
            "type": "frame",
            "image": base64.b64encode(b"jpeg-data").decode("ascii"),
            "ts": 123,
        }))
        asyncio.run(self.app_module.websocket_endpoint(websocket))
        response = websocket.replies[0]

        self.assertTrue(websocket.accepted)
        self.assertEqual(response["type"], "result")
        self.assertEqual(response["ts"], 123)
        self.assertEqual(response["detections"][0]["class_name"], "bus")
        self.assertEqual(
            set(response),
            {"type", "ts", "detections", "alert", "nav", "stats"},
        )
        self.assertEqual(response["stats"]["frame_width"], 32)
        self.assertEqual(response["stats"]["frame_height"], 24)
        self.assertIn("/ws", self.app_module.app.websocket_routes)

    @staticmethod
    def frame_message(image=b"jpeg-data", ts=123):
        return {
            "type": "frame",
            "image": base64.b64encode(image).decode("ascii"),
            "ts": ts,
        }

    def run_messages(self, *messages):
        websocket = FakeWebSocket(
            [json.dumps(message) for message in messages]
        )
        asyncio.run(self.app_module.websocket_endpoint(websocket))
        return websocket.replies

    def test_describe_uses_latest_successful_frame_without_redetecting(self):
        bus = {
            "label": "bus 90%",
            "class_name": "bus",
            "confidence": 0.9,
            "box": [0.1, 0.2, 0.3, 0.4],
            "level": "normal",
        }
        person = {
            "label": "person 80%",
            "class_name": "person",
            "confidence": 0.8,
            "box": [0.2, 0.3, 0.1, 0.2],
            "level": "normal",
        }
        with patch.object(
            self.app_module,
            "detect_objects",
            side_effect=[[bus], [person]],
        ) as detect:
            replies = self.run_messages(
                self.frame_message(ts=1),
                self.frame_message(ts=2),
                {"type": "describe"},
            )

        self.assertEqual(detect.call_count, 2)
        self.assertEqual(replies[-1]["type"], "describe_result")
        self.assertIn("person (1 detection)", replies[-1]["text"])
        self.assertNotIn("bus", replies[-1]["text"])
        self.assertIn("exact distances", replies[-1]["text"])
        self.assertIn("path is safe", replies[-1]["text"])

    def test_summary_is_a_distinct_count_of_cached_detections(self):
        detections = [
            {
                "label": "person 90%",
                "class_name": "person",
                "confidence": 0.9,
                "box": [0.1, 0.2, 0.3, 0.4],
                "level": "normal",
            },
            {
                "label": "person 80%",
                "class_name": "person",
                "confidence": 0.8,
                "box": [0.2, 0.3, 0.1, 0.2],
                "level": "normal",
            },
            {
                "label": "bus 70%",
                "class_name": "bus",
                "confidence": 0.7,
                "box": [0.3, 0.3, 0.2, 0.2],
                "level": "normal",
            },
        ]
        with patch.object(
            self.app_module,
            "detect_objects",
            return_value=detections,
        ) as detect:
            replies = self.run_messages(
                self.frame_message(),
                {"type": "summary"},
                {"type": "describe"},
            )

        self.assertEqual(detect.call_count, 1)
        summary, description = replies[1], replies[2]
        self.assertEqual(summary["type"], "describe_result")
        self.assertEqual(description["type"], "describe_result")
        self.assertIn("person: 2 detections", summary["text"])
        self.assertIn("bus: 1 detection", summary["text"])
        self.assertIn("In the latest processed frame", description["text"])
        self.assertNotEqual(summary["text"], description["text"])

    def test_summary_and_description_without_frame_explain_how_to_proceed(self):
        replies = self.run_messages(
            {"type": "summary"},
            {"type": "describe"},
        )
        self.assertEqual(
            [reply["type"] for reply in replies],
            ["describe_result", "describe_result"],
        )
        self.assertTrue(
            all(
                "No successfully analyzed camera frame" in reply["text"]
                for reply in replies
            )
        )

    def test_empty_detections_do_not_claim_the_area_is_clear(self):
        with patch.object(self.app_module, "detect_objects", return_value=[]):
            replies = self.run_messages(
                self.frame_message(),
                {"type": "summary"},
                {"type": "describe"},
            )

        self.assertIn(
            "no recognizable objects",
            replies[1]["text"].lower(),
        )
        self.assertIn("does not mean the area is clear", replies[1]["text"])
        self.assertIn(
            "no recognizable objects",
            replies[2]["text"].lower(),
        )
        self.assertIn("does not mean the area is clear", replies[2]["text"])

    def test_invalid_image_returns_error_and_does_not_create_cached_frame(self):
        replies = self.run_messages(
            self.frame_message(image=b"invalid-image"),
            {"type": "describe"},
        )
        self.assertEqual(
            [reply["type"] for reply in replies],
            ["error", "describe_result"],
        )
        self.assertIn("Invalid message", replies[0]["message"])
        self.assertIn(
            "No successfully analyzed camera frame",
            replies[1]["text"],
        )

    def test_detector_error_is_logged_reported_and_not_cached(self):
        with patch.object(
            self.app_module,
            "detect_objects",
            side_effect=RuntimeError("private detector detail"),
        ), self.assertLogs("main", level="ERROR"):
            replies = self.run_messages(
                self.frame_message(),
                {"type": "describe"},
            )

        self.assertEqual(
            [reply["type"] for reply in replies],
            ["error", "describe_result"],
        )
        self.assertIn("Object detection failed", replies[0]["message"])
        self.assertNotIn("private detector detail", replies[0]["message"])
        self.assertIn(
            "No successfully analyzed camera frame",
            replies[1]["text"],
        )

    def test_cached_detections_are_isolated_per_websocket(self):
        with patch.object(
            self.app_module,
            "detect_objects",
            return_value=[{
                "label": "bus 90%",
                "class_name": "bus",
                "confidence": 0.9,
                "box": [0.1, 0.2, 0.3, 0.4],
                "level": "normal",
            }],
        ):
            first_connection = self.run_messages(
                self.frame_message(),
                {"type": "describe"},
            )
            second_connection = self.run_messages({"type": "describe"})

        self.assertIn("bus (1 detection)", first_connection[1]["text"])
        self.assertIn(
            "No successfully analyzed camera frame",
            second_connection[0]["text"],
        )

    def test_destination_acknowledges_entry_without_claiming_navigation(self):
        replies = self.run_messages({
            "type": "set_destination",
            "query": "Central Library",
        })

        self.assertEqual(replies[0]["type"], "describe_result")
        self.assertIn("Destination entered: Central Library", replies[0]["text"])
        self.assertIn(
            "PathVoice does not provide turn-by-turn directions. Use a "
            "dedicated navigation app for route guidance. PathVoice has not "
            "verified your route or its safety.",
            replies[0]["text"],
        )

    def test_repeated_destination_uses_short_navigation_notice(self):
        replies = self.run_messages(
            {"type": "set_destination", "query": "Central Library"},
            {"type": "set_destination", "query": "City Museum"},
        )

        self.assertIn(
            "PathVoice does not provide turn-by-turn directions.",
            replies[0]["text"],
        )
        self.assertIn(
            "Turn-by-turn navigation is not available.",
            replies[1]["text"],
        )
        self.assertNotIn("dedicated navigation app", replies[1]["text"])
        self.assertIn("Destination entered: City Museum", replies[1]["text"])

    def test_empty_destination_is_rejected(self):
        replies = self.run_messages({
            "type": "set_destination",
            "query": "   ",
        })

        self.assertEqual(replies[0]["type"], "error")
        self.assertIn("enter a destination", replies[0]["message"].lower())


if __name__ == "__main__":
    unittest.main()
