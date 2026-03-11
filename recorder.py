import sys
import os

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

# ============================================================
# DEVELOPER CONFIG
# ============================================================
FPS         = 20          # frames per second
CRF         = 28          # video quality: lower = better (18–32 recommended for screen)
PRESET      = "fast"      # ffmpeg preset: ultrafast / fast / medium / slow
SAMPLE_RATE = 44100       # audio sample rate
CHANNELS    = 1           # audio channels (1=mono, 2=stereo)
OUTPUT_DIR  = ""          # folder to save recordings, e.g. r"C:\Recordings" (empty = same folder as script)
# ============================================================

import mss
import numpy as np
import sounddevice as sd
import subprocess
import threading
import wave
import time
import tkinter as tk

# --- Drag to select screen region ---
def select_region():
    # mss monitors[0] = entire virtual desktop across all screens
    with mss.mss() as sct:
        virt = sct.monitors[0]
        virt_left, virt_top = virt["left"], virt["top"]
        virt_w, virt_h = virt["width"], virt["height"]

    root = tk.Tk()
    root.geometry(f"{virt_w}x{virt_h}+{virt_left}+{virt_top}")
    root.attributes("-alpha", 0.3)
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    root.configure(bg="black")
    root.config(cursor="cross")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)

    coords = {}
    rect = [None]

    def on_press(e):
        coords["x1"], coords["y1"] = e.x, e.y

    def on_drag(e):
        if rect[0]:
            canvas.delete(rect[0])
        rect[0] = canvas.create_rectangle(
            coords["x1"], coords["y1"], e.x, e.y,
            outline="red", width=2, fill="white"
        )

    def on_release(e):
        coords["x2"], coords["y2"] = e.x, e.y
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.mainloop()

    x1, x2 = min(coords["x1"], coords["x2"]), max(coords["x1"], coords["x2"])
    y1, y2 = min(coords["y1"], coords["y2"]), max(coords["y1"], coords["y2"])
    # offset by virtual desktop origin (negative on left/top monitors)
    return x1 + virt_left, y1 + virt_top, x2 + virt_left, y2 + virt_top

# --- Floating timer window ---
def show_timer(stop_event):
    root = tk.Tk()
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.85)
    root.overrideredirect(True)
    root.configure(bg="#1a1a1a")
    root.geometry("220x90+20+20")

    frame = tk.Frame(root, bg="#1a1a1a", padx=10, pady=8)
    frame.pack(fill=tk.BOTH, expand=True)

    top_row = tk.Frame(frame, bg="#1a1a1a")
    top_row.pack(fill=tk.X)

    dot = tk.Label(top_row, text="⏺", font=("Arial", 14), fg="red", bg="#1a1a1a")
    dot.pack(side=tk.LEFT)

    timer_label = tk.Label(top_row, text="00:00:00", font=("Consolas", 20, "bold"),
                           fg="white", bg="#1a1a1a")
    timer_label.pack(side=tk.LEFT, padx=6)

    stop_btn = tk.Button(frame, text="⏹ Stop", font=("Arial", 11, "bold"),
                         fg="white", bg="#c0392b", activebackground="#e74c3c",
                         activeforeground="white", relief=tk.FLAT, padx=8, pady=2,
                         command=stop_event.set)
    stop_btn.pack(fill=tk.X, pady=(4, 0))

    start = time.time()

    def update():
        if stop_event.is_set():
            root.destroy()
            return
        elapsed = int(time.time() - start)
        timer_label.config(text=f"{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}")
        root.after(500, update)

    update()
    root.mainloop()


# --- Setup ---
print("Drag to select the recording area...")
x1, y1, x2, y2 = select_region()
width, height = (x2 - x1) & ~1, (y2 - y1) & ~1  # must be even for yuv420p

if width < 2 or height < 2:
    print("Selection too small, exiting.")
    sys.exit(1)

timestamp = time.strftime("%m-%d-%y-%H-%M")
out_dir = OUTPUT_DIR if OUTPUT_DIR else os.path.dirname(os.path.abspath(__file__))
os.makedirs(out_dir, exist_ok=True)
output_file = os.path.join(out_dir, f"record_{timestamp}.mp4")
video_tmp   = os.path.join(out_dir, "tmp_video.mp4")
audio_tmp   = os.path.join(out_dir, "tmp_audio.wav")

# --- Audio recording ---
audio_frames = []
stop_event = threading.Event()

def record_audio():
    def callback(indata, frames, time_info, status):
        if not stop_event.is_set():
            audio_frames.append(indata.copy())
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, callback=callback):
        stop_event.wait()

audio_thread = threading.Thread(target=record_audio, daemon=True)
audio_thread.start()

# --- Timer ---
timer_thread = threading.Thread(target=show_timer, args=(stop_event,), daemon=True)
timer_thread.start()

# --- Video: pipe raw BGRA frames to ffmpeg ---
ffmpeg_video = subprocess.Popen([
    "ffmpeg", "-y",
    "-f", "rawvideo", "-vcodec", "rawvideo",
    "-s", f"{width}x{height}",
    "-pix_fmt", "bgra",
    "-r", str(FPS),
    "-i", "pipe:0",
    "-vcodec", "libx264",
    "-pix_fmt", "yuv420p",
    "-preset", PRESET,
    "-crf", str(CRF),
    video_tmp
], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

print("Recording... Press CTRL+C to stop")

with mss.mss() as sct:
    monitor = {"top": y1, "left": x1, "width": width, "height": height}
    try:
        while not stop_event.is_set():
            ffmpeg_video.stdin.write(sct.grab(monitor).raw)
    except KeyboardInterrupt:
        stop_event.set()

ffmpeg_video.stdin.close()
ffmpeg_video.wait()
stop_event.set()
audio_thread.join()
timer_thread.join(timeout=2)

# --- Save audio as WAV (built-in wave module, no soundfile needed) ---
if audio_frames:
    audio_data = np.concatenate(audio_frames).astype(np.float32)
    audio_int16 = (audio_data * 32767).astype(np.int16)
    with wave.open(audio_tmp, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())

    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_tmp,
        "-i", audio_tmp,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_file
    ], check=True, stderr=subprocess.DEVNULL)

    os.remove(video_tmp)
    os.remove(audio_tmp)
else:
    os.rename(video_tmp, output_file)

print(f"Saved: {output_file}")
