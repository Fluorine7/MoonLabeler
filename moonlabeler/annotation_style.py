# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
"""Optional presentation presets; never overwrite the underlying label settings."""
from dataclasses import dataclass, replace
from functools import lru_cache
import math
import unicodedata
from xml.sax.saxutils import escape


@dataclass(frozen=True)
class ArtPreset:
    title: str
    palette: str
    elevation_opacity: int
    contour_opacity: int


# Stable IDs are saved in projects; titles pass through the interface translator.
ART_PRESETS = {
    "manuscript": ArtPreset("中世纪风", "antique", 72, 48),
    "topographic": ArtPreset("旷野地形图", "wilderness", 100, 75),
    "cyanotype": ArtPreset("蓝晒星图", "cyanotype", 90, 55),
    "copperplate": ArtPreset("铜版图录", "copperplate", 90, 50),
    "inkwash": ArtPreset("水墨朱砂", "inkwash", 78, 62),
    "redalert": ArtPreset("红警地形图", "redalert", 100, 32),
}
ART_STYLES = ("standard", *ART_PRESETS)
SERIF_STYLES = ("manuscript", "copperplate", "inkwash")
HIERARCHICAL_STYLES = ("manuscript", "cyanotype", "copperplate", "inkwash", "redalert")


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
    halo_ratio: float = .16
    face_ratio: float = .012

    def halo_width(self, size):
        if self.map_style:
            return max(2.4, size*self.halo_ratio)
        return max(2., size*.06)

    def face_width(self, size):
        # Give fine serif strokes a little ink without replacing the typeface.
        return max(.35, size*self.face_ratio) if self.serif else 0.


def appearance(project, *, landing=False):
    if project.art_style == "topographic":
        return Appearance("#8bdddf" if landing else "#f3dfa0",
                          "#69c1cb" if landing else "#d2b765", "#352e19", "normal", map_style=True)
    if project.art_style == "manuscript":
        return Appearance("#f0c27f" if landing else "#f4e0a8",
                          "#d5a25c" if landing else "#d7af59", "#182029", "normal", serif=True, map_style=True)
    if project.art_style == "cyanotype":
        return Appearance("#f0d9a4" if landing else "#e3f2ee",
                          "#d8c08c" if landing else "#a8d7e0", "#102d48", "normal", map_style=True)
    if project.art_style == "copperplate":
        return Appearance("#974b35" if landing else "#412a21",
                          "#974b35" if landing else "#6e4836", "#f3e3bb", "normal", serif=True, map_style=True,
                          halo_ratio=.10, face_ratio=.028)
    if project.art_style == "inkwash":
        return Appearance("#a84335" if landing else "#243c40",
                          "#a84335" if landing else "#656c68", "#f2ead8", "normal", serif=True, map_style=True,
                          halo_ratio=.10, face_ratio=.028)
    if project.art_style == "redalert":
        return Appearance("#efb963" if landing else "#f4eccb",
                          "#d4a251" if landing else "#d7d39c", "#17251b", "bold", map_style=True,
                          halo_ratio=.12)
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
    glyphs: tuple = ()  # Shared native/SVG baselines for a real landform path.
    origin: tuple | None = None  # Preferred caption position in photograph pixels.
    glyph_scales: tuple = ()  # Secondary-language text is smaller.
    glyph_advances: tuple = ()  # Actual shaped-cluster advances, in pixels.
    glyph_families: tuple = ()  # Resolved fallback faces, shared with SVG.


