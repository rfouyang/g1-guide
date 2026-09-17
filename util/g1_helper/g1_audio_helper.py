from __future__ import annotations

import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger

from util.g1_helper.g1_network_helper import G1NetworkHelper


class G1AudioHelper:
    """Read a validated WAV file and stream its PCM frames to G1 audio."""

    def __init__(
        self,
        network_interface: str | None = None,
        **kwargs: object,
    ) -> None:
        if network_interface is None:
            network_interface = G1NetworkHelper.detect()
        self.network_interface = network_interface.strip()
        self.timeout = float(kwargs.get("timeout", 10.0))
        self.app_name = str(kwargs.get("app_name", "g1_guide_tts"))
        self.chunk_size = int(kwargs.get("chunk_size", 32000))
        self.sleeper = kwargs.get("sleeper", time.sleep)
        self._channel_initializer = kwargs.get("channel_initializer")
        self._client_factory = kwargs.get("client_factory")
        self._audio_client: Any | None = None

        if not self.network_interface:
            raise ValueError("network_interface cannot be empty")
        if self.timeout <= 0 or self.chunk_size <= 0:
            raise ValueError("timeout and chunk_size must be positive")
        if not callable(self.sleeper):
            raise TypeError("sleeper must be callable")
        self._validate_injected_sdk()

    @property
    def connected(self) -> bool:
        connection_ready = self._audio_client is not None
        return connection_ready

    def connect(self) -> None:
        if self.connected:
            return

        channel_initializer, client_factory = self._resolve_sdk()
        logger.info(
            "Initializing Unitree audio DDS on interface {}",
            self.network_interface,
        )
        channel_initializer(0, self.network_interface)
        audio_client = client_factory()
        audio_client.SetTimeout(self.timeout)
        audio_client.Init()
        self._audio_client = audio_client
        logger.info("G1 audio helper initialized")

    def play(self, audio_path: Path) -> None:
        if not self.connected:
            raise RuntimeError("G1 audio helper is not connected")

        resolved_audio_path = audio_path.resolve()
        with wave.open(str(resolved_audio_path), "rb") as wav_file:
            self._validate_wav(wav_file)
            pcm_audio = wav_file.readframes(wav_file.getnframes())
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()

        self._play_pcm(pcm_audio, sample_rate, channels)
        logger.info("G1 played audio file {}", resolved_audio_path)

    def _play_pcm(self, pcm_audio: bytes, sample_rate: int, channels: int) -> None:
        stream_id = str(uuid4())
        bytes_per_second = sample_rate * channels * 2
        try:
            for chunk_start in range(0, len(pcm_audio), self.chunk_size):
                audio_chunk = pcm_audio[
                    chunk_start : chunk_start + self.chunk_size
                ]
                response_code, _ = self._audio_client.PlayStream(
                    self.app_name,
                    stream_id,
                    audio_chunk,
                )
                if int(response_code) != 0:
                    raise RuntimeError(
                        f"Unitree audio stream failed with code {response_code}"
                    )
                chunk_duration = len(audio_chunk) / bytes_per_second
                self.sleeper(chunk_duration)
        finally:
            self._audio_client.PlayStop(self.app_name)

    def _validate_wav(self, wav_file: wave.Wave_read) -> None:
        if wav_file.getframerate() != 16000:
            raise ValueError("G1 audio requires a 16 kHz WAV file")
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise ValueError("G1 audio requires 16-bit mono WAV")
        if wav_file.getnframes() == 0:
            raise ValueError("Audio file cannot be empty")

    def _validate_injected_sdk(self) -> None:
        has_initializer = self._channel_initializer is not None
        has_factory = self._client_factory is not None
        if has_initializer != has_factory:
            raise ValueError(
                "channel_initializer and client_factory must be provided together"
            )
        if has_initializer and not callable(self._channel_initializer):
            raise TypeError("channel_initializer must be callable")
        if has_factory and not callable(self._client_factory):
            raise TypeError("client_factory must be callable")

    def _resolve_sdk(self) -> tuple[Callable[..., object], Callable[..., object]]:
        if self._channel_initializer is not None and self._client_factory is not None:
            return self._channel_initializer, self._client_factory

        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient

        return ChannelFactoryInitialize, AudioClient


def demo_g1_audio_helper() -> None:
    helper = G1AudioHelper(network_interface="offline-demo")
    assert not helper.connected
    print("G1 audio helper: safe demo only, no DDS connection")


def main() -> None:
    demo_g1_audio_helper()


if __name__ == "__main__":
    main()
