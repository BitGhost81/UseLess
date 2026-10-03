import tkinter as tk
from pynput import keyboard
import threading
import time
import ctypes
import logging
import platform

from PIL import Image, ImageDraw
from logging_utils import configure_logging, read_recent_logs

logger = configure_logging()

try:
    import pystray
except Exception:
    pystray = None
    logger.exception("System tray import failed; install pystray to enable the tray")

from ai_logic import get_ai_answer, set_active_gear
from led_control import blink_caps_lock

# Windows-specific constants for non-focus-stealing window
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008

class ExamHelperApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Helper")
        self.root.geometry("200x100+50+50")
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
            font=("Consolas", 14, "bold")
        )
        self.label.pack(expand=True)

        # Initially hide the window
        self.root.withdraw()

        self.is_visible = False
        self._shutdown = False
        self.tray_icon = None
        self.tray_thread = None

        # Prevent repeated hotkey presses from starting overlapping API calls.
        self._solve_lock = threading.Lock()
        self._cooldown_seconds = 0.5
        self._last_solve_finished = 0.0
        # Answers are session-only and are never sent back to Gemini.
        self._history_lock = threading.Lock()
        self._answer_history = []
        self._history_index = -1
        self.setup_windows_attributes()

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

    def _tray_exit(self, icon, item):
        self.root.after(0, self.on_exit)

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

    def _current_answer_display(self):
        with self._history_lock:
            if not self._answer_history:
                return None
            answer = self._answer_history[self._history_index]
            position = self._history_index + 1
            total = len(self._answer_history)
        return f"ANS: {answer} ({position}/{total})"

    def _record_answer(self, answer):
        with self._history_lock:
            self._answer_history.append(answer)
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
            answer = self._answer_history[self._history_index]
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

    def solve_process(self):
        try:
            self.root.after(0, self.update_ui, "Analyzing...", "#ffff00")
            was_visible = self.is_visible
            if not was_visible:
                self.root.after(0, self.root.deiconify)

            # get_ai_answer performs exactly one synchronous Gemini request;
            # no automatic retry is added here for quota or other API errors.
            answer = get_ai_answer()

            if answer in ['A', 'B', 'C', 'D', 'E']:
                display = self._record_answer(answer)
                self.root.after(0, self.update_ui, display, "#00ff00")
                logger.info("Solve request completed with a valid answer")
            else:
                # Failed requests do not change history or replace an answer
                # the user is currently viewing.
                display = self._current_answer_display()
                if display is None:
                    self.root.after(0, self.update_ui, "ANS: ERR", "#ff0000")
                else:
                    self.root.after(0, self.update_ui, display, "#00ff00")
                logger.warning("Solve request completed without a valid answer")

            # Blink LED
            if answer in ['A', 'B', 'C', 'D', 'E']:
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
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.on_exit()


if __name__ == "__main__":
    app = ExamHelperApp()
    app.run()
