"""Unit tests for scansort.document.ocr text-layer engine."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from scansort.document.converter import convert_to_pdf
from scansort.document.ocr import (
    OcrError,
    OcrUnavailableError,
    _escape_pdf_text,
    _parse_ocr_data,
    has_ocr_support,
    needs_ocr,
    ocr_pdf_inplace,
    resolve_tesseract_cmd,
)


def _make_image_only_pdf(tmp_path: Path, name: str = "scan.pdf") -> Path:
    """Create a PDF whose page content is a single raster image (no text)."""
    img_path = tmp_path / "source.png"
    Image.new("RGB", (200, 100), "white").save(img_path, format="PNG")
    return convert_to_pdf(img_path, output_path=tmp_path / name)


def _make_text_pdf(tmp_path: Path, name: str = "digital.pdf") -> Path:
    """Create a PDF with a real extractable text layer."""
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    resources = DictionaryObject()
    resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 20 100 Td "
        b"(Hello searchable digital world - this is a longer native text layer) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = tmp_path / name
    with open(out, "wb") as f:
        writer.write(f)
    return out


def _make_mixed_pdf(tmp_path: Path, name: str = "mixed.pdf") -> Path:
    """Create a PDF whose first page has text and second page is an image."""
    text_pdf = _make_text_pdf(tmp_path, "text_page.pdf")
    image_pdf = _make_image_only_pdf(tmp_path, "image_page.pdf")
    writer = PdfWriter()
    writer.append(PdfReader(str(text_pdf)))
    writer.append(PdfReader(str(image_pdf)))
    out = tmp_path / name
    with open(out, "wb") as f:
        writer.write(f)
    return out


def test_escape_pdf_text():
    assert _escape_pdf_text("a(b)c\\d") == "a\\(b\\)c\\\\d"
    # Non-latin-1 characters degrade to '?' rather than corrupting the stream.
    assert _escape_pdf_text("naïve☃") == "naïve?"


def test_parse_ocr_data_filters_blank_and_negative_confidence():
    data = {
        "text": ["", "Invoice", "42"],
        "conf": ["-1", "90", "80"],
        "left": [0, 10, 20],
        "top": [0, 5, 6],
        "width": [0, 30, 10],
        "height": [0, 12, 10],
    }
    words, confidence = _parse_ocr_data(data)
    assert words == [(10, 5, 30, 12, "Invoice"), (20, 6, 10, 10, "42")]
    assert confidence == pytest.approx(85.0)


def test_parse_ocr_data_all_blank_returns_none_confidence():
    data = {
        "text": [""],
        "conf": ["-1"],
        "left": [0],
        "top": [0],
        "width": [0],
        "height": [0],
    }
    words, confidence = _parse_ocr_data(data)
    assert words == []
    assert confidence is None


def test_needs_ocr_true_for_image_only_pdf(tmp_path: Path):
    assert needs_ocr(_make_image_only_pdf(tmp_path)) is True


def test_needs_ocr_false_for_digital_text_pdf(tmp_path: Path):
    assert needs_ocr(_make_text_pdf(tmp_path)) is False


def test_needs_ocr_true_for_mixed_text_and_image_pdf(tmp_path: Path):
    """A per-page predicate must not average an image page away against text."""
    assert needs_ocr(_make_mixed_pdf(tmp_path)) is True


def test_needs_ocr_raises_on_corrupt_pdf(tmp_path: Path):
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"NOT A PDF AT ALL")
    with pytest.raises(OcrError, match="unreadable"):
        needs_ocr(corrupt)


def test_needs_ocr_raises_on_encrypted_pdf(tmp_path: Path):
    enc = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    with open(enc, "wb") as f:
        writer.write(f)
    with pytest.raises(OcrError, match="password"):
        needs_ocr(enc)


@pytest.mark.parametrize(
    "handler_error",
    [NotImplementedError("unsupported filter"), KeyError("/Encrypt")],
)
def test_needs_ocr_wraps_unsupported_encryption_handler(
    tmp_path: Path, handler_error: Exception
):
    """pypdf's encryption handler raises outside PyPdfError/OSError/ValueError."""
    pdf = tmp_path / "unsupported.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with (
        patch("scansort.document.ocr.PdfReader", side_effect=handler_error),
        pytest.raises(OcrError, match="unreadable"),
    ):
        needs_ocr(pdf)


