# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional presentation presets; never overwrite the underlying label settings."""
from dataclasses import dataclass, replace
import math
import unicodedata
from xml.sax.saxutils import escape

ART_STYLES = ("standard", "manuscript", "topographic")


def photo_for_style(image, art_style):
    """Desaturate the artistic display base; leave recognition pixels untouched."""
    if art_style == "standard":
        return image
    import numpy as np
    from PIL import Image
    return np.asarray(Image.fromarray(image).convert("L").convert("RGB"))


@dataclass(frozen=True)
class Appearance:
    text: str
    line: str
    halo: str
    weight: str
    serif: bool = False
    map_style: bool = False

    def halo_width(self, size):
        if self.map_style:
            return max(2.4, size*.16)
        return max(2., size*.06)

    def face_width(self, size):
        # Give fine serif strokes a little ink without replacing the typeface.
        return max(.35, size*.012) if self.serif else 0.


def appearance(project, *, landing=False):
    if project.art_style == "topographic":
        return Appearance("#8bdddf" if landing else "#f3dfa0",
                          "#69c1cb" if landing else "#d2b765", "#352e19", "normal", map_style=True)
    if project.art_style == "manuscript":
        return Appearance("#f0c27f" if landing else "#f4e0a8",
                          "#d5a25c" if landing else "#d7af59", "#182029", "normal", serif=True, map_style=True)
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


def svg_serif_family(families):
    """Qt SVG needs one available family rather than a CSS fallback list."""
    from PySide6.QtGui import QFontDatabase, QGuiApplication
    if QGuiApplication.instance() is not None:
        installed = {family.casefold() for family in QFontDatabase.families()}
        return next((family for family in families if family.casefold() in installed), "serif")
    return families[0]


@dataclass(frozen=True)
class CaptionTypography:
    uppercase: bool = False
    italic: bool = False
    tracking: float = 0.  # em
    arc: float = 0.  # rise / width
    region: bool = False
    scale: float = 1.
    positioned: bool = False  # Explicit baselines for an arc flattened outside the disk.


def caption_typography(project, feature):
    if project.art_style != "manuscript":
        return CaptionTypography()
    kind = feature.get("kind", "").split(",")[0]
    if kind in ("Mare", "Oceanus"):
        return CaptionTypography(True, tracking=.18, arc=.09, region=True, scale=1.85)
    if kind in ("Lacus", "Palus", "Sinus"):
        return CaptionTypography(True, tracking=.08, region=True, scale=1.12)
    if kind == "Mons" and feature.get("diameter", 0) >= 80:
        return CaptionTypography(True, tracking=.12, arc=.055, region=True, scale=1.3)
    if kind in ("Mons", "Rima", "Rupes", "Vallis", "Dorsum", "Promontorium", "Catena"):
        return CaptionTypography(italic=True, scale=.8)
    if kind == "Satellite Feature":
        return CaptionTypography(True, tracking=.02, scale=.68)
    return CaptionTypography(uppercase=bool(kind), tracking=.035)


def caption_text(project, feature):
    text = project.label_text(feature)
    if caption_typography(project, feature).uppercase and "text" not in project.labels.get(feature['id'], {}):
        return text.upper()
    return text


def glyph_advance(character):
    """Nominal Roman cap advances, shared by native and editable SVG arcs.

    Absolute glyph baselines avoid renderer-specific textPath support. Font
    fallback changes the face but never changes the placement of the letters.
    """
    if unicodedata.combining(character):
        return 0.
    if unicodedata.east_asian_width(character) in ("W", "F"):
        return 1.
    if character.isspace():
        return .32
    if character in "Iil.,:;!|'":
        return .30
    if character in "MWmw":
        return .9
    return .66


def caption_span(text, typography):
    return sum(glyph_advance(character) for character in text)+typography.tracking*max(0, len(text)-1)


