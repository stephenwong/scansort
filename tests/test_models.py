"""Unit tests for scansort.models module."""

from datetime import UTC, datetime

from scansort.models import (
    DocumentClassification,
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
    assert model.target_filename == "260901_Origin_Energy_Bill.pdf"


def test_sanitizers_numeric_types():
    assert sanitize_description(12345) == "12345"
    assert sanitize_description(None) == "Scanned_Document"
    assert sanitize_description("") == "Scanned_Document"
    assert sanitize_description("   ") == "Scanned_Document"
    assert sanitize_description("???") == "Scanned_Document"
    assert sanitize_date(20260901) == "260901"
    assert sanitize_date(None) == datetime.now(UTC).strftime("%y%m%d")


def test_sanitize_description_null_bytes_and_control_chars():
    dirty = "Invoice\x00\x01\x1f\x7f_2026\tSpecial"
    assert sanitize_description(dirty) == "Invoice_2026_Special"
