"""Procedural and asset-based system tray icon generation for ScanSort."""

import logging
from pathlib import Path

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

DEFAULT_ICON_SIZE: tuple[int, int] = (64, 64)


def _draw_badge(
    draw, w: int, h: int, doc_right: int, doc_bottom: int, radius_factor: float, fill
) -> tuple[int, int, int]:
    """Draw the corner status badge circle and return ``(cx, cy, radius)``."""
    badge_radius = int(w * radius_factor)
    badge_cx = min(doc_right, w - badge_radius - 1) - int(badge_radius * 0.4)
    badge_cy = min(doc_bottom, h - badge_radius - 1) - int(badge_radius * 0.4)
    badge_box = [
        badge_cx - badge_radius,
        badge_cy - badge_radius,
        badge_cx + badge_radius,
        badge_cy + badge_radius,
    ]
    draw.ellipse(badge_box, fill=fill, outline=(255, 255, 255, 255), width=2)
    return badge_cx, badge_cy, badge_radius


def get_tray_icon(
    paused: bool = False,
    size: tuple[int, int] = DEFAULT_ICON_SIZE,
    custom_icon_path: Path | None = None,
) -> Image.Image:
    """Generate or load an RGBA icon suitable for the system tray notification area.

    Args:
        paused: Whether to render a paused badge / muted color scheme.
        size: Target width and height in pixels (defaults to 64x64 for crisp high-DPI scaling).
        custom_icon_path: Optional path to a user-provided or bundled .ico/.png asset.

    Returns:
        A PIL RGBA Image object.
    """
    if custom_icon_path is not None and custom_icon_path.is_file():
        try:
            with Image.open(custom_icon_path) as loaded:
                return loaded.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        except OSError as e:
            logger.warning(
                "Could not load custom tray icon from %s: %s; falling back to procedural icon.",
                custom_icon_path,
                e,
            )

    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Margins and document coordinates
    pad_x = max(2, int(w * 0.12))
    pad_y = max(2, int(h * 0.08))
    doc_left = pad_x
    doc_top = pad_y
    doc_right = w - pad_x
    doc_bottom = h - pad_y
    corner_size = max(4, int(w * 0.22))

    # Base colors
    if paused:
        page_bg = (220, 225, 230, 240)
        border_color = (120, 130, 140, 255)
        line_color = (150, 160, 170, 200)
    else:
        page_bg = (245, 248, 255, 255)
        border_color = (30, 110, 210, 255)
        line_color = (70, 140, 230, 220)

    # Document polygon with folded corner in top-right
    doc_polygon = [
        (doc_left, doc_top),
        (doc_right - corner_size, doc_top),
        (doc_right, doc_top + corner_size),
        (doc_right, doc_bottom),
        (doc_left, doc_bottom),
    ]
    draw.polygon(
        doc_polygon, fill=page_bg, outline=border_color, width=max(1, int(w * 0.03))
    )

    # Folded corner flap
    flap_polygon = [
        (doc_right - corner_size, doc_top),
        (doc_right - corner_size, doc_top + corner_size),
        (doc_right, doc_top + corner_size),
    ]
    draw.polygon(flap_polygon, fill=(200, 215, 235, 255), outline=border_color, width=1)

    # Document text lines
    line_left = doc_left + max(3, int(w * 0.12))
    line_right = doc_right - max(3, int(w * 0.12))
    line_w = max(1, int(h * 0.03))

    y1 = doc_top + int(h * 0.35)
    y2 = doc_top + int(h * 0.50)
    y3 = doc_top + int(h * 0.65)
    draw.line(
        [(line_left, y1), (line_right - corner_size, y1)], fill=line_color, width=line_w
    )
    draw.line([(line_left, y2), (line_right, y2)], fill=line_color, width=line_w)
    draw.line(
        [(line_left, y3), (line_right - max(2, int(w * 0.15)), y3)],
        fill=line_color,
        width=line_w,
    )

    if paused:
        # Amber/Orange pause circle badge in bottom-right corner
        badge_cx, badge_cy, badge_radius = _draw_badge(
            draw, w, h, doc_right, doc_bottom, 0.22, (235, 140, 20, 255)
        )

        # Two vertical white pause bars
        bar_w = max(2, int(badge_radius * 0.30))
        bar_h = int(badge_radius * 1.0)
        gap = max(2, int(badge_radius * 0.30))

        bar1_left = badge_cx - gap // 2 - bar_w
        bar2_left = badge_cx + gap // 2
        bar_top = badge_cy - bar_h // 2
        bar_bottom = badge_cy + bar_h // 2

        draw.rectangle(
            [bar1_left, bar_top, bar1_left + bar_w, bar_bottom],
            fill=(255, 255, 255, 255),
        )
        draw.rectangle(
            [bar2_left, bar_top, bar2_left + bar_w, bar_bottom],
            fill=(255, 255, 255, 255),
        )
    else:
        # Green / cyan active filing badge
        badge_cx, badge_cy, badge_radius = _draw_badge(
            draw, w, h, doc_right, doc_bottom, 0.20, (35, 175, 95, 255)
        )

        # Checkmark in active badge
        chk = [
            (badge_cx - int(badge_radius * 0.5), badge_cy),
            (badge_cx - int(badge_radius * 0.1), badge_cy + int(badge_radius * 0.4)),
            (badge_cx + int(badge_radius * 0.5), badge_cy - int(badge_radius * 0.4)),
        ]
        draw.line(chk, fill=(255, 255, 255, 255), width=max(2, int(w * 0.035)))

    return image
