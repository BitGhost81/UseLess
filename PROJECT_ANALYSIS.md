# UseLess Project Audit

## 1. Architecture overview

The documented entry point is `main.py`:

1. `pynput.keyboard.GlobalHotKeys` registers `Ctrl + Alt + S` and `Ctrl + Alt + O`.
2. `Ctrl + Alt + S` starts `ExamHelperApp.solve_process()` on a daemon thread.
3. `solve_process()` updates the Tkinter overlay, then calls `ai_logic.get_ai_answer()`.
4. `ai_logic.py` captures the entire screen with `PIL.ImageGrab.grab()`.
5. The screenshot is sent once through the `google.genai` client using `client.models.generate_content(...)`.
6. The returned text is normalized and reduced to the first valid answer letter (`A`–`E`), or `ERR`.
7. `main.py` displays the result and blinks Caps Lock once per answer-letter position.
8. The overlay is hidden after five seconds when the solve action opened it.

`overlay.py` is a separate, older standalone Tkinter application. It has its own Gemini model, screenshot capture, and Solve button. It is not imported by `main.py` and is not the documented entry point.

## 2. Root cause of API-limit usage

### Primary cause: overlapping hotkey requests

Before the change, `main.py:on_solve()` unconditionally started a new daemon thread:

```python
threading.Thread(target=self.solve_process, daemon=True).start()
```

Every `Ctrl + Alt + S` press could therefore start another `solve_process()` while an earlier Gemini request was still running. Each worker reached `ai_logic.py:get_ai_answer()` and called:

```python
response = model.generate_content([screenshot])
```

A single accidental burst of hotkey presses could produce multiple simultaneous Gemini requests. There was no in-flight flag, lock, disabled state, debounce, or cooldown.

### Secondary cause: two independent application entry points

Gemini is called in two places:

- `ai_logic.py:35` — used by the documented `main.py` hotkey path.
- `overlay.py:34` — used only when the legacy standalone `overlay.py` program is run.

Launching both programs, or repeatedly launching `overlay.py`, can consume quota through the second integration. `overlay.py` is not part of the `main.py` execution path.

### What is not causing repeated usage

The code audit found no evidence of the following in the documented path:

- React/component re-renders — this is a Tkinter desktop app, not React.
- `useEffect`-style behavior.
- Automatic retries or exponential backoff.
- Polling loops.
- Chat history or prior image resends.
- Multi-turn conversation state.
- File-upload retry loops.
- API calls from `led_control.py`.
- A loop around `generate_content()`.

## 3. Problems found, ranked

### CRITICAL

- **No request gate in the original hotkey path.** Repeated hotkey events could create concurrent Gemini calls. This was the most direct accidental quota-spam mechanism.

### HIGH

- **Two Gemini integrations exist.** `overlay.py` is a legacy duplicate entry point. It can generate additional requests if run separately or alongside `main.py`.
- **The application sends the full screen for every solve.** This is simple and preserves context, but can produce a large vision payload and may include irrelevant UI or the answer overlay itself.

### MEDIUM

- **No image resizing or compression.** This may increase vision-token usage and latency on high-resolution or multi-monitor setups. It should be optimized only with care because aggressive resizing can make question text unreadable.
- **The configured model is `gemini-2.5-flash`, while older README text claimed Gemini 2.0 Flash.** The code is authoritative; the documentation was corrected. Whether this model is appropriate for a particular free tier depends on the account's current Gemini limits.
- **Error details are collapsed to `ERR` in the main UI.** This avoids exposing raw exceptions in the overlay, but it does not distinguish quota errors from capture or configuration errors.
- **The full-screen capture is performed after the overlay is scheduled to appear.** Depending on Tkinter scheduling and capture timing, the overlay may be included in the screenshot.

### LOW

- **`overlay.py` has no in-flight protection of its own.** Its synchronous button callback blocks the Tkinter event loop during the request, so ordinary repeated mouse clicks are less likely to queue, but it remains a separate unprotected integration.
- **There is no cancellation control.** A synchronous Gemini request cannot currently be stopped from the UI.
- **There is no normal chat input, screenshot-file upload, conversation reset, or retry button in the documented app.** These are absent features, not hidden API consumers.

