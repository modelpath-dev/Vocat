import asyncio
import json
import logging
import uuid
import os
import re
import time
import fractions
from collections import deque
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from pydub import AudioSegment
import webrtcvad
from openai import OpenAI
from elevenlabs.client import ElevenLabs
import numpy as np
import av

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable not set.")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_LABS_API_KEY")
if not ELEVENLABS_API_KEY:
    raise ValueError("ELEVENLABS_API_KEY environment variable not set.")
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

pcs = set()
session_resumes = {}

# VAD config
VAD_AGGRESSIVENESS = 3
vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
SAMPLE_RATE = 16000
VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = int(SAMPLE_RATE * (VAD_FRAME_MS / 1000.0))
VAD_SILENCE_TIMEOUT_MS = 600
VAD_NUM_SILENT_FRAMES_TO_TRIGGER = VAD_SILENCE_TIMEOUT_MS // VAD_FRAME_MS
MIN_AUDIO_DURATION_MS = 500  # Minimum audio duration to bother transcribing
MAX_AUDIO_DURATION_MS = 30000  # Maximum single utterance length

SENTENCE_ENDINGS = re.compile(r'([.!?;])\s')

# Audio output config
OUTPUT_SAMPLE_RATE = 48000
OUTPUT_CHANNELS = 1
SAMPLES_PER_FRAME = 960  # 20ms at 48kHz
AUDIO_PTIME = fractions.Fraction(1, 50)  # 20ms

INTERVIEWER_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "interviewer.md")
with open(INTERVIEWER_PROMPT_PATH, "r") as f:
    INTERVIEWER_PROMPT_TEMPLATE = f.read()


def extract_text_from_pdf(file_bytes):
    try:
        import pdfminer.high_level
        import io
        return pdfminer.high_level.extract_text(io.BytesIO(file_bytes))
    except ImportError:
        temp_path = f"/tmp/resume_{uuid.uuid4()}.pdf"
        with open(temp_path, "wb") as f:
            f.write(file_bytes)
        try:
            import subprocess
            result = subprocess.run(["pdftotext", temp_path, "-"], capture_output=True, text=True)
            return result.stdout
        except Exception:
            return ""
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


def split_into_sentences(text):
    sentences = []
    last_end = 0
    for match in SENTENCE_ENDINGS.finditer(text):
        end_pos = match.end()
        sentence = text[last_end:end_pos].strip()
        if sentence:
            sentences.append(sentence)
        last_end = end_pos
    remaining = text[last_end:].strip()
    if remaining:
        sentences.append(remaining)
    return sentences


def tts_to_pcm(text):
    """Convert text to raw PCM s16 samples at OUTPUT_SAMPLE_RATE using ElevenLabs."""
    audio_generator = eleven_client.text_to_speech.convert(
        text=text,
        voice_id="EXAVITQu4vr4xnSDxMaL",  # Sarah
        model_id="eleven_turbo_v2_5",
        output_format="mp3_22050_32",
    )
    audio_data = b"".join(audio_generator)

    # Decode MP3 to raw PCM at target sample rate
    seg = AudioSegment.from_mp3(
        __import__("io").BytesIO(audio_data)
    ).set_frame_rate(OUTPUT_SAMPLE_RATE).set_channels(OUTPUT_CHANNELS).set_sample_width(2)

    return np.frombuffer(seg.raw_data, dtype=np.int16)


class AudioOutputTrack(MediaStreamTrack):
    """
    A track that streams audio frames to the browser.
    Feed it PCM samples via enqueue_samples() and it will
    output them as WebRTC audio frames.
    """
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._queue = deque()
        self._start = None
        self._timestamp = 0

    def enqueue_samples(self, samples: np.ndarray):
        """Add PCM int16 samples to the playback queue."""
        # Split into frame-sized chunks
        for i in range(0, len(samples), SAMPLES_PER_FRAME):
            chunk = samples[i:i + SAMPLES_PER_FRAME]
            if len(chunk) < SAMPLES_PER_FRAME:
                # Pad the last chunk with silence
                chunk = np.pad(chunk, (0, SAMPLES_PER_FRAME - len(chunk)))
            self._queue.append(chunk)

    async def recv(self):
        if self._start is None:
            self._start = time.time()

        # Pace output at real-time (20ms per frame)
        target_time = self._start + (self._timestamp / OUTPUT_SAMPLE_RATE)
        wait = target_time - time.time()
        if wait > 0:
            await asyncio.sleep(wait)

        if self._queue:
            samples = self._queue.popleft()
        else:
            # Silence when nothing to play
            samples = np.zeros(SAMPLES_PER_FRAME, dtype=np.int16)

        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = OUTPUT_SAMPLE_RATE
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, OUTPUT_SAMPLE_RATE)
        self._timestamp += SAMPLES_PER_FRAME

        return frame


MAX_CONVERSATION_TURNS = 50  # Limit conversation history to prevent token overflow


