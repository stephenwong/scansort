"""Unit tests for structured Gemini event logging (scansort.logging.gemini_logger)."""

import logging

from scansort.classification.models import DocumentClassification
from scansort.logging.gemini_logger import log_classification_event


def test_log_classification_event(caplog):
    caplog.set_level(logging.DEBUG)
    classification = DocumentClassification(
        document_date="260906",
        description="Origin_Energy_Bill",
        target_folder="Utilities/Electricity",
        confidence=0.92,
        orientation_correction=0,
        document_type="Invoice",
        summary="Quarterly electricity statement.",
        folder_reasoning="Electricity bill from Origin matches Utilities/Electricity.",
    )

    log_classification_event(
        file_name="scan_001.pdf",
        model="gemini-3.1-flash-lite",
        latency_seconds=1.24,
        classification=classification,
        routing_rationale="Matched discovered taxonomy folder 'Utilities/Electricity' with 92% confidence.",
        prompt_tokens=1500,
        candidates_tokens=100,
        raw_response_text='{"document_date": "260906"}',
    )

    logs = caplog.text
    assert "Classified 'scan_001.pdf' in 1.24s using gemini-3.1-flash-lite" in logs
    assert "target='Utilities/Electricity'" in logs
    assert "conf=0.92" in logs
    assert "Folder reason: Electricity bill from Origin" in logs
    assert "Routing decision: Matched discovered taxonomy folder" in logs
    assert "Tokens: 1,500 in / 100 out" in logs
    assert 'Raw Gemini response: {"document_date": "260906"}' in logs
