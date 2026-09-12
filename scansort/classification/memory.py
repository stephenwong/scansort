"""Local retrieval-augmented memory for the self-improving classifier.

Every ``SUCCESS`` / ``COLLISION_RENAMED`` / ``REVIEWED`` filing is embedded
with a deterministic stdlib hashed lexical vector (word tokens plus character
n-grams, ``blake2b`` bucketing, L2-normalized) and stored in
``app_dir/vectors/memory.sqlite3``. New scans retrieve the top neighbours as
few-shot prompt examples; ``undo`` removes the mis-filed vector.

Everything here is local-only (no network traffic, no API keys, no document
bytes leaving the machine) and best-effort: store failures degrade to empty
results and must never break filing.
"""

import hashlib
import io
import json
import logging
import math
import re
import sqlite3
import struct
import uuid
from collections import deque
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from scansort.core.constants import (
    CALIBRATION_STEP,
    DEFAULT_OCR_LANGUAGE,
    MAX_CONFIDENCE_THRESHOLD,
    MAX_MEMORY_EXAMPLES,
    MEMORY_BACKFILL_LIMIT,
    MEMORY_DB_FILENAME,
    MEMORY_DIRNAME,
    MEMORY_EXAMPLE_SUMMARY_CHARS,
    MEMORY_INDEX_LOCK_FILENAME,
    MEMORY_MIN_QUERY_CHARS,
    MEMORY_MIN_SIMILARITY,
    MEMORY_QUERY_MAX_CHARS,
    MEMORY_SEARCH_CANDIDATE_LIMIT,
    MEMORY_VECTOR_DIM,
    MEMORY_WRITE_TIMEOUT_S,
    MIN_CONFIDENCE_THRESHOLD,
    STATUS_COLLISION_RENAMED,
    STATUS_REVIEWED,
    STATUS_SUCCESS,
    STATUS_UNDONE,
)
from scansort.core.fs import normalize_relative_folder, relative_folder_is_safe
from scansort.document.ocr import OcrError, has_ocr_support, ocr_pdf_inplace

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_INDEXABLE_STATUSES = frozenset(
    {STATUS_SUCCESS, STATUS_COLLISION_RENAMED, STATUS_REVIEWED}
)

_EXAMPLES_DDL = """
CREATE TABLE IF NOT EXISTS examples (
    sha256 TEXT PRIMARY KEY,
    folder TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT '',
    vector BLOB NOT NULL,
    dim INTEGER NOT NULL
)
"""

_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

#: DDL bundle describing the vector-store schema (diagnostics and tests).
MEMORY_SCHEMA_HINT = _EXAMPLES_DDL.strip()

_BACKFILL_META_KEY = "backfilled_history_size"

_HINT_STOPWORDS = frozenset(
    {
        "with",
        "from",
        "that",
        "this",
        "these",
        "those",
        "have",
        "your",
        "their",
        "them",
        "they",
        "will",
        "would",
        "about",
        "into",
        "over",
        "under",
        "such",
        "then",
        "than",
        "also",
        "when",
        "what",
        "which",
        "there",
        "been",
    }
)

#: Boilerplate terms from failure/duplicate summaries that must never become hints.
_GENERIC_HINT_TERMS = frozenset(
    {
        "failed",
        "processing",
        "routed",
        "route",
        "review",
        "folder",
        "folders",
        "duplicate",
        "duplicates",
        "automated",
        "classification",
        "encountered",
        "error",
        "errors",
        "previous",
        "needed",
    }
)

_GENERIC_SUMMARY_PREFIXES = (
    "failed processing",
    "duplicate scan of",
    "automated classification",
)

_GENERIC_SUMMARY_LITERALS = frozenset({"scanned_document", "scanned document"})


def _is_boilerplate_summary(summary: str | None) -> bool:
    """Return True for failure/fallback summaries that carry no signal."""
    text = " ".join(str(summary or "").split()).lower()
    if not text:
        return False
    return text in _GENERIC_SUMMARY_LITERALS or text.startswith(
        _GENERIC_SUMMARY_PREFIXES
    )


@dataclass(frozen=True)
class MemoryExample:
    """A past filing retrieved as a few-shot classification example."""

    folder: str
    summary: str
    similarity: float
    sha256: str = ""


