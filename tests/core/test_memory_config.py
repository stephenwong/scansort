"""Config + constants tests for the RAG self-improving classifier memory."""

from pathlib import Path

from scansort.core import constants
from scansort.core.config import AppConfig, load_config, save_config


def test_rag_memory_enabled_defaults_true():
    assert AppConfig().rag_memory_enabled is True


def test_rag_memory_enabled_roundtrip(tmp_path: Path):
    path = tmp_path / "config.json"
    save_config(AppConfig(rag_memory_enabled=False), path)
    assert load_config(path).rag_memory_enabled is False


def test_memory_constants_sane():
    assert constants.MAX_MEMORY_EXAMPLES == 3
    assert constants.MEMORY_VECTOR_DIM == 512
    assert constants.MEMORY_EXAMPLE_SUMMARY_CHARS == 80
    assert 0.0 < constants.MEMORY_MIN_SIMILARITY < 1.0
    assert (
        constants.MIN_CONFIDENCE_THRESHOLD <= constants.MAX_CONFIDENCE_THRESHOLD <= 1.0
    )
    assert constants.CALIBRATION_STEP > 0.0
    assert constants.MEMORY_BACKFILL_LIMIT > 0