def test_resolve_tesseract_cmd_prefers_bundled(tmp_path: Path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ScanSort.exe"))
    bundled = tmp_path / "tesseract" / "tesseract.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"exe")

    assert resolve_tesseract_cmd() == bundled


def test_resolve_tesseract_cmd_falls_back_to_path(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with patch("scansort.document.ocr.shutil.which", return_value="/usr/bin/tesseract"):
        assert resolve_tesseract_cmd() == Path("/usr/bin/tesseract")
    with patch("scansort.document.ocr.shutil.which", return_value=None):
        assert resolve_tesseract_cmd() is None


def test_has_ocr_support_reflects_resolver(monkeypatch):
    with patch("scansort.document.ocr.resolve_tesseract_cmd", return_value=None):
        assert has_ocr_support() is False
    with patch(
        "scansort.document.ocr.resolve_tesseract_cmd",
        return_value=Path("/usr/bin/tesseract"),
    ):
        assert has_ocr_support() is True


def test_ocr_pdf_inplace_raises_when_unavailable(tmp_path: Path, monkeypatch):
    pdf = _make_image_only_pdf(tmp_path)
    with (
        patch("scansort.document.ocr.resolve_tesseract_cmd", return_value=None),
        pytest.raises(OcrUnavailableError, match="tesseract"),
    ):
        ocr_pdf_inplace(pdf)


def test_ocr_pdf_inplace_skips_digital_pdf_byte_stable(tmp_path: Path):
    pdf = _make_text_pdf(tmp_path)
    original = pdf.read_bytes()
    with patch(
        "scansort.document.ocr.resolve_tesseract_cmd",
        return_value=Path("/usr/bin/tesseract"),
    ):
        target, confidence = ocr_pdf_inplace(pdf)
    assert target == pdf
    assert confidence is None
    assert pdf.read_bytes() == original, "searchable PDF must not be rewritten"


def test_ocr_pdf_inplace_materializes_output_path_for_searchable_pdf(tmp_path: Path):
    """A no-write early return must still honour an explicit output_path."""
    pdf = _make_text_pdf(tmp_path)
    out = tmp_path / "copy.pdf"
    with patch(
        "scansort.document.ocr.resolve_tesseract_cmd",
        return_value=Path("/usr/bin/tesseract"),
    ):
        target, confidence = ocr_pdf_inplace(pdf, output_path=out)

    assert target == out
    assert confidence is None
    assert out.exists()
    assert out.read_bytes() == pdf.read_bytes()


def test_ocr_pdf_inplace_materializes_output_path_when_no_text_found(tmp_path: Path):
    pdf = _make_image_only_pdf(tmp_path)
    out = tmp_path / "copy.pdf"
    fake_tesseract = MagicMock()
    fake_tesseract.Output.DICT = "dict"
    fake_tesseract.image_to_data.return_value = {
        "text": [""],
        "conf": ["-1"],
        "left": [0],
        "top": [0],
        "width": [0],
        "height": [0],
    }
    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr.pytesseract", fake_tesseract),
    ):
        target, confidence = ocr_pdf_inplace(pdf, output_path=out)

    assert target == out
    assert confidence is None
    assert out.exists()
    assert out.read_bytes() == pdf.read_bytes()


def test_ocr_pdf_inplace_adds_searchable_text(tmp_path: Path):
    pdf = _make_image_only_pdf(tmp_path)
    fake_tesseract = MagicMock()
    fake_tesseract.Output.DICT = "dict"
    fake_tesseract.image_to_data.return_value = {
        "text": ["Invoice", "Total"],
        "conf": ["92", "88"],
        "left": [20, 60],
        "top": [10, 40],
        "width": [50, 40],
        "height": [12, 12],
    }

    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr.pytesseract", fake_tesseract),
    ):
        target, confidence = ocr_pdf_inplace(pdf)

    assert target == pdf
    assert confidence == pytest.approx(90.0)
    text = PdfReader(io.BytesIO(pdf.read_bytes())).pages[0].extract_text()
    assert "Invoice" in text
    assert "Total" in text