def _tokens(text: str) -> list[str]:
    """Return word tokens plus character 3-grams for longer words."""
    words = _TOKEN_RE.findall(text.lower())
    grams = [
        word[i : i + 3]
        for word in words
        if len(word) >= 5
        for i in range(len(word) - 2)
    ]
    return words + grams


def vectorize_text(text: str, dim: int = MEMORY_VECTOR_DIM) -> bytes:
    """Embed *text* as a deterministic L2-normalized float32 blob.

    Uses the hashing trick (``blake2b`` bucket + sign) so no vocabulary or
    model download is required. The empty string maps to the zero vector.
    """
    counts: dict[int, float] = {}
    for token in _tokens(text or ""):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest, "little") % dim
        sign = 1.0 if digest[0] & 1 else -1.0
        counts[bucket] = counts.get(bucket, 0.0) + sign
    values = [0.0] * dim
    for bucket, weight in counts.items():
        values[bucket] = weight
    norm = math.sqrt(sum(value * value for value in values))
    if norm > 0.0:
        values = [value / norm for value in values]
    return struct.pack(f"<{dim}f", *values)


def cosine_similarity(vec_a: bytes, vec_b: bytes) -> float:
    """Return the cosine similarity of two blobs from :func:`vectorize_text`."""
    if not vec_a or len(vec_a) != len(vec_b) or len(vec_a) % 4:
        return 0.0
    # Lengths are equal non-zero multiples of 4 here, so unpack cannot fail.
    values_a = struct.unpack(f"<{len(vec_a) // 4}f", bytes(vec_a))
    values_b = struct.unpack(f"<{len(vec_b) // 4}f", bytes(vec_b))
    dot = sum(a * b for a, b in zip(values_a, values_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in values_a))
    norm_b = math.sqrt(sum(b * b for b in values_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def memory_db_path_for(base_dir: Path | str) -> Path:
    """Return the vector-store path colocated with history under *base_dir*."""
    return Path(base_dir) / MEMORY_DIRNAME / MEMORY_DB_FILENAME


def memory_lock_path_for(base_dir: Path | str) -> Path:
    """Return the dedicated index-lock path colocated with history."""
    return Path(base_dir) / MEMORY_INDEX_LOCK_FILENAME


def _record_text(record: dict[str, Any]) -> str:
    """Return the indexed text schema: summary + type + folders."""
    parts = [
        str(record.get("summary") or ""),
        str(record.get("document_type") or ""),
        str(record.get("destination_folder") or ""),
        str(record.get("suggested_folder") or ""),
    ]
    return " ".join(part for part in parts if part.strip())


def _build_row(record: dict[str, Any]) -> tuple | None:
    """Return the ``examples`` row for *record*, or None when ineligible."""
    if not isinstance(record, dict):
        return None
    status = str(record.get("status") or "")
    if status not in _INDEXABLE_STATUSES:
        return None
    sha = str(record.get("sha256") or "").strip()
    folder = normalize_relative_folder(str(record.get("destination_folder") or ""))
    if not sha or sha == "UNKNOWN" or not folder:
        return None
    if not relative_folder_is_safe(folder):
        return None
    summary = str(record.get("summary") or "")
    if _is_boilerplate_summary(summary):
        # Failure/fallback boilerplate must never seed retrieval examples.
        return None
    doc_type = str(record.get("document_type") or "")
    timestamp = str(record.get("timestamp") or "")
    return (
        sha,
        folder,
        summary,
        doc_type,
        status,
        timestamp,
        vectorize_text(_record_text(record)),
        MEMORY_VECTOR_DIM,
    )


class MemoryStore:
    """SQLite-backed vector store for filing-history examples.

    Read paths (:meth:`search`, :meth:`count`, :meth:`remove` on a missing
    database) never create files. Write paths create the database on demand.
    All methods fail open and never raise.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def _init_schema(
        self, conn: sqlite3.Connection, busy_timeout_ms: int = 5000
    ) -> None:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)};")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(_EXAMPLES_DDL)
        conn.execute(_METADATA_DDL)

    def _remove_db_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)

    def _connect(self, timeout: float = 5.0) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        busy_timeout_ms = max(0, int(timeout * 1000))
        conn = sqlite3.connect(str(self.db_path), timeout=timeout)
        try:
            self._init_schema(conn, busy_timeout_ms)
        except sqlite3.OperationalError:
            # Transient lock/IO error (e.g. "database is locked"): never treat
            # it as corruption or destroy a live store. Fail open at the caller.
            conn.close()
            raise
        except sqlite3.DatabaseError:
            # Corrupt/unreadable file: start over rather than failing forever.
            conn.close()
            self._remove_db_files()
            conn = sqlite3.connect(str(self.db_path), timeout=timeout)
            self._init_schema(conn, busy_timeout_ms)
        return conn

    def index_record(self, record: dict[str, Any]) -> bool:
        """Upsert a filing-history record; False when ineligible or on error."""
        row = _build_row(record)
        if row is None:
            return False
        try:
            with (
                closing(self._connect(MEMORY_WRITE_TIMEOUT_S)) as conn,
                conn,
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO examples "
                    "(sha256, folder, summary, document_type, status,"
                    " timestamp, vector, dim) VALUES (?,?,?,?,?,?,?,?)",
                    row,
                )
            return True
        except (sqlite3.Error, OSError, ValueError) as e:
            logger.warning("RAG memory index failed: %s", e)
            return False

    def remove(self, sha256: str) -> bool:
        """Delete the vector for *sha256*; False when absent or on error."""
        sha = str(sha256 or "").strip()
        if not sha or not self.db_path.exists():
            return False
        try:
            with (
                closing(self._connect(MEMORY_WRITE_TIMEOUT_S)) as conn,
                conn,
            ):
                cursor = conn.execute("DELETE FROM examples WHERE sha256 = ?", (sha,))
                return cursor.rowcount > 0
        except (sqlite3.Error, OSError, ValueError) as e:
            logger.warning("RAG memory remove failed: %s", e)
            return False

    def count(self) -> int:
        """Return the number of indexed examples (0 when unavailable)."""
        if not self.db_path.exists():
            return 0
        try:
            with closing(self._connect()) as conn:
                (total,) = conn.execute("SELECT COUNT(*) FROM examples").fetchone()
                return int(total)
        except (sqlite3.Error, OSError, ValueError) as e:
            logger.warning("RAG memory count failed: %s", e)
            return 0

    def search(
        self,
        query_text: str,
        *,
        k: int = MAX_MEMORY_EXAMPLES,
        min_similarity: float = MEMORY_MIN_SIMILARITY,
        taxonomy: list[str] | None = None,
    ) -> list[MemoryExample]:
        """Return up to *k* neighbours of *query_text* above *min_similarity*.

        When *taxonomy* is supplied, examples whose folder is stale (renamed
        or deleted) or unsafe are dropped before prompt construction so they
        can never steer the model toward hallucinated folders.
        """
        query = str(query_text or "").strip()
        if not query or k <= 0 or not self.db_path.exists():
            return []
        allowed: set[str] | None = None
        if taxonomy is not None:
            allowed = {normalize_relative_folder(item).lower() for item in taxonomy}
        try:
            query_vector = vectorize_text(query)
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT sha256, folder, summary, vector FROM examples"
                    " ORDER BY rowid DESC LIMIT ?",
                    (MEMORY_SEARCH_CANDIDATE_LIMIT,),
                ).fetchall()
        except (sqlite3.Error, OSError, ValueError) as e:
            logger.warning("RAG memory search failed: %s", e)
            return []
        scored: list[MemoryExample] = []
        for sha, folder, summary, blob in rows:
            folder_str = str(folder or "")
            if allowed is not None and (
                not relative_folder_is_safe(folder_str)
                or normalize_relative_folder(folder_str).lower() not in allowed
            ):
                continue
            similarity = cosine_similarity(query_vector, bytes(blob or b""))
            if similarity < min_similarity:
                continue
            scored.append(
                MemoryExample(
                    folder=folder_str,
                    summary=str(summary or ""),
                    similarity=similarity,
                    sha256=str(sha or ""),
                )
            )
        scored.sort(key=lambda example: example.similarity, reverse=True)
        return scored[:k]

    def _get_meta(self, key: str) -> str | None:
        try:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT value FROM metadata WHERE key = ?", (key,)
                ).fetchone()
                return str(row[0]) if row else None
        except sqlite3.Error, OSError, ValueError:
            return None

    def backfill_from_history(
        self, jsonl_path: Path | str, *, limit: int = MEMORY_BACKFILL_LIMIT
    ) -> int:
        """Index eligible history rows once; returns the rows upserted.

        Idempotent via ``INSERT OR REPLACE`` plus a history-size watermark, so
        concurrent first-run callers cannot double-index. Only the most recent
        *limit* lines are processed to bound worker blocking.
        """
        try:
            size = Path(jsonl_path).stat().st_size
        except OSError:
            return 0
        if self._get_meta(_BACKFILL_META_KEY) == str(size):
            return 0
        if limit <= 0:
            return 0
        try:
            with open(jsonl_path, encoding="utf-8") as f:
                # Bounded tail: a huge history must not be materialized in memory.
                lines = deque(f, maxlen=limit)
        except (OSError, UnicodeError) as e:
            logger.warning("RAG memory backfill read failed: %s", e)
            return 0
        # Latest-status-wins: a later UNDONE row must suppress the earlier
        # SUCCESS/COLLISION_RENAMED/REVIEWED row for the same sha so an undone
        # mis-filing is never resurrected by a subsequent backfill.
        latest: dict[str, tuple] = {}
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            sha = str(record.get("sha256") or "").strip()
            if str(record.get("status") or "") == STATUS_UNDONE:
                latest.pop(sha, None)
                continue
            row = _build_row(record)
            if row is not None:
                latest[sha] = row
        rows = list(latest.values())
        try:
            with closing(self._connect()) as conn, conn:
                if rows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO examples "
                        "(sha256, folder, summary, document_type, status,"
                        " timestamp, vector, dim) VALUES (?,?,?,?,?,?,?,?)",
                        rows,
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    (_BACKFILL_META_KEY, str(size)),
                )
            return len(rows)
        except (sqlite3.Error, OSError, ValueError) as e:
            logger.warning("RAG memory backfill write failed: %s", e)
            return 0


def _extract_pdf_text(pdf_path: Path, max_chars: int) -> str:
    """Return whitespace-collapsed text from *pdf_path* ("" when unavailable)."""
    try:
        data = Path(pdf_path).read_bytes()
    except OSError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except PyPdfError, OSError, ValueError, TypeError, KeyError:
                parts.append("")
    except PyPdfError, OSError, ValueError, NotImplementedError, KeyError:
        return ""
    return " ".join(" ".join(parts).split())[:max_chars]


def _ocr_skim_text(pdf_path: Path, language: str, max_chars: int) -> str:
    """OCR *pdf_path* into a throwaway sibling copy and return its text."""
    tmp_copy = pdf_path.parent / f".queryskim_{uuid.uuid4().hex}.pdf"
    try:
        ocr_pdf_inplace(pdf_path, language=language, output_path=tmp_copy)
        return _extract_pdf_text(tmp_copy, max_chars)
    except OcrError, OSError, ValueError:
        return ""
    finally:
        tmp_copy.unlink(missing_ok=True)


def build_retrieval_query(
    pdf_path: Path | str,
    original_filename: str | Path | None = "",
    *,
    ocr_language: str = DEFAULT_OCR_LANGUAGE,
    allow_ocr_skim: bool = True,
    max_chars: int = MEMORY_QUERY_MAX_CHARS,
) -> str:
    """Build the retrieval query for a staged PDF.

    Prefers embedded text; when the PDF is image-only, runs a local OCR skim
    over a throwaway copy (never mutating the staging file); otherwise falls
    back to the original filename. The staging filename itself (a UUID name)
    is never included.
    """
    name_part = ""
    if original_filename:
        name_part = Path(original_filename).stem.strip()
    target = Path(pdf_path)
    text = _extract_pdf_text(target, max_chars)
    if len(text) < MEMORY_MIN_QUERY_CHARS and allow_ocr_skim and has_ocr_support():
        skimmed = _ocr_skim_text(target, ocr_language, max_chars)
        if len(skimmed) > len(text):
            text = skimmed
    query = " ".join(part for part in (name_part, text) if part).strip()
    return " ".join(query.split())[:max_chars]


def format_examples_for_prompt(examples: list[MemoryExample] | None) -> str:
    """Render retrieved neighbours as a bounded few-shot prompt block."""
    items = list(examples or [])[:MAX_MEMORY_EXAMPLES]
    lines = []
    for example in items:
        folder = " ".join(str(getattr(example, "folder", "") or "").split())
        if not folder:
            continue
        summary = " ".join(str(getattr(example, "summary", "") or "").split())
        summary = summary[:MEMORY_EXAMPLE_SUMMARY_CHARS]
        try:
            similarity = float(getattr(example, "similarity", 0.0))
        except TypeError, ValueError:
            similarity = 0.0
        lines.append(f"- Past similar: '{summary}' -> {folder} ({similarity:.2f})")
    if not lines:
        return ""
    return (
        "PAST SIMILAR FILINGS (your own history — strong signal, but choose"
        " only from AVAILABLE DESTINATION FOLDERS above):\n" + "\n".join(lines)
    )


def compute_folder_thresholds(
    jsonl_path: Path | str,
    *,
    base: float = MIN_CONFIDENCE_THRESHOLD,
    step: float = CALIBRATION_STEP,
    cap: float = MAX_CONFIDENCE_THRESHOLD,
) -> dict[str, float]:
    """Derive per-folder confidence thresholds from correction history.

    ``UNDONE`` penalizes the folder it was wrongly filed into;
    ``REVIEWED`` penalizes the mistaken ``suggested_folder`` (never the
    human-corrected destination). Legacy rows without a suggestion are
    ignored, never counted as corrections.
    """
    counts: dict[str, int] = {}
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError, UnicodeError:
        return {}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        status = str(record.get("status") or "")
        folder = ""
        if status == STATUS_UNDONE:
            folder = str(record.get("destination_folder") or "")
        elif status == STATUS_REVIEWED:
            suggested = str(record.get("suggested_folder") or "")
            destination = str(record.get("destination_folder") or "")
            if not suggested or not destination:
                continue
            if normalize_relative_folder(suggested).lower() == (
                normalize_relative_folder(destination).lower()
            ):
                continue
            folder = suggested
        else:
            continue
        key = normalize_relative_folder(folder)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return {name: min(cap, base + step * total) for name, total in counts.items()}


#: In-process cache of derived thresholds keyed by path -> (size, mtime_ns).
_THRESHOLDS_CACHE: dict[str, tuple[tuple[int, int], dict[str, float]]] = {}


def clear_folder_thresholds_cache() -> None:
    """Drop the derived-threshold cache (used by tests and config reloads)."""
    _THRESHOLDS_CACHE.clear()


def compute_folder_thresholds_cached(jsonl_path: Path | str) -> dict[str, float]:
    """Return :func:`compute_folder_thresholds` memoized on file identity.

    ``history.jsonl`` is append-only, so ``(size, mtime_ns)`` uniquely
    identifies its contents; unchanged history never re-parses on the hot path.
    """
    path = Path(jsonl_path)
    try:
        stat = path.stat()
    except OSError:
        return {}
    identity = (stat.st_size, stat.st_mtime_ns)
    key = str(path)
    cached = _THRESHOLDS_CACHE.get(key)
    if cached is not None and cached[0] == identity:
        return dict(cached[1])
    result = compute_folder_thresholds(path)
    _THRESHOLDS_CACHE[key] = (identity, dict(result))
    return result


def propose_hint_keywords(summary: str | None, *, max_keywords: int = 3) -> list[str]:
    """Propose (never persist) distinctive hint keywords for a summary.

    Failure-boilerplate summaries (``FAILED``/``DUPLICATE``/fallback) yield
    no proposal so junk can never steer future prompts.
    """
    text = " ".join(str(summary or "").split()).lower()
    if not text or _is_boilerplate_summary(text):
        return []
    keywords: list[str] = []
    for token in _TOKEN_RE.findall(text):
        if (
            len(token) < 4
            or token in _HINT_STOPWORDS
            or token in _GENERIC_HINT_TERMS
            or token in keywords
        ):
            continue
        keywords.append(token)
        if len(keywords) >= max_keywords:
            break
    return keywords
