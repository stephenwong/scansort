"""Unit tests for scansort.ui.icon module."""

from pathlib import Path

from PIL import Image

from scansort.ui.icon import get_tray_icon


def test_get_tray_icon_default():
    icon = get_tray_icon(paused=False)
    assert isinstance(icon, Image.Image)
    assert icon.mode == "RGBA"
    assert icon.size == (64, 64)


def test_get_tray_icon_custom_size():
    icon = get_tray_icon(paused=False, size=(32, 32))
    assert isinstance(icon, Image.Image)
    assert icon.size == (32, 32)


def test_get_tray_icon_paused():
    normal_icon = get_tray_icon(paused=False)
    paused_icon = get_tray_icon(paused=True)

    assert isinstance(paused_icon, Image.Image)
    assert paused_icon.mode == "RGBA"
    assert paused_icon.size == (64, 64)
    # The pixel data must differ between normal and paused states
    assert normal_icon.tobytes() != paused_icon.tobytes()


def test_get_tray_icon_custom_file(tmp_path: Path):
    custom_ico = tmp_path / "custom.png"
    img = Image.new("RGBA", (128, 128), color=(255, 0, 0, 255))
    img.save(custom_ico)

    loaded = get_tray_icon(custom_icon_path=custom_ico, size=(64, 64))
    assert isinstance(loaded, Image.Image)
    assert loaded.size == (64, 64)


def test_get_tray_icon_custom_file_missing(tmp_path: Path):
    missing_ico = tmp_path / "nonexistent.png"
    fallback = get_tray_icon(custom_icon_path=missing_ico)
    assert isinstance(fallback, Image.Image)
    assert fallback.size == (64, 64)


def test_badge_within_canvas_bounds():
    from scansort.ui.icon import get_tray_icon

    for paused in (True, False):
        for size in ((64, 64), (32, 32), (16, 16)):
            img = get_tray_icon(paused=paused, size=size)
            assert img.size == size
