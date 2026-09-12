"""Multimodal document classification and OCR client powered by Google Gemini."""

import json
import logging
import math
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError

from scansort.classification.models import (
    DocumentClassification,
    GeminiClassificationResponse,
    sanitize_date,
    sanitize_description,
)
from scansort.classification.taxonomy import format_taxonomy_for_prompt
from scansort.core.constants import (
    BLANK_SCANS_DIR,
    DEFAULT_GEMINI_MODEL,
    MAX_DESCRIPTION_LENGTH,
    MIN_CONFIDENCE_THRESHOLD,
    REVIEW_NEEDED_DIR,
)
from scansort.core.fs import normalize_relative_folder, relative_folder_is_safe
from scansort.logging.cost import calculate_gemini_cost
from scansort.logging.gemini_logger import log_classification_event
from scansort.platform.secrets import get_api_key, redact_secrets_from_text

logger = logging.getLogger(__name__)


def _extract_usage(response) -> tuple[int, int]:
    """Return ``(prompt_tokens, candidates_tokens)`` from a Gemini response."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    prompt = getattr(usage, "prompt_token_count", 0)
    candidates = getattr(usage, "candidates_token_count", 0)
    prompt_tokens = prompt if isinstance(prompt, int) else 0
    candidates_tokens = candidates if isinstance(candidates, int) else 0
    return prompt_tokens, candidates_tokens


class GeminiClassifier:
    """Client for classifying documents using Google Gemini."""

    def __init__(
        self, api_key: str | None = None, model: str = DEFAULT_GEMINI_MODEL
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client: genai.Client | None = None
        self._cached_key: str | None = api_key

    def _get_client(self) -> genai.Client:
        active_key = self.api_key or get_api_key()
        if not active_key:
            raise ValueError(
                "Gemini API key is not configured. Please set your key via the "
                "Settings wizard, scansort config --set-key, or GEMINI_API_KEY environment variable."
            )

        if self._client is not None and self._cached_key == active_key:
            return self._client

        self._cached_key = active_key
        self._client = genai.Client(api_key=active_key)
        return self._client

    def _build_system_instruction(
        self, taxonomy: list[str], hints: dict[str, list[str]] | None = None
    ) -> str:
        """Build the structured system prompt including discovered taxonomy."""
        taxonomy_block = format_taxonomy_for_prompt(taxonomy, hints)
        return (
            "You are ScanSort, an expert document sorting assistant for personal and business records.\n"
            "Analyze the attached scanned document and classify it strictly according to the user's pre-existing folder hierarchy.\n\n"
            f"{taxonomy_block}\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Target Folder: Choose the DEEPEST specific matching leaf folder from the list above.\n"
            f"   - If no pre-existing folder fits or confidence is below {MIN_CONFIDENCE_THRESHOLD:.2f}, choose '{REVIEW_NEEDED_DIR}'.\n"
            "   - DO NOT invent new folder names outside the provided list.\n"
            "   - Event & Trip Folders: Destination folders often represent specific events, trips, tournaments, conferences, vacations, or projects (e.g. '2026 Sydney Marathon', 'Tokyo Trip 2025', 'DEFCON 34'). These folders are intended to collect ALL related logistics and expenses: lodging/hotel invoices, flights/trains, car rentals, registration fees, tickets, and travel receipts.\n"
            f"   - Date & Context Cross-Referencing: When evaluating event folders, cross-reference the document's dates (issuance date, hotel stay check-in/out, flight dates) and location/city against the year, date range, or known schedule and location of the event. If the dates and location align with the event timeframe, assign the document to that event folder with high confidence (>= {MIN_CONFIDENCE_THRESHOLD:.2f}) instead of defaulting to '_Review_Needed'.\n"
            "2. Document Date: Identify the official issuance / billing date. Output in YYMMDD format.\n"
            "   - If no explicit date exists, output today's date in YYMMDD.\n"
            "3. Description: Write a clear, concise title in English using Title_Case_With_Underscores.\n"
            f"   - Strip punctuation, limit to {MAX_DESCRIPTION_LENGTH} characters (e.g. 'Origin_Energy_Electricity_Bill').\n"
            "   - If the document is foreign, translate the description to English.\n"
            "4. Orientation: Check if the text is upside-down or sideways. Output orientation_correction in clockwise degrees (0, 90, 180, or 270).\n"
            "5. Blank Detection: If the document is an empty white sheet or blank scan, set document_type to 'Blank'.\n"
            "6. Summary: Provide a crisp 1-sentence summary of the document contents.\n"
            "7. Folder Reasoning: Briefly explain why the chosen target folder is the best match for this document, explicitly citing any date or event cross-referencing used (e.g. 'Good Life Suites hotel invoice dates match 2026 Sydney Marathon event timeframe')."
        )

    def _parse_and_route_response(
        self, raw_text: str, taxonomy: list[str]
    ) -> DocumentClassification:
        """Parse raw JSON output from Gemini and route to a valid taxonomy folder."""
        try:
            data = json.loads(raw_text)
            if not isinstance(data, dict):
                data = {}
        except json.JSONDecodeError:
            data = {}

        doc_date = sanitize_date(data.get("document_date"))
        desc = sanitize_description(data.get("description"))
        target = str(data.get("target_folder", "") or "").strip()
        try:
            conf = float(data.get("confidence", 0.0) or 0.0)
            conf = conf if math.isfinite(conf) else 0.0
        except TypeError, ValueError:
            # Malformed confidence must route to _Review_Needed, not abort or
            # bypass the threshold (NaN/Infinity comparisons are unreliable).
            conf = 0.0
        doc_type = str(data.get("document_type", "Other") or "Other")

        try:
            orient_val = int(data.get("orientation_correction", 0))
            orient = orient_val if orient_val in {0, 90, 180, 270} else 0
        except ValueError, TypeError:
            orient = 0

        summary = str(data.get("summary", "") or "").strip()
        folder_reasoning = str(data.get("folder_reasoning", "") or "").strip()

        routing_rationale = ""
        clean_target = target.strip()
        suggested_folder = ""
        if not relative_folder_is_safe(clean_target):
            target = REVIEW_NEEDED_DIR
            routing_rationale = f"Unsafe target folder '{clean_target}' rejected -> routed to {REVIEW_NEEDED_DIR}."
        else:
            target = normalize_relative_folder(clean_target)
            suggested_folder = target
            if doc_type.lower() == "blank":
                target = f"{REVIEW_NEEDED_DIR}/{BLANK_SCANS_DIR}"
                routing_rationale = (
                    f"Blank scan detected -> routed to "
                    f"{REVIEW_NEEDED_DIR}/{BLANK_SCANS_DIR}."
                )
            elif conf < MIN_CONFIDENCE_THRESHOLD:
                routing_rationale = (
                    f"Confidence {conf:.2f} below {MIN_CONFIDENCE_THRESHOLD:.2f} threshold "
                    f"(suggested '{target}') -> routed to {REVIEW_NEEDED_DIR}."
                )
                target = REVIEW_NEEDED_DIR
            elif target not in taxonomy and target != REVIEW_NEEDED_DIR:
                routing_rationale = f"Suggested folder '{target}' not in discovered taxonomy -> routed to {REVIEW_NEEDED_DIR}."
                target = REVIEW_NEEDED_DIR
            else:
                routing_rationale = f"Matched discovered taxonomy folder '{target}' with {conf * 100:.0f}% confidence."

        return DocumentClassification(
            document_date=doc_date,
            description=desc,
            target_folder=target,
            suggested_folder=suggested_folder,
            confidence=conf,
            orientation_correction=orient,
            document_type=doc_type,
            summary=summary,
            folder_reasoning=folder_reasoning,
            routing_rationale=routing_rationale,
        )

    def _create_fallback_classification(self, error_msg: str) -> DocumentClassification:
        """Create a safe fallback classification pointing to _Review_Needed."""
        return DocumentClassification(
            document_date=sanitize_date(None),
            description="Failed_Scan_Classification",
            target_folder=REVIEW_NEEDED_DIR,
            confidence=0.0,
            orientation_correction=0,
            document_type="Other",
            summary=f"Automated classification encountered error: {error_msg[:100]}",
            folder_reasoning="Classification failed due to error",
            routing_rationale=f"Classification encountered error ({error_msg[:60]}) -> routed to {REVIEW_NEEDED_DIR}.",
            prompt_tokens=0,
            candidates_tokens=0,
            estimated_cost_usd=None,
        )

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
        client = self._get_client()
        system_instruction = self._build_system_instruction(taxonomy, hints)
        start_time = time.monotonic()

        try:
            pdf_bytes = pdf_path.read_bytes()
            part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=GeminiClassificationResponse,
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            )

            response = client.models.generate_content(
                model=self.model,
                contents=[
                    part,
                    "Extract document metadata and determine the deepest destination folder.",
                ],
                config=config,
            )
            latency = time.monotonic() - start_time

            prompt_tokens, candidates_tokens = _extract_usage(response)

            cost = calculate_gemini_cost(self.model, prompt_tokens, candidates_tokens)

            classification = self._parse_and_route_response(
                response.text or "{}", taxonomy
            )
            classification.prompt_tokens = prompt_tokens
            classification.candidates_tokens = candidates_tokens
            classification.estimated_cost_usd = cost

            log_classification_event(
                file_name=pdf_path.name,
                model=self.model,
                latency_seconds=latency,
                classification=classification,
                routing_rationale=classification.routing_rationale,
                prompt_tokens=prompt_tokens,
                candidates_tokens=candidates_tokens,
                raw_response_text=response.text,
            )

            return classification

        except (
            APIError,
            httpx.HTTPError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            redacted_err = redact_secrets_from_text(
                str(e), self._cached_key or self.api_key
            )
            logger.warning(
                "Gemini classification failed: %s. Routing to _Review_Needed.",
                redacted_err,
            )
            return self._create_fallback_classification(redacted_err)
