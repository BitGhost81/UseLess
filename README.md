# Upgraded BITCH NIGGA

This version of the application has been completely rebuilt to address the flaws you mentioned.

## Key Improvements

1.  **Global Hotkeys**:
    *   `Ctrl + Alt + S`: Triggers the screenshot and AI solving process. This works even when the browser or any other app is in fullscreen.
    *   `Ctrl + Alt + O`: Toggles the visibility of the answer overlay.
2.  **Non-Focus-Stealing Overlay**:
    *   The overlay window uses the Windows `WS_EX_NOACTIVATE` flag. This means when it appears, it **will not** steal focus from your exam window, preventing any "tab change" or "focus lost" detection.
3.  **Upgraded AI Integration**:
    *   Switched to **Gemini 2.0 Flash** for faster and more accurate vision processing.
    *   The prompt is now a robust System Instruction that enforces strict MCQ solving rules and handles multiple questions or non-MCQ content gracefully.
4.  **Caps Lock Blink Logic**:
    *   The blinking logic is more reliable and will always return your Caps Lock to its initial state after the blinking is done.
5.  **Stealth Mode**:
    *   The overlay automatically hides after 5 seconds if it was triggered via hotkey while hidden. You can also manually toggle it with `Ctrl + Alt + O`.

## How to Run

1.  Ensure you have Python installed.
2.  Install dependencies:
    ```bash
    pip install pynput google-generativeai pillow python-dotenv
    ```
3.  Add your `GEMINI_API_KEY` to the `.env` file.
4.  Run the application:
    ```bash
    python main.py
    ```

## Files
- `main.py`: The core application with hotkeys and non-focus GUI.
- `ai_logic.py`: Upgraded Gemini 2.0 Flash integration.
- `led_control.py`: Windows-specific Caps Lock LED control.
- `.env`: Place your API key here.
