"""Unit tests for scansort.gemini_client module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from google.genai.errors import APIError

from scansort.gemini_client import GeminiClassifier


def test_analyze_document_missing_api_key(tmp_path: Path):
    dummy_pdf = tmp_path / "doc.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    classifier = GeminiClassifier(api_key=None)
    with pytest.raises(ValueError, match="Gemini API key is not configured"):
        classifier.classify_document(dummy_pdf, taxonomy=["Utilities"])


def test_analyze_document_mock_success(tmp_path: Path):
    dummy_pdf = tmp_path / "bill.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """{
        "document_date": "260901",
        "description": "Origin Energy Electricity Bill",
        "target_folder": "Utilities/Electricity",
        "confidence": 0.95,
        "orientation_correction": 180,
        "document_type": "Invoice",
        "summary": "Electricity bill for September"
    }"""
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    taxonomy = ["Utilities/Electricity", "Finances/Banking"]
    result = classifier.classify_document(dummy_pdf, taxonomy=taxonomy)

    assert result.document_date == "260901"
    assert result.description == "Origin_Energy_Electricity_Bill"
    assert result.target_folder == "Utilities/Electricity"
    assert result.orientation_correction == 180
    assert result.confidence == 0.95


def test_analyze_document_unmatched_folder_falls_back(tmp_path: Path):
    dummy_pdf = tmp_path / "random.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """{
        "document_date": "260901",
        "description": "Unknown Document",
        "target_folder": "NonExistent/Folder",
        "confidence": 0.85
    }"""
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    taxonomy = ["Utilities/Electricity", "Finances/Banking"]
    result = classifier.classify_document(dummy_pdf, taxonomy=taxonomy)

    # Since 'NonExistent/Folder' is not in taxonomy, it must fallback to _Review_Needed
    assert result.target_folder == "_Review_Needed"


def test_analyze_document_blank_scan_routes_to_blank_subfolder(tmp_path: Path):
    dummy_pdf = tmp_path / "blank.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """{
        "document_date": "260901",
        "description": "Blank Page",
        "target_folder": "Utilities",
        "confidence": 0.99,
        "document_type": "Blank",
        "summary": "Empty white sheet."
    }"""
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    taxonomy = ["Utilities"]
    result = classifier.classify_document(dummy_pdf, taxonomy=taxonomy)

    assert result.target_folder == "_Review_Needed/Blank_Scans"
    assert result.document_type == "Blank"


def test_analyze_document_api_failure_returns_graceful_fallback(tmp_path: Path):
    dummy_pdf = tmp_path / "fail.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API down")

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    taxonomy = ["Utilities"]
    result = classifier.classify_document(dummy_pdf, taxonomy=taxonomy)

    assert result.target_folder == "_Review_Needed"
    assert result.confidence == 0.0
    assert "Failed" in result.description or "Error" in result.description


def test_low_confidence_forces_review_needed(tmp_path: Path):
    dummy = tmp_path / "doc.pdf"
    dummy.write_bytes(b"%PDF-1.4")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(
        {
            "document_date": "260901",
            "description": "Bill",
            "target_folder": "Utilities",
            "confidence": 0.45,
        }
    )
    mock_client.models.generate_content.return_value = mock_resp
    cls = GeminiClassifier(api_key="AIzaSyTest")
    cls._client = mock_client
    cls._cached_key = "AIzaSyTest"
    res = cls.classify_document(dummy, taxonomy=["Utilities"])
    assert res.target_folder == "_Review_Needed"


def test_path_traversal_target_folder_blocked(tmp_path: Path):
    dummy = tmp_path / "doc.pdf"
    dummy.write_bytes(b"%PDF-1.4")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(
        {
            "document_date": "260901",
            "description": "Escape",
            "target_folder": "../../Escaped",
            "confidence": 0.95,
        }
    )
    mock_client.models.generate_content.return_value = mock_resp
    cls = GeminiClassifier(api_key="AIzaSyTest")
    cls._client = mock_client
    cls._cached_key = "AIzaSyTest"
    res = cls.classify_document(dummy, taxonomy=["Utilities"])
    assert res.target_folder == "_Review_Needed"


def test_gemini_api_error_handled(tmp_path: Path):
    dummy = tmp_path / "doc.pdf"
    dummy.write_bytes(b"%PDF-1.4")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = APIError(
        429, {"error": {"message": "Quota exceeded"}}
    )
    cls = GeminiClassifier(api_key="AIzaSyTest")
    cls._client = mock_client
    cls._cached_key = "AIzaSyTest"
    res = cls.classify_document(dummy, taxonomy=["Utilities"])
    assert res.target_folder == "_Review_Needed"
    assert res.confidence == 0.0


def test_gemini_malformed_json_and_non_dict(tmp_path: Path):
    dummy = tmp_path / "doc.pdf"
    dummy.write_bytes(b"%PDF-1.4")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "{malformed json"
    mock_client.models.generate_content.return_value = mock_resp
    cls = GeminiClassifier(api_key="AIzaSyTest")
    cls._client = mock_client
    cls._cached_key = "AIzaSyTest"
    res = cls.classify_document(dummy, taxonomy=["Utilities"])
    assert res.target_folder == "_Review_Needed"

    # Non-dict JSON list
    mock_resp.text = '["item1", "item2"]'
    res2 = cls.classify_document(dummy, taxonomy=["Utilities"])
    assert res2.target_folder == "_Review_Needed"


def test_gemini_non_orthogonal_rotation(tmp_path: Path):
    dummy = tmp_path / "doc.pdf"
    dummy.write_bytes(b"%PDF-1.4")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(
        {
            "document_date": "260901",
            "description": "Doc",
            "target_folder": "Utilities",
            "confidence": 0.9,
            "orientation_correction": 45,
        }
    )
    mock_client.models.generate_content.return_value = mock_resp
    cls = GeminiClassifier(api_key="AIzaSyTest")
    cls._client = mock_client
    cls._cached_key = "AIzaSyTest"
    res = cls.classify_document(dummy, taxonomy=["Utilities"])
    assert res.orientation_correction == 0


def test_malformed_confidence_and_orientation(tmp_path: Path):
    dummy = tmp_path / "doc.pdf"
    dummy.write_bytes(b"%PDF-1.4")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(
        {
            "document_date": "260901",
            "description": "Doc",
            "target_folder": "Utilities",
            "confidence": "not_a_float",
            "orientation_correction": "not_an_int",
        }
    )
    mock_client.models.generate_content.return_value = mock_resp
    cls = GeminiClassifier(api_key="AIzaSyTest")
    cls._client = mock_client
    cls._cached_key = "AIzaSyTest"
    res = cls.classify_document(dummy, taxonomy=["Utilities"])
    assert res.confidence == 0.0
    assert res.orientation_correction == 0
    # Because confidence is 0.0, it should be routed to _Review_Needed
    assert res.target_folder == "_Review_Needed"


def test_client_caching_and_key_rotation(monkeypatch):
    cls = GeminiClassifier()
    with (
        patch("scansort.gemini_client.get_api_key", return_value="Key1"),
        patch("scansort.gemini_client.genai.Client") as mock_client_cls,
    ):
        c1 = cls._get_client()
        assert cls.api_key is None
        assert cls._cached_key == "Key1"
        c2 = cls._get_client()
        assert c1 == c2
        assert mock_client_cls.call_count == 1

    # Key rotated in vault without manual cls.api_key reset
    with (
        patch("scansort.gemini_client.get_api_key", return_value="Key2"),
        patch("scansort.gemini_client.genai.Client") as mock_client_cls2,
    ):
        c3 = cls._get_client()
        assert cls.api_key is None
        assert cls._cached_key == "Key2"
        assert c3 != c1
        assert mock_client_cls2.call_count == 1


def test_analyze_document_safety_block_value_error_handled(tmp_path: Path):
    dummy_pdf = tmp_path / "blocked.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_response = MagicMock()
    type(mock_response).text = PropertyMock(
        side_effect=ValueError("Response content was blocked by safety filters.")
    )
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client
    classifier._cached_key = "AIzaSyDummyKey123"

    result = classifier.classify_document(dummy_pdf, taxonomy=["Utilities"])
    assert result.target_folder == "_Review_Needed"
    assert result.confidence == 0.0


def test_missing_confidence_defaults_to_zero(tmp_path: Path):
    dummy_pdf = tmp_path / "doc.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "document_date": "260901",
            "description": "Electric Bill",
            "target_folder": "Utilities/Electricity",
            # confidence omitted entirely
        }
    )
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client
    classifier._cached_key = "AIzaSyDummyKey123"

    result = classifier.classify_document(dummy_pdf, taxonomy=["Utilities/Electricity"])
    assert result.confidence == 0.0
    # Because confidence < 0.70, it must route to _Review_Needed
    assert result.target_folder == "_Review_Needed"


def test_windows_backslashes_in_target_folder_normalized(tmp_path: Path):
    dummy_pdf = tmp_path / "doc.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "document_date": "260901",
            "description": "Electric Bill",
            "target_folder": "Utilities\\Electricity",
            "confidence": 0.95,
        }
    )
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client
    classifier._cached_key = "AIzaSyDummyKey123"

    result = classifier.classify_document(dummy_pdf, taxonomy=["Utilities/Electricity"])
    assert result.target_folder == "Utilities/Electricity"
    assert result.confidence == 0.95