def caption_typography(project, feature):
    if project.art_style == "redalert":
        kind = feature.get("kind", "").split(",")[0]
        if kind in ("Mare", "Oceanus"):
            return CaptionTypography(uppercase=True, tracking=.055, region=True, scale=1.4)
        if kind in ("Lacus", "Palus", "Sinus"):
            return CaptionTypography(uppercase=True, tracking=.025, region=True, scale=1.1)
        if kind in ("Mons", "Rima", "Rupes", "Vallis", "Dorsum", "Promontorium", "Catena"):
            return CaptionTypography(tracking=.015, scale=.85)
        return CaptionTypography(uppercase=True, tracking=.02, scale=.72 if kind == "Satellite Feature" else 1.)
    if project.art_style in ("cyanotype", "copperplate", "inkwash"):
        kind = feature.get("kind", "").split(",")[0]
        blueprint = project.art_style == "cyanotype"
        copper = project.art_style == "copperplate"
        if kind in ("Mare", "Oceanus"):
            return CaptionTypography(uppercase=blueprint or copper, tracking=.14 if blueprint else .08,
                                     arc=.045 if copper else 0., region=True, scale=1.6 if copper else 1.45)
        if kind in ("Lacus", "Palus", "Sinus"):
            return CaptionTypography(uppercase=blueprint or copper, tracking=.06, region=True, scale=1.1)
        if kind in ("Mons", "Rima", "Rupes", "Vallis", "Dorsum", "Promontorium", "Catena"):
            return CaptionTypography(italic=copper, tracking=.025 if blueprint else 0., scale=.85)
        if kind == "Satellite Feature":
            return CaptionTypography(uppercase=blueprint, tracking=.02, scale=.7)
        return CaptionTypography(uppercase=blueprint, tracking=.045 if blueprint else .015)
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


def caption_font(pixel_size, project=None, feature=None):
    """One font definition for native painting, path measurement and export."""
    from PySide6.QtGui import QFont
    from .project import label_font_families
    font = QFont()
    font.setFamilies(project.label_families() if project is not None else label_font_families())
    font.setPixelSize(pixel_size)
    font.setWeight(QFont.Weight.Normal if project is not None and appearance(project).weight == "normal" else QFont.Weight.Bold)
    if project is not None and feature is not None:
        typography = caption_typography(project, feature)
        font.setItalic(typography.italic)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, typography.tracking*pixel_size)
    return font


def _path_units(text):
    """Fallback units for geometry-only consumers without an active Qt GUI."""
    result, word = [], ""
    for character in text:
        if character.isspace() or unicodedata.east_asian_width(character) in ("W", "F"):
            if word:
                result.append(word)
                word = ""
            result.append(character)
        else:
            word += character
    if word:
        result.append(word)
    return tuple(result)


def _fallback_clusters(layout, text, flags):
    """Recover source positions when Qt's whole runs lose fallback indices."""
    from PySide6.QtCore import QTextBoundaryFinder
    boundaries = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    start, previous = 0, None
    clusters = {}
    while (end := boundaries.toNextBoundary()) != -1:
        # QTextLayout and the boundary finder both count UTF-16 units. A
        # ranged query also finds spaces/punctuation whose whole-run index
        # can incorrectly be zero on CoreText.
        positions = ((point.x(), run.rawFont().familyName())
                     for run in layout.glyphRuns(start, end-start, flags)
                     for point in run.positions())
        cluster = min(positions, default=None)
        if cluster is not None and cluster != previous:
            # Two graphemes in one ligature can share a glyph position.
            clusters[start] = previous = cluster
        start = end
    return clusters


