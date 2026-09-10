import os
import time
import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model


SAMPLE_RATE = 16000
CHUNK_SIZE = 1280          # 80 ms
THRESHOLD = 0.55
COOLDOWN = 2.5


def find_hey_jarvis_model():
    """
    Find the installed pretrained Hey Jarvis model.
    """

    model_dir = os.path.join(
        os.path.dirname(openwakeword.__file__),
        "resources",
        "models",
    )

    for filename in os.listdir(model_dir):
        name = filename.lower()

        if (
            "hey_jarvis" in name
            and name.endswith(".tflite")
        ):
            return os.path.join(
                model_dir,
                filename,
            )

    return None


print("=" * 60)
print("COLD-START WAKE LISTENER")
print("=" * 60)

print("\nDownloading the wake model if necessary...")

openwakeword.utils.download_models(
    model_names=["hey_jarvis"]
)

model_path = find_hey_jarvis_model()

if model_path is None:
    raise RuntimeError(
        "Could not find the Hey Jarvis wake-word model."
    )

print(
    f"\n✅ Wake model: "
    f"{os.path.basename(model_path)}"
)

wake_model = Model(
    wakeword_models=[model_path],
    inference_framework="tflite",
)

print("\n✅ Wake listener ready.")
print("Temporary wake phrase: HEY JARVIS")
print("Say it naturally.")
print("Press Ctrl+C to stop.\n")

last_trigger = 0.0


def callback(indata, frames, time_info, status):
    global last_trigger

    if status:
        print(
            f"\nAudio status: {status}"
        )

    audio = np.frombuffer(
        indata,
        dtype=np.int16,
    )

    predictions = wake_model.predict(
        audio
    )

    now = time.time()

    for name, score in predictions.items():

        if score < THRESHOLD:
            continue

        if now - last_trigger < COOLDOWN:
            continue

        last_trigger = now

        print(
            f"\n✨ WAKE DETECTED"
            f"  score={score:.3f}"
        )


with sd.RawInputStream(
    samplerate=SAMPLE_RATE,
    blocksize=CHUNK_SIZE,
    dtype="int16",
    channels=1,
    callback=callback,
):
    while True:
        time.sleep(0.1)