def test_ocr_pdf_inplace_preserves_docinfo_and_xmp(tmp_path: Path):
    from pypdf.xmp import XmpInformation

    img_path = tmp_path / "source.png"
    Image.new("RGB", (200, 100), "white").save(img_path, format="PNG")
    pdf = convert_to_pdf(img_path, output_path=tmp_path / "scan.pdf")

    writer = PdfWriter()
    writer.append(PdfReader(str(pdf)))
    writer.add_metadata({"/Title": "Original Title", "/CustomKey": "KeepMe"})
    writer.xmp_metadata = XmpInformation.create()
    with open(pdf, "wb") as f:
        writer.write(f)

    fake_tesseract = MagicMock()
    fake_tesseract.Output.DICT = "dict"
    fake_tesseract.image_to_data.return_value = {
        "text": ["Invoice"],
        "conf": ["90"],
        "left": [20],
        "top": [10],
        "width": [50],
        "height": [12],
    }
    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr.pytesseract", fake_tesseract),
    ):
        ocr_pdf_inplace(pdf)

    reader = PdfReader(io.BytesIO(pdf.read_bytes()))
    assert reader.metadata.get("/Title") == "Original Title"
    assert reader.metadata.get("/CustomKey") == "KeepMe"
    assert reader.xmp_metadata is not None


def test_ocr_pdf_inplace_no_words_leaves_file_unchanged(tmp_path: Path):
    pdf = _make_image_only_pdf(tmp_path)
    original = pdf.read_bytes()
    fake_tesseract = MagicMock()
    fake_tesseract.Output.DICT = "dict"
    fake_tesseract.image_to_data.return_value = {
        "text": [""],
        "conf": ["-1"],
        "left": [0],
        "top": [0],
        "width": [0],
        "height": [0],
    }
    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr.pytesseract", fake_tesseract),
    ):
        _, confidence = ocr_pdf_inplace(pdf)

    assert confidence is None
    assert pdf.read_bytes() == original


def test_ocr_pdf_inplace_wraps_tesseract_errors(tmp_path: Path):
    pdf = _make_image_only_pdf(tmp_path)
    fake_tesseract = MagicMock()
    fake_tesseract.Output.DICT = "dict"
    fake_tesseract.image_to_data.side_effect = RuntimeError("engine blew up")

    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr.pytesseract", fake_tesseract),
        pytest.raises(OcrError, match="engine blew up"),
    ):
        ocr_pdf_inplace(pdf)


def test_ocr_pdf_inplace_wraps_writer_append_errors(tmp_path: Path):
    """A PdfWriter cloning failure must surface as OcrError, not escape."""
    from pypdf.errors import PyPdfError

    pdf = _make_image_only_pdf(tmp_path)
    fake_writer = MagicMock()
    fake_writer.return_value.append.side_effect = PyPdfError("clone failed")

    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr.PdfWriter", fake_writer),
        pytest.raises(OcrError, match="Could not reparse"),
    ):
        ocr_pdf_inplace(pdf)


def test_ocr_pdf_inplace_wraps_writer_serialization_errors(tmp_path: Path):
    """A PdfWriter serialization failure must surface as OcrError, not escape."""
    from pypdf.errors import PyPdfError

    pdf = _make_image_only_pdf(tmp_path)
    fake_tesseract = MagicMock()
    fake_tesseract.Output.DICT = "dict"
    fake_tesseract.image_to_data.return_value = {
        "text": ["Invoice"],
        "conf": ["90"],
        "left": [20],
        "top": [10],
        "width": [50],
        "height": [12],
    }

    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr.pytesseract", fake_tesseract),
        patch(
            "scansort.document.ocr.atomic_write",
            side_effect=PyPdfError("serialize failed"),
        ),
        pytest.raises(OcrError, match="Could not write OCR output"),
    ):
        ocr_pdf_inplace(pdf)


def test_bundled_tesseract_path_returns_none_when_absent(tmp_path: Path, monkeypatch):
    import sys

    from scansort.document.ocr import _bundled_tesseract_path

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ScanSort.exe"))
    assert _bundled_tesseract_path() is None


