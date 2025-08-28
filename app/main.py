# main.py
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import logging
import asyncio
import base64
import re
import inspect
import config
from app.services import stt, llm, tts
from app.services.agent import agent_response


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("voice-agent")

app = FastAPI()

# Mount static files for CSS/JS
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
async def home(request: Request):
    """Serves the main HTML page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handles WebSocket connection for real-time transcription and voice response."""
    await websocket.accept()
    logging.info("WebSocket client connected.")

    loop = asyncio.get_event_loop()
    chat_history = []

    async def handle_transcript(text: str):
        """Processes the final transcript, gets LLM and TTS responses, and streams audio."""
        await websocket.send_json({"type": "final", "text": text})
        try:
            # 1. Get the full text response from the LLM (non-streaming)
            full_response, updated_history = agent_response(text, chat_history)

            # Update history
            chat_history.clear()
            chat_history.extend(updated_history)

            # Send assistant text response
            await websocket.send_json({"type": "assistant", "text": full_response})

            # 2. Split into sentences
            sentences = re.split(r'(?<=[.?!])\s+', full_response.strip())

            # 3. Convert each to audio and stream back
            for sentence in sentences:
                if sentence.strip():
                    audio_bytes = await loop.run_in_executor(
                        None, tts.speak, sentence.strip()
                    )
                    if audio_bytes:
                        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                        await websocket.send_json({"type": "audio", "b64": b64_audio})

        except Exception as e:
            logging.error(f"Error in LLM/TTS pipeline: {e}")
            await websocket.send_json(
                {"type": "error", "text": "Sorry, something went wrong."}
            )

    def on_final_transcript(text: str):
        logging.info(f"Final transcript received: {text}")
        asyncio.run_coroutine_threadsafe(handle_transcript(text), loop)

    # ✅ Initialize async AssemblyAI transcriber (no need to call connect)
    transcriber = stt.AssemblyAIStreamingTranscriber(
        on_final_callback=on_final_transcript
    )

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message:  # audio chunks
                if inspect.iscoroutinefunction(transcriber.stream_audio):
                    await transcriber.stream_audio(message["bytes"])
                else:
                    transcriber.stream_audio(message["bytes"])

            elif "text" in message:  # metadata or ping
                logging.info(f"Received text from client: {message['text']}")
                await websocket.send_json({"type": "ack", "text": "Message received"})

            else:
                logging.warning(f"Unknown message type: {message}")

    except Exception as e:
        logging.info(f"WebSocket connection closed: {e}")

    finally:
        if transcriber is not None:
            close_method = getattr(transcriber, "close", None)
            if callable(close_method):
                maybe_coro = close_method()
                if maybe_coro is not None and inspect.iscoroutine(maybe_coro):
                    await maybe_coro
        logger.info("WebSocket connection closed.")
