import google.generativeai as genai
import PIL.ImageGrab
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY, transport='rest')

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

# Switching to 1.5 Flash as it has more stable free tier availability
model = genai.GenerativeModel(
    'gemini-2.5-flash', 
    system_instruction=SYSTEM_INSTRUCTION
)

def get_ai_answer():
    try:
        # Capture the entire screen
        screenshot = PIL.ImageGrab.grab()
        
        # Request Answer
        response = model.generate_content([screenshot])
        
        # Clean the output
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
        print(f"AI Error: {e}")
        return "ERR"
