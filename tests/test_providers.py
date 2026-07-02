import json
import os
import unittest
from unittest import mock

from sts_rag.providers import OllamaProvider, OpenRouterProvider, ProviderError


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ProviderTests(unittest.TestCase):
    @mock.patch("urllib.request.urlopen")
    def test_ollama_chat(self, urlopen):
        urlopen.return_value = _Response({"message": {"content": "hello"}})
        provider = OllamaProvider(model="test-model")
        result = provider.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "hello")
        self.assertEqual(result.provider, "ollama")

    @mock.patch("urllib.request.urlopen")
    def test_openrouter_chat(self, urlopen):
        urlopen.return_value = _Response({"choices": [{"message": {"content": "answer"}}]})
        provider = OpenRouterProvider(model="x/y", api_key="key")
        result = provider.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "answer")
        self.assertEqual(result.provider, "openrouter")

    @mock.patch("urllib.request.urlopen")
    def test_openrouter_chat_web_plugin(self, urlopen):
        urlopen.return_value = _Response({"choices": [{"message": {"content": "answer"}}]})
        provider = OpenRouterProvider(
            model="x/y",
            api_key="key",
            web=True,
            web_max_results=2,
            web_domains=["reddit.com"],
        )
        provider.chat([{"role": "user", "content": "hi"}])
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["plugins"][0]["id"], "web")
        self.assertEqual(payload["plugins"][0]["max_results"], 2)
        self.assertEqual(payload["plugins"][0]["include_domains"], ["reddit.com"])

    def test_openrouter_missing_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderError):
                OpenRouterProvider()


if __name__ == "__main__":
    unittest.main()
