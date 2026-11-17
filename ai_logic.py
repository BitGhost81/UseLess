import base64
import io
import logging
import os
import re
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from google import genai
from google.genai import types
import PIL.ImageGrab

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

SYSTEM_INSTRUCTION = """
You are a highly precise exam-solving assistant. 
Your task is to identify the multiple-choice question (MCQ) in the provided screenshot and determine the correct answer.

Rules:
1. Output ONLY the letter of the correct option (e.g., 'A', 'B', 'C', 'D', or 'E').
2. If there are multiple questions, solve the one that is most prominent or centered.
3. If the question is not an MCQ, output 'N/A'.
4. Do NOT provide any explanation, context, or extra characters.
5. Accuracy is critical. Double-check your reasoning before outputting the letter.
"""

GEARS = {
    1: {
        "provider": "Google Gemini",
        "model": "gemini-2.5-flash",
        "api_key": "GEMINI_API_KEY",
    },
    2: {
        "provider": "Google Gemini",
        "model": "gemini-2.5-flash-lite",
        "api_key": "GEMINI_API_KEY",
    },
    3: {
        "provider": "Google Gemini",
        "model": "gemini-3.5-flash",
        "api_key": "GEMINI_API_KEY",
    },
    4: {
        "provider": "Google Gemini",
        "model": "gemini-3.5-flash-lite",
        "api_key": "GEMINI_API_KEY",
    },
    5: {
        "provider": "Groq",
        "model": "qwen/qwen3.8-27b",
        "api_key": "GROQ_API_KEY",
    },
}

_active_gear = 1
_gear_lock = __import__("threading").Lock()
_gemini_client = None
_groq_client = None
REQUEST_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION
)
logger = logging.getLogger("useless.ai")


def get_active_gear():
    with _gear_lock:
        gear_number = _active_gear
    return gear_number, GEARS[gear_number].copy()


def set_active_gear(gear_number):
    if gear_number not in GEARS:
        raise ValueError(f"Unknown gear: {gear_number}")
    global _active_gear
    with _gear_lock:
        _active_gear = gear_number
    return get_active_gear()


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=API_KEY)
    return _gemini_client


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from openai import OpenAI
        _groq_client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
    return _groq_client


def _image_data_url(screenshot):
    image_buffer = io.BytesIO()
    screenshot.save(image_buffer, format="PNG")
    encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _extract_groq_text(response):
    """Extract text from the OpenAI-compatible message without logging contents."""
    content = response.choices[0].message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
            else:
                text = getattr(part, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(content)


def _normalize_option_answer(raw_answer, ignore_reasoning=False):
    """Return the final standalone A-Z option token, never a word-internal letter."""
    text = raw_answer.strip().upper()
    # Qwen reasoning responses may put the final answer after a </think> block.
    if ignore_reasoning and "</THINK>" in text:
        text = text.rsplit("</THINK>", 1)[1]
    matches = re.findall(r"(?<![A-Z])([A-F])(?![A-Z])", text)
    return matches[-1] if matches else "ERR"


def _normalize_groq_answer(raw_answer):
    """Backward-compatible wrapper for the Qwen-specific normalizer."""
    return _normalize_option_answer(raw_answer, ignore_reasoning=True)


def _generate_answer(gear_number, gear, screenshot):
    if gear["provider"] == "Google Gemini":
        response = _get_gemini_client().models.generate_content(
            model=gear["model"],
            contents=[screenshot],
            config=REQUEST_CONFIG,
        )
        return response.text

    if gear["provider"] == "Groq":
        response = _get_groq_client().chat.completions.create(
            model=gear["model"],
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_data_url(screenshot)},
                        }
                    ],
                },
            ],
        )
        raw_answer = _extract_groq_text(response)
        logger.info(
            "Groq response extracted: content_type=%s text_length=%s",
            type(response.choices[0].message.content).__name__,
            len(raw_answer),
        )
        return raw_answer

    raise ValueError(f"Unsupported gear: {gear_number}")


