# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional presentation presets; never overwrite the underlying label settings."""
from dataclasses import dataclass
from xml.sax.saxutils import escape

ART_STYLES = ("standard", "manuscript")


@dataclass(frozen=True)
class Appearance:
    text: str
    line: str
    halo: str
    weight: str
    ornament: bool = False

    def halo_width(self, size):
        return max(2.6, size*.13) if self.ornament else max(2., size*.06)

    def face_width(self, size):
        # Give fine serif strokes a little ink without replacing the typeface.
        return max(.35, size*.012) if self.ornament else 0.


def appearance(project, *, landing=False):
    if project.art_style == "manuscript":
        return Appearance("#ffe3c7" if landing else "#fff1cf",
                          "#d49c7b" if landing else "#c6a35e", "#211b13", "normal", True)
    color = project.landing_color if landing else project.color
    return Appearance(color, color, "#141923", project.font_weight)


def manuscript_fonts(traditional, platform):
    """System serif fonts, with explicit Simplified/Traditional CJK fallbacks."""
    if platform == "darwin":
        return ["Baskerville", "Palatino", "Songti TC" if traditional else "Songti SC", "Songti SC"]
    if platform == "win32":
        return ["Palatino Linotype", "Georgia", "PMingLiU" if traditional else "SimSun", "SimSun"]
    return ["Noto Serif", "DejaVu Serif", "Noto Serif CJK TC" if traditional else "Noto Serif CJK SC",
            "Source Han Serif", "Noto Serif CJK SC"]


def diamond(x, y, radius):
    return ((x, y-radius), (x+radius*.7, y), (x, y+radius), (x-radius*.7, y), (x, y-radius))


def caption_ornament(size):
    """A short illuminated rule, in the same local coordinates as the caption.

    Fixed proportions keep Qt and editable SVG text independent of font metrics.
    Its extent participates in the editor's collision layout.
    """
    y, mid, radius = size*1.24, size*.9, size*.085
    return (((0., y), (mid-radius*1.8, y)),
            diamond(mid, y, radius),
            ((mid+radius*1.8, y), (size*1.8, y)))


def svg_segments(segments):
    return " ".join("M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in segment) for segment in segments)


def svg_caption(text, x, y, size, color, halo, halo_width, element_id, *, face_width=0.):
    """One editable text node, drawn as halo then fill in SVG 1.1 renderers.

    Qt and some editors ignore SVG 2 paint-order. A use instance inherits the
    surrounding font but not the halo group's stroke or transparent fill.
    """
    foreground = (f'stroke="{color}" stroke-width="{face_width:.3f}" stroke-linejoin="round"'
                  if face_width else 'stroke="none"')
    return (f'<g stroke="{halo}" stroke-width="{halo_width:.3f}" stroke-linejoin="round" fill-opacity="0">'
            f'<text id="{element_id}" xml:space="preserve" x="{x:.3f}" y="{y:.3f}" '
            f'fill="{color}" font-size="{size}">{escape(text)}</text></g>'
            f'<use xlink:href="#{element_id}" {foreground}/>')
