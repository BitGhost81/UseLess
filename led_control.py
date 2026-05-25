import ctypes
import time
import platform

def blink_caps_lock(times):
    if platform.system() != "Windows":
        print("Caps Lock control is only implemented for Windows.")
        return

    # VK_CAPITAL = 0x14
    # KEYEVENTF_EXTENDEDKEY = 0x0001
    # KEYEVENTF_KEYUP = 0x0002

    def toggle():
        ctypes.windll.user32.keybd_event(0x14, 0x45, 0x1, 0)
        ctypes.windll.user32.keybd_event(0x14, 0x45, 0x1 | 0x2, 0)

    # Get current state
    initial_state = ctypes.windll.user32.GetKeyState(0x14) & 1
    
    # We want to blink 'times' times.
    # Each blink is ON then OFF.
    # However, toggling Caps Lock changes the state.
    # To blink N times and return to original state:
    # If state is OFF: Toggle 2N times (ON, OFF, ON, OFF...)
    # If state is ON: Toggle 2N times (OFF, ON, OFF, ON...)
    
    for _ in range(times * 2):
        toggle()
        time.sleep(0.2) # Delay between toggles

    # Verify we are back to initial state (just in case)
    current_state = ctypes.windll.user32.GetKeyState(0x14) & 1
    if current_state != initial_state:
        toggle()
