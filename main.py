import tkinter as tk
from pynput import keyboard
import threading
import time
import ctypes
import platform
from ai_logic import get_ai_answer
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
            '<ctrl>+<alt>+<right>': self.show_next_answer
        })
        self.listener.start()

    def setup_windows_attributes(self):
        if platform.system() == "Windows":
            # Use ctypes to set WS_EX_NOACTIVATE
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOPMOST)

    def toggle_overlay(self):
        if self.is_visible:
            self.root.withdraw()
        else:
            self.root.deiconify()
        self.is_visible = not self.is_visible

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
            self.root.after(0, self.update_ui, display, "#00ff00")

    def show_next_answer(self):
        display = self._navigate_history(1)
        if display is not None:
            self.root.after(0, self.update_ui, display, "#00ff00")

    def on_solve(self):
        # GlobalHotKeys can invoke this callback repeatedly while a request is
        # still running. Acquire before starting the worker so only one
        # screenshot submission can be in flight at a time.
        if not self._solve_lock.acquire(blocking=False):
            return

        now = time.monotonic()
        if now - self._last_solve_finished < self._cooldown_seconds:
            self._solve_lock.release()
            return

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
            else:
                # Failed requests do not change history or replace an answer
                # the user is currently viewing.
                display = self._current_answer_display()
                if display is None:
                    self.root.after(0, self.update_ui, "ANS: ERR", "#ff0000")
                else:
                    self.root.after(0, self.update_ui, display, "#00ff00")

            # Blink LED
            if answer in ['A', 'B', 'C', 'D', 'E']:
                times = ord(answer) - ord('A') + 1
                blink_caps_lock(times)

            # Auto-hide after 5 seconds only when this solve opened the overlay.
            if not was_visible:
                self.root.after(5000, self.root.withdraw)
        finally:
            self._last_solve_finished = time.monotonic()
            self._solve_lock.release()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = ExamHelperApp()
    app.run()
