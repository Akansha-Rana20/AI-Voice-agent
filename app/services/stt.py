import assemblyai as aai
import os
import logging

aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")

logger = logging.getLogger(__name__)

class STTService:
    @staticmethod
    def transcribe_audio(file_path: str) -> str:
        logger.info("Transcribing audio via AssemblyAI")
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(file_path)

        if transcript.error:
            logger.error(f"AssemblyAI transcription error: {transcript.error}")
            raise RuntimeError(f"AssemblyAI error: {transcript.error}")

        return transcript.text or "[Unrecognized speech]"
