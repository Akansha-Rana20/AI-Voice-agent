# main.py
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import logging
import asyncio
import base64
import re
import inspect
import json
from typing import Dict, Any, Optional
import time
import uuid

# Import original services with fallback
try:
    from services import stt, llm, tts
    from services.agent import agent_response
except ImportError as e:
    logging.warning(f"Import warning: {e}")
    # We'll handle this in the websocket endpoint

try:
    from app.services.memory import MemoryManager

    memory_manager = MemoryManager()
except ImportError:
    logging.warning("Memory manager not available")
    memory_manager = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("voice-agent-pro")

app = FastAPI(title="AI Voice Agent Pro", version="2.0.0")

# Mount static files
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Session storage
active_sessions: Dict[str, Dict[str, Any]] = {}


@app.get("/")
async def home(request: Request):
    """Serves the enhanced main HTML page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0",
        "active_sessions": len(active_sessions)
    }


class SimpleWebSocketManager:
    """Simplified WebSocket manager."""

    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.session_data: Dict[str, Dict] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.connections[session_id] = websocket
        self.session_data[session_id] = {
            "connected_at": time.time(),
            "message_count": 0,
            "chat_history": [],
            "api_keys": {},
            "settings": {
                "voice": "en-US-natalie",
                "speech_rate": 1.0
            },
            "transcriber": None
        }
        logger.info(f"WebSocket session {session_id} connected")

    async def disconnect(self, session_id: str):
        if session_id in self.connections:
            # Cleanup transcriber
            session = self.session_data.get(session_id)
            if session and session.get("transcriber"):
                transcriber = session["transcriber"]
                try:
                    if hasattr(transcriber, "close"):
                        close_method = getattr(transcriber, "close")
                        if callable(close_method):
                            if inspect.iscoroutinefunction(close_method):
                                await close_method()
                            else:
                                close_method()
                except Exception as e:
                    logger.warning(f"Error closing transcriber: {e}")

            del self.connections[session_id]
            if session_id in self.session_data:
                del self.session_data[session_id]
            logger.info(f"WebSocket session {session_id} disconnected")

    async def send_message(self, session_id: str, message: dict):
        if session_id in self.connections:
            try:
                await self.connections[session_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {session_id}: {e}")
                await self.disconnect(session_id)

    def get_session(self, session_id: str) -> Dict:
        return self.session_data.get(session_id, {})

    def update_session(self, session_id: str, updates: Dict):
        if session_id in self.session_data:
            self.session_data[session_id].update(updates)


# Initialize WebSocket manager
ws_manager = SimpleWebSocketManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Enhanced WebSocket endpoint with configuration support."""

    session_id = f"session_{uuid.uuid4().hex[:8]}"

    try:
        await ws_manager.connect(websocket, session_id)
        loop = asyncio.get_event_loop()

        async def handle_transcript(text: str):
            """Handle transcript processing."""
            try:
                session = ws_manager.get_session(session_id)
                chat_history = session.get("chat_history", [])
                api_keys = session.get("api_keys", {})

                # Validate API keys
                required_keys = ["gemini", "assembly", "murf"]
                missing_keys = [key for key in required_keys if not api_keys.get(key)]

                if missing_keys:
                    await ws_manager.send_message(session_id, {
                        "type": "error",
                        "text": f"Please configure these API keys: {', '.join(missing_keys)}"
                    })
                    return

                # Send final transcript
                await ws_manager.send_message(session_id, {
                    "type": "final",
                    "text": text
                })

                # Get LLM response
                try:
                    # Use the original agent_response function with API keys
                    full_response, updated_history = await get_agent_response(
                        text, chat_history, api_keys
                    )

                    # Update chat history
                    ws_manager.update_session(session_id, {"chat_history": updated_history})

                    # Send assistant response
                    await ws_manager.send_message(session_id, {
                        "type": "assistant",
                        "text": full_response
                    })

                    # Generate TTS
                    await process_tts(session_id, full_response, session.get("settings", {}), api_keys)

                except Exception as e:
                    logger.error(f"Error in agent response: {e}")
                    await ws_manager.send_message(session_id, {
                        "type": "error",
                        "text": "Sorry, I encountered an error processing your request."
                    })

            except Exception as e:
                logger.error(f"Error in transcript handler: {e}")
                await ws_manager.send_message(session_id, {
                    "type": "error",
                    "text": "Sorry, an error occurred while processing your request."
                })

        def on_final_transcript(text: str):
            """Callback for final transcript."""
            logger.info(f"Final transcript for {session_id}: {text}")
            asyncio.run_coroutine_threadsafe(handle_transcript(text), loop)

        # Main message loop
        while True:
            try:
                message = await websocket.receive()

                if "bytes" in message:  # Audio data
                    session = ws_manager.get_session(session_id)
                    transcriber = session.get("transcriber")

                    if transcriber:
                        try:
                            if inspect.iscoroutinefunction(transcriber.stream_audio):
                                await transcriber.stream_audio(message["bytes"])
                            else:
                                transcriber.stream_audio(message["bytes"])
                        except Exception as e:
                            logger.error(f"Transcriber error: {e}")

                elif "text" in message:  # Control messages
                    try:
                        data = json.loads(message["text"])
                        await handle_control_message(session_id, data, on_final_transcript)
                    except json.JSONDecodeError:
                        await ws_manager.send_message(session_id, {
                            "type": "ack",
                            "text": "Message received"
                        })

            except WebSocketDisconnect:
                logger.info(f"WebSocket {session_id} disconnected by client")
                break
            except Exception as e:
                logger.error(f"WebSocket error for {session_id}: {e}")
                break

    finally:
        await ws_manager.disconnect(session_id)