## 4. Changes made

Only targeted changes were made:

- Added a non-blocking `threading.Lock` in `main.py` so only one solve request can be active at once.
- Added a 0.5-second post-completion cooldown to absorb accidental rapid repeat presses.
- Ensured the lock is released in a `finally` block whether the request succeeds or fails.
- Changed the loading label from `...` to `Analyzing...`.
- Replaced the worker's five-second blocking sleep with Tkinter's scheduled callbacks, so the worker no longer remains occupied after the API request has finished.
- Updated `README.md` to document the real controls, model, request protection, and legacy overlay status.
- Added this audit report.

No Gemini model, prompt, API transport, or screenshot-capture behavior was otherwise changed.

## 5. Free-tier protection now in place

The `main.py` flow now behaves as follows:

1. The hotkey callback tries to acquire `_solve_lock` before starting a worker.
2. If a request is already in progress, the callback returns immediately and makes no Gemini call.
3. While the request is running, the overlay shows `Analyzing...`.
4. The worker performs the existing single synchronous `generate_content()` call.
5. On success or failure, the `finally` block releases the lock.
6. A 0.5-second cooldown rejects immediate accidental repeat presses after completion.
7. There is no automatic retry for quota errors or other exceptions.

Thus, one accepted `Ctrl + Alt + S` action produces at most one request in the documented `main.py` path. The legacy `overlay.py` program should not be run alongside it.

## 6. How to control/use the application

### Start

From the project directory on Windows:

```bash
pip install pynput google-genai pillow python-dotenv
```

Create a `.env` file containing:

```env
GEMINI_API_KEY=your_key_here
```

Then run:

```bash
python main.py
```

The application is Windows-oriented because of the global hotkeys, non-focus-stealing Windows attributes, and Caps Lock LED control.

### Controls

| Control | Action |
|---|---|
| `Ctrl + Alt + S` | Capture the entire screen and submit one solve request |
| `Ctrl + Alt + O` | Show or hide the overlay |
| Valid answer `A`–`E` | Display answer and blink Caps Lock 1–5 times |
| No documented cancel shortcut | None available |
| No documented retry shortcut/button | None available |
| No documented clear/reset control | None available |

### Status and errors

- `Analyzing...` means a request is in progress.
- `ANS: A` through `ANS: E` means a valid answer was returned.
- `ANS: ERR` means the request failed or the response could not be normalized to `A`–`E`.
- The code prints the underlying exception to the console, but the overlay only displays `ERR`.
- Quota errors are not retried automatically.

### Configuration

- API key variable: `GEMINI_API_KEY` in `.env`.
- Current model: `gemini-2.5-flash` in `ai_logic.py`.
- System instruction: `SYSTEM_INSTRUCTION` in `ai_logic.py`.
- Screenshot source: full desktop capture via `PIL.ImageGrab.grab()`.

## 7. Remaining risks

1. Running `overlay.py` separately can create requests outside the protected `main.py` path. Keep it closed or remove/archive it once the active path is confirmed.
2. A user can intentionally submit many different screenshots sequentially; the lock prevents overlap but does not impose a daily usage budget.
3. Full-screen images may be larger than necessary. A future targeted optimization could capture only the relevant monitor/window or resize with a readability-preserving maximum dimension, but this should be validated against real question screenshots.
4. The current UI does not expose whether an error was a quota error, invalid key, network failure, or image-capture failure.
5. The overlay may be included in a capture in some timing situations because it is scheduled for display before the existing capture call.
6. Gemini free-tier limits and model availability can change independently of this code.

## 8. Files changed

- `main.py` — added in-flight request locking, cooldown protection, explicit analyzing status, guaranteed lock cleanup, and non-blocking auto-hide scheduling.
- `README.md` — corrected the project title and model documentation, documented actual controls and limitations, and identified `overlay.py` as legacy.
- `PROJECT_ANALYSIS.md` — this audit and usage guide.

Validation performed: `python3 -m py_compile main.py ai_logic.py overlay.py led_control.py` completed successfully.
