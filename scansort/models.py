"""Domain models and text-sanitization rules for document classification."""

import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from scansort.constants import DEFAULT_DESCRIPTION, MAX_DESCRIPTION_LENGTH

_INVALID_CHARS_REGEX: re.Pattern = re.compile(
    r'[\x00-\x1f\x7f<>:"/\\|?*,\.;!\'#\$%&\(\)\[\]\{\}=+]'
)


def sanitize_description(desc: object, max_length: int = MAX_DESCRIPTION_LENGTH) -> str:
    """Sanitize and format a title into clean Title_Case_With_Underscores for Windows filenames.

    Args:
        desc: Raw description value or string.
        max_length: Maximum character length cap.

    Returns:
        Clean Title_Case_With_Underscores string.
    """
    if desc is None:
        return DEFAULT_DESCRIPTION
    desc_str = str(desc)
    if not desc_str or not desc_str.strip():
        return DEFAULT_DESCRIPTION

    # Replace invalid Windows chars and punctuation with spaces
    cleaned = _INVALID_CHARS_REGEX.sub(" ", desc_str)
    # Replace dashes and underscores with spaces to split words cleanly
    cleaned = cleaned.replace("-", " ").replace("_", " ")

    words = [w.capitalize() for w in cleaned.split() if w]
    if not words:
        return DEFAULT_DESCRIPTION

    joined = "_".join(words)
    if len(joined) > max_length:
        joined = joined[:max_length].rstrip("_")

    return joined or DEFAULT_DESCRIPTION


def sanitize_date(date_str: object) -> str:
    """Validate or convert a date string into YYMMDD format, falling back to today's date.

    Args:
        date_str: Input date value or string (e.g. '260901', '2026-09-01', 20260901).

    Returns:
        6-digit YYMMDD date string.
    """
    if date_str is not None:
        clean = str(date_str).strip().replace("-", "").replace("/", "")
        if len(clean) == 6 and clean.isdigit():
            return clean
        if len(clean) == 8 and clean.isdigit():
            # YYYYMMDD -> YYMMDD
            return clean[2:]

    return datetime.now(UTC).strftime("%y%m%d")


class DocumentClassification(BaseModel):
    """Structured classification and metadata returned by the document classifier."""

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

    @property
    def target_filename(self) -> str:
        """Standardized YYMMDD_<Description>.pdf filename."""
        return f"{self.document_date}_{self.description}.pdf"
