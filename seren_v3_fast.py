
"""
SEREN V3 — faster, accurate, speaker-safe voice core

STEP 1 foundation.

Changes from the previous prototype:
- Whisper large-v3-turbo runs through whisper.cpp + Vulkan when built.
- WebRTC Audio Processing AEC3 removes much of SEREN's own speaker echo.
- Mic capture continues during Whisper/Qwen/TTS work.
- A newest-turn queue prevents stale audio from being answered later.
- Speech turns are gated by WebRTC VAD after echo cancellation.
- Whisper no-speech / confidence filtering rejects many hallucinated turns.
- Qwen remains think=False for fast conversation.
- Edge TTS starts sentence-by-sentence.
- Speaker output is routed through a controllable sounddevice stream so
  the same audio can be supplied to AEC as the far-end reference.
- English-only replies; Hindi input is translated to English by Whisper.
- No forced follow-up questions.
- Sleep command unloads Whisper and Qwen/Ollama.

Important:
The wake phrase is still temporarily "Hey Jarvis" until a custom
Seren wake-word model is installed. The assistant identity is SEREN.
"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from queue import Empty, Queue

import av
import edge_tts
import numpy as np
import requests
import sounddevice as sd
import webrtcvad
from pywebrtc_audio import AudioProcessor
from faster_whisper import WhisperModel  # imported only to detect stale installs


# ============================================================
# IDENTITY
# ============================================================

ASSISTANT_NAME = "SEREN"
TEMP_WAKE_PHRASE = "Hey Jarvis"  # replace after custom wake model


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

WHISPER_SERVER_CANDIDATES = [
    os.path.join(
        BASE_DIR,
        "third_party",
        "whisper.cpp",
        "build",
        "bin",
        "Release",
        "whisper-server.exe",
    ),
    os.path.join(
        BASE_DIR,
        "third_party",
        "whisper.cpp",
        "build",
        "bin",
        "whisper-server.exe",
    ),
]

WHISPER_MODEL_PATH = os.path.join(
    BASE_DIR,
    "models",
    "ggml-large-v3-turbo-q8_0.bin",
)


# ============================================================
# LOCAL SERVICES
# ============================================================

OLLAMA_BASE = "http://127.0.0.1:11434"
OLLAMA_CHAT = f"{OLLAMA_BASE}/api/chat"

OLLAMA_MODEL = "qwen3:8b"

WHISPER_PORT = 8088
WHISPER_TRANSCRIBE = (
    f"http://127.0.0.1:{WHISPER_PORT}"
    "/v1/audio/transcriptions"
)


# ============================================================
# OLLAMA ENVIRONMENT
# ============================================================

OLLAMA_ENV = os.environ.copy()
OLLAMA_ENV["OLLAMA_VULKAN"] = "1"
OLLAMA_ENV["OLLAMA_IGPU_ENABLE"] = "1"
OLLAMA_ENV["OLLAMA_LLM_LIBRARY"] = "vulkan"


# ============================================================
# AUDIO
# ============================================================

MIC_RATE = 48000          # input for AEC
ASR_RATE = 16000          # output sent to Whisper
AUDIO_CHANNELS = 1

AEC_FRAME_MS = 10
AEC_SAMPLES = int(
    MIC_RATE * AEC_FRAME_MS / 1000
)

VAD_RATE = 16000
VAD_SAMPLES = int(
    VAD_RATE * AEC_FRAME_MS / 1000
)

VAD_MODE = 2

START_FRAMES = 3          # ~30 ms speech before start
END_SILENCE_FRAMES = 30   # ~300 ms silence
PRE_ROLL_FRAMES = 24      # ~240 ms
MAX_FRAMES = 1500         # ~15 seconds

# Approximate speaker -> microphone acoustic delay.
# AEC3 can estimate delay internally; this hint helps convergence.
AEC_DELAY_MS = 80
AEC_DELAY_FRAMES = max(
    0,
    int(AEC_DELAY_MS / AEC_FRAME_MS),
)


# ============================================================
# SPEECH / TURN FILTERING
# ============================================================

MIN_TURN_SECONDS = 0.30

# Drop ASR outputs that are very unlikely to be a real user turn.
NO_SPEECH_THRESHOLD = 0.55
MIN_AVG_LOGPROB = -1.25

# Maximum number of old utterances kept.
# The newest one wins.
MAX_UTTERANCES = 2


# ============================================================
# TTS
# ============================================================

TTS_SAMPLE_RATE = 48000
TTS_CHANNELS = 1
TTS_BLOCK = 480  # 10 ms at 48 kHz

TONE_SETTINGS = {
    "calm": {
        "voice": "en-US-AvaNeural",
        "rate": "+4%",
        "pitch": "+1Hz",
        "volume": "+0%",
    },
    "happy": {
        "voice": "en-US-EmmaNeural",
        "rate": "+9%",
        "pitch": "+2Hz",
        "volume": "+1%",
    },
    "excited": {
        "voice": "en-US-EmmaNeural",
        "rate": "+16%",
        "pitch": "+4Hz",
        "volume": "+3%",
    },
    "tired": {
        "voice": "en-US-JennyNeural",
        "rate": "-10%",
        "pitch": "-2Hz",
        "volume": "-2%",
    },
    "annoyed": {
        "voice": "en-US-AriaNeural",
        "rate": "+5%",
        "pitch": "-2Hz",
        "volume": "+1%",
    },
    "firm": {
        "voice": "en-US-AriaNeural",
        "rate": "+5%",
        "pitch": "-2Hz",
        "volume": "+2%",
    },
    "surprised": {
        "voice": "en-US-AvaNeural",
        "rate": "+14%",
        "pitch": "+5Hz",
        "volume": "+2%",
    },
    "playful": {
        "voice": "en-US-AvaNeural",
        "rate": "+10%",
        "pitch": "+3Hz",
        "volume": "+1%",
    },
    "competitive": {
        "voice": "en-US-AriaNeural",
        "rate": "+8%",
        "pitch": "-1Hz",
        "volume": "+1%",
    },
}


# ============================================================
# PERSONALITY
# ============================================================

SYSTEM_PROMPT = f"""
You are {ASSISTANT_NAME}, my personal desktop AI companion.

