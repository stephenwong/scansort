"""Unit tests for scansort.gemini_client module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from google.genai.errors import APIError

from scansort.classification.client import GeminiClassifier


def test_analyze_document_missing_api_key(minimal_pdf: Path):
    classifier = GeminiClassifier(api_key=None)
    with pytest.raises(ValueError, match="Gemini API key is not configured"):
        classifier.classify_document(minimal_pdf, taxonomy=["Utilities"])


def test_analyze_document_mock_success(minimal_pdf: Path):
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
    result = classifier.classify_document(minimal_pdf, taxonomy=taxonomy)

    assert result.document_date == "260901"
    assert result.description == "Origin_Energy_Electricity_Bill"
    assert result.target_folder == "Utilities/Electricity"
    assert result.confidence == 0.95
    assert result.orientation_correction == 180
    assert result.document_type == "Invoice"
    assert result.summary == "Electricity bill for September"


def test_analyze_document_unmatched_folder_falls_back(minimal_pdf: Path):
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
    result = classifier.classify_document(minimal_pdf, taxonomy=taxonomy)

    # Since 'NonExistent/Folder' is not in taxonomy, it must fallback to _Review_Needed
    assert result.target_folder == "_Review_Needed"


def test_analyze_document_blank_scan_routes_to_blank_subfolder(minimal_pdf: Path):
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
    result = classifier.classify_document(minimal_pdf, taxonomy=taxonomy)

    assert result.target_folder == "_Review_Needed/Blank_Scans"
    assert result.document_type == "Blank"


def test_analyze_document_api_failure_returns_graceful_fallback(minimal_pdf: Path):
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API down")

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    taxonomy = ["Utilities"]
    result = classifier.classify_document(minimal_pdf, taxonomy=taxonomy)

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
        patch("scansort.classification.client.get_api_key", return_value="Key1"),
        patch("scansort.classification.client.genai.Client") as mock_client_cls,
    ):
        c1 = cls._get_client()
        assert cls.api_key is None
        assert cls._cached_key == "Key1"
        c2 = cls._get_client()
        assert c1 == c2
        assert mock_client_cls.call_count == 1

    # Key rotated in vault without manual cls.api_key reset
    with (
        patch("scansort.classification.client.get_api_key", return_value="Key2"),
        patch("scansort.classification.client.genai.Client") as mock_client_cls2,
    ):
        c3 = cls._get_client()
        assert cls.api_key is None
        assert cls._cached_key == "Key2"
        assert c3 != c1
        assert mock_client_cls2.call_count == 1


def test_analyze_document_safety_block_value_error_handled(minimal_pdf: Path):
    mock_client = MagicMock()
    mock_response = MagicMock()
    type(mock_response).text = PropertyMock(
        side_effect=ValueError("Response content was blocked by safety filters.")
    )
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client
    classifier._cached_key = "AIzaSyDummyKey123"

    result = classifier.classify_document(minimal_pdf, taxonomy=["Utilities"])
    assert result.target_folder == "_Review_Needed"
    assert result.confidence == 0.0


def test_missing_confidence_defaults_to_zero(minimal_pdf: Path):
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

    result = classifier.classify_document(
        minimal_pdf, taxonomy=["Utilities/Electricity"]
    )
    assert result.confidence == 0.0
    # Because confidence < 0.70, it must route to _Review_Needed
    assert result.target_folder == "_Review_Needed"


def test_windows_backslashes_in_target_folder_normalized(minimal_pdf: Path):
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

    result = classifier.classify_document(
        minimal_pdf, taxonomy=["Utilities/Electricity"]
    )
    assert result.target_folder == "Utilities/Electricity"
    assert result.confidence == 0.95


def _classify_text(text: str, taxonomy=None, api_key="AIzaSyTest"):
    """Drive classify_document with a canned raw response text."""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"%PDF-1.4")
        dummy = Path(tmp.name)
    try:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = text
        mock_client.models.generate_content.return_value = mock_resp
        cls = GeminiClassifier(api_key=api_key)
        cls._client = mock_client
        cls._cached_key = api_key
        return cls.classify_document(dummy, taxonomy=taxonomy or ["Utilities"])
    finally:
        dummy.unlink(missing_ok=True)


def test_model_invented_review_subfolder_rerouted():
    """Only the exact _Review_Needed literal may bypass the taxonomy gate."""
    res = _classify_text(
        json.dumps(
            {
                "document_date": "260901",
                "description": "Insured",
                "target_folder": "_Review_Needed/Home_Insurance",
                "confidence": 0.95,
            }
        )
    )
    assert res.target_folder == "_Review_Needed"

    res_lookalike = _classify_text(
        json.dumps(
            {
                "document_date": "260901",
                "description": "Insured",
                "target_folder": "_Review_NeededX",
                "confidence": 0.95,
            }
        )
    )
    assert res_lookalike.target_folder == "_Review_Needed"

    # A genuine low-confidence result still routes to the exact review folder.
    res_low = _classify_text(
        json.dumps(
            {
                "document_date": "260901",
                "description": "Insured",
                "target_folder": "Utilities",
                "confidence": 0.4,
            }
        )
    )
    assert res_low.target_folder == "_Review_Needed"


def test_malformed_confidence_string_keeps_description():
    res = _classify_text(
        json.dumps(
            {
                "document_date": "260901",
                "description": "Real Bill",
                "target_folder": "Utilities",
                "confidence": "not_a_float",
            }
        )
    )
    assert res.confidence == 0.0
    assert res.description == "Real_Bill"
    assert res.target_folder == "_Review_Needed"


def test_container_confidence_does_not_escape():
    res = _classify_text(
        json.dumps(
            {
                "document_date": "260901",
                "description": "Real Bill",
                "target_folder": "Utilities",
                "confidence": {"nested": 0.9},
            }
        )
    )
    assert res.confidence == 0.0
    assert res.target_folder == "_Review_Needed"


def test_nan_confidence_routed_to_review():
    # json.loads accepts a non-standard NaN literal; it must not bypass the gate.
    res = _classify_text(
        '{"document_date":"260901","description":"Doc",'
        '"target_folder":"Utilities","confidence":NaN}'
    )
    assert res.confidence == 0.0
    assert res.target_folder == "_Review_Needed"


def test_classify_document_with_usage_metadata_and_reasoning(minimal_pdf: Path, caplog):
    caplog.set_level("INFO")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "document_date": "260906",
            "description": "Council Rates Notice",
            "target_folder": "Finances/Rates",
            "confidence": 0.96,
            "orientation_correction": 0,
            "document_type": "Invoice",
            "summary": "Annual council rates notice.",
            "folder_reasoning": "Council rates notice matches municipal finances.",
        }
    )
    usage = MagicMock()
    usage.prompt_token_count = 1200
    usage.candidates_token_count = 80
    mock_response.usage_metadata = usage

    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(
        api_key="AIzaSyDummyKey123", model="gemini-3.1-flash-lite"
    )
    classifier._client = mock_client

    taxonomy = ["Finances/Rates", "Utilities/Electricity"]
    res = classifier.classify_document(minimal_pdf, taxonomy=taxonomy)

    assert res.target_folder == "Finances/Rates"
    assert res.folder_reasoning == "Council rates notice matches municipal finances."
    assert (
        "Matched discovered taxonomy folder 'Finances/Rates'" in res.routing_rationale
    )
    assert res.prompt_tokens == 1200
    assert res.candidates_tokens == 80
    assert res.estimated_cost_usd > 0.0

    log_text = caplog.text
    assert "Classified 'minimal.pdf'" in log_text
    assert "Folder reason: Council rates notice matches municipal finances." in log_text
    assert "Tokens: 1,200 in / 80 out" in log_text
    assert "Cost: $" in log_text


def test_routing_rationale_variations():
    # 1. Blank scan
    blank_res = _classify_text(
        json.dumps(
            {
                "document_date": "260901",
                "description": "Blank Page",
                "target_folder": "Utilities",
                "confidence": 0.95,
                "document_type": "Blank",
            }
        ),
        taxonomy=["Utilities"],
    )
    assert blank_res.target_folder == "_Review_Needed/Blank_Scans"
    assert "Blank scan detected" in blank_res.routing_rationale

    # 2. Low confidence
    low_conf_res = _classify_text(
        json.dumps(
            {
                "document_date": "260901",
                "description": "Doc",
                "target_folder": "Utilities",
                "confidence": 0.50,
            }
        ),
        taxonomy=["Utilities"],
    )
    assert low_conf_res.target_folder == "_Review_Needed"
    assert "below 0.70 threshold" in low_conf_res.routing_rationale

    # 3. Unsafe folder
    unsafe_res = _classify_text(
        json.dumps(
            {
                "document_date": "260901",
                "description": "Doc",
                "target_folder": "../Escape",
                "confidence": 0.95,
            }
        ),
        taxonomy=["Utilities"],
    )
    assert unsafe_res.target_folder == "_Review_Needed"
    assert "Unsafe target folder" in unsafe_res.routing_rationale


def test_classify_document_config_thinking_level_minimal(minimal_pdf: Path):
    """Verify Gemini 3.x GenerateContentConfig uses thinking_level='minimal' and omits thinking_budget."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "document_date": "260901",
            "description": "Electricity_Bill",
            "target_folder": "Utilities",
            "confidence": 0.95,
        }
    )
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(
        api_key="AIzaSyDummyKey123", model="gemini-3.5-flash-lite"
    )
    classifier._client = mock_client

    classifier.classify_document(minimal_pdf, taxonomy=["Utilities"])

    mock_client.models.generate_content.assert_called_once()
    _, kwargs = mock_client.models.generate_content.call_args
    config = kwargs["config"]
    assert config is not None
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level in ("minimal", "MINIMAL")
    assert config.thinking_config.thinking_budget is None


def test_classify_document_config_disables_automatic_function_calling(
    minimal_pdf: Path,
):
    """Verify Gemini GenerateContentConfig explicitly disables automatic function calling (AFC)."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "document_date": "260901",
            "description": "Electricity_Bill",
            "target_folder": "Utilities",
            "confidence": 0.95,
        }
    )
    mock_client.models.generate_content.return_value = mock_response

    classifier = GeminiClassifier(api_key="AIzaSyDummyKey123")
    classifier._client = mock_client

    classifier.classify_document(minimal_pdf, taxonomy=["Utilities"])

    mock_client.models.generate_content.assert_called_once()
    _, kwargs = mock_client.models.generate_content.call_args
    config = kwargs["config"]
    assert config is not None
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True
