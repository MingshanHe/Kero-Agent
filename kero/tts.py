from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class TTSError(RuntimeError):
    pass


def _find_player() -> Optional[str]:
    for player in ("ffplay", "ffmpeg"):
        path = shutil.which(player)
        if path:
            return path
    return None


def text_to_speech(text: str, output_path: Path | str | None = None, lang: str = "zh-cn") -> str:
    """Convert text to speech and save to a local MP3 file."""
    if not text or not text.strip():
        raise TTSError("No text provided for speech synthesis.")

    try:
        from gtts import gTTS
    except ImportError as exc:
        raise TTSError("The gTTS package is required for speech synthesis. Install it with `pip install gTTS`.") from exc

    if output_path is None:
        output_path = Path(tempfile.mktemp(suffix=".mp3"))
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(str(output_path))
    except Exception as exc:
        raise TTSError(f"Failed to synthesize speech: {exc}") from exc

    return str(output_path)


def play_audio(audio_path: str) -> None:
    """Play an audio file using ffplay or ffmpeg if available."""
    path = Path(audio_path)
    if not path.exists():
        raise TTSError(f"Audio file not found: {audio_path}")

    player = _find_player()
    if player is None:
        raise TTSError("No ffplay or ffmpeg binary found on PATH. Install ffmpeg to play audio.")

    if Path(player).name == "ffplay":
        command = [player, "-nodisp", "-autoexit", "-loglevel", "error", str(path)]
    else:
        command = [player, "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "alsa", "default"]

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise TTSError(f"Audio playback failed: {exc}") from exc


def speak_text(text: str, lang: str = "zh-cn") -> None:
    """Generate speech from text and play it."""
    audio_path = text_to_speech(text, lang=lang)
    try:
        play_audio(audio_path)
    finally:
        try:
            Path(audio_path).unlink()
        except OSError:
            pass