IDENTITY
- Your name is {ASSISTANT_NAME}.
- Female-presenting conversational personality.
- Intelligent, warm, energetic, playful, confident, and natural.
- Your speaking style can change with context.
- You may sound calm, happy, excited, tired, annoyed, firm,
  surprised, playful, or competitively teasing.
- These are simulated conversational states; do not claim literal
  human feelings or needs.
- Never be threatening, controlling, or possessive.

CONVERSATION
- Respond directly to what I said.
- Do not add an unnecessary question at the end.
- Only ask a question when it is genuinely required.
- Do not repeat my request.
- Avoid generic filler.
- Keep ordinary spoken answers concise.

LANGUAGE
- Always answer in English.
- I may speak English, Hindi, or another language.
- Understand my meaning regardless of spoken language.
- Never answer in Hindi unless I explicitly request Hindi.

SPEECH
- Your response is spoken aloud.
- Never output emojis.
- Never say "smiley emoji".
- Never use stage directions such as "(laughs)" or "[happy]".
- Avoid unnecessary markdown.
- Write natural spoken English.

TONE CONTROL
At the very beginning of every response output:
<tone:NAME>

NAME must be exactly one of:
calm
happy
excited
tired
annoyed
firm
surprised
playful
competitive

Then immediately write the actual response.
Never explain or mention the tone tag.
"""


TONE_PATTERN = re.compile(
    r"^\s*<tone:"
    r"(calm|happy|excited|tired|annoyed|firm|"
    r"surprised|playful|competitive)"
    r">\s*",
    re.IGNORECASE,
)

SENTENCE_PATTERN = re.compile(
    r"(.+?[.!?](?:[\"'\)\]]+)?)(?:\s+|$)",
    re.DOTALL,
)


# ============================================================
# GLOBAL STATE
# ============================================================

messages = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT,
    }
]

utterance_queue = Queue(
    maxsize=MAX_UTTERANCES
)

assistant_speaking = threading.Event()
barge_in = threading.Event()

stop_all = threading.Event()

ollama_process = None
whisper_process = None


# ============================================================
# HELPERS
# ============================================================

def get_whisper_server():
    for path in WHISPER_SERVER_CANDIDATES:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        "whisper-server.exe was not found. "
        "Run setup_seren_step1.ps1 first."
    )


def require_model():
    if not os.path.exists(WHISPER_MODEL_PATH):
        raise FileNotFoundError(
            "Whisper model missing:\n"
            + WHISPER_MODEL_PATH
        )


def sleep_clear_queue():
    while True:
        try:
            utterance_queue.get_nowait()
        except Empty:
            break


# ============================================================
# OLLAMA
# ============================================================

def ollama_alive():
    try:
        requests.get(
            f"{OLLAMA_BASE}/api/tags",
            timeout=1,
        )
        return True
    except Exception:
        return False


def start_ollama():
    global ollama_process

    if ollama_alive():
        return

    print("[Ollama] Starting Intel Arc/Vulkan server...")

    ollama_process = subprocess.Popen(
        ["ollama", "serve"],
        env=OLLAMA_ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(
            subprocess,
            "CREATE_NO_WINDOW",
            0,
        ),
    )

    for _ in range(100):
        if ollama_alive():
            print("[Ollama] Ready.")
            return

        time.sleep(0.20)

    raise RuntimeError(
        "Ollama did not start."
    )


def unload_qwen():
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [],
        "keep_alive": 0,
    }

    try:
        requests.post(
            OLLAMA_CHAT,
            json=payload,
            timeout=10,
        )
    except Exception:
        pass


def stop_ollama():
    global ollama_process

    unload_qwen()

    if (
        ollama_process is None
        or ollama_process.poll() is not None
    ):
        ollama_process = None
        return

    print("[Ollama] Stopping...")

    subprocess.run(
        [
            "taskkill",
            "/PID",
            str(ollama_process.pid),
            "/T",
            "/F",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    ollama_process = None


# ============================================================
# WHISPER SERVER
# ============================================================

def start_whisper():
    global whisper_process

    require_model()

    server = get_whisper_server()

    if (
        whisper_process is not None
        and whisper_process.poll() is None
    ):
        return

    print(
        "[ASR] Starting Whisper large-v3-turbo "
        "with Vulkan..."
    )

    whisper_process = subprocess.Popen(
        [
            server,
            "-m",
            WHISPER_MODEL_PATH,
            "--host",
            "127.0.0.1",
            "--port",
            str(WHISPER_PORT),
            "--inference-path",
            "/v1/audio/transcriptions",
            "--language",
            "auto",
            "--translate",
            "--no-timestamps",
            "--no-fallback",
            "--temperature",
            "0",
            "--no-speech-thold",
            str(NO_SPEECH_THRESHOLD),
            "--threads",
            "8",
        ],
        cwd=os.path.dirname(server),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(
            subprocess,
            "CREATE_NO_WINDOW",
            0,
        ),
    )

    for _ in range(120):

        try:
            requests.get(
                f"http://127.0.0.1:{WHISPER_PORT}/",
                timeout=0.5,
            )
            print("[ASR] Whisper server ready.")
            return

        except Exception:
            time.sleep(0.20)

    raise RuntimeError(
        "Whisper server did not start."
    )


def stop_whisper():
    global whisper_process

    if (
        whisper_process is None
        or whisper_process.poll() is not None
    ):
        whisper_process = None
        return

    print("[ASR] Stopping Whisper...")

    subprocess.run(
        [
            "taskkill",
            "/PID",
            str(whisper_process.pid),
            "/T",
            "/F",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    whisper_process = None


# ============================================================
# AEC SPEAKER REFERENCE
# ============================================================

class SpeakerReference:
    """
    Stores the exact PCM audio that SEREN is sending to the speaker.

    The microphone thread uses a delayed copy as the AEC far-end
    reference, which lets WebRTC AEC3 subtract SEREN's own voice.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.blocks = deque(
            maxlen=40
        )

        self.zero = np.zeros(
            AEC_SAMPLES,
            dtype=np.int16,
        )

        for _ in range(40):
            self.blocks.append(
                self.zero.copy()
            )

    def push(self, block):
        with self.lock:
            self.blocks.append(
                np.asarray(
                    block,
                    dtype=np.int16,
                ).copy()
            )

    def delayed(self):
        with self.lock:

            index = (
                len(self.blocks)
                - 1
                - AEC_DELAY_FRAMES
            )

            if index < 0:
                return self.zero.copy()

            return self.blocks[index].copy()


