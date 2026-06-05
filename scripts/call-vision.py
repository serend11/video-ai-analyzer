#!/usr/bin/env python3
"""
Call OpenAI Vision API (GPT-4V/GPT-4o) to analyze a video frame.

Usage:
    call-vision.py <frame.jpg> [--prompt "analysis prompt"] [--model gpt-4o] [--out result.txt]

Environment:
    OPENAI_API_KEY    Required
    OPENAI_BASE_URL   Optional, for custom endpoints
"""

import sys, os, json, base64, argparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

def main():
    parser = argparse.ArgumentParser(description="Analyze video frame with GPT-4V")
    parser.add_argument("frame", help="Path to frame image (jpg/png)")
    parser.add_argument("--prompt", default="Describe this video frame in detail.", help="Analysis prompt")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI vision model")
    parser.add_argument("--out", help="Output file (default: stdout)")
    parser.add_argument("--detail", default="low", choices=["low", "high", "auto"], help="Image detail level")
    parser.add_argument("--max-tokens", type=int, default=500, help="Max response tokens")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Error: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    # Read and encode the frame
    with open(args.frame, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    # Determine MIME type
    ext = os.path.splitext(args.frame)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"

    # Build request payload
    payload = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": args.prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64}",
                            "detail": args.detail,
                        },
                    },
                ],
            }
        ],
    }

    # Call API
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["choices"][0]["message"]["content"]
    except HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"Error: API returned HTTP {e.code}: {err_body[:500]}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Error: Could not connect to API: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error: Unexpected API response: {e}", file=sys.stderr)
        sys.exit(1)

    # Output
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result)
    else:
        print(result)


if __name__ == "__main__":
    main()
