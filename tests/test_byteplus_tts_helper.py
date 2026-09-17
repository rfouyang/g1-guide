from __future__ import annotations

import base64
import json
import tempfile
import unittest
import wave
from pathlib import Path

from util.byteplus_tts_helper import BytePlusTtsError, BytePlusTtsHelper


class FakeHttpResponse:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.events = events
        self.encoding = ""
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, **_: object) -> list[str]:
        response_text = "".join(json.dumps(event) for event in self.events)
        midpoint = max(1, len(response_text) // 2)
        response_chunks = [response_text[:midpoint], response_text[midpoint:]]
        return response_chunks

    def close(self) -> None:
        self.closed = True


class FakeHttpSession:
    def __init__(self, response: FakeHttpResponse) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeHttpResponse:
        self.requests.append({"url": url, **kwargs})
        return self.response


class BytePlusTtsHelperTests(unittest.TestCase):
    def test_kian_request_is_saved_as_valid_wav(self) -> None:
        pcm_audio = b"\x01\x02\x03\x04"
        response = FakeHttpResponse(
            [
                {"code": 0, "data": base64.b64encode(pcm_audio).decode()},
                {"code": 20000000, "message": "ok", "data": None},
            ]
        )
        session = FakeHttpSession(response)
        helper = BytePlusTtsHelper(api_key="secret", session=session)

        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_path = Path(temporary_directory) / "welcome.wav"
            generated_path = helper.generate("你好，welcome to G1.", audio_path)
            with wave.open(str(generated_path), "rb") as wav_file:
                self.assertEqual(wav_file.getframerate(), 16000)
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.readframes(wav_file.getnframes()), pcm_audio)

        request = session.requests[0]
        payload = request["json"]
        self.assertEqual(
            payload["req_params"]["speaker"],
            BytePlusTtsHelper.KIAN_SPEAKER,
        )
        additions = json.loads(payload["req_params"]["additions"])
        self.assertEqual(additions["explicit_language"], "zh-cn")
        self.assertNotIn("secret", str(payload))
        self.assertTrue(response.closed)

    def test_service_error_does_not_create_file(self) -> None:
        response = FakeHttpResponse(
            [{"code": 45000000, "message": "speaker permission denied"}]
        )
        helper = BytePlusTtsHelper(
            api_key="secret",
            session=FakeHttpSession(response),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_path = Path(temporary_directory) / "failed.wav"
            with self.assertRaisesRegex(BytePlusTtsError, "45000000"):
                helper.generate("Hello", audio_path)
            self.assertFalse(audio_path.exists())

        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
