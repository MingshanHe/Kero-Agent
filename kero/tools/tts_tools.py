from __future__ import annotations

import asyncio
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class TTSError(RuntimeError):
    pass


def _find_player() -> str | None:
    for player in ("ffplay", "ffmpeg"):
        path = shutil.which(player)
        if path:
            return path
    return None


def text_to_speech(
    text: str,
    output_path: Path | str | None = None,
    *,
    lang: str = "zh-cn",
    provider: str = "gtts",
    voice: str = "",
    command: str = "",
) -> str:
    """Convert text to speech and return the generated audio path."""
    if not text or not text.strip():
        raise TTSError("No text provided for speech synthesis.")

    output = Path(output_path) if output_path is not None else Path(tempfile.mktemp(suffix=".mp3"))
    output.parent.mkdir(parents=True, exist_ok=True)

    selected = (provider or "gtts").strip().lower()
    if selected == "command" or command:
        return _command_tts(text, output, command)
    if selected == "edge":
        return _edge_tts(text, output, voice=voice or "zh-CN-XiaoxiaoNeural")
    if selected in {"gtts", "google"}:
        return _gtts(text, output, lang=lang)
    raise TTSError(f"Unsupported TTS provider: {provider}")


def _gtts(text: str, output_path: Path, *, lang: str) -> str:
    try:
        from gtts import gTTS
    except ImportError as exc:
        raise TTSError("The gTTS package is required for speech synthesis. Install it with `pip install gTTS`.") from exc

    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(str(output_path))
    except Exception as exc:
        raise TTSError(f"Failed to synthesize speech: {exc}") from exc
    return str(output_path)


def _edge_tts(text: str, output_path: Path, *, voice: str) -> str:
    try:
        import edge_tts
    except ImportError as exc:
        raise TTSError("The edge-tts package is required for provider=edge. Install it with `pip install edge-tts`.") from exc

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))

    try:
        asyncio.run(_run())
    except Exception as exc:
        raise TTSError(f"Failed to synthesize speech with Edge TTS: {exc}") from exc
    return str(output_path)


def _command_tts(text: str, output_path: Path, command: str) -> str:
    if not command:
        raise TTSError("Command TTS requires a command.")

    input_path = Path(tempfile.mktemp(suffix=".txt"))
    input_path.write_text(text, encoding="utf-8")
    try:
        formatted = command.format(
            input=str(input_path),
            output=str(output_path),
            text=text,
        )
        completed = subprocess.run(
            shlex.split(formatted),
            text=True,
            capture_output=True,
            check=True,
        )
    except KeyError as exc:
        raise TTSError(f"Unknown command TTS placeholder: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise TTSError(f"Command TTS failed: {detail or exc}") from exc
    finally:
        try:
            input_path.unlink()
        except OSError:
            pass

    if not output_path.exists():
        stdout = (completed.stdout or "").strip()
        if stdout:
            candidate = Path(stdout)
            if candidate.exists():
                return str(candidate)
        raise TTSError(f"Command TTS did not create audio file: {output_path}")
    return str(output_path)


def play_audio(audio_path: str | Path) -> None:
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


def speak_text(
    text: str,
    *,
    lang: str = "zh-cn",
    provider: str = "gtts",
    voice: str = "",
    command: str = "",
) -> None:
    """Generate speech from text and play it."""
    audio_path = text_to_speech(text, lang=lang, provider=provider, voice=voice, command=command)
    try:
        play_audio(audio_path)
    finally:
        try:
            Path(audio_path).unlink()
        except OSError:
            pass


def check_tts_requirements(provider: str = "gtts") -> dict[str, Any]:
    selected = (provider or "gtts").strip().lower()
    if selected == "edge":
        ok = _module_available("edge_tts")
        return {"ok": ok, "provider": selected, "missing": [] if ok else ["edge-tts"]}
    if selected in {"gtts", "google"}:
        ok = _module_available("gtts")
        return {"ok": ok, "provider": selected, "missing": [] if ok else ["gTTS"]}
    if selected == "command":
        return {"ok": True, "provider": selected, "missing": []}
    return {"ok": False, "provider": selected, "missing": [selected]}


def text_to_speech_tool(text: str, **kwargs: Any) -> dict[str, Any]:
    audio_path = text_to_speech(text, **kwargs)
    return {"audio_path": audio_path, "provider": kwargs.get("provider", "gtts")}


def _module_available(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True
