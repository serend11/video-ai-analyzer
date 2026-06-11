#!/usr/bin/env python3
"""
Multi-provider AI API client — OPTIMIZED

Performance improvements:
  - Added jitter to exponential backoff (prevents thundering herd)
  - Structured error handling
  - Cleaner provider abstraction for use as a module
  - Rate limiting awareness

Supported providers:
  - openai             GPT-4V / GPT-4o (vision + text)
  - anthropic          Claude 3 Sonnet / Haiku (vision + text)
  - google             Gemini Flash / Pro (vision + text)
  - ollama             Local models: llava, minicpm-v, etc.
  - openai-compatible  DeepSeek, Groq, LM Studio, vLLM, etc.
"""

import sys
import os
import json
import base64
import time
import random
import argparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from typing import Optional

VERSION = "3.2.0"

# Retryable HTTP status codes
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


# ═══════════════════════════════════════════════════════════════════════════
# Provider Implementations
# ═══════════════════════════════════════════════════════════════════════════

class AIProvider:
    """Base class for AI providers."""

    name: str = "base"
    default_model: str = ""
    default_summary_model: str = ""

    def get_endpoint(self, model: str = "") -> str:
        raise NotImplementedError

    def get_auth_headers(self) -> dict:
        return {}

    def build_payload(self, *, model: str, prompt: str, image_b64: Optional[str],
                      mime: str, max_tokens: int, detail: str,
                      temperature: float) -> dict:
        raise NotImplementedError

    def parse_response(self, data: dict) -> str:
        raise NotImplementedError


class OpenAIProvider(AIProvider):
    name = "openai"
    default_model = "gpt-4o"
    default_summary_model = "gpt-4o-mini"

    def get_endpoint(self) -> str:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
        return f"{base.rstrip('/')}/v1/chat/completions"

    def get_auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}

    def build_payload(self, *, model, prompt, image_b64, mime, max_tokens,
                      detail, temperature):
        content = []
        if image_b64:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{image_b64}",
                    "detail": detail,
                },
            })
        content.append({"type": "text", "text": prompt})

        return {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": content}],
        }

    def parse_response(self, data: dict) -> str:
        return data["choices"][0]["message"]["content"]


class AnthropicProvider(AIProvider):
    name = "anthropic"
    default_model = "claude-3-5-sonnet-20241022"
    default_summary_model = "claude-3-5-haiku-20241022"

    def get_endpoint(self) -> str:
        base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        return f"{base.rstrip('/')}/v1/messages"

    def get_auth_headers(self) -> dict:
        return {
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        }

    def build_payload(self, *, model, prompt, image_b64, mime, max_tokens,
                      detail, temperature):
        content = []
        if image_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": image_b64,
                },
            })
        content.append({"type": "text", "text": prompt})

        return {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": content}],
        }

    def parse_response(self, data: dict) -> str:
        parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                parts.append(block["text"])
        return "\n".join(parts)


