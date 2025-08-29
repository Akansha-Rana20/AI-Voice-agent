# app/services/tts.py
import logging
import requests
import config

logger = logging.getLogger("app.services.tts")

MURF_API_URL = "https://api.murf.ai/v1/speech/generate"

def speak(text: str, voice_id: str = "en-US-natalie", format: str = "MP3"):
    """
    Wrapper to synthesize speech using Murf API.
    Returns audio bytes or None.
    """
    headers = {
        "api-key": config.MURF_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "voiceId": voice_id,
        "text": text,
        "format": format
    }

    try:
        response = requests.post(MURF_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        audio_url = data.get("audioFile")
        if not audio_url:
            logger.error("Murf response missing audioFile: %s", data)
            return None

        audio_response = requests.get(audio_url)
        audio_response.raise_for_status()
        return audio_response.content

    except Exception as e:
        logger.error("TTS error: %s", e)
        return None
