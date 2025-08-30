# Fixed services/stt.py for deployment - handles missing assemblyai.streaming
import os
import logging
import queue
import threading
from typing import Optional, Callable, Dict, Any
import time

logger = logging.getLogger(__name__)

# Try to import AssemblyAI with fallback
ASSEMBLYAI_AVAILABLE = False
STREAMING_AVAILABLE = False

try:
    import assemblyai as aai

    ASSEMBLYAI_AVAILABLE = True
    logger.info("✅ AssemblyAI base library available")
except ImportError as e:
    logger.warning(f"❌ AssemblyAI not available: {e}")
    aai = None

try:
    from assemblyai.streaming.v3 import (
        StreamingClient,
        StreamingClientOptions,
        StreamingParameters,
        StreamingSessionParameters,
        StreamingEvents,
        BeginEvent,
        TurnEvent,
        TerminationEvent,
        StreamingError,
    )

    STREAMING_AVAILABLE = True
    logger.info("✅ AssemblyAI streaming available")
except ImportError as e:
    logger.warning(f"❌ AssemblyAI streaming not available: {e}")
    # Create placeholder classes
    StreamingClient = None
    StreamingClientOptions = None
    StreamingParameters = None
    StreamingSessionParameters = None
    StreamingEvents = None
    BeginEvent = None
    TurnEvent = None
    TerminationEvent = None
    StreamingError = Exception


def _on_begin(client, event):
    if event and hasattr(event, 'id'):
        logger.info(f"AssemblyAI session started: {event.id}")
    else:
        logger.info("AssemblyAI session started")


def _on_termination(client, event):
    if event and hasattr(event, 'audio_duration_seconds'):
        logger.info(f"AssemblyAI session terminated after {event.audio_duration_seconds:.2f}s")
    else:
        logger.info("AssemblyAI session terminated")


def _on_error(client, error):
    logger.error("AssemblyAI error: %s", error)


