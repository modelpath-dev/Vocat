import asyncio
import json
import logging
import uuid
import os
import re
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaPlayer
from pydub import AudioSegment
import webrtcvad
from openai import OpenAI
from elevenlabs.client import ElevenLabs
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable not set.")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

ELEVEN_LABS_API_KEY = os.environ.get("ELEVEN_LABS_API_KEY")
if not ELEVEN_LABS_API_KEY:
    raise ValueError("ELEVEN_LABS_API_KEY environment variable not set.")
eleven_client = ElevenLabs(api_key=ELEVEN_LABS_API_KEY)

redis_client = None

async def init_redis():
    global redis_client
    try:
        redis_client = await aioredis.from_url("redis://localhost:6379")
        await redis_client.ping()
        logger.info("Connected to Redis successfully.")
    except Exception as e:
        logger.warning(f"Could not connect to Redis. Caching disabled. Error: {e}")
        redis_client = None

pcs = set()

VAD_AGGRESSIVENESS = 3
vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
SAMPLE_RATE = 16000
VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = int(SAMPLE_RATE * (VAD_FRAME_MS / 1000.0))
VAD_SILENCE_TIMEOUT_MS = 600
VAD_NUM_SILENT_FRAMES_TO_TRIGGER = VAD_SILENCE_TIMEOUT_MS // VAD_FRAME_MS

SENTENCE_ENDINGS = re.compile(r'([.!?;])\s')

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

class VADAudioProcessor(MediaStreamTrack):
    kind = "audio"

    def __init__(self, track, pc):
        super().__init__()
        self.track = track
        self.pc = pc
        self.is_speaking = False
        self.silent_frames_count = 0
        self.audio_buffer = AudioSegment.empty()
        self.players = []
        self.chat_history = [
            {"role": "system", "content": "You are a helpful, conversational AI assistant. Your responses should be concise and natural, as if you are on a phone call. Do not use markdown. Keep your answers to one or two sentences."}
        ]
        logger.info("VADAudioProcessor initialized.")

    async def play_sentence_audio(self, text):
        try:
            logger.info(f"Generating audio for: {text[:50]}...")
            
            audio_generator = eleven_client.generate(
                text=text,
                voice="Rachel",
                model="eleven_multilingual_v2"
            )
            
            audio_data = b""
            for chunk in audio_generator:
                audio_data += chunk
            
            ai_file_path = f"temp_ai_response_{uuid.uuid4()}.mp3"
            with open(ai_file_path, "wb") as f:
                f.write(audio_data)
            
            player = MediaPlayer(ai_file_path)
            ai_audio_track = player.audio
            
            if ai_audio_track:
                self.pc.addTrack(ai_audio_track)
                self.players.append(player)
                logger.info("Audio track added to peer connection.")
                
                @ai_audio_track.on("ended")
                def on_ended():
                    logger.info("Audio track finished playing.")
                    if os.path.exists(ai_file_path):
                        try:
                            os.remove(ai_file_path)
                        except:
                            pass
                    if player in self.players:
                        self.players.remove(player)

        except Exception as e:
            logger.error(f"Error playing audio: {e}")

    async def generate_and_play_ai_response(self, text):
        try:
            self.chat_history.append({"role": "user", "content": text})
            
            cached_response = None
            if redis_client:
                try:
                    cached_response = await redis_client.get(f"vocat:transcript:{text}")
                except Exception as e:
                    logger.warning(f"Redis GET failed: {e}")
            
            if cached_response:
                response_text = cached_response.decode('utf-8')
                logger.info(f"Cache HIT: {response_text[:50]}...")
                
                sentences = split_into_sentences(response_text)
                for sentence in sentences:
                    if sentence.strip():
                        await self.play_sentence_audio(sentence)
                
                self.chat_history.append({"role": "assistant", "content": response_text})
                return

            logger.info("Cache MISS. Streaming from GPT-4...")
            stream = openai_client.chat.completions.create(
                model="gpt-4",
                messages=self.chat_history,
                stream=True
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
                            asyncio.create_task(self.play_sentence_audio(sentence))
            
            if sentence_buffer.strip():
                asyncio.create_task(self.play_sentence_audio(sentence_buffer.strip()))
            
            logger.info(f"GPT-4 response: {full_response[:100]}...")
            self.chat_history.append({"role": "assistant", "content": full_response})

            if redis_client and full_response:
                try:
                    await redis_client.set(f"vocat:transcript:{text}", full_response, ex=3600)
                    logger.info("Response cached.")
                except Exception as e:
                    logger.warning(f"Redis SET failed: {e}")

        except Exception as e:
            logger.error(f"Error in AI pipeline: {e}")

    async def transcribe_audio(self):
        logger.info(f"Transcribing {len(self.audio_buffer)}ms of audio.")
        temp_file_path = f"temp_audio_{uuid.uuid4()}.wav"
        
        try:
            self.audio_buffer.export(temp_file_path, format="wav")

            with open(temp_file_path, "rb") as audio_file:
                transcript = openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="en"
                )
            
            logger.info(f"Transcription: {transcript.text}")

            if transcript.text.strip():
                asyncio.create_task(self.generate_and_play_ai_response(transcript.text))

        except Exception as e:
            logger.error(f"Transcription error: {e}")
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except:
                    pass
            self.audio_buffer = AudioSegment.empty()
            self.is_speaking = False
            self.silent_frames_count = 0

    async def recv(self):
        frame = await self.track.recv()

        try:
            segment = AudioSegment(
                data=frame.to_ndarray().tobytes(),
                sample_width=2,
                frame_rate=frame.sample_rate,
                channels=len(frame.layout.channels)
            ).set_frame_rate(SAMPLE_RATE).set_channels(1)
            
            raw_samples = segment.raw_data
            
            for i in range(0, len(raw_samples), VAD_FRAME_SAMPLES * 2):
                chunk = raw_samples[i : i + VAD_FRAME_SAMPLES * 2]
                
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
                        asyncio.create_task(self.transcribe_audio())
                        self.is_speaking = False
                        self.silent_frames_count = 0
                        self.audio_buffer = AudioSegment.empty()

        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            
        return frame

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pc_id = f"PeerConnection({uuid.uuid4()})"
    pcs.add(pc)
    logger.info(f"Created {pc_id}")

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"[{pc_id}] Connection state: {pc.connectionState}")
        if pc.connectionState in ["failed", "closed"]:
            logger.info(f"[{pc_id}] Closing connection.")
            await pc.close()
            pcs.discard(pc)

    @pc.on("track")
    def on_track(track):
        logger.info(f"[{pc_id}] Track received: {track.kind}")
        
        if track.kind == "audio":
            vad_processor = VADAudioProcessor(track, pc)
            pc.addTrack(vad_processor)
            logger.info(f"[{pc_id}] VADAudioProcessor attached.")

        @track.on("ended")
        async def on_ended():
            logger.info(f"[{pc_id}] Track {track.kind} ended")

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    logger.info(f"[{pc_id}] Sending answer.")
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )

async def index(request):
    try:
        with open("index.html", "r") as f:
            return web.Response(text=f.read(), content_type="text/html")
    except FileNotFoundError:
        logger.error("index.html not found")
        return web.Response(text="index.html not found", status=404)

async def on_startup(app):
    await init_redis()

async def on_shutdown(app):
    logger.info("Shutting down...")
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
    if redis_client:
        await redis_client.close()
        logger.info("Redis closed.")

app = web.Application()
app.router.add_get("/", index)
app.router.add_post("/offer", offer)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    logger.info("Starting Vocat server on http://localhost:8080")
    web.run_app(app, port=8080)