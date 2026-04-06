import os
import datetime
from openai import OpenAI
from elevenlabs.client import ElevenLabs, Voice
from elevenlabs import stream
import argparse
from dataclasses import asdict
from models import Message
import speech_recognition as sr
import logging
from pathlib import Path
from pydub import AudioSegment
from pydub.playback import play

logging.basicConfig(level=logging.INFO)

# Ensure these directories exist
os.makedirs("recordings", exist_ok=True)
os.makedirs("transcripts", exist_ok=True)
os.makedirs("outputs", exist_ok=True)
os.makedirs("logs", exist_ok=True)

oai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

CHAT_MODEL = "gpt-4o"
TTS_MODEL = "tts-1"
MODEL_TEMPERATURE = 0.5
AUDIO_MODEL = "whisper-1"
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

def ask_gpt_chat(prompt: str, messages: list[Message]):
    """Returns ChatGPT's response to the given prompt."""
    system_message = [{"role": "system", "content": prompt}]
    message_dicts = [asdict(message) for message in messages]
    conversation_messages = system_message + message_dicts
    response = oai_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=conversation_messages,
        temperature=MODEL_TEMPERATURE
    )
    return response.choices[0].message.content

def setup_prompt(prompt_file: str = 'prompts/customer_support.md') -> str:
    """Loads a conversation prompt from a file."""
    with open(prompt_file, 'r') as f:
        return f.read()

def get_transcription(file_path: str):
    audio_file = open(file_path, "rb")
    transcription = oai_client.audio.transcriptions.create(
        model=AUDIO_MODEL,
        file=audio_file
    )
    return transcription.text

def record():
    # load the speech recognizer with CLI settings
    r = sr.Recognizer()

    # record audio stream from multiple sources
    m = sr.Microphone()

    with m as source:
        r.adjust_for_ambient_noise(source)
        logging.info(f'Listening...')
        audio = r.listen(source)

    # write audio to a WAV file
    timestamp = datetime.datetime.now().timestamp()
    recording_path = Path(f"./recordings/{timestamp}.wav")
    with recording_path.open("wb") as f:
        f.write(audio.get_wav_data())
    transcript = get_transcription(str(recording_path))
    transcript_path = Path(f"./transcripts/{timestamp}.txt")
    with transcript_path.open("w") as f:
        f.write(transcript)
    return transcript

def clean_up():
    logging.info('Exiting...')
    dirs_to_clean = ['./recordings', './transcripts', './outputs']
    for dir_path in dirs_to_clean:
        try:
            for file in os.listdir(dir_path):
                file_path = os.path.join(dir_path, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except OSError as e:
            logging.warning(f"Failed to clean {dir_path}: {e}")
    # Save the conversation
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(f'logs/conversation_{timestamp}.txt', 'w') as f:
        for message in conversation_messages:
            f.write(f"{message.role}: {message.content}\n")

def oai_text_to_speech(text: str):
    timestamp = datetime.datetime.now().timestamp()
    speech_file_path = Path(f"./outputs/{timestamp}.mp3")
    response = oai_client.audio.speech.create(
        model=TTS_MODEL,
        voice="nova",
        input=text
    )
    with speech_file_path.open("wb") as f:
        f.write(response.content)
    return str(speech_file_path)

def play_audio(file_path):
    audio = AudioSegment.from_file(file_path)
    play(audio)

def elevenlabs_text_to_speech(text: str):
    audio_stream = elevenlabs_client.generate(
        text=text,
        voice=Voice(
            voice_id=VOICE_ID
        ),
        stream=True
    )
    stream(audio_stream)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-pf", "--prompt_file", help="Specify the prompt file to use.", type=str)
    parser.add_argument("-tts", "--tts_type", help="Specify the TTS type to use.", type=str, default="openai", choices=["openai", "elevenlabs"])
    args = parser.parse_args()
    prompt_file = args.prompt_file
    tts_type = args.tts_type or "openai"

    prompt = setup_prompt(prompt_file)
    conversation_messages = []
    while True:
        try:
            user_input = record()
            logging.info(f'Receiver: {user_input}')
            conversation_messages.append(Message(role="user", content=user_input))
            answer = ask_gpt_chat(prompt, conversation_messages)
            logging.info(f'Caller: {answer}')
            logging.info('Playing audio...')
            if tts_type == "elevenlabs":
                elevenlabs_text_to_speech(answer)
            else:
                audio_file = oai_text_to_speech(answer)
                # Play the audio file
                play_audio(audio_file)
            conversation_messages.append(Message(role="assistant", content=answer))
            if 'bye' in user_input.lower():
                clean_up()
                break
        except KeyboardInterrupt:
            clean_up()
            break
