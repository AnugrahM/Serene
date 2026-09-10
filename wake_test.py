import time

import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model


SAMPLE_RATE = 16000
CHUNK = 1280          # 80 ms at 16 kHz
THRESHOLD = 0.5
COOLDOWN = 2.0


print("=" * 60)
print("WAKE-WORD TEST")
print("=" * 60)

print("\nDownloading/loading wake-word models...")

# Download the included pretrained models if needed.
openwakeword.utils.download_models()

# Load the included models.
wake_model = Model()

print("✅ Wake-word engine ready.")
print("\nTemporary wake phrase: HEY JARVIS")
print("Say 'hey jarvis' near your microphone.")
print("Press Ctrl+C to stop.\n")


last_trigger = 0.0


def audio_callback(indata, frames, time_info, status):
    global last_trigger

    if status:
        print(status)

    audio = np.frombuffer(
        indata,
        dtype=np.int16
    )

    predictions = wake_model.predict(audio)

    now = time.time()

    for name, score in predictions.items():

        if "jarvis" not in name.lower():
            continue

        if score >= THRESHOLD:

            if now - last_trigger >= COOLDOWN:

                last_trigger = now

                print()
                print("✨ WAKE WORD DETECTED!")
                print(f"Model: {name}")
                print(f"Score: {score:.3f}")
                print()


with sd.RawInputStream(
    samplerate=SAMPLE_RATE,
    blocksize=CHUNK,
    dtype="int16",
    channels=1,
    callback=audio_callback,
):

    while True:
        time.sleep(0.1)