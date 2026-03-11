import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import cv2
import numpy as np
import mss
import sounddevice as sd
import soundfile as sf
import threading
import subprocess
import os
import time
import tkinter as tk
import whisper

# --- Drag to select screen region ---
def select_region():
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-alpha", 0.3)
    root.attributes("-topmost", True)
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
    return x1, y1, x2, y2

# --- Floating timer window ---
def show_timer(stop_event):
    root = tk.Tk()
    root.title("Recording")
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

    def on_stop():
        stop_event.set()

    stop_btn = tk.Button(frame, text="⏹ Stop", font=("Arial", 11, "bold"),
                         fg="white", bg="#c0392b", activebackground="#e74c3c",
                         activeforeground="white", relief=tk.FLAT, padx=8, pady=2,
                         command=on_stop)
    stop_btn.pack(fill=tk.X, pady=(4, 0))

    start = time.time()

    def update():
        if stop_event.is_set():
            root.destroy()
            return
        elapsed = int(time.time() - start)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        timer_label.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        root.after(500, update)

    update()
    root.mainloop()


print("Drag to select the recording area...")
x1, y1, x2, y2 = select_region()

width = x2 - x1
height = y2 - y1

fps = 20
video_tmp = "tmp_video.mp4"
audio_tmp = "tmp_audio.wav"
timestamp = time.strftime("%m-%d-%y-%H-%M")
output_file = f"record_{timestamp}.mp4"

SAMPLE_RATE = 44100
CHANNELS = 1

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

# --- Timer in background thread ---
timer_thread = threading.Thread(target=show_timer, args=(stop_event,), daemon=True)
timer_thread.start()

# --- Video recording ---
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(video_tmp, fourcc, fps, (width, height))

monitor = {"top": y1, "left": x1, "width": width, "height": height}

print("Recording... Press CTRL+C to stop")

with mss.mss() as sct:
    try:
        while not stop_event.is_set():
            img = np.array(sct.grab(monitor))
            frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            out.write(frame)
    except KeyboardInterrupt:
        stop_event.set()

out.release()
stop_event.set()
audio_thread.join()

# --- Save audio ---
if audio_frames:
    audio_data = np.concatenate(audio_frames, axis=0)
    sf.write(audio_tmp, audio_data, SAMPLE_RATE)

    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_tmp,
        "-i", audio_tmp,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_file
    ], check=True)

    os.remove(video_tmp)
    os.remove(audio_tmp)
    print(f"Saved: {output_file}")

    # --- Transcribe audio with Whisper ---
    print("Transcribing audio... (first run downloads model ~145MB)")
    model = whisper.load_model("base")
    result = model.transcribe(output_file)
    transcript_file = output_file.replace(".mp4", ".txt")
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(result["text"].strip())
    print(f"Transcript saved: {transcript_file}")
else:
    os.rename(video_tmp, output_file)
    print(f"Saved (no audio): {output_file}")