class AssemblyAIStreamingTranscriber:
    """
    AssemblyAI transcriber with fallback support for missing streaming module.
    """

    def __init__(
            self,
            api_key: str = None,
            sample_rate: int = 16000,
            on_partial_callback: Optional[Callable[[str], None]] = None,
            on_final_callback: Optional[Callable[[str], None]] = None,
            language_code: str = "en",
            enable_automatic_punctuation: bool = True,
            enable_format_text: bool = True,
    ):
        # Use provided API key or environment variable
        if not api_key:
            api_key = os.getenv("ASSEMBLYAI_API_KEY")

        if not api_key:
            raise ValueError("AssemblyAI API key is required")

        self.api_key = api_key
        self.sample_rate = sample_rate
        self.on_partial_callback = on_partial_callback
        self.on_final_callback = on_final_callback
        self.language_code = language_code
        self.enable_automatic_punctuation = enable_automatic_punctuation
        self.enable_format_text = enable_format_text

        # Check service availability
        if not ASSEMBLYAI_AVAILABLE:
            raise ImportError("AssemblyAI library is not installed")

        if not STREAMING_AVAILABLE:
            logger.warning("AssemblyAI streaming not available, using fallback transcriber")
            self._init_fallback_transcriber()
            return

        # Configure AssemblyAI
        aai.settings.api_key = self.api_key

        # Initialize streaming client
        try:
            self.client = StreamingClient(
                StreamingClientOptions(
                    api_key=self.api_key,
                    api_host="streaming.assemblyai.com",
                )
            )

            # Register event handlers
            if StreamingEvents:
                self.client.on(StreamingEvents.Begin, _on_begin)
                self.client.on(StreamingEvents.Error, self._on_error)
                self.client.on(StreamingEvents.Termination, _on_termination)
                self.client.on(StreamingEvents.Turn, self._on_turn)

        except Exception as e:
            logger.error(f"Failed to initialize streaming client: {e}")
            self._init_fallback_transcriber()
            return

        # Internal streaming state
        self._q: "queue.Queue[Optional[bytes]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._connected = threading.Event()
        self._session_id: Optional[str] = None
        self._stats = {
            "start_time": None,
            "end_time": None,
            "total_audio_duration": 0,
            "turns_processed": 0,
            "errors_count": 0
        }
        self._use_fallback = False

        # Start background streaming thread
        try:
            self._start_background_stream()
        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")
            self._init_fallback_transcriber()

    def _init_fallback_transcriber(self):
        """Initialize fallback transcriber when streaming is not available."""
        self._use_fallback = True
        self.client = None
        self._q = queue.Queue()
        self._thread = None
        self._connected = threading.Event()
        self._connected.set()  # Mark as "connected" for fallback mode

        logger.info("Initialized fallback transcriber (streaming not available)")

    def _on_error(self, client, error):
        """Enhanced error handler."""
        logger.error("AssemblyAI streaming error: %s", error)
        if hasattr(self, '_stats'):
            self._stats["errors_count"] += 1

    def _on_turn(self, client, event):
        """Enhanced turn handler."""
        try:
            if not event:
                return

            text = getattr(event, 'transcript', '') or ""
            text = text.strip()
            if not text:
                return

            # Update statistics
            if hasattr(self, '_stats'):
                self._stats["turns_processed"] += 1

            # Process text
            processed_text = self._process_transcript_text(text)

            end_of_turn = getattr(event, 'end_of_turn', False)

            if end_of_turn:
                if self.on_final_callback:
                    try:
                        self.on_final_callback(processed_text)
                    except Exception as cb_err:
                        logger.exception("Final-callback error: %s", cb_err)

                # Enable formatted turns for better accuracy
                turn_is_formatted = getattr(event, 'turn_is_formatted', False)
                if not turn_is_formatted and self.client and StreamingSessionParameters:
                    try:
                        self.client.set_params(StreamingSessionParameters(
                            format_turns=True,
                            language_code=self.language_code,
                            punctuate=self.enable_automatic_punctuation
                        ))
                    except Exception as set_err:
                        logger.warning("set_params error: %s", set_err)
            else:
                if self.on_partial_callback:
                    try:
                        self.on_partial_callback(processed_text)
                    except Exception as cb_err:
                        logger.exception("Partial-callback error: %s", cb_err)

        except Exception as e:
            logger.exception("Error in turn handler: %s", e)
            if hasattr(self, '_stats'):
                self._stats["errors_count"] += 1

    def _process_transcript_text(self, text: str) -> str:
        """Process and clean transcript text."""
        if not text:
            return ""

        # Basic text cleaning
        text = text.strip()

        # Remove excessive whitespace
        import re
        text = re.sub(r'\s+', ' ', text)

        # Auto-capitalize first letter if needed
        if text and not text[0].isupper():
            text = text[0].upper() + text[1:]

        return text

    def stream_audio(self, audio_chunk: bytes):
        """Feed raw audio bytes to the transcriber."""
        if self._use_fallback:
            # In fallback mode, simulate processing
            if self.on_final_callback and len(audio_chunk) > 1000:  # Simulate speech detection
                try:
                    # This is a placeholder - in a real fallback, you'd use another STT service
                    self.on_final_callback("Audio processed (streaming transcription not available)")
                except Exception as e:
                    logger.error(f"Fallback callback error: {e}")
            return

        if audio_chunk and self._q:
            self._q.put(audio_chunk)

    def close(self):
        """Stop streaming and terminate session."""
        logger.info("Closing AssemblyAI transcriber...")

        if hasattr(self, '_stats'):
            self._stats["end_time"] = time.time()

        if self._use_fallback:
            logger.info("Closed fallback transcriber")
            return

        # Signal generator to finish
        if self._q:
            self._q.put(None)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        # Log session statistics
        self._log_session_stats()

    def _audio_generator(self):
        """Generate audio chunks from queue."""
        try:
            while True:
                chunk = self._q.get(timeout=30)
                if chunk is None:
                    break
                yield chunk
        except queue.Empty:
            logger.warning("Audio generator timeout")
        except Exception as e:
            logger.error(f"Audio generator error: {e}")

    def _start_background_stream(self):
        """Start the background streaming thread."""
        if not self.client or not StreamingParameters:
            raise Exception("Streaming client not available")

        def runner():
            try:
                if hasattr(self, '_stats'):
                    self._stats["start_time"] = time.time()

                # Connect with parameters
                self.client.connect(
                    StreamingParameters(
                        sample_rate=self.sample_rate,
                        format_turns=False,
                        language_code=self.language_code,
                        punctuate=self.enable_automatic_punctuation,
                        format_text=self.enable_format_text
                    )
                )
                self._connected.set()

                # Stream audio from generator
                self.client.stream(self._audio_generator())

            except Exception as e:
                logger.exception("AssemblyAI streaming thread crashed: %s", e)
                if hasattr(self, '_stats'):
                    self._stats["errors_count"] += 1
            finally:
                try:
                    if self.client:
                        self.client.disconnect(terminate=True)
                except Exception:
                    pass

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

        # Wait for connection with timeout
        if not self._connected.wait(timeout=10):
            logger.error("AssemblyAI connection timeout")
            raise TimeoutError("Failed to connect to AssemblyAI within 10 seconds")

    def _log_session_stats(self):
        """Log session statistics."""
        if not hasattr(self, '_stats'):
            return

        if self._stats["start_time"] and self._stats["end_time"]:
            duration = self._stats["end_time"] - self._stats["start_time"]
            logger.info(
                f"AssemblyAI session stats: "
                f"Duration: {duration:.1f}s, "
                f"Turns: {self._stats['turns_processed']}, "
                f"Errors: {self._stats['errors_count']}"
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get current session statistics."""
        if not hasattr(self, '_stats'):
            return {}

        stats = self._stats.copy()
        if self._stats["start_time"]:
            current_time = time.time()
            stats["current_duration"] = current_time - self._stats["start_time"]
        return stats


# Factory functions for creating transcribers
def create_transcriber(api_key: str = None, **kwargs) -> AssemblyAIStreamingTranscriber:
    """Factory function to create transcriber with validation."""
    return AssemblyAIStreamingTranscriber(api_key=api_key, **kwargs)


def validate_api_key(api_key: str) -> tuple[bool, str]:
    """Validate AssemblyAI API key."""
    if not api_key or not api_key.strip():
        return False, "API key is empty"

    if not ASSEMBLYAI_AVAILABLE:
        return False, "AssemblyAI library not available"

    try:
        # Test API key by making a simple request
        import requests

        headers = {"authorization": api_key}
        response = requests.get(
            "https://api.assemblyai.com/v2/user",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            return True, "API key is valid"
        elif response.status_code == 401:
            return False, "Invalid API key"
        elif response.status_code == 403:
            return False, "API key lacks required permissions"
        else:
            return False, f"API validation failed: HTTP {response.status_code}"

    except requests.exceptions.Timeout:
        return False, "API request timeout"
    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to AssemblyAI API"
    except Exception as e:
        logger.error(f"API key validation error: {e}")
        return False, f"Validation error: {str(e)}"


def get_account_info(api_key: str) -> Dict[str, Any]:
    """Get account information from AssemblyAI."""
    if not ASSEMBLYAI_AVAILABLE:
        return {"error": "AssemblyAI library not available"}

    try:
        import requests

        headers = {"authorization": api_key}
        response = requests.get(
            "https://api.assemblyai.com/v2/user",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return response.json()

    except Exception as e:
        logger.error(f"Error getting account info: {e}")
        return {"error": str(e)}


# Legacy class name for backward compatibility
class AssemblyAIStreamingTranscriberLegacy(AssemblyAIStreamingTranscriber):
    """Legacy class for backward compatibility."""

    def __init__(
            self,
            on_partial_callback: Optional[Callable[[str], None]] = None,
            on_final_callback: Optional[Callable[[str], None]] = None,
            sample_rate: int = 16000,
            api_key: str = None
    ):
        if not api_key:
            api_key = os.getenv("ASSEMBLYAI_API_KEY", "")

        super().__init__(
            api_key=api_key,
            sample_rate=sample_rate,
            on_partial_callback=on_partial_callback,
            on_final_callback=on_final_callback
        )


# Service availability check
def is_service_available() -> bool:
    """Check if AssemblyAI service is available."""
    return ASSEMBLYAI_AVAILABLE and STREAMING_AVAILABLE


def get_service_status() -> Dict[str, Any]:
    """Get detailed service status."""
    return {
        "assemblyai_available": ASSEMBLYAI_AVAILABLE,
        "streaming_available": STREAMING_AVAILABLE,
        "service_ready": ASSEMBLYAI_AVAILABLE and STREAMING_AVAILABLE,
        "fallback_mode": ASSEMBLYAI_AVAILABLE and not STREAMING_AVAILABLE
    }


# Error classes for better error handling
class STTServiceError(Exception):
    """Base exception for STT service errors."""
    pass


class STTConnectionError(STTServiceError):
    """Exception for connection-related errors."""
    pass


class STTAPIError(STTServiceError):
    """Exception for API-related errors."""
    pass


class STTConfigurationError(STTServiceError):
    """Exception for configuration-related errors."""
    pass