async def handle_control_message(session_id: str, data: dict, transcript_callback):
    """Handle control messages like configuration updates."""
    message_type = data.get("type")

    if message_type == "config":
        # Update API keys and settings
        api_keys = data.get("apiKeys", {})
        settings = data.get("settings", {})

        ws_manager.update_session(session_id, {
            "api_keys": api_keys,
            "settings": settings
        })

        # Initialize transcriber with new API key
        if api_keys.get("assembly"):
            try:
                # Create transcriber with dynamic API key
                transcriber = stt.AssemblyAIStreamingTranscriber(
                    api_key=api_keys["assembly"],
                    on_final_callback=transcript_callback
                )

                ws_manager.update_session(session_id, {"transcriber": transcriber})

                await ws_manager.send_message(session_id, {
                    "type": "status",
                    "text": "Configuration updated successfully! 🎉",
                    "level": "success"
                })
            except Exception as e:
                logger.error(f"Failed to initialize transcriber: {e}")
                await ws_manager.send_message(session_id, {
                    "type": "error",
                    "text": "Failed to initialize speech recognition. Please check your AssemblyAI API key."
                })


async def get_agent_response(query: str, history: list, api_keys: dict):
    """Get agent response with API key support."""
    try:
        # Simple search trigger check
        search_triggers = ["latest", "today", "current", "news", "price", "weather"]
        needs_search = any(trigger in query.lower() for trigger in search_triggers)

        if needs_search and api_keys.get("serpapi"):
            # Use search (simplified)
            from app.services.search import web_search
            search_result = web_search(query)
            enhanced_query = f"Based on this information: {search_result}\n\nAnswer: {query}"
            response, updated_history = llm.get_llm_response(enhanced_query, history)
        else:
            # Use LLM directly
            response, updated_history = llm.get_llm_response(query, history)

        return response, updated_history

    except Exception as e:
        logger.error(f"Error in agent response: {e}")
        return "I apologize, but I encountered an error. Please check your API configuration.", history


async def process_tts(session_id: str, text: str, settings: dict, api_keys: dict):
    """Process text-to-speech."""
    try:
        # Split into sentences
        sentences = re.split(r'(?<=[.?!])\s+', text.strip())

        for sentence in sentences:
            if sentence.strip():
                # Generate audio
                loop = asyncio.get_event_loop()
                audio_bytes = await loop.run_in_executor(
                    None,
                    tts.speak,
                    sentence.strip(),
                    settings.get("voice", "en-US-natalie"),  # ✅ valid voiceId
                    "mp3"
                )

                if audio_bytes:
                    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                    await ws_manager.send_message(session_id, {
                        "type": "audio",
                        "b64": b64_audio
                    })

    except Exception as e:
        logger.error(f"TTS processing error: {e}")
        await ws_manager.send_message(session_id, {
            "type": "error",
            "text": "Audio generation failed"
        })


@app.on_event("startup")
async def startup_event():
    """Application startup event."""
    logger.info("🚀 AI Voice Agent Pro started successfully!")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event."""
    logger.info("🛑 AI Voice Agent Pro shutting down...")

    # Close all WebSocket connections
    for session_id in list(ws_manager.connections.keys()):
        await ws_manager.disconnect(session_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )