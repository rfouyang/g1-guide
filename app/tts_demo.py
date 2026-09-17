from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from component.speech.tour_audio_component import TourAudioComponent
from util.byteplus_tts_helper import BytePlusTtsHelper
from util.g1_helper.g1_audio_helper import G1AudioHelper


class TtsDemoApplication:
    """Generate a guide WAV file, then ask G1 to play that named file."""

    def __init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[1]
        self.audio_root = self.project_root / "data" / "tts"

    def run(self) -> None:
        arguments = self._parse_arguments()
        if not arguments.live:
            print("TTS demo: safe mode, no cloud or robot connection")
            return
        if not arguments.confirm_stationary:
            raise SystemExit(
                "Live TTS requires --confirm-stationary; no request was sent"
            )
        if (
            not arguments.audio_name.strip()
            or Path(arguments.audio_name).name != arguments.audio_name
            or arguments.audio_name.lower().endswith(".wav")
        ):
            raise SystemExit("--audio-name must be a file stem without a path")

        load_dotenv()
        api_key = os.getenv("BYTEPLUS_API_KEY", "")
        if not api_key:
            raise SystemExit("BYTEPLUS_API_KEY is required for live TTS")

        audio_path = self.audio_root / f"{arguments.audio_name}.wav"
        tts_helper = BytePlusTtsHelper(api_key=api_key)
        generated_path = tts_helper.generate(arguments.text, audio_path)

        audio_helper = G1AudioHelper(network_interface=arguments.interface)
        audio_helper.connect()
        tour_audio = TourAudioComponent(
            player=audio_helper,
            audio_root=self.audio_root,
        )
        playback_receipt = tour_audio.play(arguments.audio_name)
        print(
            f"Generated {generated_path} and played "
            f"{playback_receipt.audio_name} on G1"
        )

    def _parse_arguments(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description="BytePlus TTS 2.0 to Unitree G1 audio demo"
        )
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--confirm-stationary", action="store_true")
        parser.add_argument(
            "--interface",
            help=(
                "DDS network interface; defaults to the interface on "
                "192.168.123.0/24"
            ),
        )
        parser.add_argument("--audio-name", default="welcome_bilingual")
        parser.add_argument(
            "--text",
            default="你好，welcome to the Unitree G1 guide. 很高兴为你服务。",
        )
        parsed_arguments = parser.parse_args()
        return parsed_arguments


def demo_tts_demo() -> None:
    TtsDemoApplication().run()


def main() -> None:
    demo_tts_demo()


if __name__ == "__main__":
    main()
