import tkinter as tk
from pynput import keyboard
import threading
import time
import ctypes
import logging
import platform
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageTk
from logging_utils import configure_logging, mark_session_end, read_recent_logs

logger = configure_logging()

try:
    import pystray
except Exception:
    pystray = None
    logger.exception("System tray import failed; install pystray to enable the tray")

from ai_logic import get_active_gear, get_ai_answer_with_details, set_active_gear
from led_control import blink_caps_lock

# Windows-specific constants for non-focus-stealing window
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
SW_HIDE = 0
SW_SHOW = 5
REQUEST_TIMEOUT_SECONDS = 60
MAX_HISTORY_ITEMS = 400
VALID_ANSWERS = frozenset("ABCDEF")


def top_right_geometry(screen_width, overlay_width=280, overlay_height=110, margin=24):
    x_position = max(0, screen_width - overlay_width - margin)
    return f"{overlay_width}x{overlay_height}+{x_position}+{margin}"


class ExamHelperApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Helper")
        self.root.geometry(top_right_geometry(self.root.winfo_screenwidth()))
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.9)
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

        self.frame = tk.Frame(self.root, bg="#1e1e1e", bd=2, relief="ridge")
        self.frame.pack(expand=True, fill="both")

        self.label = tk.Label(
            self.frame,
            text="IDLE",
            fg="#00ff00",
            bg="#1e1e1e",
            font=("Consolas", 14, "bold"),
            wraplength=210,
            justify="center",
        )
        self.label.pack(side="left", expand=True, fill="both", padx=(8, 0))
        self.show_screenshot_button = tk.Button(
            self.frame, text="▾", command=self.show_current_screenshot,
            fg="#eeeeee", bg="#333333", activebackground="#555555",
            relief="flat", font=("Segoe UI Symbol", 13, "bold"),
            takefocus=False, cursor="hand2", state="disabled",
        )
        self.show_screenshot_button.pack(side="right", padx=6)

        # Initially hide the window
        self.root.withdraw()

        self.is_visible = False
        self._shutdown = False
        self.tray_icon = None
        self.tray_thread = None
        self._console_hwnd = None
        self._console_visible = True

        # Prevent repeated hotkey presses from starting overlapping API calls.
        self._solve_lock = threading.Lock()
        self._cooldown_seconds = 0.5
        self._last_solve_finished = 0.0
        # Answers are session-only and are never sent back to Gemini.
        self._history_lock = threading.Lock()
        self._answer_history = []
        self._history_index = -1
        self._screenshot_dir = tempfile.TemporaryDirectory(prefix="useless-session-")
        self._screenshot_counter = 0
        self.setup_windows_attributes()
        self.hide_console_on_windows()

        # Start hotkey listener
        self.listener = keyboard.GlobalHotKeys({
            '<ctrl>+<alt>+s': self.on_solve,
            '<ctrl>+<alt>+o': self.toggle_overlay,
            '<ctrl>+<alt>+<left>': self.show_previous_answer,
            '<ctrl>+<alt>+<right>': self.show_next_answer,
            '<ctrl>+<alt>+1': lambda: self.select_gear(1),
            '<ctrl>+<alt>+2': lambda: self.select_gear(2),
            '<ctrl>+<alt>+3': lambda: self.select_gear(3),
            '<ctrl>+<alt>+4': lambda: self.select_gear(4),
            '<ctrl>+<alt>+5': lambda: self.select_gear(5),
        })
        self.listener.start()
        self._start_tray()
        logger.info("Application started")

    def setup_windows_attributes(self):
        if platform.system() == "Windows":
            # Use ctypes to set WS_EX_NOACTIVATE
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                style | WS_EX_NOACTIVATE | WS_EX_TOPMOST,
            )

    def _make_tray_image(self):
        try:
            image = Image.new("RGBA", (64, 64), (30, 30, 30, 255))
            draw = ImageDraw.Draw(image)
            draw.ellipse((8, 8, 56, 56), fill=(0, 170, 102, 255), outline=(0, 255, 0, 255), width=3)
            draw.text((25, 19), "U", fill=(255, 255, 255, 255))
            return image
        except Exception:
            logger.exception("Generated tray icon failed; using fallback icon")
            return Image.new("RGBA", (32, 32), (0, 170, 102, 255))

    def _start_tray(self):
        if pystray is None:
            logger.error("System tray unavailable because pystray could not be imported")
            return

        try:
            menu = pystray.Menu(
                pystray.MenuItem("Show/Hide Overlay", self._tray_toggle_overlay),
                pystray.MenuItem("Show/Hide Console", self._tray_toggle_console),
                pystray.MenuItem("View Logs", self._tray_view_logs),
                pystray.MenuItem("Exit", self._tray_exit),
            )
            self.tray_icon = pystray.Icon(
                "useless",
                self._make_tray_image(),
                "UseLess",
                menu,
            )
            self.tray_thread = threading.Thread(
                target=self._run_tray,
                name="UseLessTray",
                daemon=False,
            )
            self.tray_thread.start()
            logger.info("System tray icon started")
        except Exception:
            self.tray_icon = None
            self.tray_thread = None
            logger.exception("System tray initialization failed")

    def _run_tray(self):
        try:
            self.tray_icon.run()
        except Exception:
            logger.exception("System tray stopped unexpectedly")

    def _tray_toggle_overlay(self, icon, item):
        self.root.after(0, self.toggle_overlay)

    def _tray_view_logs(self, icon, item):
        self.root.after(0, self.show_logs)

    def _tray_toggle_console(self, icon, item):
        self.root.after(0, self.toggle_console)

    def _tray_exit(self, icon, item):
        self.root.after(0, self.on_exit)

    def hide_console_on_windows(self):
        if platform.system() != "Windows":
            return
        try:
            self._console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if self._console_hwnd:
                ctypes.windll.user32.ShowWindow(self._console_hwnd, SW_HIDE)
                self._console_visible = False
                logger.info("Windows console hidden at startup")
        except Exception:
            logger.exception("Unable to hide the Windows console at startup")

    def toggle_console(self):
        if platform.system() != "Windows":
            logger.info("Console visibility toggle ignored: not running on Windows")
            return
        try:
            if not self._console_hwnd:
                self._console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if not self._console_hwnd:
                logger.info("Console visibility toggle ignored: no attached console")
                return
            self._console_visible = not self._console_visible
            ctypes.windll.user32.ShowWindow(
                self._console_hwnd,
                SW_SHOW if self._console_visible else SW_HIDE,
            )
            logger.info("Windows console visibility changed: visible=%s", self._console_visible)
        except Exception:
            logger.exception("Unable to change Windows console visibility")

    def toggle_overlay(self):
        if self.is_visible:
            self.root.withdraw()
        else:
            self.root.deiconify()
        self.is_visible = not self.is_visible
        logger.info("Overlay visibility changed: visible=%s", self.is_visible)

    def show_logs(self):
        logger.info("Log viewer opened")
        window = tk.Toplevel(self.root)
        window.title("UseLess Logs")
        window.geometry("800x500")
        window.attributes("-topmost", True)

        text = tk.Text(window, wrap="none", bg="#111111", fg="#eeeeee")
        scrollbar = tk.Scrollbar(window, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", expand=True, fill="both")
        scrollbar.pack(side="right", fill="y")
        text.insert("1.0", read_recent_logs())
        text.configure(state="disabled")
        text.see("end")

    def select_gear(self, gear_number):
        try:
            selected_number, gear = set_active_gear(gear_number)
        except ValueError:
            logger.exception("Unable to select gear: %s", gear_number)
            return

        logger.info(
            "Active gear changed: Gear %s - %s / %s",
            selected_number,
            gear["provider"],
            gear["model"],
        )
        status = f"GEAR {selected_number}\n{gear['model']} / {gear['provider']}"
        self.root.after(0, self.update_ui, status, "#00ccff")
        self.root.after(1800, self.restore_normal_display)

    def restore_normal_display(self):
        if self._solve_lock.locked():
            self.update_ui("Analyzing...", "#ffff00")
            return
        self.update_ui(self._current_answer_display() or "IDLE")

    def update_ui(self, text, color="#00ff00"):
        self.label.config(text=text, fg=color)

    def _save_screenshot_preview(self, screenshot):
        if screenshot is None:
            return None
        try:
            preview = screenshot.copy()
            preview.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
            self._screenshot_counter += 1
            path = Path(self._screenshot_dir.name) / f"question_{self._screenshot_counter:04d}.jpg"
            preview.convert("RGB").save(path, format="JPEG", quality=82, optimize=True)
            return str(path)
        except Exception:
            logger.exception("Unable to save local screenshot preview")
            return None

    def show_current_screenshot(self):
        with self._history_lock:
            if not self._answer_history or self._history_index < 0:
                return
            entry = self._answer_history[self._history_index]
            position, total = self._history_index + 1, len(self._answer_history)
        image_path = entry.get("screenshot")
        if not image_path or not Path(image_path).is_file():
            self.update_ui("SCREENSHOT UNAVAILABLE", "#ff9900")
            return
        try:
            with Image.open(image_path) as source_image:
                image = source_image.copy()
            image.thumbnail((1200, 900), Image.Resampling.LANCZOS)
            window = tk.Toplevel(self.root)
            window.title(f"Question screenshot — {entry['answer']} ({position}/{total})")
            window.attributes("-topmost", True)
            photo = ImageTk.PhotoImage(image)
            display = tk.Label(window, image=photo, bg="#111111")
            display.image = photo
            display.pack()
            close_button = tk.Button(
                window,
                text="Close screenshot",
                command=window.destroy,
                takefocus=True,
                padx=12,
                pady=4,
            )
            close_button.pack(pady=6)
            window.bind("<Escape>", lambda _event: window.destroy())
            window.geometry(f"{image.width}x{image.height + 48}")
        except Exception:
            logger.exception("Unable to display screenshot preview")
            self.update_ui("SCREENSHOT VIEW FAILED", "#ff9900")

    def _current_answer_display(self):
        with self._history_lock:
            if not self._answer_history:
                return None
            answer = self._answer_history[self._history_index]["answer"]
            position = self._history_index + 1
            total = len(self._answer_history)
        return f"ANS: {answer} ({position}/{total})"

    def _record_answer(self, answer, screenshot_path=None):
        with self._history_lock:
            self._answer_history.append({"answer": answer, "screenshot": screenshot_path})
            if len(self._answer_history) > MAX_HISTORY_ITEMS:
                evicted = self._answer_history.pop(0)
                if evicted.get("screenshot"):
                    try:
                        Path(evicted["screenshot"]).unlink(missing_ok=True)
                    except OSError:
                        logger.exception("Unable to remove expired screenshot preview")
            self._history_index = len(self._answer_history) - 1
            position = self._history_index + 1
            total = len(self._answer_history)
        return f"ANS: {answer} ({position}/{total})"

    def _navigate_history(self, step):
        with self._history_lock:
            if not self._answer_history:
                return None
            new_index = self._history_index + step
            if new_index < 0 or new_index >= len(self._answer_history):
                return None
            self._history_index = new_index
            answer = self._answer_history[self._history_index]["answer"]
            position = self._history_index + 1
            total = len(self._answer_history)
        return f"ANS: {answer} ({position}/{total})"

    def show_previous_answer(self):
        display = self._navigate_history(-1)
        if display is not None:
            logger.info("Answer history navigation: previous, index=%s", self._history_index + 1)
            self.root.after(0, self.update_ui, display, "#00ff00")

    def show_next_answer(self):
        display = self._navigate_history(1)
        if display is not None:
            logger.info("Answer history navigation: next, index=%s", self._history_index + 1)
            self.root.after(0, self.update_ui, display, "#00ff00")

    def on_solve(self):
        # GlobalHotKeys can invoke this callback repeatedly while a request is
        # still running. Acquire before starting the worker so only one
        # screenshot submission can be in flight at a time.
        if not self._solve_lock.acquire(blocking=False):
            logger.info("Solve request ignored: another request is in progress")
            return

        now = time.monotonic()
        if now - self._last_solve_finished < self._cooldown_seconds:
            logger.info("Solve request ignored: cooldown active")
            self._solve_lock.release()
            return

        logger.info("Solve request accepted")
        threading.Thread(target=self.solve_process, daemon=True).start()

    def _get_answer_with_timeout(self):
        result = {}
        completed = threading.Event()
        request_started_at = datetime.now(timezone.utc)
        gear_number, gear = get_active_gear()

        def request_worker():
            try:
                result["answer"], result["error"], result["screenshot"] = get_ai_answer_with_details()
            except Exception:
                logger.exception("Unexpected AI worker error")
                result["answer"] = "ERR"
                result["error"] = "AI REQUEST FAILED\nCheck the selected gear and local logs."
            finally:
                completed.set()

        threading.Thread(
            target=request_worker,
            name="UseLessAIRequest",
            daemon=True,
        ).start()

        if completed.wait(REQUEST_TIMEOUT_SECONDS):
            return result.get("answer", "ERR"), result.get("error"), result.get("screenshot"), False

        timeout_at = datetime.now(timezone.utc)
        logger.error(
            "AI request timeout: gear=%s provider=%s model=%s timeout_seconds=%s request_start=%s timeout_time=%s",
            gear_number,
            gear["provider"],
            gear["model"],
            REQUEST_TIMEOUT_SECONDS,
            request_started_at.isoformat(),
            timeout_at.isoformat(),
        )
        self.root.after(0, self._show_timeout)
        return None, None, None, True

    def _show_timeout(self):
        current = self._current_answer_display()
        timeout_display = f"TIMEOUT ({REQUEST_TIMEOUT_SECONDS}s)"
        if current is not None:
            timeout_display = f"{timeout_display}\n{current}"
        self.update_ui(timeout_display, "#ff0000")

    def solve_process(self):
        try:
            self.root.after(0, self.update_ui, "Analyzing...", "#ffff00")
            was_visible = self.is_visible
            if not was_visible:
                self.root.after(0, self.root.deiconify)

            # The watchdog abandons only the application-level wait. A late
            # worker result is kept local and cannot update UI or history.
            answer, error_message, screenshot, timed_out = self._get_answer_with_timeout()
            if timed_out:
                return

            if answer in VALID_ANSWERS:
                screenshot_path = self._save_screenshot_preview(screenshot)
                display = self._record_answer(answer, screenshot_path)
                self.root.after(0, lambda: self.show_screenshot_button.config(
                    state="normal" if screenshot_path else "disabled"
                ))
                self.root.after(0, self.update_ui, display, "#00ff00")
                logger.info("Solve request completed with a valid answer")
            else:
                # Surface the current failure; never let an older answer appear to be fresh.
                error_message = error_message or "AI REQUEST FAILED\nCheck the selected gear and local logs."
                self.root.after(0, lambda: self.show_screenshot_button.config(state="disabled"))
                self.root.after(0, self.update_ui, error_message, "#ff5555")
                logger.warning("Solve request failed visibly: %s", error_message.splitlines()[0])

            # Blink LED
            if answer in VALID_ANSWERS:
                times = ord(answer) - ord('A') + 1
                blink_caps_lock(times)

            # Auto-hide after 5 seconds only when this solve opened the overlay.
            if not was_visible:
                self.root.after(5000, self.root.withdraw)
        except Exception:
            logger.exception("Unhandled solve-process error")
        finally:
            self._last_solve_finished = time.monotonic()
            self._solve_lock.release()

    def on_exit(self):
        if self._shutdown:
            return
        self._shutdown = True
        logger.info("Application shutting down")
        try:
            self.listener.stop()
        except Exception:
            logger.exception("Error stopping global hotkey listener")
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                logger.exception("Error stopping system tray icon")
        logger.info("Application shutdown complete")
        mark_session_end()
        try:
            self._screenshot_dir.cleanup()
        except Exception:
            logger.exception("Unable to clean up temporary session screenshots")
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.on_exit()


if __name__ == "__main__":
    app = ExamHelperApp()
    app.run()
