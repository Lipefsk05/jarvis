"""Voice notes and audio files sent to the bot: size/length guard and transcription through Groq Whisper."""
from __future__ import annotations

MODEL = "whisper-large-v3-turbo"
REQUEST_TIMEOUT_S = 60.0
MAX_SECONDS = 300           # a spoken message, not a podcast; also keeps the free audio quota safe
MAX_BYTES = 20 * 1024 * 1024  # Telegram does not let bots download more than 20 MB anyway
QUOTA_CODES = {429}


class TranscribeError(Exception):
    """Transcription failed. `reason` is a short sentence for the user and never contains secrets."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def check_audio(duration_s: int | None, size_bytes: int | None, max_seconds: int = MAX_SECONDS) -> str | None:
    """None when the audio is fine to transcribe, else the sentence to tell the user."""
    if duration_s is not None and duration_s > max_seconds:
        return f"Esse áudio passa de {max_seconds // 60} minutos, senhor. Pode mandar em partes menores?"
    if size_bytes is not None and size_bytes > MAX_BYTES:
        return "Esse áudio é grande demais para eu baixar, senhor. Pode mandar em partes menores?"
    return None


class GroqTranscriber:
    def __init__(self, api_key: str, model: str = MODEL, client=None) -> None:
        if client is None:
            from groq import Groq  # imported lazily so tests do not need the package

            client = Groq(api_key=api_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
        self._client = client
        self._model = model

    def transcribe(self, filename: str, data: bytes) -> str:
        try:
            result = self._client.audio.transcriptions.create(
                file=(filename, data), model=self._model, language="pt", response_format="json", temperature=0.0,
            )
        except Exception as exc:  # SDK errors never carry the key; keep only type and code
            code = getattr(exc, "status_code", None)
            if code in QUOTA_CODES:
                raise TranscribeError("O limite de transcrição de áudio acabou por agora, senhor. Tente mais tarde ou escreva.") from exc
            raise TranscribeError("Não consegui transcrever o áudio agora, senhor.") from exc
        text = (getattr(result, "text", None) or "").strip()
        if not text:
            raise TranscribeError("Não entendi nada nesse áudio, senhor.")
        return text


def transcript_line(text: str, limit: int = 600) -> str:
    """What the bot shows so the user can see how he was understood before the answer."""
    shown = text if len(text) <= limit else text[: limit - 1] + "…"
    return f"🎙 “{shown}”"
