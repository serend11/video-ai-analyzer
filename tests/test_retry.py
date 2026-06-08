"""
Test retry logic with mocked HTTP responses.
"""

import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
import socket

from conftest import call_ai


def make_http_error(code: int, body: str = ""):
    """Create a mock HTTPError with the given status code."""
    resp = MagicMock()
    resp.code = code
    resp.read.return_value = body.encode("utf-8")
    err = HTTPError("http://fake", code, "Error", {}, resp)
    return err


def make_url_error(reason: str = "connection refused"):
    """Create a mock URLError."""
    return URLError(reason)


class TestRetryLogic:
    """Test the retry behavior in call_api."""

    @patch("call_ai.urlopen")
    @patch("call_ai.time.sleep")
    def test_success_on_first_try(self, mock_sleep, mock_urlopen):
        """Should succeed immediately without any retries."""
        provider = call_ai.OpenAIProvider()
        os_patch = patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with os_patch:
            result = call_ai.call_api(
                provider,
                {"model": "gpt-4o", "messages": []},
                provider.get_auth_headers(),
                max_retries=3,
                retry_delay=1.0,
            )

        assert result == {"choices": [{"message": {"content": "ok"}}]}
        mock_sleep.assert_not_called()
        assert mock_urlopen.call_count == 1

    @patch("call_ai.urlopen")
    @patch("call_ai.time.sleep")
    def test_retry_on_429_then_success(self, mock_sleep, mock_urlopen):
        """Should retry on rate limit (429) and succeed on second attempt."""
        provider = call_ai.OpenAIProvider()
        os_patch = patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})

        # First call fails with 429, second succeeds
        mock_success = MagicMock()
        mock_success.read.return_value = (
            b'{"choices":[{"message":{"content":"retry_ok"}}]}'
        )
        mock_urlopen.side_effect = [
            make_http_error(429, '{"error":"rate limit"}'),
            MagicMock(
                __enter__=MagicMock(return_value=mock_success),
                __exit__=MagicMock(return_value=None),
            ),
        ]

        with os_patch:
            result = call_ai.call_api(
                provider,
                {"model": "gpt-4o", "messages": []},
                provider.get_auth_headers(),
                max_retries=3,
                retry_delay=1.0,
            )

        assert result == {"choices": [{"message": {"content": "retry_ok"}}]}
        # Should sleep once (1.0 * 2^0 = 1.0 seconds) before retry
        mock_sleep.assert_called_once_with(1.0)
        assert mock_urlopen.call_count == 2

    @patch("call_ai.urlopen")
    @patch("call_ai.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep, mock_urlopen):
        """Delays should double each retry: 1s, 2s, 4s."""
        provider = call_ai.OpenAIProvider()
        os_patch = patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})

        # All three attempts fail with 429, fourth succeeds
        mock_success = MagicMock()
        mock_success.read.return_value = (
            b'{"choices":[{"message":{"content":"ok"}}]}'
        )
        mock_urlopen.side_effect = [
            make_http_error(429),
            make_http_error(429),
            make_http_error(429),
            MagicMock(
                __enter__=MagicMock(return_value=mock_success),
                __exit__=MagicMock(return_value=None),
            ),
        ]

        with os_patch:
            call_ai.call_api(
                provider,
                {"model": "gpt-4o", "messages": []},
                provider.get_auth_headers(),
                max_retries=3,
                retry_delay=1.0,
            )

        # Should have 3 sleep calls with increasing delays
        assert mock_sleep.call_count == 3
        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]

    @patch("call_ai.urlopen")
    @patch("call_ai.time.sleep")
    def test_retry_on_500(self, mock_sleep, mock_urlopen):
        """Should retry on server errors (5xx)."""
        provider = call_ai.OpenAIProvider()
        os_patch = patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})

        mock_success = MagicMock()
        mock_success.read.return_value = (
            b'{"choices":[{"message":{"content":"ok"}}]}'
        )
        mock_urlopen.side_effect = [
            make_http_error(503),
            MagicMock(
                __enter__=MagicMock(return_value=mock_success),
                __exit__=MagicMock(return_value=None),
            ),
        ]

        with os_patch:
            result = call_ai.call_api(
                provider,
                {"model": "gpt-4o", "messages": []},
                provider.get_auth_headers(),
                max_retries=3,
                retry_delay=0.1,
            )

        assert result["choices"][0]["message"]["content"] == "ok"

    @patch("call_ai.urlopen")
    @patch("call_ai.time.sleep")
    def test_no_retry_on_401(self, mock_sleep, mock_urlopen):
        """Should NOT retry on auth errors (401) — fail immediately."""
        import pytest
        provider = call_ai.OpenAIProvider()
        os_patch = patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})

        mock_urlopen.side_effect = make_http_error(401, '{"error":"unauthorized"}')

        with os_patch:
            with pytest.raises(SystemExit) as excinfo:
                call_ai.call_api(
                    provider,
                    {"model": "gpt-4o", "messages": []},
                    provider.get_auth_headers(),
                    max_retries=3,
                    retry_delay=1.0,
                )
            assert excinfo.value.code == 1

        mock_sleep.assert_not_called()
        assert mock_urlopen.call_count == 1

    @patch("call_ai.urlopen")
    @patch("call_ai.time.sleep")
    def test_retry_on_connection_error(self, mock_sleep, mock_urlopen):
        """Should retry on connection errors (URLError)."""
        provider = call_ai.OpenAIProvider()
        os_patch = patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})

        mock_success = MagicMock()
        mock_success.read.return_value = (
            b'{"choices":[{"message":{"content":"ok"}}]}'
        )
        mock_urlopen.side_effect = [
            make_url_error("connection refused"),
            MagicMock(
                __enter__=MagicMock(return_value=mock_success),
                __exit__=MagicMock(return_value=None),
            ),
        ]

        with os_patch:
            result = call_ai.call_api(
                provider,
                {"model": "gpt-4o", "messages": []},
                provider.get_auth_headers(),
                max_retries=3,
                retry_delay=0.1,
            )

        assert result["choices"][0]["message"]["content"] == "ok"

    @patch("call_ai.urlopen")
    @patch("call_ai.time.sleep")
    def test_exhaust_retries_gives_up(self, mock_sleep, mock_urlopen):
        """After max_retries+1 attempts, should give up and exit."""
        import pytest
        provider = call_ai.OpenAIProvider()
        os_patch = patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})

        # All 4 attempts fail (3 retries + 1 initial = 4 total)
        mock_urlopen.side_effect = [
            make_http_error(429),
            make_http_error(429),
            make_http_error(429),
            make_http_error(429),
        ]

        with os_patch:
            with pytest.raises(SystemExit) as excinfo:
                call_ai.call_api(
                    provider,
                    {"model": "gpt-4o", "messages": []},
                    provider.get_auth_headers(),
                    max_retries=3,
                    retry_delay=0.1,
                )
            assert excinfo.value.code == 1

        # 3 retries (exponential backoff), then gives up
        assert mock_sleep.call_count == 3
        assert mock_urlopen.call_count == 4
