import tkinter as tk
import PIL.ImageGrab
import google.generativeai as genai
import os
from dotenv import load_dotenv

# ==========================================
# CONFIGURATION
# ==========================================
# Load the variables from the .env file
load_dotenv()

# Get the key from the environment
API_KEY = os.getenv("GEMINI_API_KEY")

# Configure the AI
genai.configure(api_key=API_KEY, transport='rest')

# Use the 2026 stable model ID
model = genai.GenerativeModel('gemini-2.5-flash', system_instruction="You are a precise quiz solver. Look at the image and identify the multiple-choice question. Output ONLY the correct option letter (e.g., 'A', 'B', 'C', or 'D'). Do NOT provide any explanations, headers, or additional text.")

# ==========================================
# AI LOGIC
# ==========================================
def get_ai_answer():
    label.config(text="Thinking...")
    root.update()
    
    try:
        # 1. Capture the entire screen
        screenshot = PIL.ImageGrab.grab()
        
        # 2. Request Answer (Empty prompt because the System Instruction handles the rules)
        response = model.generate_content([screenshot])
        
        # Clean the output just in case (removes extra spaces or periods)
        final_answer = response.text.strip().upper()
        
        label.config(text=f"ANSWER: {final_answer}")
    except Exception as e:
        label.config(text=f"Error: {str(e)}")

# ==========================================
# GUI SETUP (The "Mini Window")
# ==========================================
root = tk.Tk()
root.title("AI Assistant")
root.geometry("300x200+50+50") # Width x Height + X offset + Y offset
root.attributes("-topmost", True)  # Always on top
root.attributes("-alpha", 0.85)    # Slight transparency
root.overrideredirect(True)        # Remove borders/title bar

# Create a container frame for styling
frame = tk.Frame(root, bg="#1e1e1e", bd=2, relief="ridge")
frame.pack(expand=True, fill="both")

# The text display area
label = tk.Label(
    frame, 
    text="Ready for Quiz...", 
    wraplength=280, 
    fg="#00ff00", # Matrix green text
    bg="#1e1e1e", 
    font=("Consolas", 11)
)
label.pack(expand=True, fill="both", padx=10, pady=10)

# The "Solve" Button
btn = tk.Button(
    frame, 
    text="SOLVE SCREENSHOT", 
    command=get_ai_answer,
    bg="#444", 
    fg="white", 
    relief="flat",
    font=("Arial", 10, "bold")
)
btn.pack(side="bottom", fill="x")

# --- DRAGGING LOGIC ---
# Since we removed the title bar, we need to manually allow dragging
def start_move(event):
    root.x = event.x
    root.y = event.y

def on_move(event):
    deltax = event.x - root.x
    deltay = event.y - root.y
    x = root.winfo_x() + deltax
    y = root.winfo_y() + deltay
    root.geometry(f"+{x}+{y}")

frame.bind("<Button-1>", start_move)
frame.bind("<B1-Motion>", on_move)

# A small "Exit" button in the corner
exit_btn = tk.Button(frame, text="X", command=root.destroy, bg="#ff4444", fg="white", bd=0)
exit_btn.place(x=275, y=5, width=20, height=20)

root.mainloop()