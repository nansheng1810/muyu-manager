import json
import unittest
from unittest import mock

from server import llm


PROVIDER = {
    "api_base": "https://api.example.com/v1",
    "model": "test-model",
    "key": ["sk-test"],
    "provider_type": "chat_completion",
    "custom_headers": {"User-Agent": "BrowserUA/1.0"},
}


class _Response:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {"Content-Type": "application/json"}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _headers(request):
    return {name.lower(): value for name, value in request.header_items()}


class LlmCustomHeaderTests(unittest.TestCase):
    def test_chat_forwards_provider_custom_headers(self):
        payload = json.dumps(
            {"choices": [{"message": {"content": "ok"}}]}
        ).encode("utf-8")
        with mock.patch.object(llm, "_load_provider", return_value=PROVIDER):
            with mock.patch.object(
                llm.urllib.request, "urlopen", return_value=_Response(payload)
            ) as opened:
                self.assertEqual(llm.chat({}, "p", [], max_tokens=16), "ok")
        headers = _headers(opened.call_args[0][0])
        self.assertEqual(headers["user-agent"], "BrowserUA/1.0")
        self.assertEqual(headers["authorization"], "Bearer sk-test")

    def test_stream_forwards_provider_custom_headers(self):
        payload = json.dumps(
            {"choices": [{"message": {"content": "ok"}}]}
        ).encode("utf-8")
        with mock.patch.object(llm, "_load_provider", return_value=PROVIDER):
            with mock.patch.object(
                llm.urllib.request, "urlopen", return_value=_Response(payload)
            ) as opened:
                llm.chat_stream({}, "p", [])
        headers = _headers(opened.call_args[0][0])
        self.assertEqual(headers["user-agent"], "BrowserUA/1.0")
        self.assertEqual(headers["authorization"], "Bearer sk-test")

    def test_custom_headers_cannot_override_authorization(self):
        provider = dict(PROVIDER, custom_headers={"Authorization": "Bearer evil"})
        payload = json.dumps(
            {"choices": [{"message": {"content": "ok"}}]}
        ).encode("utf-8")
        with mock.patch.object(llm, "_load_provider", return_value=provider):
            with mock.patch.object(
                llm.urllib.request, "urlopen", return_value=_Response(payload)
            ) as opened:
                llm.chat({}, "p", [], max_tokens=16)
        headers = _headers(opened.call_args[0][0])
        self.assertEqual(headers["authorization"], "Bearer sk-test")


if __name__ == "__main__":
    unittest.main()