class InterviewSession:
    """Manages VAD, transcription, LLM, and TTS for one call."""

    def __init__(self, output_track: AudioOutputTrack, resume_text: str):
        self.output_track = output_track
        self.is_speaking = False
        self.silent_frames_count = 0
        self.audio_buffer = AudioSegment.empty()
        self.is_processing = False

        system_prompt = INTERVIEWER_PROMPT_TEMPLATE.replace("{resume_text}", resume_text)
        self.system_message = {"role": "system", "content": system_prompt}
        self.chat_history = [self.system_message]
        logger.info("InterviewSession created.")

    async def send_greeting(self):
        await asyncio.sleep(2)
        greeting = "Hi there! Thanks for joining. I'm your interviewer today. I've had a chance to look over your resume, and I'm excited to learn more about you. So, to kick things off, could you tell me a little bit about yourself?"
        self.chat_history.append({"role": "assistant", "content": greeting})
        await self._speak(greeting)

    async def _speak(self, text):
        """Convert text to audio and enqueue for playback."""
        try:
            logger.info(f"TTS: {text[:70]}...")
            loop = asyncio.get_event_loop()
            samples = await loop.run_in_executor(None, tts_to_pcm, text)
            self.output_track.enqueue_samples(samples)
            logger.info(f"Enqueued {len(samples)} samples for playback.")
        except Exception as e:
            logger.error(f"TTS error: {e}")

    def _trim_history(self):
        """Keep conversation history within token limits by trimming old turns."""
        # Always keep the system message + last N turns
        if len(self.chat_history) > MAX_CONVERSATION_TURNS * 2 + 1:
            self.chat_history = [self.system_message] + self.chat_history[-(MAX_CONVERSATION_TURNS * 2):]
            logger.info(f"Trimmed conversation history to {len(self.chat_history)} messages.")

    async def handle_transcript(self, text):
        if self.is_processing:
            logger.info("Already processing, skipping.")
            return
        self.is_processing = True

        try:
            self.chat_history.append({"role": "user", "content": text})
            self._trim_history()

            logger.info("Streaming from GPT-4o...")
            loop = asyncio.get_event_loop()
            stream = await loop.run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=self.chat_history,
                    stream=True,
                    temperature=0.7,
                    max_tokens=300,
                )
            )

            sentence_buffer = ""
            full_response = ""

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    sentence_buffer += delta
                    full_response += delta

                    match = SENTENCE_ENDINGS.search(sentence_buffer)
                    if match:
                        end_pos = match.end()
                        sentence = sentence_buffer[:end_pos].strip()
                        sentence_buffer = sentence_buffer[end_pos:]
                        if sentence:
                            await self._speak(sentence)

            if sentence_buffer.strip():
                await self._speak(sentence_buffer.strip())

            logger.info(f"AI: {full_response[:100]}...")
            self.chat_history.append({"role": "assistant", "content": full_response})

        except Exception as e:
            logger.error(f"AI pipeline error: {e}")
        finally:
            self.is_processing = False

    async def transcribe_and_respond(self):
        audio_duration = len(self.audio_buffer)
        logger.info(f"Transcribing {audio_duration}ms of audio.")

        if audio_duration < MIN_AUDIO_DURATION_MS:
            logger.info(f"Audio too short ({audio_duration}ms), skipping transcription.")
            self.audio_buffer = AudioSegment.empty()
            self.is_speaking = False
            self.silent_frames_count = 0
            return

        if audio_duration > MAX_AUDIO_DURATION_MS:
            logger.warning(f"Audio too long ({audio_duration}ms), truncating to {MAX_AUDIO_DURATION_MS}ms.")
            self.audio_buffer = self.audio_buffer[:MAX_AUDIO_DURATION_MS]

        temp_path = f"/tmp/vocat_stt_{uuid.uuid4()}.wav"

        try:
            self.audio_buffer.export(temp_path, format="wav")

            loop = asyncio.get_event_loop()
            transcript = await loop.run_in_executor(
                None,
                lambda: openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=open(temp_path, "rb"),
                    language="en"
                )
            )

            logger.info(f"Transcript: {transcript.text}")

            if transcript.text.strip():
                asyncio.create_task(self.handle_transcript(transcript.text))

        except Exception as e:
            logger.error(f"Transcription error: {e}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            self.audio_buffer = AudioSegment.empty()
            self.is_speaking = False
            self.silent_frames_count = 0

    def process_audio_frame(self, frame):
        """Process incoming audio frame for VAD."""
        try:
            segment = AudioSegment(
                data=frame.to_ndarray().tobytes(),
                sample_width=2,
                frame_rate=frame.sample_rate,
                channels=len(frame.layout.channels)
            ).set_frame_rate(SAMPLE_RATE).set_channels(1)

            raw_samples = segment.raw_data

            for i in range(0, len(raw_samples), VAD_FRAME_SAMPLES * 2):
                chunk = raw_samples[i: i + VAD_FRAME_SAMPLES * 2]
                if len(chunk) != VAD_FRAME_SAMPLES * 2:
                    continue

                is_speech = vad.is_speech(chunk, SAMPLE_RATE)

                if is_speech:
                    if not self.is_speaking:
                        logger.info("Speech detected.")
                        self.is_speaking = True
                    self.audio_buffer += AudioSegment(
                        data=chunk, sample_width=2, frame_rate=SAMPLE_RATE, channels=1
                    )
                    self.silent_frames_count = 0

                elif self.is_speaking:
                    self.silent_frames_count += 1
                    self.audio_buffer += AudioSegment(
                        data=chunk, sample_width=2, frame_rate=SAMPLE_RATE, channels=1
                    )
                    if self.silent_frames_count >= VAD_NUM_SILENT_FRAMES_TO_TRIGGER:
                        asyncio.create_task(self.transcribe_and_respond())
                        self.is_speaking = False
                        self.silent_frames_count = 0
                        self.audio_buffer = AudioSegment.empty()

        except Exception as e:
            logger.error(f"Frame processing error: {e}")


class VADPassthrough(MediaStreamTrack):
    """Receives incoming audio, runs VAD on it, and passes frames through."""
    kind = "audio"

    def __init__(self, track, session: InterviewSession):
        super().__init__()
        self.track = track
        self.session = session

    async def recv(self):
        frame = await self.track.recv()
        self.session.process_audio_frame(frame)
        return frame


async def upload_resume(request):
    try:
        reader = await request.multipart()
        field = await reader.next()

        if field is None:
            return web.json_response({"error": "No file uploaded"}, status=400)

        file_bytes = await field.read()
        filename = field.filename or "resume"
        logger.info(f"Resume uploaded: {filename} ({len(file_bytes)} bytes)")

        if filename.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(file_bytes)
        else:
            try:
                resume_text = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                resume_text = file_bytes.decode("latin-1")

        if not resume_text.strip():
            return web.json_response({"error": "Could not extract text from resume"}, status=400)

        session_id = str(uuid.uuid4())
        session_resumes[session_id] = resume_text.strip()
        logger.info(f"Resume stored for session {session_id}: {resume_text[:100]}...")

        return web.json_response({"session_id": session_id, "preview": resume_text[:200]})

    except Exception as e:
        logger.error(f"Resume upload error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def offer(request):
    params = await request.json()
    offer_desc = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    session_id = params.get("session_id", "")
    resume_text = session_resumes.get(session_id, "No resume provided.")

    pc = RTCPeerConnection()
    pc_id = f"PC({uuid.uuid4().hex[:8]})"
    pcs.add(pc)
    logger.info(f"Created {pc_id} (session: {session_id})")

    # Create the output audio track BEFORE setting remote description
    output_track = AudioOutputTrack()
    pc.addTrack(output_track)

    session = InterviewSession(output_track, resume_text)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"[{pc_id}] State: {pc.connectionState}")
        if pc.connectionState == "connected":
            asyncio.create_task(session.send_greeting())
        elif pc.connectionState in ["failed", "closed"]:
            await pc.close()
            pcs.discard(pc)
            session_resumes.pop(session_id, None)

    @pc.on("track")
    def on_track(track):
        logger.info(f"[{pc_id}] Track: {track.kind}")
        if track.kind == "audio":
            # We don't re-add VADPassthrough as a track since we already have output_track.
            # Just process incoming audio for VAD.
            vad_passthrough = VADPassthrough(track, session)
            # We need to consume this track so frames flow through VAD
            asyncio.ensure_future(_consume_track(vad_passthrough))

        @track.on("ended")
        async def on_ended():
            logger.info(f"[{pc_id}] Track {track.kind} ended")

    await pc.setRemoteDescription(offer_desc)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    logger.info(f"[{pc_id}] Answer sent.")
    return web.json_response(
        {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    )


async def _consume_track(track):
    """Consume a track to keep frames flowing through it."""
    try:
        while True:
            await track.recv()
    except Exception:
        pass


async def health(request):
    return web.json_response({
        "status": "ok",
        "active_connections": len(pcs),
        "pending_sessions": len(session_resumes),
    })


async def index(request):
    try:
        with open("index.html", "r") as f:
            return web.Response(text=f.read(), content_type="text/html")
    except FileNotFoundError:
        return web.Response(text="index.html not found", status=404)


async def on_shutdown(app):
    logger.info("Shutting down...")
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


app = web.Application(client_max_size=10 * 1024 * 1024)
app.router.add_get("/", index)
app.router.add_get("/health", health)
app.router.add_post("/offer", offer)
app.router.add_post("/upload-resume", upload_resume)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    logger.info("Starting Vocat server on http://localhost:8080")
    web.run_app(app, port=8080)