def test_bundled_tesseract_path_uses_pyinstaller_internal_dir(
    tmp_path: Path, monkeypatch
):
    """PyInstaller 6 bundles files under _internal (sys._MEIPASS)."""
    import sys

    from scansort.document.ocr import _bundled_tesseract_path

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ScanSort.exe"))
    meipass = tmp_path / "_internal"
    bundled = meipass / "tesseract" / "tesseract.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"exe")
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    assert _bundled_tesseract_path() == bundled


def test_needs_ocr_missing_file_raises(tmp_path: Path):
    with pytest.raises(OcrError, match="not found"):
        needs_ocr(tmp_path / "ghost.pdf")


def test_page_text_length_swallows_extraction_errors():
    from pypdf.errors import PyPdfError

    from scansort.document.ocr import _page_text_length

    class _ExplodingPage:
        def extract_text(self):
            raise PyPdfError("boom")

    assert _page_text_length(_ExplodingPage()) == 0


def test_reader_needs_ocr_empty_document_is_false():
    from scansort.document.ocr import _reader_needs_ocr

    class _EmptyReader:
        pages: list = []

    assert _reader_needs_ocr(_EmptyReader(), 25) is False


def test_parse_ocr_data_skips_invalid_confidence_rows():
    data = {
        "text": ["Bad", "Negative", "Good"],
        "conf": ["not-a-number", "-1", "70"],
        "left": [0, 0, 0],
        "top": [0, 0, 0],
        "width": [1, 1, 1],
        "height": [1, 1, 1],
    }
    words, confidence = _parse_ocr_data(data)
    assert [word[4] for word in words] == ["Good"]
    assert confidence == pytest.approx(70.0)


def test_extract_page_image_handles_broken_images():
    from scansort.document.ocr import _extract_page_image

    class _BadCollection:
        @property
        def images(self):
            raise RuntimeError("cannot enumerate")

    class _BadImage:
        @property
        def image(self):
            raise OSError("cannot decode")

    class _NoneImage:
        image = None

    class _Page:
        def __init__(self, images):
            self._images = images

        @property
        def images(self):
            return self._images

    assert _extract_page_image(_BadCollection()) is None
    assert _extract_page_image(_Page([_BadImage(), _NoneImage()])) is None


def test_append_text_layer_covers_content_shapes():
    from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject

    from scansort.document.ocr import _append_text_layer

    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = writer._add_object(DecodedStreamObject())
    page[NameObject("/Contents")] = ArrayObject([stream, stream])

    words = [(1, 1, 5, 5, "Hello")]
    # ArrayObject contents append branch.
    _append_text_layer(writer, page, words, (100, 100))
    assert isinstance(page[NameObject("/Contents")], ArrayObject)
    assert len(page[NameObject("/Contents")]) == 3

    # Missing /Resources and then existing-font branches.
    bare = writer.add_blank_page(width=100, height=100)
    del bare[NameObject("/Resources")]
    _append_text_layer(writer, bare, words, (100, 100))
    _append_text_layer(writer, bare, words, (100, 100))
    assert bare[NameObject("/Resources")].get(NameObject("/Font")) is not None


def test_append_text_layer_dereferences_indirect_contents_array():
    """An indirect /Contents array must be dereferenced before appending."""
    from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject, StreamObject

    from scansort.document.ocr import _append_text_layer

    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    first = writer._add_object(DecodedStreamObject())
    second = writer._add_object(DecodedStreamObject())
    page[NameObject("/Contents")] = writer._add_object(ArrayObject([first, second]))

    _append_text_layer(writer, page, [(1, 1, 5, 5, "Hello")], (100, 100))

    contents = page[NameObject("/Contents")].get_object()
    assert isinstance(contents, ArrayObject)
    assert len(contents) == 3
    # Every element is a stream — never a nested array (ISO 32000-1 §7.7.3.3).
    for element in contents:
        assert isinstance(element.get_object(), StreamObject)


