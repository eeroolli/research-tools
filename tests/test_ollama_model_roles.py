#!/usr/bin/env python3
"""
Tests for role-based Ollama model selection in OllamaClient.
"""

import unittest
from unittest.mock import patch, MagicMock


class TestOllamaModelRoles(unittest.TestCase):
    """Verify that OllamaClient uses role-specific models and temperatures."""

    @patch("shared_tools.ai.ollama_client.requests.post")
    def test_extract_paper_metadata_uses_metadata_model(self, mock_post):
        from shared_tools.ai.ollama_client import OllamaClient

        # Create a bare instance without running full __init__
        client = OllamaClient.__new__(OllamaClient)

        # Minimal attributes required by extract_paper_metadata
        class _Validator:
            def validate_all(self, metadata):
                return metadata

        client.validator = _Validator()
        client.ollama_base_url = "http://dummy:11434"
        client.fallback_hosts = []
        client.timeout = 5
        client.ollama_model = "base-model"
        client.metadata_model = "metadata-model"
        client.metadata_temperature = 0.15

        # Avoid building the huge real prompt by monkeypatching via setattr
        setattr(client, "_build_extraction_prompt", lambda text, document_context, language=None: "PROMPT")

        # Mock successful Ollama response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": '{"doi": null, "issn": null, "isbn": null, '
                        '"url": null, "title": "X", "authors": [], '
                        '"journal": null, "publisher": null, '
                        '"year": null, "pages": null, '
                        '"document_type": "journal_article"}'
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = client.extract_paper_metadata("dummy text", validate=False)
        self.assertIsNotNone(result)

        # Verify payload uses the metadata-model role and temperature
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("model"), "metadata-model")
        self.assertIn("options", payload)
        self.assertAlmostEqual(payload["options"].get("temperature"), 0.15)

    @patch("shared_tools.ai.ollama_client.requests.post")
    def test_shorten_title_uses_title_model(self, mock_post):
        from shared_tools.ai.ollama_client import OllamaClient

        client = OllamaClient.__new__(OllamaClient)
        client.ollama_base_url = "http://dummy:11434"
        client.fallback_hosts = []
        client.timeout = 5
        client.ollama_model = "base-model"
        client.title_model = "title-model"
        client.title_temperature = 0.0
        client.max_retries = 1

        # Mock successful Ollama response with JSON
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": '{"shortened": "Shortened_Title"}'
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        shortened = client.shorten_title("Very_Long_Title_For_Testing_Purposes")
        self.assertIsNotNone(shortened)

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("model"), "title-model")
        self.assertIn("options", payload)
        self.assertAlmostEqual(payload["options"].get("temperature"), 0.0)


if __name__ == "__main__":
    unittest.main()

