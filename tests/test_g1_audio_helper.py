from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from util.g1_helper.g1_audio_helper import G1AudioHelper


class FakeAudioSdkClient:
    def __init__(self, response_code: int = 0) -> None:
        self.response_code = response_code
        self.timeout = 0.0
        self.initialized = False
        self.chunks: list[bytes] = []
        self.stopped_apps: list[str] = []

    def SetTimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def Init(self) -> None:
        self.initialized = True

    def PlayStream(
        self,
        _: str,
        __: str,
        pcm_audio: bytes,
    ) -> tuple[int, None]:
        self.chunks.append(pcm_audio)
        return self.response_code, None

    def PlayStop(self, app_name: str) -> int:
        self.stopped_apps.append(app_name)
        return 0


class FakeSdkBoundary:
    def __init__(self) -> None:
        self.channel_calls: list[tuple[int, str]] = []
        self.audio_client = FakeAudioSdkClient()

    def initialize_channel(self, domain_id: int, interface: str) -> None:
        self.channel_calls.append((domain_id, interface))

    def create_client(self) -> FakeAudioSdkClient:
        return self.audio_client


class G1AudioHelperTests(unittest.TestCase):
    def _write_wav(self, audio_path: Path, pcm_audio: bytes) -> None:
        with wave.open(str(audio_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(pcm_audio)

    def test_wav_is_read_chunked_paced_and_stopped(self) -> None:
        boundary = FakeSdkBoundary()
        sleep_durations: list[float] = []
        helper = G1AudioHelper(
            "eth0",
            chunk_size=4,
            sleeper=sleep_durations.append,
            channel_initializer=boundary.initialize_channel,
            client_factory=boundary.create_client,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_path = Path(temporary_directory) / "welcome.wav"
            self._write_wav(audio_path, b"123456")
            helper.connect()
            helper.play(audio_path)

        self.assertEqual(boundary.channel_calls, [(0, "eth0")])
        self.assertEqual(boundary.audio_client.chunks, [b"1234", b"56"])
        self.assertEqual(sleep_durations, [4 / 32000, 2 / 32000])
        self.assertEqual(boundary.audio_client.stopped_apps, ["g1_guide_tts"])

    def test_play_requires_connection(self) -> None:
        helper = G1AudioHelper("eth0")

        with self.assertRaisesRegex(RuntimeError, "not connected"):
            helper.play(Path("missing.wav"))

    def test_stream_error_still_stops_audio(self) -> None:
        boundary = FakeSdkBoundary()
        boundary.audio_client.response_code = 3102
        helper = G1AudioHelper(
            "eth0",
            sleeper=lambda _: None,
            channel_initializer=boundary.initialize_channel,
            client_factory=boundary.create_client,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_path = Path(temporary_directory) / "welcome.wav"
            self._write_wav(audio_path, b"\x00\x00")
            helper.connect()
            with self.assertRaisesRegex(RuntimeError, "3102"):
                helper.play(audio_path)

        self.assertEqual(boundary.audio_client.stopped_apps, ["g1_guide_tts"])


if __name__ == "__main__":
    unittest.main()
