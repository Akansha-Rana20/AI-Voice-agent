import os
import logging
import queue
import threading
from typing import Optional, Callable, Dict, Any
import time
import hashlib

import assemblyai as aai
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

logger = logging.getLogger(__name__)

# Cache for API validation
_api_cache = {}
_cache_timeout = 3600  # 1 hour


def _on_begin(client: StreamingClient, event: BeginEvent):
    logger.info(f"AssemblyAI session started: {event.id}")


def _on_termination(client: StreamingClient, event: TerminationEvent):
    logger.info(f"AssemblyAI session terminated after {event.audio_duration_seconds:.2f}s")


def _on_error(client: StreamingClient, error: StreamingError):
    logger.error("AssemblyAI error: %s", error)


class EnhancedAssemblyAITranscriber:
    """
    Enhanced AssemblyAI transcriber with dynamic API key support and better error handling.
    """

    @staticmethod
    def validate_api_key(api_key: str) -> tuple[bool, str]:
        """Validate AssemblyAI API key with caching."""
        if not api_key or not api_key.strip():
            return False, "API key is empty"

        # Check cache
        cache_key = hashlib.sha256(api_key.encode()).hexdigest()
        current_time = time.time()

        if cache_key in _api_cache:
            result, timestamp = _api_cache[cache_key]
            if current_time - timestamp < _cache_timeout:
                return result

        try:
            # Test API key by getting account info
            import requests

            headers = {"authorization": api_key}
            response = requests.get(
                "https://api.assemblyai.com/v2/account",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                result = (True, "API key is valid")
            elif response.status_code == 401:
                result = (False, "Invalid API key")
            elif response.status_code == 403:
                result = (False, "API key lacks required permissions")
            else:
                result = (False, f"API validation failed: HTTP {response.status_code}")

            # Cache result
            _api_cache[cache_key] = (result, current_time)
            return result

        except requests.exceptions.Timeout:
            return False, "API request timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to AssemblyAI API"
        except Exception as e:
            logger.error(f"API key validation error: {e}")
            return False, f"Validation error: {str(e)}"

    @staticmethod
    def get_account_info(api_key: str) -> Dict[str, Any]:
        """Get account information from AssemblyAI."""
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


class AssemblyAIStreamingTranscriber:
    """
    Enhanced streaming transcriber with dynamic API key support.
    """

    def __init__(
            self,
            api_key: str,
            sample_rate: int = 16000,
            on_partial_callback: Optional[Callable[[str], None]] = None,
            on_final_callback: Optional[Callable[[str], None]] = None,
            language_code: str = "en",
            enable_automatic_punctuation: bool = True,
            enable_format_text: bool = True,
    ):
        if not api_key:
            raise ValueError(
                "AssemblyAI API key is required. Please provide it via UI or set ASSEMBLYAI_API_KEY in .env"
            )

        self.api_key = api_key
        self.sample_rate = sample_rate
        self.on_partial_callback = on_partial_callback
        self.on_final_callback = on_final_callback
        self.language_code = language_code
        self.enable_automatic_punctuation = enable_automatic_punctuation
        self.enable_format_text = enable_format_text

        # Validate API key
        is_valid, message = EnhancedAssemblyAITranscriber.validate_api_key(api_key)
        if not is_valid:
            raise ValueError(f"Invalid AssemblyAI API key: {message}")

        # Configure AssemblyAI
        aai.settings.api_key = self.api_key

        # Initialize streaming client
        self.client = StreamingClient(
            StreamingClientOptions(
                api_key=self.api_key,
                api_host="streaming.assemblyai.com",
            )
        )

        # Register event handlers
        self.client.on(StreamingEvents.Begin, _on_begin)
        self.client.on(StreamingEvents.Error, self._on_error)
        self.client.on(StreamingEvents.Termination, _on_termination)
        self.client.on(StreamingEvents.Turn, self._on_turn)

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

        # Start background streaming thread
        self._start_background_stream()

    def _on_error(self, client: StreamingClient, error: StreamingError):
        """Enhanced error handler with statistics."""
        logger.error("AssemblyAI streaming error: %s", error)
        self._stats["errors_count"] += 1

        # Attempt to recover from certain errors
        if "connection" in str(error).lower():
            logger.info("Attempting to reconnect after connection error...")
            self._reconnect()

    def _on_turn(self, client: StreamingClient, event: TurnEvent):
        """Enhanced turn handler with better text processing."""
        try:
            text = (event.transcript or "").strip()
            if not text:
                return

            # Update statistics
            self._stats["turns_processed"] += 1

            # Process text
            processed_text = self._process_transcript_text(text)

            if event.end_of_turn:
                if self.on_final_callback:
                    try:
                        self.on_final_callback(processed_text)
                    except Exception as cb_err:
                        logger.exception("Final-callback error: %s", cb_err)

                # Enable formatted turns for better accuracy
                if not event.turn_is_formatted:
                    try:
                        client.set_params(StreamingSessionParameters(
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
        if audio_chunk:
            self._q.put(audio_chunk)

    def close(self):
        """Stop streaming and terminate session."""
        logger.info("Closing AssemblyAI transcriber...")

        self._stats["end_time"] = time.time()

        # Signal generator to finish
        self._q.put(None)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        # Log session statistics
        self._log_session_stats()

    def _reconnect(self):
        """Attempt to reconnect the streaming client."""
        try:
            logger.info("Reconnecting AssemblyAI transcriber...")

            # Close existing connection
            if self.client:
                try:
                    self.client.disconnect(terminate=True)
                except Exception:
                    pass

            # Create new client
            self.client = StreamingClient(
                StreamingClientOptions(
                    api_key=self.api_key,
                    api_host="streaming.assemblyai.com",
                )
            )

            # Re-register events
            self.client.on(StreamingEvents.Begin, _on_begin)
            self.client.on(StreamingEvents.Error, self._on_error)
            self.client.on(StreamingEvents.Termination, _on_termination)
            self.client.on(StreamingEvents.Turn, self._on_turn)

            # Restart streaming
            self._start_background_stream()

            logger.info("Successfully reconnected AssemblyAI transcriber")

        except Exception as e:
            logger.error(f"Failed to reconnect: {e}")

    def _audio_generator(self):
        """Generate audio chunks from queue."""
        try:
            while True:
                chunk = self._q.get(timeout=30)  # Add timeout to prevent hanging
                if chunk is None:
                    break
                yield chunk
        except queue.Empty:
            logger.warning("Audio generator timeout - no audio received")
        except Exception as e:
            logger.error(f"Audio generator error: {e}")

    def _start_background_stream(self):
        """Start the background streaming thread."""

        def runner():
            try:
                self._stats["start_time"] = time.time()

                # Connect with enhanced parameters
                self.client.connect(
                    StreamingParameters(
                        sample_rate=self.sample_rate,
                        format_turns=False,  # Start with False, switch to True after first turn
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
                self._stats["errors_count"] += 1
            finally:
                try:
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
        stats = self._stats.copy()
        if self._stats["start_time"]:
            current_time = time.time()
            stats["current_duration"] = current_time - self._stats["start_time"]
        return stats


# ✅ Factory function with fallback to .env
def create_transcriber(api_key: Optional[str] = None, **kwargs) -> AssemblyAIStreamingTranscriber:
    """Factory function to create transcriber with validation and fallback."""
    if not api_key:
        api_key = os.getenv("ASSEMBLYAI_API_KEY", "")
    return AssemblyAIStreamingTranscriber(api_key=api_key, **kwargs)


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
