from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class AudioFilePlayer(Protocol):
    """Boundary for playing one audio file."""

    def play(self, audio_path: Path) -> None:
        """Play a validated audio file."""


@dataclass(frozen=True)
class TourAudioReceipt:
    """Evidence that a named guide audio file was submitted for playback."""

    audio_name: str
    audio_path: Path


class TourAudioComponent:
    """Play a named audio asset required by the current guide scene."""

    def __init__(self, player: AudioFilePlayer, audio_root: Path) -> None:
        self.player = player
        self.audio_root = audio_root.resolve()
        self.last_receipt: TourAudioReceipt | None = None

    def play(self, audio_name: str) -> TourAudioReceipt:
        normalized_name = audio_name.strip()
        if not normalized_name:
            raise ValueError("audio_name cannot be empty")
        if Path(normalized_name).name != normalized_name:
            raise ValueError("audio_name must be a file name without a path")

        file_name = (
            normalized_name
            if normalized_name.lower().endswith(".wav")
            else f"{normalized_name}.wav"
        )
        audio_path = (self.audio_root / file_name).resolve()
        if audio_path.parent != self.audio_root:
            raise ValueError("audio_name resolves outside the TTS directory")
        if not audio_path.is_file():
            raise FileNotFoundError(f"Guide audio does not exist: {audio_path}")

        self.player.play(audio_path)
        playback_receipt = TourAudioReceipt(
            audio_name=Path(file_name).stem,
            audio_path=audio_path,
        )
        self.last_receipt = playback_receipt
        return playback_receipt


class DemoAudioFilePlayer:
    """Record a file path without opening audio hardware."""

    def __init__(self) -> None:
        self.played_paths: list[Path] = []

    def play(self, audio_path: Path) -> None:
        self.played_paths.append(audio_path)


def demo_tour_audio_component() -> None:
    audio_root = Path(__file__).resolve().parents[2] / "data" / "tts"
    demo_path = audio_root / ".demo_audio.wav"
    audio_root.mkdir(parents=True, exist_ok=True)
    demo_path.touch()
    try:
        player = DemoAudioFilePlayer()
        component = TourAudioComponent(player=player, audio_root=audio_root)
        receipt = component.play(".demo_audio")
        assert player.played_paths == [demo_path.resolve()]
        assert receipt.audio_name == ".demo_audio"
        print("Tour audio component: named audio selection verified")
    finally:
        demo_path.unlink(missing_ok=True)


def main() -> None:
    demo_tour_audio_component()


if __name__ == "__main__":
    main()
