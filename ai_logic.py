from google import genai
from google.genai import types
import PIL.ImageGrab
import os
import logging
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
client = None
logger = logging.getLogger("useless.ai")

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

MODEL_NAME = 'gemini-2.5-flash'
REQUEST_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION
)

def get_ai_answer():
    global client
    phase = "client initialization"
    request_started_at = None
    request_started_monotonic = None
    try:
        if client is None:
            client = genai.Client(api_key=API_KEY)

        # Capture the entire screen
        phase = "screenshot capture"
        capture_started = time.monotonic()
        logger.info("Screenshot capture started")
        screenshot = PIL.ImageGrab.grab()
        logger.info(
            "Screenshot capture completed: duration_seconds=%.3f",
            time.monotonic() - capture_started,
        )
        
        # Request Answer
        phase = "Gemini request"
        request_started_at = datetime.now(timezone.utc)
        request_started_monotonic = time.monotonic()
        logger.info(
            "Gemini request started: model=%s start=%s",
            MODEL_NAME,
            request_started_at.isoformat(),
        )
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[screenshot],
            config=REQUEST_CONFIG
        )
        request_ended_at = datetime.now(timezone.utc)
        request_duration = time.monotonic() - request_started_monotonic
        logger.info(
            "Gemini request completed: model=%s start=%s end=%s duration_seconds=%.3f",
            MODEL_NAME,
            request_started_at.isoformat(),
            request_ended_at.isoformat(),
            request_duration,
        )
        
        # Clean the output
        phase = "response processing"
        final_answer = response.text.strip().upper()
        
        # Validate if it's a single letter A-E
        if final_answer in ['A', 'B', 'C', 'D', 'E']:
            return final_answer
        else:
            # Fallback for slightly longer responses
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
            "Gemini/API error: phase=%s start=%s end=%s duration_seconds=%s",
            phase,
            request_started_at.isoformat() if request_started_at else "n/a",
            ended_at.isoformat(),
            f"{duration:.3f}" if duration is not None else "n/a",
        )
        print(f"AI Error: {e}")
        return "ERR"
