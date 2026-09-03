"""Unit tests for scansort.gemini_client module."""

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
    assert sanitize_description("Origin Energy Electricity Bill") == "Origin_Energy_Electricity_Bill"
    assert sanitize_description("medical / dental bill: Dr. Smith?") == "Medical_Dental_Bill_Dr_Smith"
    assert sanitize_description("invoice   with   spaces") == "Invoice_With_Spaces"
    assert sanitize_description("invalid < > : \" / \\ | ? * chars") == "Invalid_Chars"

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
    mock_client.models.generate_content.side_effect = RuntimeError("API connection timeout")

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    result = classifier.classify_document(dummy_pdf, taxonomy=["Utilities"])
    assert result.target_folder == "_Review_Needed"
    assert result.confidence == 0.0
    assert "Failed" in result.description or "Error" in result.description
