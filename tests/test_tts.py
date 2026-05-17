from __future__ import annotations

from pathlib import Path

import pytest

from kero.tts import TTSError, play_audio, speak_text, text_to_speech


def test_text_to_speech_missing_text() -> None:
    with pytest.raises(TTSError, match="No text provided"):
        text_to_speech("  ")


def test_speak_text_creates_and_removes_audio(tmp_path, monkeypatch) -> None:
    temp_audio = tmp_path / "speech.mp3"
    saved_paths = []

    class DummyTTS:
        def __init__(self, text: str, lang: str, slow: bool) -> None:
            assert text == "hello"
            assert lang == "zh-cn"
            assert slow is False

        def save(self, path: str) -> None:
            saved_paths.append(path)
            Path(path).write_text("dummy audio")

    import sys
    import types

    dummy_module = types.ModuleType("gtts")
    dummy_module.gTTS = DummyTTS

    monkeypatch.setitem(sys.modules, "gtts", dummy_module)
    monkeypatch.setattr("kero.tts.shutil.which", lambda name: "/usr/bin/ffplay")
    monkeypatch.setattr("kero.tts.subprocess.run", lambda command, check: None)
    monkeypatch.setattr("kero.tts.tempfile.mktemp", lambda suffix: str(temp_audio))

    speak_text("hello")
    assert saved_paths == [str(temp_audio)]
    assert not temp_audio.exists()


def test_play_audio_missing_file() -> None:
    with pytest.raises(TTSError, match="Audio file not found"):
        play_audio("does-not-exist.mp3")
