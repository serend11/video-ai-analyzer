#!/usr/bin/env python3
"""
Multi-provider AI API client — vision analysis + text generation.

Supported providers:
  - openai             GPT-4V / GPT-4o (vision + text)
  - anthropic          Claude 3 Sonnet / Haiku (vision + text)
  - google             Gemini Flash / Pro (vision + text)
  - ollama             Local models: llava, minicpm-v, etc.
  - openai-compatible  DeepSeek, Groq, LM Studio, vLLM, etc.

Usage:
  # Vision mode (analyze a frame)
  call-ai.py frame.jpg --provider openai --model gpt-4o --prompt "Describe..."

  # Text-only mode (generate summary)
  call-ai.py --provider anthropic --model claude-3-5-haiku-20241022 \
    --prompt "Summarize..." --text-only --max-tokens 2000

Environment:
  Required per provider:
    openai / openai-compatible → OPENAI_API_KEY
    anthropic                 → ANTHROPIC_API_KEY
    google                    → GOOGLE_API_KEY
    ollama                    → (none; defaults to localhost:11434)

  Optional:
    OPENAI_BASE_URL          → custom endpoint for openai / openai-compatible
    ANTHROPIC_BASE_URL       → custom endpoint for anthropic
    GOOGLE_BASE_URL          → custom endpoint for google
    OLLAMA_BASE_URL          → custom endpoint for ollama
"""

import sys
import os
import json
import base64
import time
import argparse
import mimetypes
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

VERSION = "2.0.0"

# ─── Retry configuration ──────────────────────────────────────────────
MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds; doubles each retry
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


# ═══════════════════════════════════════════════════════════════════════
# Provider Implementations
# ═══════════════════════════════════════════════════════════════════════

class AIProvider:
    """Base class for AI providers."""

    name: str = "base"
    default_model: str = ""
    default_summary_model: str = ""

    def get_endpoint(self) -> str:
        raise NotImplementedError

    def get_auth_headers(self) -> dict:
        return {}

    def build_payload(self, *, model: str, prompt: str, image_b64: str | None,
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
        # Anthropic returns content as a list of blocks
        parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                parts.append(block["text"])
        return "\n".join(parts)


class GoogleProvider(AIProvider):
    name = "google"
    default_model = "gemini-2.0-flash-exp"
    default_summary_model = "gemini-2.0-flash-exp"  # already cheap

    def get_endpoint(self) -> str:
        base = os.environ.get(
            "GOOGLE_BASE_URL",
            "https://generativelanguage.googleapis.com",
        )
        key = os.environ["GOOGLE_API_KEY"]
        return (f"{base.rstrip('/')}/v1beta/models/"
                f"{self._current_model}:generateContent?key={key}")

    def _set_model(self, model: str):
        self._current_model = model

    def get_auth_headers(self) -> dict:
        return {}  # API key in query string

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
                      detail, temperature):
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


# ─── Provider registry ────────────────────────────────────────────────

PROVIDERS: dict[str, AIProvider] = {
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
    "google": GoogleProvider(),
    "ollama": OllamaProvider(),
    "openai-compatible": OpenAIProvider(),  # same wire format
}

PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openai-compatible": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "ollama": "",  # no key needed
}


# ═══════════════════════════════════════════════════════════════════════
# Core logic
# ═══════════════════════════════════════════════════════════════════════

def encode_image(path: str) -> tuple[str, str]:
    """Read image from disk and return (base64_string, mime_type)."""
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        print(f"Error: Image file not found: {abs_path}", file=sys.stderr)
        sys.exit(1)

    ext = os.path.splitext(path)[1].lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp",
                ".gif": "image/gif"}
    mime = mime_map.get(ext, "image/jpeg")

    with open(abs_path, "rb") as f:
        raw = f.read()

    if len(raw) == 0:
        print(f"Error: Image file is empty: {abs_path}", file=sys.stderr)
        sys.exit(1)

    return base64.b64encode(raw).decode("ascii"), mime