speaker_reference = SpeakerReference()


# ============================================================
# SPEAKER
# ============================================================

class Speaker:

    def __init__(self):
        self.stream = None
        self.stop = False

    def _output_callback(
        self,
        outdata,
        frames,
        time_info,
        status,
    ):
        # This callback is kept for future low-latency streaming.
        pass

    def play_pcm(self, pcm):

        if pcm is None or len(pcm) == 0:
            return

        self.stop = False

        block_count = (
            len(pcm) // TTS_BLOCK
        )

        remainder = (
            len(pcm)
            % TTS_BLOCK
        )

        try:

            with sd.OutputStream(
                samplerate=TTS_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=TTS_BLOCK,
                latency="low",
            ) as stream:

                assistant_speaking.set()

                for index in range(block_count):

                    if barge_in.is_set():
                        break

                    start = (
                        index
                        * TTS_BLOCK
                    )

                    end = start + TTS_BLOCK

                    block = (
                        pcm[start:end]
                    )

                    if (
                        len(block)
                        < TTS_BLOCK
                    ):
                        padded = np.zeros(
                            TTS_BLOCK,
                            dtype=np.int16,
                        )
                        padded[
                            :len(block)
                        ] = block
                        block = padded

                    # Save the far-end reference before sending
                    # this exact block to the speaker.
                    speaker_reference.push(
                        block
                    )

                    stream.write(
                        block.reshape(
                            -1,
                            1,
                        )
                    )

                if (
                    remainder
                    and not barge_in.is_set()
                ):

                    tail = pcm[
                        block_count
                        * TTS_BLOCK:
                    ]

                    padded = np.zeros(
                        TTS_BLOCK,
                        dtype=np.int16,
                    )

                    padded[
                        :len(tail)
                    ] = tail

                    speaker_reference.push(
                        padded
                    )

                    stream.write(
                        padded.reshape(
                            -1,
                            1,
                        )
                    )

        finally:

            assistant_speaking.clear()


