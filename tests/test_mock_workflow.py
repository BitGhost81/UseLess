import logging
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

# Importing main.py normally configures/rotates the user's application log.
# Stub that side effect so these isolated tests leave logs and credentials alone.
logging_stub = types.ModuleType("logging_utils")
logging_stub.configure_logging = lambda: logging.getLogger("mock-test")
logging_stub.mark_session_end = lambda: None
logging_stub.read_recent_logs = lambda: ""
with patch.dict(sys.modules, {"logging_utils": logging_stub}):
    import ai_logic
    import main


class MockWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="useless-test-")
        self.app = main.ExamHelperApp.__new__(main.ExamHelperApp)
        self.app._history_lock = threading.Lock()
        self.app._answer_history = []
        self.app._history_index = -1
        self.app._screenshot_dir = self.scratch
        self.app._screenshot_counter = 0

    def tearDown(self):
        self.scratch.cleanup()

    def test_ai_success_is_simulated_without_provider_call(self):
        fake_image = Image.new("RGB", (32, 24), "red")
        gear = ai_logic.GEARS[1].copy()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-real-key"}), \
             patch.object(ai_logic, "get_active_gear", return_value=(1, gear)), \
             patch.object(ai_logic.PIL.ImageGrab, "grab", return_value=fake_image), \
             patch.object(ai_logic, "_generate_answer", return_value="C") as provider:
            answer, error, screenshot = ai_logic.get_ai_answer_with_details()
        self.assertEqual((answer, error), ("C", None))
        self.assertIs(screenshot, fake_image)
        provider.assert_called_once()

    def test_quota_exception_becomes_friendly_message_without_network(self):
        fake_image = Image.new("RGB", (32, 24), "blue")
        gear = ai_logic.GEARS[1].copy()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-not-a-real-key"}), \
             patch.object(ai_logic, "get_active_gear", return_value=(1, gear)), \
             patch.object(ai_logic.PIL.ImageGrab, "grab", return_value=fake_image), \
             patch.object(ai_logic, "_generate_answer", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")) as provider:
            answer, error, screenshot = ai_logic.get_ai_answer_with_details()
        self.assertEqual(answer, "ERR")
        self.assertIn("LIMIT REACHED", error)
        self.assertIs(screenshot, fake_image)
        provider.assert_called_once()

    def test_answer_history_keeps_400_and_evicts_oldest_screenshot(self):
        first_screenshot = Path(self.scratch.name) / "oldest.jpg"
        first_screenshot.write_bytes(b"test image")
        self.app._record_answer("A", str(first_screenshot))
        for number in range(1, main.MAX_HISTORY_ITEMS + 1):
            self.app._record_answer("B")
        self.assertEqual(len(self.app._answer_history), 400)
        self.assertEqual(self.app._answer_history[0]["answer"], "B")
        self.assertFalse(first_screenshot.exists())
        self.assertIn("(400/400)", self.app._current_answer_display())

    def test_answer_and_screenshot_remain_associated_when_navigating(self):
        red = self.app._save_screenshot_preview(Image.new("RGB", (40, 30), "red"))
        blue = self.app._save_screenshot_preview(Image.new("RGB", (40, 30), "blue"))
        self.app._record_answer("A", red)
        self.app._record_answer("F", blue)
        self.assertIn("ANS: A (1/2)", self.app._navigate_history(-1))
        self.assertEqual(self.app._answer_history[self.app._history_index]["screenshot"], red)
        self.assertTrue(Path(red).is_file())
        self.assertTrue(Path(blue).is_file())

    def test_viewer_opens_the_selected_entry_screenshot(self):
        red = self.app._save_screenshot_preview(Image.new("RGB", (40, 30), "red"))
        blue = self.app._save_screenshot_preview(Image.new("RGB", (40, 30), "blue"))
        self.app._record_answer("A", red)
        self.app._record_answer("F", blue)
        self.app._navigate_history(-1)
        self.app.root = object()

        class FakeWindow:
            def title(self, value):
                self.window_title = value

            def attributes(self, *_args):
                pass

            def geometry(self, value):
                self.window_geometry = value

            def bind(self, sequence, callback):
                self.binding = (sequence, callback)

            def destroy(self):
                self.destroyed = True

        class FakeLabel:
            def pack(self):
                pass

        class FakeButton:
            def __init__(self, _parent, **options):
                self.options = options

            def pack(self, **_options):
                pass

        fake_window = FakeWindow()
        fake_buttons = []

        def make_button(parent, **options):
            button = FakeButton(parent, **options)
            fake_buttons.append(button)
            return button

        opened_paths = []
        original_open = Image.open

        def tracked_open(path):
            opened_paths.append(str(path))
            return original_open(path)

        with patch.object(main.tk, "Toplevel", return_value=fake_window), \
             patch.object(main.tk, "Label", return_value=FakeLabel()), \
             patch.object(main.tk, "Button", side_effect=make_button), \
             patch.object(main.ImageTk, "PhotoImage", return_value=object()), \
             patch.object(main.Image, "open", side_effect=tracked_open):
            self.app.show_current_screenshot()

        self.assertEqual(opened_paths, [red])
        self.assertIn("A (1/2)", fake_window.window_title)
        self.assertEqual(fake_buttons[0].options["text"], "Close screenshot")
        self.assertEqual(fake_window.binding[0], "<Escape>")

    def test_request_worker_uses_mocked_complete_response_tuple(self):
        self.app.root = types.SimpleNamespace(after=lambda *_args: None)
        gear = ai_logic.GEARS[2].copy()
        fake_image = Image.new("RGB", (12, 12), "green")
        with patch.object(main, "get_active_gear", return_value=(2, gear)), \
             patch.object(main, "get_ai_answer_with_details", return_value=("D", None, fake_image)) as fake_request:
            answer, error, screenshot, timed_out = self.app._get_answer_with_timeout()
        self.assertEqual((answer, error, timed_out), ("D", None, False))
        self.assertIs(screenshot, fake_image)
        fake_request.assert_called_once()

    def test_top_right_placement_uses_margin(self):
        geometry = main.top_right_geometry(1920)
        self.assertEqual(geometry, "280x110+1616+24")


if __name__ == "__main__":
    unittest.main()
