"""Unit tests for scansort.gemini_client module."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scansort.gemini_client import (
    DocumentClassification,
    GeminiClassifier,
    sanitize_date,
    sanitize_description,
)


def test_sanitize_description():
    assert (
        sanitize_description("Origin Energy Electricity Bill")
        == "Origin_Energy_Electricity_Bill"
    )
    assert (
        sanitize_description("medical / dental bill: Dr. Smith?")
        == "Medical_Dental_Bill_Dr_Smith"
    )
    assert sanitize_description("invoice   with   spaces") == "Invoice_With_Spaces"
    assert sanitize_description('invalid < > : " / \\ | ? * chars') == "Invalid_Chars"

    long_title = "A" * 100
    sanitized_long = sanitize_description(long_title)
    assert len(sanitized_long) <= 60


def test_sanitize_date():
    assert sanitize_date("260901") == "260901"
    today = datetime.now(UTC).strftime("%y%m%d")
    assert sanitize_date("invalid") == today
    assert sanitize_date("") == today
    assert sanitize_date("2026-09-01") == "260901"


def test_document_classification_model():
    model = DocumentClassification(
        document_date="260901",
        description="Origin_Energy_Bill",
        target_folder="Utilities/Electricity",
        confidence=0.95,
        orientation_correction=0,
        document_type="Invoice",
        summary="Quarterly electricity bill",
    )
    assert model.document_date == "260901"
    assert model.target_folder == "Utilities/Electricity"
    assert model.orientation_correction == 0


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
        "confidence": 0.40,
        "orientation_correction": 0,
        "document_type": "Other",
        "summary": "Unknown"
    }"""
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    taxonomy = ["Utilities/Electricity"]
    result = classifier.classify_document(dummy_pdf, taxonomy=taxonomy)

    assert result.target_folder == "_Review_Needed"


def test_analyze_document_blank_scan_routes_to_blank_subfolder(tmp_path: Path):
    dummy_pdf = tmp_path / "blank.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """{
        "document_date": "260901",
        "description": "Blank Page",
        "target_folder": "_Review_Needed",
        "confidence": 0.99,
        "orientation_correction": 0,
        "document_type": "Blank",
        "summary": "Empty white scanned page"
    }"""
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    result = classifier.classify_document(dummy_pdf, taxonomy=["Utilities"])
    assert result.target_folder == "_Review_Needed/Blank_Scans"


def test_analyze_document_api_failure_returns_graceful_fallback(tmp_path: Path):
    dummy_pdf = tmp_path / "broken.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError(
        "API connection timeout"
    )

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    result = classifier.classify_document(dummy_pdf, taxonomy=["Utilities"])
    assert result.target_folder == "_Review_Needed"
    assert result.confidence == 0.0
    assert "Failed" in result.description or "Error" in result.description


def test_low_confidence_forces_review_needed(tmp_path: Path):
    import json

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
    import json

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
    from google.genai.errors import APIError

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
    mock_resp.text = "not json at all"
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
    import json

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


def test_sanitizers_numeric_types():
    assert sanitize_description(12345) == "12345"
    assert sanitize_description(None) == "Scanned_Document"
    assert sanitize_description("") == "Scanned_Document"
    assert sanitize_description("   ") == "Scanned_Document"
    assert sanitize_description("???") == "Scanned_Document"
    assert sanitize_date(20260901) == "260901"
    assert sanitize_date(None) == datetime.now(UTC).strftime("%y%m%d")


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
    from unittest.mock import patch

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


def test_sanitize_description_null_bytes_and_control_chars():
    dirty = "Invoice\x00\x01\x1f\x7f_2026\tSpecial"
    assert sanitize_description(dirty) == "Invoice_2026_Special"


def test_analyze_document_safety_block_value_error_handled(tmp_path: Path):
    from unittest.mock import PropertyMock

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