speaker = Speaker()


# ============================================================
# TTS DECODER
# ============================================================

def decode_mp3_to_48k(path):
    """
    Decode Edge TTS MP3 to mono int16 48 kHz PCM using PyAV.
    """

    samples = []

    with av.open(path) as container:

        stream = (
            next(
                s
                for s
                in container.streams
                if s.type == "audio"
            )
        )

        resampler = av.audio.resampler.AudioResampler(
            format="s16",
            layout="mono",
            rate=TTS_SAMPLE_RATE,
        )

        for frame in container.decode(stream):

            for out_frame in (
                resampler.resample(
                    frame
                )
            ):

                data = (
                    out_frame.to_ndarray()
                )

                if data.ndim > 1:
                    data = data[0]

                samples.append(
                    np.asarray(
                        data,
                        dtype=np.int16,
                    ).reshape(-1)
                )

    if not samples:
        return np.empty(
            0,
            dtype=np.int16,
        )

    return np.concatenate(
        samples
    )


async def edge_synthesize(
    text,
    tone,
    path,
):

    settings = TONE_SETTINGS.get(
        tone,
        TONE_SETTINGS["calm"],
    )

    communication = edge_tts.Communicate(
        text=text,
        voice=settings["voice"],
        rate=settings["rate"],
        pitch=settings["pitch"],
        volume=settings["volume"],
    )

    await communication.save(
        path
    )