def call_api(provider: AIProvider, payload: dict, headers: dict,
             max_retries: int, retry_delay: float) -> dict:
    """Call the AI API with exponential backoff retry."""
    url = provider.get_endpoint()
    body = json.dumps(payload).encode("utf-8")
    all_headers = {"Content-Type": "application/json", **headers}

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            req = Request(url, data=body, headers=all_headers)
            with urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            status = e.code

            if status in RETRYABLE_STATUSES and attempt < max_retries:
                delay = retry_delay * (2 ** attempt)
                print(f"   ⚠️  HTTP {status}, retrying in {delay:.1f}s "
                      f"(attempt {attempt + 1}/{max_retries})...",
                      file=sys.stderr)
                time.sleep(delay)
                last_error = e
                continue

            print(f"Error: API returned HTTP {status}: {err_body}",
                  file=sys.stderr)
            sys.exit(1)
        except URLError as e:
            if attempt < max_retries:
                delay = retry_delay * (2 ** attempt)
                print(f"   ⚠️  Connection error: {e.reason}, "
                      f"retrying in {delay:.1f}s...", file=sys.stderr)
                time.sleep(delay)
                last_error = e
                continue
            print(f"Error: Could not connect to API: {e.reason}",
                  file=sys.stderr)
            sys.exit(1)

    # Should never reach here, but just in case
    print(f"Error: All retries exhausted", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description=f"Multi-provider AI API client v{VERSION}",
    )
    # Provider
    parser.add_argument("--provider", default="openai",
                        choices=list(PROVIDERS.keys()),
                        help="AI provider (default: openai)")
    parser.add_argument("--model", default="",
                        help="Model name (provider-specific default if empty)")
    parser.add_argument("--base-url", default="",
                        help="Override API base URL")

    # Input
    parser.add_argument("image", nargs="?", default="",
                        help="Path to image file (omit for text-only mode)")
    parser.add_argument("--prompt", default="Describe this video frame.",
                        help="Analysis / generation prompt")
    parser.add_argument("--prompt-file", default="",
                        help="Read prompt from file")
    parser.add_argument("--text-only", action="store_true",
                        help="Text-only mode (no image)")

    # Output
    parser.add_argument("--out", default="",
                        help="Write result to file (default: stdout)")
    parser.add_argument("--max-tokens", type=int, default=500,
                        help="Max response tokens (default: 500)")
    parser.add_argument("--temperature", type=float, default=0.7,
                        help="Sampling temperature (default: 0.7)")

    # Vision-specific
    parser.add_argument("--detail", default="low",
                        choices=["low", "high", "auto"],
                        help="Image detail level for OpenAI (default: low)")

    # Retry
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                        help=f"Max retry attempts (default: {MAX_RETRIES})")
    parser.add_argument("--retry-delay", type=float, default=BASE_RETRY_DELAY,
                        help=f"Base retry delay in seconds (default: {BASE_RETRY_DELAY})")

    args = parser.parse_args()

    # ─── Select and configure provider ─────────────────────────────────
    provider = PROVIDERS[args.provider]

    # Override base URL via env if --base-url is set
    if args.base_url:
        env_key = f"{args.provider.upper().replace('-', '_')}_BASE_URL"
        if args.provider == "openai-compatible":
            os.environ["OPENAI_BASE_URL"] = args.base_url
        else:
            os.environ[env_key] = args.base_url

    # For Google, we need to set the model before building the endpoint
    if isinstance(provider, GoogleProvider):
        provider._set_model(args.model or provider.default_model)

    # ─── Validate API key ──────────────────────────────────────────────
    env_key = PROVIDER_ENV_KEYS.get(args.provider, "")
    if env_key and not os.environ.get(env_key):
        print(f"Error: {env_key} is not set. "
              f"Required for provider '{args.provider}'.", file=sys.stderr)
        print(f"  export {env_key}=\"your-key\"", file=sys.stderr)
        sys.exit(1)

    # ─── Resolve model name ────────────────────────────────────────────
    model = args.model or provider.default_model

    # ─── Load prompt ───────────────────────────────────────────────────
    prompt = args.prompt
    if args.prompt_file:
        if not os.path.isfile(args.prompt_file):
            print(f"Error: Prompt file not found: {args.prompt_file}",
                  file=sys.stderr)
            sys.exit(1)
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
        if not prompt:
            print(f"Error: Prompt file is empty: {args.prompt_file}",
                  file=sys.stderr)
            sys.exit(1)

    # ─── Handle image (if vision mode) ─────────────────────────────────
    image_b64 = None
    mime = "image/jpeg"
    if not args.text_only and args.image:
        image_b64, mime = encode_image(args.image)
    elif not args.text_only and not args.image:
        print("Error: Image path required for vision mode "
              "(or use --text-only)", file=sys.stderr)
        sys.exit(1)

    # ─── Build payload and headers ─────────────────────────────────────
    payload = provider.build_payload(
        model=model,
        prompt=prompt,
        image_b64=image_b64,
        mime=mime,
        max_tokens=args.max_tokens,
        detail=args.detail,
        temperature=args.temperature,
    )
    headers = provider.get_auth_headers()

    # ─── Call API with retry ───────────────────────────────────────────
    data = call_api(provider, payload, headers,
                    args.max_retries, args.retry_delay)

    # ─── Parse response ────────────────────────────────────────────────
    try:
        result = provider.parse_response(data)
    except (KeyError, IndexError, TypeError) as e:
        print(f"Error: Unexpected API response structure: {e}",
              file=sys.stderr)
        print(f"Raw response: {json.dumps(data, indent=2)[:1000]}",
              file=sys.stderr)
        sys.exit(1)

    if not result or not result.strip():
        print("Error: API returned empty response", file=sys.stderr)
        sys.exit(1)

    # ─── Output ────────────────────────────────────────────────────────
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result)
    else:
        print(result)


if __name__ == "__main__":
    main()