def _friendly_error(error, phase):
    """Map common capture, configuration, quota, auth, network and API errors to safe UI text."""
    message = str(error).lower()
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    status_text = str(status).lower()
    if phase == "screenshot capture":
        return "SCREEN CAPTURE FAILED\nCheck display permissions and try again."
    if "api_key" in message or "api key" in message or "unauthorized" in message or "forbidden" in message or "401" in status_text or "403" in status_text:
        return "API KEY ERROR\nCheck the selected gear's key in .env."
    if any(token in message for token in ("quota", "rate limit", "rate_limit", "resource_exhausted", "too many requests", "429")) or "429" in status_text:
        return "LIMIT REACHED\nProvider quota/rate limit reached. Try later or select another gear."
    if any(token in message for token in ("not found", "not supported", "model")) and ("404" in message or "model" in message):
        return "MODEL UNAVAILABLE\nCheck this gear's model/provider availability."
    if any(token in message for token in ("timeout", "timed out", "deadline")):
        return "PROVIDER TIMEOUT\nTry again when the service is responsive."
    if any(token in message for token in ("connection", "network", "dns", "unavailable", "temporarily")):
        return "NETWORK/SERVICE ERROR\nCheck your connection and try again."
    if phase == "response processing":
        return "UNREADABLE RESPONSE\nNo option A–F was returned; try again."
    return "AI REQUEST FAILED\nCheck the selected gear and local logs."


def get_ai_answer_with_details():
    gear_number, gear = get_active_gear()
    phase = "client initialization"
    request_started_at = None
    request_started_monotonic = None
    try:
        if not os.getenv(gear["api_key"]):
            return "ERR", f"MISSING API KEY\nSet {gear['api_key']} in .env for this gear.", None
        # Capture the entire screen exactly as before.
        phase = "screenshot capture"
        capture_started = time.monotonic()
        logger.info("Screenshot capture started: gear=%s", gear_number)
        screenshot = PIL.ImageGrab.grab()
        logger.info(
            "Screenshot capture completed: gear=%s duration_seconds=%.3f",
            gear_number,
            time.monotonic() - capture_started,
        )

        phase = "AI request"
        request_started_at = datetime.now(timezone.utc)
        request_started_monotonic = time.monotonic()
        logger.info(
            "AI request started: gear=%s provider=%s model=%s start=%s",
            gear_number,
            gear["provider"],
            gear["model"],
            request_started_at.isoformat(),
        )
        raw_answer = _generate_answer(gear_number, gear, screenshot)
        request_ended_at = datetime.now(timezone.utc)
        request_duration = time.monotonic() - request_started_monotonic
        logger.info(
            "AI response received: gear=%s provider=%s model=%s start=%s end=%s duration_seconds=%.3f",
            gear_number,
            gear["provider"],
            gear["model"],
            request_started_at.isoformat(),
            request_ended_at.isoformat(),
            request_duration,
        )

        # Both providers use standalone option tokens; Qwen additionally ignores
        # its optional reasoning block.
        phase = "response processing"
        final_answer = _normalize_option_answer(
            raw_answer,
            ignore_reasoning=gear["provider"] == "Groq",
        )
        if final_answer in "ABCDEF":
            return final_answer, None, screenshot
        return "ERR", _friendly_error(ValueError("No option A-F found"), phase), screenshot
    except Exception as e:
        ended_at = datetime.now(timezone.utc)
        duration = (
            time.monotonic() - request_started_monotonic
            if request_started_monotonic is not None
            else None
        )
        logger.exception(
            "AI/API error: gear=%s provider=%s model=%s phase=%s start=%s end=%s duration_seconds=%s",
            gear_number,
            gear["provider"],
            gear["model"],
            phase,
            request_started_at.isoformat() if request_started_at else "n/a",
            ended_at.isoformat(),
            f"{duration:.3f}" if duration is not None else "n/a",
        )
        return "ERR", _friendly_error(e, phase), locals().get("screenshot")


def get_ai_answer():
    """Backward-compatible answer-only interface."""
    answer, _error, _screenshot = get_ai_answer_with_details()
    return answer
