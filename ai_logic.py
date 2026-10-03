import base64
import io
import logging
import os
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
        return response.choices[0].message.content

    raise ValueError(f"Unsupported gear: {gear_number}")


def get_ai_answer():
    gear_number, gear = get_active_gear()
    phase = "client initialization"
    request_started_at = None
    request_started_monotonic = None
    try:
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

        # Keep the existing response normalization and return behavior.
        phase = "response processing"
        final_answer = raw_answer.strip().upper()
        if final_answer in ['A', 'B', 'C', 'D', 'E']:
            return final_answer
        for char in final_answer:
            if char in ['A', 'B', 'C', 'D', 'E']:
                return char
        return "ERR"
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
        print(f"AI Error: {e}")
        return "ERR"
