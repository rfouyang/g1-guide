from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from component.speech.tour_audio_component import TourAudioComponent


class FakeAudioFilePlayer:
    def __init__(self) -> None:
        self.played_paths: list[Path] = []

    def play(self, audio_path: Path) -> None:
        self.played_paths.append(audio_path)


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
