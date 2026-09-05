"""Domain models and text-sanitization rules for document classification."""

import calendar
import re
import unicodedata

from pydantic import BaseModel, Field, field_validator

from scansort.constants import DEFAULT_DESCRIPTION, MAX_DESCRIPTION_LENGTH
from scansort.timeutil import sydney_now

_INVALID_CHARS_REGEX: re.Pattern = re.compile(
    r'[\x00-\x1f\x7f<>:"/\\|?*,\.;!\'#\$%&\(\)\[\]\{\}=+]'
)


def _strip_format_characters(value: str) -> str:
    """Remove Unicode format characters (BOM, zero-width, bidi) from a string."""
    return "".join(ch for ch in value if unicodedata.category(ch) != "Cf")


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
    desc_str = unicodedata.normalize("NFKC", str(desc))
    if not desc_str or not desc_str.strip():
        return DEFAULT_DESCRIPTION

    # Replace invalid Windows chars and punctuation with spaces
    cleaned = _INVALID_CHARS_REGEX.sub(" ", desc_str)
    # Replace dashes and underscores with spaces to split words cleanly
    cleaned = cleaned.replace("-", " ").replace("_", " ")
    cleaned = _strip_format_characters(cleaned)

    words = [w.capitalize() for w in cleaned.split() if w]
    if not words:
        return DEFAULT_DESCRIPTION

    joined = "_".join(words)
    if len(joined) > max_length:
        # Prefer whole-word truncation: drop trailing words until the title fits.
        while len(words) > 1 and len("_".join(words)) > max_length:
            words.pop()
        joined = "_".join(words)
        if len(joined) > max_length:
            # A single over-long word cannot be split; cut at the cap.
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
        if (
            len(clean) == 6
            and clean.isdigit()
            and _is_valid_calendar_date(
                int(clean[0:2]), int(clean[2:4]), int(clean[4:6])
            )
        ):
            return clean
        if (
            len(clean) == 8
            and clean.isdigit()
            and _is_valid_calendar_date(
                int(clean[0:4]), int(clean[4:6]), int(clean[6:8])
            )
        ):
            # YYYYMMDD -> YYMMDD
            return clean[2:]

    return sydney_now().strftime("%y%m%d")


def _is_valid_calendar_date(year: int, month: int, day: int) -> bool:
    """Return True for a real calendar date (month 1-12, day within month)."""
    if not (1 <= month <= 12) or day < 1:
        return False
    # Two-digit years map to 2000-2099 (matching strptime %y for 00-68; the
    # leap-day difference for 69-99 is bounded to years not divisible by 4).
    full_year = 2000 + year if year < 100 else year
    return day <= calendar.monthrange(full_year, month)[1]


class DocumentClassification(BaseModel):
    """Structured classification and metadata returned by the document classifier."""

    document_date: str = Field(pattern=r"^\d{6}$", description="Date in YYMMDD format")
    description: str = Field(
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Concise description in Title_Case_With_Underscores (English)",
    )
    target_folder: str = Field(
        description="Matching relative folder from taxonomy, or _Review_Needed"
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0"
    )
    orientation_correction: int = Field(
        default=0, description="Degrees to rotate clockwise (0, 90, 180, 270)"
    )
    document_type: str = Field(
        default="Other",
        description="Type: Invoice, Statement, Receipt, Letter, Medical, Blank, Other",
    )
    summary: str = Field(default="", description="1-sentence summary of the document")

    @field_validator("description")
    @classmethod
    def validate_description_clean(cls, v: str) -> str:
        """Enforce the filename-safe contract at the type boundary."""
        if _INVALID_CHARS_REGEX.search(v) or _strip_format_characters(v) != v:
            raise ValueError(
                "description must not contain illegal filename characters "
                "or Unicode format characters"
            )
        return v

    @field_validator("document_date")
    @classmethod
    def validate_document_date(cls, v: str) -> str:
        if not _is_valid_calendar_date(int(v[0:2]), int(v[2:4]), int(v[4:6])):
            raise ValueError("document_date must be a real calendar date in YYMMDD")
        return v

    @property
    def target_filename(self) -> str:
        """Standardized YYMMDD_<Description>.pdf filename."""
        return f"{self.document_date}_{self.description}.pdf"
