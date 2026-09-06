"""Structured logging for Google Gemini document classification events."""

import logging
from typing import TYPE_CHECKING

from scansort.logging.cost import format_token_cost_summary

if TYPE_CHECKING:
    from scansort.models import DocumentClassification

logger = logging.getLogger(__name__)


def log_classification_event(
    file_name: str,
    model: str,
    latency_seconds: float,
    classification: "DocumentClassification",
    routing_rationale: str | None = None,
    prompt_tokens: int = 0,
    candidates_tokens: int = 0,
    raw_response_text: str | None = None,
) -> None:
    """Emit comprehensive structured log messages for a completed Gemini classification.

    Logs high-signal classification details, folder reasoning, routing explanation,
    and token/cost accounting at INFO level, and raw response payload at DEBUG.

    Args:
        file_name: Name of the input file being classified.
        model: Model name string (e.g. 'gemini-3.1-flash-lite').
        latency_seconds: Execution duration of the Gemini API call in seconds.
        classification: The extracted DocumentClassification instance.
        routing_rationale: Explanation of the destination folder routing decision.
        prompt_tokens: Number of prompt/input tokens consumed.
        candidates_tokens: Number of output/completion tokens returned.
        raw_response_text: Unprocessed JSON/text string returned by Gemini.
    """
    logger.info(
        "Classified '%s' in %.2fs using %s -> target='%s' "
        "(conf=%.2f, type=%s, date=%s, title='%s', orient=%d°)",
        file_name,
        latency_seconds,
        model,
        classification.target_folder,
        classification.confidence,
        classification.document_type,
        classification.document_date,
        classification.description,
        classification.orientation_correction,
    )

    reason = getattr(classification, "folder_reasoning", None)
    if reason and str(reason).strip():
        logger.info("Folder reason: %s", str(reason).strip())

    if routing_rationale and routing_rationale.strip():
        logger.info("Routing decision: %s", routing_rationale.strip())

    if prompt_tokens > 0 or candidates_tokens > 0:
        logger.info(
            format_token_cost_summary(
                model=model,
                prompt_tokens=prompt_tokens,
                candidates_tokens=candidates_tokens,
            )
        )

    if raw_response_text:
        logger.debug("Raw Gemini response: %s", raw_response_text.strip())
