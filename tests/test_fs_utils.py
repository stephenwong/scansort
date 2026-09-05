"""Unit tests for scansort.fs_utils module."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from scansort.fs_utils import atomic_write, relative_folder_is_safe


def test_atomic_write_text_creates_file(tmp_path):
    target = tmp_path / "nested" / "out.json"
    atomic_write(target, '{"a": 1}')
    assert target.read_text(encoding="utf-8") == '{"a": 1}'


def test_atomic_write_bytes_creates_file(tmp_path):
    target = tmp_path / "data.bin"
    atomic_write(target, b"\x00\x01\xff")
    assert target.read_bytes() == b"\x00\x01\xff"


def test_atomic_write_overwrites_existing_file(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")
    atomic_write(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_cleans_up_temp_file_on_replace_error(tmp_path):
    target = tmp_path / "file.txt"
    with (
        patch.object(type(target), "replace", side_effect=OSError("Read-only fs")),
        pytest.raises(OSError),
    ):
        atomic_write(target, "data")
    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_error_propagates_and_no_temp_leak(tmp_path):
    target = tmp_path / "file.txt"
    with (
        patch("tempfile.NamedTemporaryFile", side_effect=OSError("Disk full")),
        pytest.raises(OSError),
    ):
        atomic_write(target, "data")
    assert list(tmp_path.glob("*.tmp")) == []


def test_relative_folder_is_safe_accepts_plain_paths():
    assert relative_folder_is_safe("Finances")
    assert relative_folder_is_safe("Finances/Banking/ANZ")
    assert relative_folder_is_safe("Finances\\Banking")
    assert relative_folder_is_safe(".")


def test_relative_folder_is_safe_rejects_absolutes_and_traversal():
    assert not relative_folder_is_safe("/absolute/path")
    assert not relative_folder_is_safe("\\absolute\\path")
    assert not relative_folder_is_safe("C:/Drive")
    assert not relative_folder_is_safe("C:\\Drive")
    assert not relative_folder_is_safe("../Escaped")
    assert not relative_folder_is_safe("Finances/../../Escaped")
    assert not relative_folder_is_safe("")
    assert not relative_folder_is_safe("   ")


def test_normalize_relative_folder():
    from scansort.fs_utils import normalize_relative_folder

    assert normalize_relative_folder("Finances/Banking") == "Finances/Banking"
    assert normalize_relative_folder("Finances\\Banking\\ANZ") == "Finances/Banking/ANZ"
    assert normalize_relative_folder("/Finances/Banking/") == "Finances/Banking"
    assert normalize_relative_folder("\\Finances\\Banking\\") == "Finances/Banking"
    assert normalize_relative_folder("  Finances /  Taxes  ") == "Finances/Taxes"
    assert normalize_relative_folder(".") == ""
    assert normalize_relative_folder("") == ""
    assert normalize_relative_folder("   ") == ""


def test_atomic_write_callable_and_fsync(tmp_path):
    target = tmp_path / "streamed.txt"

    def write_stream(f):
        f.write(b"streamed content")

    atomic_write(target, write_stream)
    assert target.read_text(encoding="utf-8") == "streamed content"


def test_resolve_collision(tmp_path):
    from scansort.fs_utils import resolve_collision

    # Initial file does not exist
    path1 = resolve_collision(tmp_path, "doc.pdf")
    assert path1 == tmp_path / "doc.pdf"

    # Create it
    path1.write_bytes(b"1")
    path2 = resolve_collision(tmp_path, "doc.pdf")
    assert path2 == tmp_path / "doc_1.pdf"

    # Create collision 1
    path2.write_bytes(b"2")
    path3 = resolve_collision(tmp_path, "doc.pdf")
    assert path3 == tmp_path / "doc_2.pdf"


def test_interprocess_file_lock_serializes_concurrent_movers(tmp_path):
    from scansort.fs_utils import interprocess_file_lock, resolve_collision

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    lock_path = tmp_path / "operations.lock"
    errors: list[BaseException] = []

    def mover(tag: bytes) -> None:
        try:
            src = tmp_path / f"src_{tag.decode()}"
            src.write_bytes(tag * 10)
            with interprocess_file_lock(lock_path):
                chosen = resolve_collision(dest_dir, "260901_Doc.pdf")
                import shutil

                shutil.move(str(src), str(chosen))
        except OSError as exc:  # pragma: no cover - failure reporting only
            errors.append(exc)

    threads = [threading.Thread(target=mover, args=(t,)) for t in (b"A", b"B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    filed = sorted(p.name for p in dest_dir.iterdir())
    assert filed == ["260901_Doc.pdf", "260901_Doc_1.pdf"]
    assert (dest_dir / "260901_Doc.pdf").read_bytes() != (
        dest_dir / "260901_Doc_1.pdf"
    ).read_bytes()


def test_interprocess_file_lock_windows_branch(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    mock_msvcrt = MagicMock()
    with patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
        from scansort.fs_utils import interprocess_file_lock

        with interprocess_file_lock(tmp_path / "operations.lock"):
            pass
    assert mock_msvcrt.locking.call_count == 2


def test_interprocess_file_lock_posix_branch(tmp_path):
    from scansort.fs_utils import interprocess_file_lock

    lock_path = tmp_path / "operations.lock"
    with interprocess_file_lock(lock_path):
        assert lock_path.exists()
    # Lock must be released: a second acquisition succeeds immediately.
    with interprocess_file_lock(lock_path):
        pass
