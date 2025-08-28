# services/stt.py
import os
import logging
import queue
import threading
from typing import Optional, Callable

import assemblyai as aai
from dotenv import load_dotenv
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

load_dotenv()

API_KEY = os.getenv("ASSEMBLYAI_API_KEY") or ""
aai.settings.api_key = API_KEY

logger = logging.getLogger(__name__)


def _on_begin(client: StreamingClient, event: BeginEvent):
    logger.info(f"AAI session started: {event.id}")


def _on_termination(client: StreamingClient, event: TerminationEvent):
    logger.info(f"AAI session terminated after {event.audio_duration_seconds:.2f}s")


def _on_error(client: StreamingClient, error: StreamingError):
    logger.error("AAI error: %s", error)


class AssemblyAIStreamingTranscriber:
    """
    Threaded wrapper around AssemblyAI StreamingClient.
    Feed audio via .stream_audio(bytes). Call .close() to end.
    Use on_partial_callback(text) and on_final_callback(text) to receive transcripts.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        on_partial_callback: Optional[Callable[[str], None]] = None,
        on_final_callback: Optional[Callable[[str], None]] = None,
    ):
        if not API_KEY:
            logger.warning("ASSEMBLYAI_API_KEY is missing")

        self.sample_rate = sample_rate
        self.on_partial_callback = on_partial_callback
        self.on_final_callback = on_final_callback

        # Correct host for streaming
        self.client = StreamingClient(
            StreamingClientOptions(
                api_key=API_KEY,
                api_host="streaming.assemblyai.com",
            )
        )

        # Register events
        self.client.on(StreamingEvents.Begin, _on_begin)
        self.client.on(StreamingEvents.Error, _on_error)
        self.client.on(StreamingEvents.Termination, _on_termination)
        self.client.on(StreamingEvents.Turn, self._on_turn)

        # Internal streaming machinery
        self._q: "queue.Queue[Optional[bytes]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._connected = threading.Event()

        # Start background streaming thread immediately
        self._start_background_stream()

    # ---- event handlers ----
    def _on_turn(self, client: StreamingClient, event: TurnEvent):
        text = (event.transcript or "").strip()
        if not text:
            return

        if event.end_of_turn:
            if self.on_final_callback:
                try:
                    self.on_final_callback(text)
                except Exception as cb_err:
                    logger.exception("Final-callback error: %s", cb_err)

            # Enable formatted turns from this point on (optional)
            if not event.turn_is_formatted:
                try:
                    client.set_params(StreamingSessionParameters(format_turns=True))
                except Exception as set_err:
                    logger.warning("set_params error: %s", set_err)
        else:
            if self.on_partial_callback:
                try:
                    self.on_partial_callback(text)
                except Exception as cb_err:
                    logger.exception("Partial-callback error: %s", cb_err)

    # ---- public API used by your websocket handler ----
    def stream_audio(self, audio_chunk: bytes):
        """Feed raw audio bytes (50–1000 ms per chunk, 16 kHz mono)."""
        self._q.put(audio_chunk)

    def close(self):
        """Stop streaming and terminate session."""
        # Signal generator to finish
        self._q.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    # ---- internals ----
    def _audio_generator(self):
        while True:
            chunk = self._q.get()
            if chunk is None:
                break
            yield chunk

    def _start_background_stream(self):
        def runner():
            try:
                # Connect first
                self.client.connect(
                    StreamingParameters(
                        sample_rate=self.sample_rate,
                        format_turns=False,  # switch to True after first final turn
                    )
                )
                self._connected.set()

                # Then stream from our generator until closed
                self.client.stream(self._audio_generator())
            except Exception as e:
                logger.exception("AAI streaming thread crashed: %s", e)
            finally:
                try:
                    self.client.disconnect(terminate=True)
                except Exception:
                    pass

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
        # Wait a moment so connect() can complete (prevents early 404-ish flakiness)
        self._connected.wait(timeout=5)
