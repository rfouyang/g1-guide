from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from component.speech.tour_audio_component import TourAudioComponent


@dataclass(frozen=True)
class FakePlayback:
    cancelled: bool


class FakeAudioFilePlayer:
    def __init__(self) -> None:
        self.played_paths: list[Path] = []

    def play(
        self,
        audio_path: Path,
        cancel_event: Event | None = None,
    ) -> FakePlayback:
        self.played_paths.append(audio_path)
        cancelled = cancel_event.is_set() if cancel_event is not None else False
        return FakePlayback(cancelled=cancelled)


class TourAudioComponentTests(unittest.TestCase):
    def test_named_guide_audio_is_selected_and_played(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_root = Path(temporary_directory)
            audio_path = audio_root / "welcome.wav"
            audio_path.touch()
            player = FakeAudioFilePlayer()
            component = TourAudioComponent(player=player, audio_root=audio_root)

            receipt = component.play("welcome")

            self.assertEqual(player.played_paths, [audio_path.resolve()])
            self.assertEqual(receipt.audio_name, "welcome")
            self.assertEqual(receipt.audio_path, audio_path.resolve())
            self.assertFalse(receipt.cancelled)

    def test_cancellation_signal_is_propagated_to_the_player(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_root = Path(temporary_directory)
            (audio_root / "welcome.wav").touch()
            player = FakeAudioFilePlayer()
            component = TourAudioComponent(player=player, audio_root=audio_root)
            cancel_event = Event()
            cancel_event.set()

            receipt = component.play("welcome", cancel_event)

            self.assertTrue(receipt.cancelled)

    def test_missing_audio_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            component = TourAudioComponent(
                player=FakeAudioFilePlayer(),
                audio_root=Path(temporary_directory),
            )

            with self.assertRaises(FileNotFoundError):
                component.play("missing")

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            component = TourAudioComponent(
                player=FakeAudioFilePlayer(),
                audio_root=Path(temporary_directory),
            )

            with self.assertRaisesRegex(ValueError, "without a path"):
                component.play("../outside.wav")


if __name__ == "__main__":
    unittest.main()