def caption_glyphs(text, size, typography):
    """Explicit baselines for curved captions and their straight counterparts."""
    if not (typography.arc or typography.positioned) or len(text) < 2:
        return []
    width = caption_span(text, typography)*size
    rise, cursor, result = width*typography.arc, 0., []
    for character in text:
        advance = glyph_advance(character)*size
        center = cursor+advance/2
        ratio = 2*center/width-1
        baseline = size-rise*(1-ratio*ratio)
        angle = math.atan(4*rise/width*ratio) if typography.arc else 0.
        result.append((character, center-advance/2*math.cos(angle),
                       baseline-advance/2*math.sin(angle), math.degrees(angle)))
        cursor += advance+size*typography.tracking
    return result


def placed_caption_typography(project, feature, text, size, position):
    """Keep an arc only when its whole caption fits on the registered disk.

    Test the rotated glyph envelopes, not the feature's anchor or photo
    brightness. The same nominal geometry drives native and editable SVG
    glyphs, including labels dragged by the user. Without registration there
    is no limb to test, so retain the requested typography.
    """
    typography = caption_typography(project, feature)
    glyphs = caption_glyphs(text, size, typography)
    if not glyphs or project.geometry is None or project.matrix is None:
        return typography
    # Map layers also use the caption helpers; import their inverse projection
    # here to share the validated lens correction without an import cycle.
    from .map_layers import photo_coordinates
    import numpy as np

    footprint = []
    padding = appearance(project).halo_width(size)/2
    for character, x, y, angle in glyphs:
        if character.isspace():
            continue
        cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        for dx in (-padding, glyph_advance(character)*size+padding):
            for dy in (-size-padding, size*.25+padding):
                footprint.append((position[0]+x+dx*cosine-dy*sine,
                                  position[1]+y+dx*sine+dy*cosine))
    if not footprint:
        return typography
    _, _, on_disk = project.geometry.unproject(photo_coordinates(project, np.asarray(footprint)))
    return typography if on_disk.all() else replace(typography, arc=0., positioned=True)


def svg_segments(segments):
    return " ".join("M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in segment) for segment in segments)


def svg_caption(text, x, y, size, color, halo, halo_width, element_id, *, face_width=0., typography=None):
    """Editable flat text or positioned glyph groups, with SVG 1.1 halos.

    Qt and some editors ignore SVG 2 paint-order. A use instance inherits the
    surrounding font but not the halo group's stroke or transparent fill.
    """
    foreground = (f'stroke="{color}" stroke-width="{face_width:.3f}" stroke-linejoin="round"'
                  if face_width else 'stroke="none"')
    typography = typography or CaptionTypography()
    glyphs = caption_glyphs(text, size, typography)
    if glyphs:
        label = escape(text, {'"': '&quot;'})
        parts = [f'<g id="{element_id}" aria-label="{label}">']
        flat = replace(typography, arc=0., tracking=0., positioned=False)
        for index, (character, gx, gy, angle) in enumerate(glyphs):
            parts.append(f'<g transform="translate({x+gx:.3f} {y-size+gy:.3f}) rotate({angle:.3f})">')
            parts.append(svg_caption(character, 0., 0., size, color, halo, halo_width,
                                     f'{element_id}-glyph-{index}', face_width=face_width, typography=flat))
            parts.append('</g>')
        parts.append('</g>')
        return ''.join(parts)
    attrs = ' font-style="italic"' if typography.italic else ''
    if typography.tracking:
        attrs += f' letter-spacing="{size*typography.tracking:.3f}"'
    content = escape(text)
    return (f'<g stroke="{halo}" stroke-width="{halo_width:.3f}" stroke-linejoin="round" fill-opacity="0">'
            f'<text id="{element_id}" xml:space="preserve" x="{x:.3f}" y="{y:.3f}" '
            f'fill="{color}" font-size="{size}"{attrs}>{content}</text></g>'
            f'<use xlink:href="#{element_id}" {foreground}/>')