class GoogleProvider(AIProvider):
    name = "google"
    default_model = "gemini-2.0-flash-exp"
    default_summary_model = "gemini-2.0-flash-exp"

    def get_endpoint(self, model: str = "") -> str:
        m = model or self.default_model
        base = os.environ.get(
            "GOOGLE_BASE_URL",
            "https://generativelanguage.googleapis.com",
        )
        key = os.environ["GOOGLE_API_KEY"]
        return (f"{base.rstrip('/')}/v1beta/models/"
                f"{m}:generateContent?key={key}")

    def get_auth_headers(self) -> dict:
        return {}

    def build_payload(self, *, model, prompt, image_b64, mime, max_tokens,
                      detail, temperature):
        parts = []
        if image_b64:
            parts.append({
                "inlineData": {"mimeType": mime, "data": image_b64},
            })
        parts.append({"text": prompt})

        return {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

    def parse_response(self, data: dict) -> str:
        parts = []
        for part in data["candidates"][0]["content"]["parts"]:
            if "text" in part:
                parts.append(part["text"])
        return "\n".join(parts)


class OllamaProvider(AIProvider):
    name = "ollama"
    default_model = "llava"
    default_summary_model = "llava"

    def get_endpoint(self) -> str:
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        return f"{base.rstrip('/')}/api/chat"

    def get_auth_headers(self) -> dict:
        return {}

    def build_payload(self, *, model, prompt, image_b64, mime, max_tokens,
                      temperature):
        msg = {"role": "user", "content": prompt}
        if image_b64:
            msg["images"] = [image_b64]

        return {
            "model": model,
            "messages": [msg],
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

    def parse_response(self, data: dict) -> str:
        return data["message"]["content"]


# Provider registry
PROVIDERS = {
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
    "google": GoogleProvider(),
    "ollama": OllamaProvider(),
    "openai-compatible": OpenAIProvider(),
}

PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "openai-compatible": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "ollama": "",
}


# ═══════════════════════════════════════════════════════════════════════════
# CallAI Client Class
# ═══════════════════════════════════════════════════════════════════════════

class CallAI:
    """
    High-level AI client with automatic retry and jitter.
    Can be used as a module or standalone.
    """

    def __init__(
        self,
        provider: str = "openai",
        model: str = "",
        base_url: str = "",
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: int = 120,
    ):
        self.provider_name = provider
        self.provider = PROVIDERS.get(provider, PROVIDERS["openai"])
        self.model = model or self.provider.default_model
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout

        # Override base URL
        if base_url:
            env_key = f"{provider.upper().replace('-', '_')}_BASE_URL"
            os.environ[env_key] = base_url

        # Validate API key
        env_key = PROVIDER_ENV_KEYS.get(provider, "")
        if env_key and not os.environ.get(env_key):
            raise ValueError(f"Required environment variable not set: {env_key}")

    def encode_image(self, path: str) -> tuple[str, str]:
        """Read image from disk and return (base64_string, mime_type)."""
        abs_path = os.path.abspath(path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"Image file not found: {abs_path}")

        ext = os.path.splitext(path)[1].lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        mime = mime_map.get(ext, "image/jpeg")

        with open(abs_path, "rb") as f:
            raw = f.read()

        if len(raw) == 0:
            raise ValueError(f"Image file is empty: {abs_path}")

        return base64.b64encode(raw).decode("ascii"), mime

    def call_api(self, payload: dict, headers: dict, model: str = "") -> dict:
        """Call the AI API with exponential backoff + JITTER retry."""

        # Get endpoint
        if 'model' in self.provider.get_endpoint.__code__.co_varnames:
            url = self.provider.get_endpoint(model=model or self.model)
        else:
            url = self.provider.get_endpoint()

        body = json.dumps(payload).encode("utf-8")
        all_headers = {"Content-Type": "application/json", **headers}

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                req = Request(url, data=body, headers=all_headers)
                with urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            except HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                status = e.code

                if status in RETRYABLE_STATUSES and attempt < self.max_retries:
                    # JITTER: Add random ±20% to prevent thundering herd
                    delay = self.retry_delay * (2 ** attempt)
                    jitter = delay * (0.8 + random.random() * 0.4)
                    print(f"   ⚠️  HTTP {status}, retrying in {jitter:.1f}s "
                          f"(attempt {attempt + 1}/{self.max_retries})...",
                          file=sys.stderr)
                    time.sleep(jitter)
                    last_error = e
                    continue

                print(f"Error: API returned HTTP {status}: {err_body}",
                      file=sys.stderr)
                raise

            except URLError as e:
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** attempt)
                    # JITTER applied here too
                    jitter = delay * (0.8 + random.random() * 0.4)
                    print(f"   ⚠️  Connection error: {e.reason}, "
                          f"retrying in {jitter:.1f}s...", file=sys.stderr)
                    time.sleep(jitter)
                    last_error = e
                    continue
                print(f"Error: Could not connect to API: {e.reason}",
                      file=sys.stderr)
                raise

        raise RuntimeError(f"All retries exhausted: {last_error}")

    def analyze_image(
        self,
        image_path: str,
        prompt: str = "Describe this image in detail.",
        max_tokens: int = 500,
        temperature: float = 0.7,
        detail: str = "low",
    ) -> Optional[str]:
        """Analyze an image and return the description."""
        try:
            image_b64, mime = self.encode_image(image_path)

            payload = self.provider.build_payload(
                model=self.model,
                prompt=prompt,
                image_b64=image_b64,
                mime=mime,
                max_tokens=max_tokens,
                detail=detail,
                temperature=temperature,
            )
            headers = self.provider.get_auth_headers()

            data = self.call_api(payload, headers)
            result = self.provider.parse_response(data)

            if result and result.strip():
                return result
            return None

        except Exception as e:
            print(f"   ⚠️  Image analysis failed: {e}", file=sys.stderr)
            return None

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.5,
    ) -> Optional[str]:
        """Generate text (no image)."""
        try:
            payload = self.provider.build_payload(
                model=self.model,
                prompt=prompt,
                image_b64=None,
                mime="image/jpeg",
                max_tokens=max_tokens,
                detail="low",
                temperature=temperature,
            )
            headers = self.provider.get_auth_headers()

            data = self.call_api(payload, headers)
            return self.provider.parse_response(data)

        except Exception as e:
            print(f"   ⚠️  Text generation failed: {e}", file=sys.stderr)
            return None


# ═══════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=f"Multi-provider AI API client v{VERSION}",
    )
    parser.add_argument("--provider", default="openai",
                        choices=list(PROVIDERS.keys()))
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("image", nargs="?", default="")
    parser.add_argument("--prompt", default="Describe this video frame.")
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--text-only", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--detail", default="low",
                        choices=["low", "high", "auto"])
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=1.0)

    args = parser.parse_args()

    # Load prompt from file if specified
    prompt = args.prompt
    if args.prompt_file:
        if os.path.isfile(args.prompt_file):
            with open(args.prompt_file, "r", encoding="utf-8") as f:
                prompt = f.read().strip()

    # Initialize client
    client = CallAI(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
    )

    # Call API
    if args.text_only:
        result = client.generate_text(prompt, args.max_tokens, args.temperature)
    elif args.image:
        result = client.analyze_image(
            args.image, prompt, args.max_tokens, args.temperature, args.detail
        )
    else:
        print("Error: Image path required (or use --text-only)", file=sys.stderr)
        sys.exit(1)

    # Output
    if result:
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(result)
        else:
            print(result)
    else:
        print("Error: API returned empty response", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