@lru_cache(maxsize=1024)
def _shape_row(text, size, families, weight, italic, tracking, *, recover_fallback_indices=False):
    from PySide6.QtGui import QFont, QFontInfo, QFontMetricsF, QTextLayout
    font = QFont()
    font.setFamilies(list(families))
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.Normal if weight == "normal" else QFont.Weight.Bold)
    font.setItalic(italic)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking*size)
    layout = QTextLayout(text, font)
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(1e6)
    layout.endLayout()
    flags = QTextLayout.GlyphRunRetrievalFlag.RetrieveAll
    runs = layout.glyphRuns(0, -1, flags)
    if recover_fallback_indices and len({run.rawFont().familyName() for run in runs}) > 1:
        clusters = _fallback_clusters(layout, text, flags)
    else:
        clusters = {}
        for run in runs:
            for index, position in zip(run.stringIndexes(), run.positions()):
                previous = clusters.get(index)
                if previous is None or position.x() < previous[0]:
                    clusters[index] = (position.x(), run.rawFont().familyName())
    starts = sorted(clusters)
    positions = [clusters[index][0] for index in starts]
    if (not starts or any(b < a for a, b in zip(positions, positions[1:]))
            or any(unicodedata.bidirectional(c) in ('R', 'AL') for c in text)):
        # Context-dependent right-to-left scripts retain their complete run.
        return (text,), (QFontMetricsF(font).horizontalAdvance(text),), (QFontInfo(font).family(),)
    utf16 = text.encode('utf-16-le')
    ends = starts[1:]+[len(utf16)//2]
    units = tuple(utf16[start*2:end*2].decode('utf-16-le') for start, end in zip(starts, ends))
    widths = tuple(b-a for a, b in zip(positions, positions[1:]+[line.horizontalAdvance()]))
    return units, widths, tuple(clusters[index][1] for index in starts)


def svg_preferred_family(project):
    from PySide6.QtGui import QFontInfo, QGuiApplication
    if isinstance(QGuiApplication.instance(), QGuiApplication):
        return QFontInfo(caption_font(24, project)).family()
    return project.label_families()[0]


def svg_caption_font_runs(text, size, families, weight, typography, primary):
    """Keep editable SVG text while matching Qt's fallback for missing glyphs."""
    from PySide6.QtGui import QGuiApplication
    if not isinstance(QGuiApplication.instance(), QGuiApplication) or caption_glyphs(text, size, typography):
        return ()
    units, _, resolved = _shape_row(text, size, tuple(families), weight, typography.italic, typography.tracking,
                                    recover_fallback_indices=True)
    if "".join(units) != text or all(family == primary for family in resolved):
        return ()
    runs = []
    for unit, family in zip(units, resolved):
        if runs and runs[-1][1] == family:
            runs[-1] = (runs[-1][0]+unit, family)
        else:
            runs.append((unit, family))
    return runs


def path_caption_rows(project, feature, text, size):
    from PySide6.QtGui import QGuiApplication
    typography = caption_typography(project, feature)
    bilingual = (project.language in ("双语", "双语（繁体）") and feature.get("name_zh")
                 and "text" not in project.labels.get(feature['id'], {}) and " · " in text)
    parts = text.split(" · ", 1) if bilingual else [text]
    rows = []
    families = tuple(project.label_families())
    custom_font = bool(project.preferred_label_family)
    for index, part in enumerate(parts):
        row_size = max(6, round(size*.82)) if index else size
        if QGuiApplication.instance() is not None:
            units, widths, resolved = _shape_row(part, row_size, families, appearance(project).weight,
                                                typography.italic, typography.tracking,
                                                recover_fallback_indices=custom_font)
        else:
            # Geometry-only consumers need no GUI. Actual GUI/Qt SVG exports
            # measure the selected system font and share those measurements.
            units = _path_units(part)
            widths = tuple((sum(glyph_advance(c) for c in unit)+typography.tracking*len(unit))*row_size for unit in units)
            resolved = (families[0],)*len(units)
        offset = (-.22*size if index == 0 else .98*size) if bilingual else .15*size
        rows.append((units, row_size, widths, offset, resolved))
    return tuple(rows)


def caption_glyphs(text, size, typography):
    """Explicit baselines for curved captions and their straight counterparts."""
    if typography.glyphs:
        return typography.glyphs
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


def path_caption_typography(project, feature, text, size):
    """Bind a caption to a projected landform without changing its text/style."""
    typography = caption_typography(project, feature)
    if len(text) < 2 or not project.follow_feature_paths:
        return typography
    from .feature_paths import caption_on_path, PATH_KINDS
    if feature.get("kind", "").split(",")[0] not in PATH_KINDS:
        return typography
    rows = path_caption_rows(project, feature, text, size)
    placed = caption_on_path(project, feature, [(widths, row_size, offset) for _, row_size, widths, offset, _ in rows])
    if placed is None:
        return typography
    origin, coordinates = placed
    units = [unit for row, _, _, _, _ in rows for unit in row]
    return replace(typography, arc=0., positioned=True, region=True, origin=origin,
                   glyphs=tuple((unit, *position) for unit, position in zip(units, coordinates)),
                   glyph_scales=tuple(row_size/size for row, row_size, _, _, _ in rows for _ in row),
                   glyph_advances=tuple(width for _, _, widths, _, _ in rows for width in widths),
                   glyph_families=tuple(family for _, _, _, _, resolved in rows for family in resolved))


def flat_caption_typography(project, typography):
    # Preserve legacy arc spacing, but measure custom fonts as whole text
    # when a landform caption cannot follow its path at the limb.
    return replace(typography, arc=0., positioned=not project.preferred_label_family, glyphs=(), origin=None,
                   glyph_scales=(), glyph_advances=(), glyph_families=())


def placed_caption_typography(project, feature, text, size, position):
    """Keep an arc only when its whole caption fits on the registered disk.

    Test the rotated glyph envelopes, not the feature's anchor or photo
    brightness. The same nominal geometry drives native and editable SVG
    glyphs, including labels dragged by the user. Without registration there
    is no limb to test, so retain the requested typography.
    """
    typography = path_caption_typography(project, feature, text, size)
    glyphs = caption_glyphs(text, size, typography)
    if not glyphs or project.geometry is None or project.matrix is None:
        return typography
    # Map layers also use the caption helpers; import their inverse projection
    # here to share the validated lens correction without an import cycle.
    from .map_layers import photo_coordinates
    import numpy as np

    footprint = []
    padding = appearance(project).halo_width(size)/2
    for index, (character, x, y, angle) in enumerate(glyphs):
        if character.isspace():
            continue
        cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        scale = typography.glyph_scales[index] if typography.glyph_scales else 1.
        advance = typography.glyph_advances[index] if typography.glyph_advances else glyph_advance(character)*size
        for dx in (-padding, advance+padding):
            for dy in (-size*scale-padding, size*scale*.25+padding):
                footprint.append((position[0]+x+dx*cosine-dy*sine,
                                  position[1]+y+dx*sine+dy*cosine))
    if not footprint:
        return typography
    _, _, on_disk = project.geometry.unproject(photo_coordinates(project, np.asarray(footprint)))
    return typography if on_disk.all() else flat_caption_typography(project, typography)


def svg_segments(segments):
    return " ".join("M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in segment) for segment in segments)


def svg_caption(text, x, y, size, color, halo, halo_width, element_id, *, face_width=0., typography=None, font_runs=()):
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
        flat = replace(typography, arc=0., tracking=typography.tracking if typography.glyph_advances else 0.,
                       positioned=False, glyphs=(), origin=None, glyph_scales=(), glyph_advances=(), glyph_families=())
        for index, (character, gx, gy, angle) in enumerate(glyphs):
            glyph_size = size*(typography.glyph_scales[index] if typography.glyph_scales else 1.)
            family = (' font-family="'+escape(typography.glyph_families[index], {'"': '&quot;'})+'"') if typography.glyph_families else ''
            parts.append(f'<g{family} transform="translate({x+gx:.3f} {y-size+gy:.3f}) rotate({angle:.3f})">')
            parts.append(svg_caption(character, 0., 0., glyph_size, color, halo, halo_width,
                                     f'{element_id}-glyph-{index}', face_width=face_width, typography=flat))
            parts.append('</g>')
        parts.append('</g>')
        return ''.join(parts)
    attrs = ' font-style="italic"' if typography.italic else ''
    if typography.tracking:
        attrs += f' letter-spacing="{size*typography.tracking:.3f}"'
    content = escape(text)
    if font_runs:
        content = "".join('<tspan font-family="{}">{}</tspan>'.format(escape(family, {'"': '&quot;'}), escape(unit))
                          for unit, family in font_runs)
    return (f'<g stroke="{halo}" stroke-width="{halo_width:.3f}" stroke-linejoin="round" fill-opacity="0">'
            f'<text id="{element_id}" xml:space="preserve" x="{x:.3f}" y="{y:.3f}" '
            f'fill="{color}" font-size="{size}"{attrs}>{content}</text></g>'
            f'<use xlink:href="#{element_id}" {foreground}/>')