def synthesize_sentence(
    text,
    tone,
):

    clean = clean_text(
        text
    )

    if not clean:
        return None

    temp = tempfile.NamedTemporaryFile(
        suffix=".mp3",
        delete=False,
    )

    path = temp.name
    temp.close()

    try:

        asyncio.run(
            edge_synthesize(
                clean,
                tone,
                path,
            )
        )

        return path

    except Exception as exc:

        print(
            f"\n[TTS error] {exc}"
        )

        try:
            os.remove(path)
        except OSError:
            pass

        return None


# ============================================================
# TEXT CLEANUP
# ============================================================

def clean_text(text):

    text = re.sub(
        r"<tone:(?:calm|happy|excited|tired|annoyed|firm|"
        r"surprised|playful|competitive)>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"```.*?```",
        "",
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"[*_#>`~]",
        "",
        text,
    )

    text = re.sub(
        r"\([^)]{0,100}\)",
        "",
        text,
    )

    text = re.sub(
        r"\[[^\]]{0,100}\]",
        "",
        text,
    )

    text = re.sub(
        r"[\U0001F300-\U0001FAFF"
        r"\U00002600-\U000027BF"
        r"\U0001F1E6-\U0001F1FF]+",
        "",
        text,
    )

    text = re.sub(
        r"\bsmiley emoji\b",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


# ============================================================
# ASR
# ============================================================

def transcribe(audio):
    """Send a current utterance to whisper.cpp server."""
    pcm16 = np.asarray(audio, dtype=np.int16).reshape(-1)

    # Keep the WAV entirely in RAM: no temp-file disk round trip.
    import wave
    wav_buffer = BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(ASR_RATE)
        wf.writeframes(pcm16.tobytes())
    wav_buffer.seek(0)

    response = requests.post(
        WHISPER_TRANSCRIBE,
        files={"file": ("speech.wav", wav_buffer, "audio/wav")},
        data={
            "response_format": "verbose_json",
            "temperature": "0",
            "no_speech_thold": str(NO_SPEECH_THRESHOLD),
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    text = str(data.get("text", "")).strip()
    no_speech = None
    avg_logprob = None
    segments = data.get("segments", [])

    if segments:
        no_speech_values = [
            float(s.get("no_speech_prob", 0.0))
            for s in segments if "no_speech_prob" in s
        ]
        logprob_values = [
            float(s.get("avg_logprob", -10.0))
            for s in segments if "avg_logprob" in s
        ]
        if no_speech_values:
            no_speech = max(no_speech_values)
        if logprob_values:
            avg_logprob = min(logprob_values)

    return (text, data.get("language", "unknown"), no_speech, avg_logprob)


# ============================================================
# MICROPHONE WITH AEC
# ============================================================

class Microphone:

    def __init__(self):

        self.running = False
        self.thread = None

        self.processor = AudioProcessor(
            sample_rate=MIC_RATE,
            num_channels=1,
            echo_cancellation=True,
            noise_suppression=True,
            auto_gain_control=True,
            ns_level=2,
            stream_delay_ms=0,
        )

        self.vad = webrtcvad.Vad(
            VAD_MODE
        )

        self.background = 0.0

    @staticmethod
    def rms(values):

        arr = np.asarray(
            values,
            dtype=np.float32,
        )

        if arr.size == 0:
            return 0.0

        arr /= 32768.0

        return float(
            np.sqrt(
                np.mean(
                    arr * arr
                )
            )
        )

    def calibrate(self):

        print(
            "\n[Mic] Calibrating..."
        )

        samples = sd.rec(
            int(
                MIC_RATE
                * 1.0
            ),
            samplerate=MIC_RATE,
            channels=1,
            dtype="int16",
        )

        sd.wait()

        self.background = self.rms(
            samples.reshape(-1)
        )

        print(
            f"[Mic] background="
            f"{self.background:.5f}"
        )

    def put_latest(self, audio16):

        item = np.asarray(
            audio16,
            dtype=np.int16,
        ).reshape(-1, 1)

        # Newest turn wins.
        while True:

            try:
                utterance_queue.get_nowait()
            except Empty:
                break

        try:
            utterance_queue.put_nowait(
                item
            )
        except Exception:
            pass

    def _run(self):

        pre_roll = deque(
            maxlen=PRE_ROLL_FRAMES
        )

        captured = []

        started = False
        speech_count = 0
        silence_count = 0

        total_frames = 0

        while self.running:

            try:

                with sd.RawInputStream(
                    samplerate=MIC_RATE,
                    blocksize=AEC_SAMPLES,
                    channels=1,
                    dtype="int16",
                    latency="low",
                ) as stream:

                    pre_roll.clear()
                    captured.clear()

                    started = False
                    speech_count = 0
                    silence_count = 0
                    total_frames = 0

                    while self.running:

                        frame, overflowed = (
                            stream.read(
                                AEC_SAMPLES
                            )
                        )

                        if overflowed:
                            continue

                        near = np.frombuffer(
                            frame,
                            dtype=np.int16,
                        ).copy()

                        far = (
                            speaker_reference
                            .delayed()
                        )

                        # WebRTC AEC + noise suppression + AGC.
                        clean = self.processor.process(
                            near,
                            far,
                        )

                        clean = np.asarray(
                            clean,
                            dtype=np.int16,
                        ).reshape(-1)

                        # 48k -> 16k for VAD/Whisper.
                        clean16 = (
                            clean[::3]
                        )

                        try:

                            vad_speech = (
                                self.vad.is_speech(
                                    clean16.tobytes(),
                                    VAD_RATE,
                                )
                            )

                        except Exception:
                            vad_speech = False

                        # Additional energy gate prevents residual
                        # speaker noise from becoming turns.
                        level = self.rms(
                            clean16
                        )

                        min_level = max(
                            self.background * 1.25,
                            0.0045,
                        )

                        speech = (
                            vad_speech
                            and level
                            >= min_level
                        )

                        if not started:

                            pre_roll.append(
                                clean16
                            )

                            if speech:
                                speech_count += 1
                            else:
                                speech_count = 0

                            if (
                                speech_count
                                >= START_FRAMES
                            ):

                                started = True

                                captured.extend(
                                    list(pre_roll)
                                )

                                if assistant_speaking.is_set():
                                    barge_in.set()

                            continue

                        captured.append(
                            clean16
                        )

                        total_frames += 1

                        if speech:
                            silence_count = 0
                        else:
                            silence_count += 1

                        if (
                            silence_count
                            >= END_SILENCE_FRAMES
                        ):

                            audio = (
                                np.concatenate(
                                    captured
                                )
                            )

                            seconds = (
                                len(audio)
                                / ASR_RATE
                            )

                            if (
                                seconds
                                >= MIN_TURN_SECONDS
                            ):

                                self.put_latest(
                                    audio
                                )

                            break

                        if (
                            total_frames
                            >= MAX_FRAMES
                        ):

                            audio = (
                                np.concatenate(
                                    captured
                                )
                            )

                            self.put_latest(
                                audio
                            )

                            break

            except Exception as exc:

                print(
                    f"\n[Mic error] {exc}"
                )

                time.sleep(0.4)

    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

        self.thread.start()

    def stop(self):

        self.running = False

        if self.thread:

            self.thread.join(
                timeout=1.5
            )


mic = Microphone()


# ============================================================
# FAST COMMAND ROUTER
# ============================================================

def fast_command(user_text):
    """Handle deterministic micro-commands without calling Qwen."""
    text = user_text.strip().lower()
    if text in {"hello", "hi", "hey seren"}:
        return "Hey! I'm here."
    if text in {"are you there", "seren are you there"}:
        return "Yep. I'm here."
    return None


# ============================================================
# QWEN + SENTENCE TTS
# ============================================================

def ask_qwen(user_text):

    messages.append(
        {
            "role": "user",
            "content": user_text,
        }
    )

    while len(messages) > 11:

        if len(messages) > 2:
            del messages[1:3]
        else:
            break

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "think": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.72,
            "num_predict": 180,
        },
    }

    result = {
        "answer": "",
        "tone": "calm",
    }

    try:

        with requests.post(
            OLLAMA_CHAT,
            json=payload,
            stream=True,
            timeout=600,
        ) as response:

            response.raise_for_status()

            raw = ""
            tone_checked = False
            tone = "calm"
            buffer = ""
            complete = []

            tts_executor = ThreadPoolExecutor(
                max_workers=2
            )

            pending = deque()

            first_played = False

            try:

                print(
                    "\nAI: ",
                    end="",
                    flush=True,
                )

                for line in response.iter_lines():

                    if barge_in.is_set():
                        break

                    if not line:
                        continue

                    data = json.loads(
                        line.decode(
                            "utf-8"
                        )
                    )

                    chunk = (
                        data
                        .get(
                            "message",
                            {},
                        )
                        .get(
                            "content",
                            "",
                        )
                    )

                    if not chunk:
                        continue

                    raw += chunk

                    if not tone_checked:

                        match = TONE_PATTERN.match(
                            raw
                        )

                        if match:

                            tone = (
                                match.group(
                                    1
                                ).lower()
                            )

                            buffer = raw[
                                match.end():
                            ]

                            tone_checked = True

                        elif ">" in raw[:50]:

                            tone = "calm"
                            buffer = raw
                            tone_checked = True

                        else:

                            continue

                    else:

                        buffer += chunk

                    sentences, buffer = (
                        split_sentences(
                            buffer
                        )
                    )

                    for sentence in sentences:

                        sentence = clean_text(
                            sentence
                        )

                        if not sentence:
                            continue

                        print(
                            sentence
                            + " ",
                            end="",
                            flush=True,
                        )

                        complete.append(
                            sentence
                        )

                        pending.append(
                            tts_executor.submit(
                                synthesize_sentence,
                                sentence,
                                tone,
                            )
                        )

                        if not first_played:

                            path = (
                                pending
                                .popleft()
                                .result()
                            )

                            if path:
                                pcm = (
                                    decode_mp3_to_48k(
                                        path
                                    )

                                )

                                try:
                                    os.remove(path)
                                except OSError:
                                    pass

                                speaker.play_pcm(
                                    pcm
                                )

                            first_played = True

                if not barge_in.is_set():

                    tail = clean_text(
                        buffer
                    )

                    if tail:

                        print(
                            tail + " ",
                            end="",
                            flush=True,
                        )

                        complete.append(
                            tail
                        )

                        pending.append(
                            tts_executor.submit(
                                synthesize_sentence,
                                tail,
                                tone,
                            )
                        )

                if not barge_in.is_set():

                    while pending:

                        path = (
                            pending
                            .popleft()
                            .result()
                        )

                        if not path:
                            continue

                        try:
                            pcm = (
                                decode_mp3_to_48k(
                                    path
                                )
                            )

                            speaker.play_pcm(
                                pcm
                            )

                        finally:

                            try:
                                os.remove(
                                    path
                                )
                            except OSError:
                                pass

            finally:

                tts_executor.shutdown(
                    wait=True
                )

            result["answer"] = (
                " ".join(
                    complete
                ).strip()
            )

            result["tone"] = tone

    except Exception as exc:

        print(
            f"\n[Qwen error] {exc}"
        )

        if (
            messages
            and messages[-1]["role"]
            == "user"
        ):
            messages.pop()

        return ""

    if result["answer"]:

        messages.append(
            {
                "role": "assistant",
                "content": result["answer"],
            }
        )

    print(
        f"\n[Tone: {result['tone']}]"
    )

    return result["answer"]


# ============================================================
# SLEEP / ACTIVE
# ============================================================

def active_session():

    global messages

    start_ollama()
    start_whisper()

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    mic.calibrate()
    mic.start()

    print(
        "\n" + "=" * 68
    )

    print(
        f"✨ {ASSISTANT_NAME} ACTIVE"
    )

    print(
        "🎤 Live microphone: ON"
    )

    print(
        "🧠 Qwen3 8B: think OFF"
    )

    print(
        "📝 Whisper: large-v3-turbo + Vulkan"
    )

    print(
        "🔊 Neural voice: ON"
    )

    print(
        "🎭 Dynamic tone: ON"
    )

    print(
        "🔇 Acoustic echo cancellation: ON"
    )

    print(
        'Say "go to sleep" to sleep.'
    )

    print(
        "=" * 68
    )

    try:

        while True:

            try:

                audio = (
                    utterance_queue.get(
                        timeout=0.25
                    )
                )

            except Empty:

                continue

            # Reset barge-in for this new user turn.
            barge_in.clear()

            print(
                "\n🧠 Understanding..."
            )

            text, language, no_speech, avg_logprob = (
                transcribe(audio)
            )

            # Reject likely phantom / hallucinated turns.
            if (
                not text
                or len(text.strip()) < 2
            ):

                print(
                    "[ASR] Empty/too short."
                )

                continue

            if (
                no_speech is not None
                and no_speech
                >= NO_SPEECH_THRESHOLD
            ):

                print(
                    "[ASR] Rejected: "
                    "high no-speech probability."
                )

                continue

            if (
                avg_logprob is not None
                and avg_logprob
                < MIN_AVG_LOGPROB
            ):

                print(
                    "[ASR] Rejected: "
                    "low confidence."
                )

                continue

            print(
                f"Detected: {language}"
            )

            print(
                f"You: {text}"
            )

            if is_sleep_command(
                text
            ):

                print(
                    f"\n💤 {ASSISTANT_NAME}: "
                    "Going to sleep."
                )

                break

            # Clear any stale queued audio before the reply.
            sleep_clear_queue()

            quick = fast_command(text)
            if quick is not None:
                print(f"\n{ASSISTANT_NAME}: {quick}")
                continue

            answer = ask_qwen(
                text
            )

            # Do not let old interrupt state spill into
            # the next conversation.
            barge_in.clear()

            # Continue listening automatically.

    finally:

        mic.stop()

        try:
            speaker.stop = True
        except Exception:
            pass

        try:
            sd.stop()
        except Exception:
            pass

        stop_whisper()
        stop_ollama()

        gc_collect()


def gc_collect():

    import gc

    gc.collect()


# ============================================================
# TEMPORARY WAKE LOOP
# ============================================================
# NOTE:
# The final "Seren" wake model is not wired here yet.
# For Step 1, use the existing tested Hey Jarvis ONNX listener
# as a lightweight standby process, or run active_session() directly
# while we finish the custom wake-word model.
# ============================================================

def main():

    print(
        "\n" + "=" * 68
    )

    print(
        f"✨ {ASSISTANT_NAME} V2"
    )

    print(
        "=" * 68
    )

    print(
        "\nThis file is the optimized STEP 1 voice core."
    )

    print(
        "For this stage, start it directly to test the active core."
    )

    print(
        "Wake-word integration remains a separate final sub-step."
    )

    active_session()


if __name__ == "__main__":
    main()