def test_append_text_layer_preserves_single_indirect_stream_reference(tmp_path):
    """A lone indirect /Contents stream must remain indirect through a re-parse.

    Regression: dereferencing the existing stream dropped its indirect
    reference, so pypdf serialized it inline inside the /Contents array.
    Re-reading then yielded a bare DecodedStreamObject lacking
    ``indirect_reference``, crashing ``PdfWriter.append`` with AttributeError
    during the metadata phase (process_pdf_metadata_and_rotation).
    """
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        IndirectObject,
        NameObject,
        StreamObject,
    )

    from scansort.document.metadata import process_pdf_metadata_and_rotation
    from scansort.document.ocr import _append_text_layer

    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    original = DecodedStreamObject()
    original.set_data(b"q Q")
    page[NameObject("/Contents")] = writer._add_object(original)

    _append_text_layer(writer, page, [(1, 1, 5, 5, "Hello")], (100, 100))

    contents = page[NameObject("/Contents")].get_object()
    assert isinstance(contents, ArrayObject)
    assert len(contents) == 2
    for element in contents:
        assert isinstance(element, IndirectObject)
        assert isinstance(element.get_object(), StreamObject)

    out = tmp_path / "annotated.pdf"
    with open(out, "wb") as handle:
        writer.write(handle)

    reparsed = PdfReader(str(out)).pages[0][NameObject("/Contents")].get_object()
    for element in reparsed:
        assert isinstance(element, IndirectObject)

    # The metadata phase re-parses and appends; previously raised AttributeError.
    process_pdf_metadata_and_rotation(out, title="Regression")


def test_copy_document_metadata_error_paths_are_non_fatal():
    from scansort.document.ocr import _copy_document_metadata

    class _XmpRaises:
        metadata = None

        @property
        def xmp_metadata(self):
            raise OSError("xmp unreadable")

    writer = PdfWriter()
    _copy_document_metadata(_XmpRaises(), writer)  # must not raise

    class _XmpWriterRaises:
        def add_metadata(self, metadata):
            raise TypeError("bad docinfo")

        @property
        def xmp_metadata(self):
            return None

        @xmp_metadata.setter
        def xmp_metadata(self, value):
            raise TypeError("bad xmp")

    class _ReaderWithMetadata:
        metadata = {"/Title": "T"}
        xmp_metadata = object()

    _copy_document_metadata(_ReaderWithMetadata(), _XmpWriterRaises())


def test_ocr_pdf_inplace_empty_document_returns_unchanged(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4 empty")

    class _NoPagesReader:
        pages: list = []

    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr._open_reader", return_value=_NoPagesReader()),
    ):
        target, confidence = ocr_pdf_inplace(pdf)

    assert target == pdf
    assert confidence is None


def test_ocr_pdf_inplace_blank_page_left_byte_stable(tmp_path: Path):
    """A text-less page with no image is skipped, not routed to review."""
    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with open(blank, "wb") as f:
        writer.write(f)
    original = blank.read_bytes()

    with patch(
        "scansort.document.ocr.resolve_tesseract_cmd",
        return_value=Path("/usr/bin/tesseract"),
    ):
        target, confidence = ocr_pdf_inplace(blank)

    assert target == blank
    assert confidence is None
    assert blank.read_bytes() == original


def test_ocr_pdf_inplace_processes_image_page_in_mixed_pdf(tmp_path: Path):
    """The image page of a mixed native+scanned PDF still gets a text layer."""
    pdf = _make_mixed_pdf(tmp_path)
    fake_tesseract = MagicMock()
    fake_tesseract.Output.DICT = "dict"
    fake_tesseract.image_to_data.return_value = {
        "text": ["Invoice"],
        "conf": ["90"],
        "left": [20],
        "top": [10],
        "width": [50],
        "height": [12],
    }

    with (
        patch(
            "scansort.document.ocr.resolve_tesseract_cmd",
            return_value=Path("/usr/bin/tesseract"),
        ),
        patch("scansort.document.ocr.pytesseract", fake_tesseract),
    ):
        target, confidence = ocr_pdf_inplace(pdf)

    assert target == pdf
    assert confidence == pytest.approx(90.0)
    reader = PdfReader(io.BytesIO(pdf.read_bytes()))
    assert "Hello searchable digital world" in reader.pages[0].extract_text()
    assert "Invoice" in reader.pages[1].extract_text()
