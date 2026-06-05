"""
Test error handling and edge cases.
"""

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock
import json

from conftest import call_ai, FAKE_JPEG_BASE64


class TestEncodeImage:
    """Test the encode_image helper function."""

    def test_encode_valid_jpeg(self):
        """Should encode a real image file."""
        # Create a minimal JPEG
        import struct
        jpeg_data = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01"
            b"\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07"
            b"\x07\x07\x09\x09\x08\x0a\x0c\x14\x0d\x0c\x0b\x0b\x0c\x19\x12"
            b"\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c\x20\x24\x2e\x27"
            b"\x20\x22\x2c\x23\x1c\x1c\x28\x37\x29\x2c\x30\x31\x34\x34\x34"
            b"\x1f\x27\x39\x3d\x38\x32\x3c\x2e\x33\x34\x32\xff\xc0\x00\x0b"
            b"\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00"
            b"\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
            b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4\x00\xb5"
            b"\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00"
            b"\x01\x7d\x01\x02\x03\x00\x04\x11\x05\x12\x21\x31\x41\x06\x13"
            b"\x51\x61\x07\x22\x71\x14\x32\x81\x91\xa1\x08\x23\x42\xb1\xc1"
            b"\x15\x52\xd1\xf0\x24\x33\x62\x72\x82\x09\x0a\x16\x17\x18\x19"
            b"\x1a\x25\x26\x27\x28\x29\x2a\x34\x35\x36\x37\x38\x39\x3a\x43"
            b"\x44\x45\x46\x47\x48\x49\x4a\x53\x54\x55\x56\x57\x58\x59\x5a"
            b"\x63\x64\x65\x66\x67\x68\x69\x6a\x73\x74\x75\x76\x77\x78\x79"
            b"\x7a\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97"
            b"\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4"
            b"\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca"
            b"\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6"
            b"\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff"
            b"\xd9"
        )

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(jpeg_data)
            tmp_path = f.name

        try:
            b64, mime = call_ai.encode_image(tmp_path)
            assert len(b64) > 0
            assert mime == "image/jpeg"
        finally:
            os.unlink(tmp_path)

    def test_mime_detection_png(self):
        """Should detect PNG mime type."""
        png_data = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_data)
            tmp_path = f.name

        try:
            b64, mime = call_ai.encode_image(tmp_path)
            assert mime == "image/png"
        finally:
            os.unlink(tmp_path)

    def test_missing_file(self):
        """Should exit when file doesn't exist."""
        import pytest
        with pytest.raises(SystemExit):
            call_ai.encode_image("/no/such/file.jpg")

    def test_empty_file(self):
        """Should exit when file is empty."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            # Write nothing
            tmp_path = f.name

        try:
            with patch("sys.exit") as mock_exit:
                call_ai.encode_image(tmp_path)
                mock_exit.assert_called_once_with(1)
        finally:
            os.unlink(tmp_path)


class TestMainArgumentParsing:
    """Test the main() function's argument handling and validation."""

    @patch("sys.argv", ["call-ai.py", "--help"])
    def test_help_flag(self, capsys):
        """--help should print usage and exit."""
        import pytest
        with pytest.raises(SystemExit) as excinfo:
            call_ai.main()
        assert excinfo.value.code == 0
        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower() or "usage:" in captured.err.lower()

    def test_provider_validation(self):
        """Should reject unknown provider."""
        import pytest
        with patch("sys.argv", ["call-ai.py", "--provider", "unknown", "--text-only"]):
            with pytest.raises(SystemExit) as excinfo:
                call_ai.main()
            assert excinfo.value.code != 0

    @patch("sys.argv", ["call-ai.py", "--provider", "openai", "--text-only"])
    @patch.dict("os.environ", {}, clear=True)
    def test_missing_api_key(self):
        """Should error when OPENAI_API_KEY is not set."""
        import pytest
        with pytest.raises(SystemExit) as excinfo:
            call_ai.main()
        assert excinfo.value.code == 1


class TestParseResponseEdgeCases:
    """Test edge cases in response parsing."""

    def test_openai_malformed(self):
        """Should raise on completely malformed OpenAI response."""
        provider = call_ai.OpenAIProvider()
        bad = {"wrong_key": []}
        import pytest
        with pytest.raises((KeyError, IndexError, TypeError)):
            provider.parse_response(bad)

    def test_google_no_candidates(self):
        """Empty candidates in Google response."""
        provider = call_ai.GoogleProvider()
        bad = {"candidates": []}
        import pytest
        with pytest.raises((KeyError, IndexError)):
            provider.parse_response(bad)
