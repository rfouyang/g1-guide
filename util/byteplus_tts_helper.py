from __future__ import annotations

import base64
import json
import os
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from loguru import logger


class BytePlusTtsError(RuntimeError):
    """Raised when BytePlus does not return valid synthesized audio."""


class BytePlusTtsHelper:
    """Generate a 16 kHz mono WAV file with BytePlus TTS 2.0."""

    URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/unidirectional"
    RESOURCE_ID = "seed-tts-2.0"
    APP_KEY = "aGjiRDfUWi"
    KIAN_SPEAKER = "zh_male_m191_uranus_bigtts"

    def __init__(self, api_key: str, **kwargs: object) -> None:
        self.api_key = api_key.strip()
        self.speaker = str(kwargs.get("speaker", self.KIAN_SPEAKER))
        self.sample_rate = int(kwargs.get("sample_rate", 16000))
        self.timeout = kwargs.get("timeout", (5.0, 60.0))
        self.session = kwargs.get("session") or requests.Session()

        if not self.api_key:
            raise ValueError("BytePlus api_key cannot be empty")
        if self.sample_rate != 16000:
            raise ValueError("G1 playback requires a 16000 Hz sample rate")

    def generate(self, text: str, output_path: Path) -> Path:
        spoken_text = text.strip()
        audio_path = output_path.resolve()
        if not spoken_text:
            raise ValueError("TTS text cannot be empty")
        if audio_path.suffix.lower() != ".wav":
            raise ValueError("BytePlus TTS output must use the .wav extension")

        pcm_audio = self._request_pcm(spoken_text)
        self._write_wav(audio_path, pcm_audio)
        logger.info("BytePlus generated audio file {}", audio_path)
        return audio_path

    def _request_pcm(self, text: str) -> bytes:
        logger.info(
            "Requesting BytePlus TTS 2.0 speaker {} for {} characters",
            self.speaker,
            len(text),
        )
        response = self.session.post(
            self.URL,
            headers=self._headers(),
            json=self._payload(text),
            stream=True,
            timeout=self.timeout,
        )
        pcm_audio = bytearray()
        try:
            response.raise_for_status()
            response.encoding = "utf-8"
            for event in self._events(response):
                response_code = int(event.get("code", 0))
                if response_code == 20000000:
                    break
                if response_code != 0:
                    message = event.get("message", "unknown error")
                    raise BytePlusTtsError(
                        f"BytePlus TTS failed with code {response_code}: {message}"
                    )
                encoded_audio = event.get("data")
                if encoded_audio:
                    pcm_audio.extend(base64.b64decode(encoded_audio, validate=True))
        except (ValueError, json.JSONDecodeError) as error:
            raise BytePlusTtsError("BytePlus returned malformed audio data") from error
        finally:
            response.close()

        if not pcm_audio:
            raise BytePlusTtsError("BytePlus returned no audio")

        complete_pcm_audio = bytes(pcm_audio)
        return complete_pcm_audio

    def _write_wav(self, audio_path: Path, pcm_audio: bytes) -> None:
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = audio_path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            with wave.open(str(temporary_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(pcm_audio)
            os.replace(temporary_path, audio_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _headers(self) -> dict[str, str]:
        request_headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.RESOURCE_ID,
            "X-Api-App-Key": self.APP_KEY,
            "X-Api-Request-Id": str(uuid4()),
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }
        return request_headers

    def _payload(self, text: str) -> dict[str, Any]:
        additions = {
            "enable_language_detector": True,
            "explicit_language": "zh-cn",
            "disable_markdown_filter": True,
            "disable_emoji_filter": False,
            "max_length_to_filter_parenthesis": 0,
            "cache_config": {"text_type": 1, "use_cache": True},
            "context_texts": ["Speak in a warm, clear tour guide style."],
        }
        request_payload = {
            "req_params": {
                "text": text,
                "speaker": self.speaker,
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": self.sample_rate,
                },
                "additions": json.dumps(additions),
            }
        }
        return request_payload

    def _events(self, response: Any) -> Iterator[dict[str, Any]]:
        decoder = json.JSONDecoder()
        response_buffer = ""
        for response_chunk in response.iter_content(
            chunk_size=4096,
            decode_unicode=True,
        ):
            response_buffer += response_chunk
            while response_buffer.strip():
                stripped_buffer = response_buffer.lstrip()
                try:
                    event, event_end = decoder.raw_decode(stripped_buffer)
                except json.JSONDecodeError:
                    break
                yield event
                response_buffer = stripped_buffer[event_end:]

        if response_buffer.strip():
            raise BytePlusTtsError("BytePlus returned an incomplete JSON event")


def demo_byteplus_tts_helper() -> None:
    helper = BytePlusTtsHelper(api_key="offline-demo-key")
    request_payload = helper._payload("你好，welcome to G1 Guide.")
    request_parameters = request_payload["req_params"]
    assert request_parameters["speaker"] == BytePlusTtsHelper.KIAN_SPEAKER
    assert request_parameters["audio_params"]["sample_rate"] == 16000
    print("BytePlus TTS helper: Kian bilingual WAV output configured")


def main() -> None:
    demo_byteplus_tts_helper()


if __name__ == "__main__":
    main()
