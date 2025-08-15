import requests
import os
import logging

MURF_BASE_URL = os.getenv("MURF_BASE_URL")
MURF_API_KEY = os.getenv("MURF_API_KEY")

logger = logging.getLogger(__name__)

class TTSService:
    @staticmethod
    def generate_speech(text: str) -> str:
        logger.info("Requesting Murf TTS API")
        headers = {
            "api-key": MURF_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "voiceId": "en-US-natalie",
            "format": "MP3",
            "sampleRate": 44100,
            "model": "GEN2"
        }

        response = requests.post(f"{MURF_BASE_URL}/v1/speech/generate", headers=headers, json=payload)
        if response.status_code != 200:
            logger.error(f"Murf API error: {response.text}")
            raise RuntimeError(f"Murf API error: {response.text}")

        audio_file_url = response.json().get("audioFile")
        if not audio_file_url:
            logger.error("No audio URL received from Murf")
            raise RuntimeError("No audio URL received from Murf")

        return audio_file_url
