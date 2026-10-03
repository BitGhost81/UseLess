# UseLess

This is a Windows desktop helper that captures the entire screen and sends it to Gemini for a multiple-choice answer.

## Key Improvements

1.  **Global Hotkeys**:
    *   `Ctrl + Alt + S`: Captures the screen and starts one AI-solving request. Further presses are ignored while that request is running, with a short cooldown afterward.
    *   `Ctrl + Alt + O`: Toggles the answer overlay.
2.  **Non-Focus-Stealing Overlay**:
    *   The overlay window uses the Windows `WS_EX_NOACTIVATE` flag. This means when it appears, it **will not** steal focus from your exam window, preventing any "tab change" or "focus lost" detection.
3.  **AI Integration**:
    *   Uses **`gemini-2.5-flash`**, configured in `ai_logic.py`.
    *   The prompt asks for only the answer letter and handles multiple questions or non-MCQ content gracefully.
4.  **Caps Lock Blink Logic**:
    *   The blinking logic is more reliable and will always return your Caps Lock to its initial state after the blinking is done.
5.  **Stealth Mode**:
    *   The overlay automatically hides after 5 seconds when it was opened by `Ctrl + Alt + S`. You can also manually toggle it with `Ctrl + Alt + O`.

## How to Run

1.  Ensure you have Python installed.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Add your `GEMINI_API_KEY` to the `.env` file.
    For Gear 5, also add `GROQ_API_KEY`:
    ```env
    GEMINI_API_KEY=your_gemini_key_here
    GROQ_API_KEY=
    ```
4.  Run the application:
    ```bash
    python main.py
    ```
    `python main.py` is useful for development/debugging. On Windows it starts normally, then hides its console window while keeping the process and tray icon running. Use the tray's `Show/Hide Console` item to temporarily show or hide that console.

    For normal background/tray usage, use:
    ```bash
    pythonw main.py
    ```
    `pythonw main.py` remains the cleanest way to launch without a console.

The application places a UseLess icon in the Windows system tray. Its menu provides `Show/Hide Overlay`, `Show/Hide Console`, `View Logs`, and `Exit`. `View Logs` opens the current session from `logs/useless.log`. At startup, the previous current log is archived as a timestamped `logs/useless_*.log` file; the ten most recent archived sessions are retained. The current log is also protected by the existing size-based rotation. Logs do not record API keys, screenshots, prompts, or image contents.

## How to use

1. Open the question or other content to analyze.
2. Press `Ctrl + Alt + S`. The overlay shows `Analyzing...` while the single Gemini request is running.
3. Read the returned answer (`A`–`E`) in the overlay. A valid answer also blinks Caps Lock that many times.
4. Use `Ctrl + Alt + Left` and `Ctrl + Alt + Right` to view previous or newer answers from the current session. The indicator shows the current position, for example `ANS: C (3/7)`.
5. Press `Ctrl + Alt + O` to show or hide the overlay manually.

### Manual AI gears

The active gear is selected manually and remains active until changed. There is no automatic provider fallback or cycling.

| Hotkey | Gear | Provider/model |
|---|---|---|
| `Ctrl + Alt + 1` | Gear 1 | Google Gemini / `gemini-2.5-flash` |
| `Ctrl + Alt + 2` | Gear 2 | Google Gemini / `gemini-2.5-flash-lite` |
| `Ctrl + Alt + 3` | Gear 3 | Google Gemini / `gemini-3.5-flash` |
| `Ctrl + Alt + 4` | Gear 4 | Google Gemini / `gemini-3.5-flash-lite` |
| `Ctrl + Alt + 5` | Gear 5 | Groq / `qwen/qwen3.8-27b` |

After selection, the overlay briefly shows the selected gear. The next `Ctrl + Alt + S` request goes directly to that gear. Errors do not switch gears automatically. Gear selection and provider/model request timing are written to the local log without API keys.

Answer history is kept only in memory for the current run. Navigating it never calls Gemini. A new successful screenshot request is appended and becomes the latest answer. Previous/next navigation stops at the oldest/newest answer and does not wrap. Failed requests are not added to history; if an earlier answer exists, it remains displayed. The current implementation has no normal chat input, screenshot file upload, cancel action, retry button, conversation reset, or keyboard shortcut for cancellation. API and quota failures are shown as `ERR` only when there is no earlier answer; the application does not automatically retry them.

Only `main.py` is the documented entry point. `overlay.py` is an older standalone GUI that contains a second Gemini integration; running it separately would create its own API requests and should not be used alongside `main.py`.

## Files
- `main.py`: The core application with hotkeys, request-state protection, and non-focus GUI.
- `ai_logic.py`: Gemini `gemini-2.5-flash` integration and full-screen capture.
- `led_control.py`: Windows-specific Caps Lock LED control.
- `overlay.py`: Legacy standalone GUI; not used by `main.py`.
- `.env`: Place your API key here.
