"""Multimodal document classification and OCR client powered by Google Gemini 2.5 Flash."""

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from scansort.folder_mapper import format_taxonomy_for_prompt
from scansort.secrets import get_api_key, redact_secrets_from_text

logger = logging.getLogger(__name__)

_INVALID_CHARS_REGEX: re.Pattern = re.compile(r'[<>:"/\\|?*,\.;!\'#\$%&\(\)\[\]\{\}=+]')


def sanitize_description(desc: str, max_length: int = 60) -> str:
    """Sanitize and format a title into clean Title_Case_With_Underscores for Windows filenames.

    Args:
        desc: Raw description string.
        max_length: Maximum character length cap.

    Returns:
        Clean Title_Case_With_Underscores string.
    """
    if not desc or not desc.strip():
        return "Scanned_Document"

    # Replace invalid Windows chars and punctuation with spaces
    cleaned = _INVALID_CHARS_REGEX.sub(" ", desc)
    # Replace dashes and underscores with spaces to split words cleanly
    cleaned = cleaned.replace("-", " ").replace("_", " ")

    words = [w.capitalize() for w in cleaned.split() if w]
    if not words:
        return "Scanned_Document"

    joined = "_".join(words)
    if len(joined) > max_length:
        joined = joined[:max_length].rstrip("_")

    return joined or "Scanned_Document"


def sanitize_date(date_str: str) -> str:
    """Validate or convert a date string into YYMMDD format, falling back to today's date.

    Args:
        date_str: Input date string (e.g. '260901', '2026-09-01').

    Returns:
        6-digit YYMMDD date string.
    """
    today_yymmdd = datetime.now(UTC).strftime("%y%m%d")
    if not date_str:
        return today_yymmdd

    clean = date_str.strip().replace("-", "").replace("/", "")
    if len(clean) == 6 and clean.isdigit():
        return clean
    if len(clean) == 8 and clean.isdigit():
        # YYYYMMDD -> YYMMDD
        return clean[2:]

    return today_yymmdd


class DocumentClassification(BaseModel):
    """Structured classification and metadata returned by Gemini."""

    document_date: str = Field(description="Date in YYMMDD format")
    description: str = Field(
        description="Concise description in Title_Case_With_Underscores (English)"
    )
    target_folder: str = Field(
        description="Matching relative folder from taxonomy, or _Review_Needed"
    )
    confidence: float = Field(
        default=0.0, description="Confidence score from 0.0 to 1.0"
    )
    orientation_correction: int = Field(
        default=0, description="Degrees to rotate clockwise (0, 90, 180, 270)"
    )
    document_type: str = Field(
        default="Other",
        description="Type: Invoice, Statement, Receipt, Letter, Medical, Blank, Other",
    )
    summary: str = Field(default="", description="1-sentence summary of the document")


class GeminiClassifier:
    """Client for classifying documents using Google Gemini 2.5 Flash."""

    def __init__(
        self, api_key: str | None = None, model: str = "gemini-2.5-flash"
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is not None:
            return self._client

        active_key = self.api_key or get_api_key()
        if not active_key:
            raise ValueError(
                "Gemini API key is not configured. Please set your key via the "
                "Settings wizard, scansort config --set-key, or GEMINI_API_KEY environment variable."
            )

        self._client = genai.Client(api_key=active_key)
        return self._client

    def classify_document(
        self,
        pdf_path: Path,
        taxonomy: list[str],
        hints: dict[str, list[str]] | None = None,
    ) -> DocumentClassification:
        """Analyze a PDF document and return structured classification and metadata.

        Args:
            pdf_path: Path to the PDF document.
            taxonomy: Discovered folder taxonomy paths.
            hints: Optional dictionary mapping folder paths to keyword hints.

        Returns:
            Validated DocumentClassification instance.
        """
        taxonomy_block = format_taxonomy_for_prompt(taxonomy, hints)

        system_instruction = (
            "You are ScanSort, an expert document sorting assistant for personal and business records.\n"
            "Analyze the attached scanned document and classify it strictly according to the user's pre-existing folder hierarchy.\n\n"
            f"{taxonomy_block}\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Target Folder: Choose the DEEPEST specific matching leaf folder from the list above.\n"
            "   - If no pre-existing folder fits or confidence is below 0.70, choose '_Review_Needed'.\n"
            "   - DO NOT invent new folder names outside the provided list.\n"
            "2. Document Date: Identify the official issuance / billing date. Output in YYMMDD format.\n"
            "   - If no explicit date exists, output today's date in YYMMDD.\n"
            "3. Description: Write a clear, concise title in English using Title_Case_With_Underscores.\n"
            "   - Strip punctuation, limit to 60 characters (e.g. 'Origin_Energy_Electricity_Bill').\n"
            "   - If the document is foreign, translate the description to English.\n"
            "4. Orientation: Check if the text is upside-down or sideways. Output orientation_correction in clockwise degrees (0, 90, 180, or 270).\n"
            "5. Blank Detection: If the document is an empty white sheet or blank scan, set document_type to 'Blank'.\n"
            "6. Summary: Provide a crisp 1-sentence summary of the document contents."
        )

        try:
            client = self._get_client()
            pdf_bytes = pdf_path.read_bytes()

            part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=DocumentClassification,
                temperature=0.1,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            )

            response = client.models.generate_content(
                model=self.model,
                contents=[
                    part,
                    "Extract document metadata and determine the deepest destination folder.",
                ],
                config=config,
            )

            raw_text = response.text or "{}"
            data = json.loads(raw_text)

            # Sanitize description and date
            desc = sanitize_description(data.get("description", "Document"))
            doc_date = sanitize_date(data.get("document_date", ""))
            doc_type = data.get("document_type", "Other")
            target = data.get("target_folder", "_Review_Needed")
            conf = float(data.get("confidence", 0.8))
            orient = int(data.get("orientation_correction", 0)) % 360
            summary = str(data.get("summary", "")).strip()

            # Apply folder routing rules
            if doc_type.lower() == "blank":
                target = "_Review_Needed/Blank_Scans"
            elif target not in taxonomy and not target.startswith("_Review_Needed"):
                target = "_Review_Needed"

            return DocumentClassification(
                document_date=doc_date,
                description=desc,
                target_folder=target,
                confidence=conf,
                orientation_correction=orient,
                document_type=doc_type,
                summary=summary,
            )

        except ValueError:
            raise
        except (OSError, RuntimeError, TypeError, json.JSONDecodeError) as e:
            redacted_err = redact_secrets_from_text(str(e), self.api_key)
            logger.warning(
                "Gemini classification failed: %s. Routing to _Review_Needed.",
                redacted_err,
            )
            return DocumentClassification(
                document_date=datetime.now(UTC).strftime("%y%m%d"),
                description="Failed_Scan_Classification",
                target_folder="_Review_Needed",
                confidence=0.0,
                orientation_correction=0,
                document_type="Other",
                summary=f"Automated classification encountered error: {redacted_err[:100]}",
            )
