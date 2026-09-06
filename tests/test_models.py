"""Unit tests for scansort.models module."""

from datetime import datetime
from zoneinfo import ZoneInfo

from scansort.models import (
    DocumentClassification,
    sanitize_date,
    sanitize_description,
)
from scansort.timeutil import sydney_now

SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def _sydney_from_utc(iso: str) -> datetime:
    """Convert a UTC instant to its Australia/Sydney wall-clock representation."""
    return datetime.fromisoformat(iso).astimezone(SYDNEY_TZ)


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
    today = sydney_now().strftime("%y%m%d")
    assert sanitize_date("invalid") == today
    assert sanitize_date("") == today
    assert sanitize_date("2026-09-01") == "260901"


def test_sanitize_date_rejects_impossible_calendar_dates():
    today = sydney_now().strftime("%y%m%d")
    assert sanitize_date("260932") == today  # day 32
    assert sanitize_date("000000") == today  # zero year/month/day
    assert sanitize_date("20261399") == today  # month 13
    assert sanitize_date("260001") == today  # month 00
    assert sanitize_date("20260230") == today  # Feb 30


def test_sanitize_date_fallback_uses_sydney_wall_clock(monkeypatch):
    import scansort.models as models

    # 2026-09-05T14:30Z == 2026-09-06 00:30 in Sydney (AEST, UTC+10).
    monkeypatch.setattr(
        models,
        "sydney_now",
        lambda: _sydney_from_utc("2026-09-05T14:30:00+00:00"),
    )
    assert sanitize_date("no-date-here") == "260906"

    # 2026-01-31T13:30Z == 2026-02-01 00:30 in Sydney (AEDT, UTC+11).
    monkeypatch.setattr(
        models,
        "sydney_now",
        lambda: _sydney_from_utc("2026-01-31T13:30:00+00:00"),
    )
    assert sanitize_date(None) == "260201"


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
    assert sanitize_date(None) == sydney_now().strftime("%y%m%d")


def test_sanitize_description_null_bytes_and_control_chars():
    dirty = "Invoice\x00\x01\x1f\x7f_2026\tSpecial"
    assert sanitize_description(dirty) == "Invoice_2026_Special"


def test_sanitize_description_truncates_on_word_boundaries():
    long_title = "PaymentNotice " * 8
    result = sanitize_description(long_title)
    assert len(result) <= 60
    # Trailing partial words must be dropped, not sliced mid-word.
    assert not result.endswith("_")
    assert result == "Paymentnotice_Paymentnotice_Paymentnotice_Paymentnotice"


def test_sanitize_description_normalizes_fullwidth_and_format_chars():
    assert sanitize_description("Payment／Notice Bill") == "Payment_Notice_Bill"
    assert "\ufeff" not in sanitize_description("\ufeffBank Statement")
    assert "\u200b" not in sanitize_description("Bank\u200bStatement Bill")
    assert sanitize_description("Bank\u200bStatement") == "Bankstatement"
    assert "Bank\u202eStatement" not in sanitize_description("Bank\u202eStatement")


def test_document_classification_rejects_unsanitized_boundary_values():
    import pytest

    with pytest.raises(ValueError):
        DocumentClassification(
            document_date="2609",
            description="Bad/name",
            target_folder="Utilities",
        )
    with pytest.raises(ValueError):
        DocumentClassification(
            document_date="260901",
            description="bad\\name",
            target_folder="Utilities",
        )
    with pytest.raises(ValueError):
        DocumentClassification(
            document_date="260932",
            description="Good",
            target_folder="Utilities",
        )
    with pytest.raises(ValueError):
        DocumentClassification(
            document_date="260901",
            description="\ufeffHidden",
            target_folder="Utilities",
        )
    with pytest.raises(ValueError):
        DocumentClassification(
            document_date="260901",
            description="Ok",
            target_folder="Utilities",
            confidence=1.5,
        )


def test_gemini_classification_response_schema_decoupling():
    from scansort.models import GeminiClassificationResponse

    # Ensure Gemini response schema does NOT expose internal pipeline fields
    fields = GeminiClassificationResponse.model_fields.keys()
    assert "document_date" in fields
    assert "description" in fields
    assert "target_folder" in fields
    assert "folder_reasoning" in fields
    assert "routing_rationale" not in fields
    assert "prompt_tokens" not in fields
    assert "candidates_tokens" not in fields
    assert "estimated_cost_usd" not in fields


def test_document_classification_telemetry_fields():
    doc = DocumentClassification(
        document_date="260906",
        description="Electric_Bill",
        target_folder="Utilities",
        confidence=0.9,
        prompt_tokens=450,
        candidates_tokens=150,
        estimated_cost_usd="$0.000078 USD",
        routing_rationale="Matched taxonomy",
    )
    assert doc.prompt_tokens == 450
    assert doc.candidates_tokens == 150
    assert doc.total_tokens == 600
    assert doc.estimated_cost_usd == "$0.000078 USD"
    assert doc.routing_rationale == "Matched taxonomy"
