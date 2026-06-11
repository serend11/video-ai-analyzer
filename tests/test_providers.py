"""
Test each AI provider's payload construction and response parsing.
"""

import json
import os
from conftest import (
    call_ai,
    FAKE_JPEG_BASE64,
    OPENAI_RESPONSE,
    ANTHROPIC_RESPONSE,
    GOOGLE_RESPONSE,
    OLLAMA_RESPONSE,
)


# ─── OpenAI Provider ───────────────────────────────────────────────────

class TestOpenAIProvider:
    @classmethod
    def setup_class(cls):
        cls.provider = call_ai.OpenAIProvider()

    def test_name(self):
        assert self.provider.name == "openai"

    def test_default_model(self):
        assert self.provider.default_model == "gpt-4o"
        assert self.provider.default_summary_model == "gpt-4o-mini"

    def test_build_payload_vision(self):
        payload = self.provider.build_payload(
            model="gpt-4o",
            prompt="Describe this frame.",
            image_b64=FAKE_JPEG_BASE64,
            mime="image/jpeg",
            max_tokens=500,
            detail="low",
            temperature=0.7,
        )
        assert payload["model"] == "gpt-4o"
        assert payload["max_tokens"] == 500
        assert payload["temperature"] == 0.7
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

        content = payload["messages"][0]["content"]
        assert len(content) == 2  # image_url + text
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["detail"] == "low"
        assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "Describe this frame."

    def test_build_payload_text_only(self):
        payload = self.provider.build_payload(
            model="gpt-4o",
            prompt="Summarize this video.",
            image_b64=None,
            mime="image/jpeg",
            max_tokens=2000,
            detail="low",
            temperature=0.5,
        )
        content = payload["messages"][0]["content"]
        # Text-only: single text block
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Summarize this video."

    def test_parse_response(self):
        result = self.provider.parse_response(OPENAI_RESPONSE)
        assert result == "A person sitting at a desk."

    def test_parse_response_empty(self):
        empty = {"choices": [{"message": {"content": ""}}]}
        assert self.provider.parse_response(empty) == ""

    def test_auth_headers(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-key"
        headers = self.provider.get_auth_headers()
        assert headers["Authorization"] == "Bearer sk-test-key"
        del os.environ["OPENAI_API_KEY"]


# ─── Anthropic Provider ────────────────────────────────────────────────

class TestAnthropicProvider:
    @classmethod
    def setup_class(cls):
        cls.provider = call_ai.AnthropicProvider()

    def test_name(self):
        assert self.provider.name == "anthropic"

    def test_default_model(self):
        assert self.provider.default_model == "claude-3-5-sonnet-20241022"
        assert self.provider.default_summary_model == "claude-3-5-haiku-20241022"

    def test_build_payload_vision(self):
        payload = self.provider.build_payload(
            model="claude-3-5-sonnet-20241022",
            prompt="Describe this frame.",
            image_b64=FAKE_JPEG_BASE64,
            mime="image/jpeg",
            max_tokens=500,
            detail="auto",  # ignored by anthropic
            temperature=0.7,
        )
        assert payload["model"] == "claude-3-5-sonnet-20241022"
        assert payload["max_tokens"] == 500
        assert payload["temperature"] == 0.7
        assert len(payload["messages"]) == 1

        content = payload["messages"][0]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["media_type"] == "image/jpeg"
        assert content[0]["source"]["data"] == FAKE_JPEG_BASE64
        assert content[1]["type"] == "text"

    def test_parse_response(self):
        result = self.provider.parse_response(ANTHROPIC_RESPONSE)
        assert result == "A person sitting at a desk."

    def test_parse_multiple_blocks(self):
        resp = {
            "content": [
                {"type": "text", "text": "First block."},
                {"type": "text", "text": "Second block."},
            ]
        }
        result = self.provider.parse_response(resp)
        assert result == "First block.\nSecond block."

    def test_auth_headers(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        headers = self.provider.get_auth_headers()
        assert headers["x-api-key"] == "sk-ant-test"
        assert headers["anthropic-version"] == "2023-06-01"
        del os.environ["ANTHROPIC_API_KEY"]


# ─── Google Provider ───────────────────────────────────────────────────

class TestGoogleProvider:
    @classmethod
    def setup_class(cls):
        cls.provider = call_ai.GoogleProvider()

    def test_name(self):
        assert self.provider.name == "google"

    def test_default_model(self):
        assert self.provider.default_model == "gemini-2.0-flash-exp"

    def test_build_payload_vision(self):
        payload = self.provider.build_payload(
            model="gemini-2.0-flash-exp",
            prompt="Describe this.",
            image_b64=FAKE_JPEG_BASE64,
            mime="image/jpeg",
            max_tokens=500,
            detail="low",
            temperature=0.7,
        )
        assert "contents" in payload
        parts = payload["contents"][0]["parts"]
        assert len(parts) == 2
        assert "inlineData" in parts[0]
        assert parts[0]["inlineData"]["mimeType"] == "image/jpeg"
        assert parts[1]["text"] == "Describe this."
        assert payload["generationConfig"]["maxOutputTokens"] == 500

    def test_parse_response(self):
        result = self.provider.parse_response(GOOGLE_RESPONSE)
        assert result == "A person sitting at a desk."

    def test_endpoint(self):
        os.environ["GOOGLE_API_KEY"] = "test-google-key"
        url = self.provider.get_endpoint(model="gemini-2.0-flash-exp")
        assert "gemini-2.0-flash-exp" in url
        assert "key=test-google-key" in url
        assert "generativelanguage.googleapis.com" in url
        del os.environ["GOOGLE_API_KEY"]


# ─── Ollama Provider ───────────────────────────────────────────────────

class TestOllamaProvider:
    @classmethod
    def setup_class(cls):
        cls.provider = call_ai.OllamaProvider()

    def test_name(self):
        assert self.provider.name == "ollama"

    def test_default_model(self):
        assert self.provider.default_model == "llava"

    def test_build_payload_vision(self):
        payload = self.provider.build_payload(
            model="llava",
            prompt="Describe this.",
            image_b64=FAKE_JPEG_BASE64,
            mime="image/jpeg",
            max_tokens=500,
            detail="low",
            temperature=0.7,
        )
        assert payload["model"] == "llava"
        assert payload["stream"] == False
        msg = payload["messages"][0]
        assert msg["role"] == "user"
        assert msg["content"] == "Describe this."
        assert msg["images"] == [FAKE_JPEG_BASE64]
        assert payload["options"]["num_predict"] == 500

    def test_build_payload_text_only(self):
        payload = self.provider.build_payload(
            model="llava",
            prompt="Hello",
            image_b64=None,
            mime="image/jpeg",
            max_tokens=100,
            detail="low",
            temperature=0.7,
        )
        assert "images" not in payload["messages"][0]

    def test_parse_response(self):
        result = self.provider.parse_response(OLLAMA_RESPONSE)
        assert result == "A person sitting at a desk."

    def test_no_auth_required(self):
        assert self.provider.get_auth_headers() == {}


# ─── Provider Registry ─────────────────────────────────────────────────

class TestProviderRegistry:
    def test_all_providers_registered(self):
        assert set(call_ai.PROVIDERS.keys()) == {
            "openai", "anthropic", "google", "ollama", "openai-compatible"
        }

    def test_env_key_mapping(self):
        assert call_ai.PROVIDER_ENV_KEYS["openai"] == "OPENAI_API_KEY"
        assert call_ai.PROVIDER_ENV_KEYS["anthropic"] == "ANTHROPIC_API_KEY"
        assert call_ai.PROVIDER_ENV_KEYS["google"] == "GOOGLE_API_KEY"
        assert call_ai.PROVIDER_ENV_KEYS["ollama"] == ""
