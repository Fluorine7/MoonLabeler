// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import CoreText
import ImageIO
import UniformTypeIdentifiers
import MoonCore

struct ThemeInk {
    var text: String, line: String, halo: String
    var serif = false
    static func resolve(_ document: MoonDocument, landing: Bool = false) -> ThemeInk {
        switch document.style.art {
        case "manuscript": return ThemeInk(text: landing ? "#f0c27f" : "#f4e0a8", line: landing ? "#d5a25c" : "#d7af59", halo: "#182029", serif: true)
        case "topographic": return ThemeInk(text: landing ? "#8bdddf" : "#f3dfa0", line: landing ? "#69c1cb" : "#d2b765", halo: "#352e19")
        case "cyanotype": return ThemeInk(text: landing ? "#f0d9a4" : "#e3f2ee", line: landing ? "#d8c08c" : "#a8d7e0", halo: "#102d48")
        case "copperplate": return ThemeInk(text: landing ? "#974b35" : "#412a21", line: landing ? "#974b35" : "#6e4836", halo: "#f3e3bb", serif: true)
        case "inkwash": return ThemeInk(text: landing ? "#a84335" : "#243c40", line: landing ? "#a84335" : "#656c68", halo: "#f2ead8", serif: true)
        case "redalert": return ThemeInk(text: landing ? "#efb963" : "#f4eccb", line: landing ? "#d4a251" : "#d7d39c", halo: "#17251b")
        default: return ThemeInk(text: landing ? document.style.string("landing_color", "#f2b05e") : document.settings.color,
                                 line: landing ? document.style.string("landing_color", "#f2b05e") : document.settings.color, halo: "#141923")
        }
    }
}

private struct MapStroke {
    let line: MapLine, path: CGPath, bounds: CGRect
    init(_ line: MapLine) {
        self.line = line
        let path = CGMutablePath()
        if let first = line.points.first {
            path.move(to: CGPoint(x: first.x, y: first.y))
            for point in line.points.dropFirst() { path.addLine(to: CGPoint(x: point.x, y: point.y)) }
        }
        self.path = path; bounds = path.boundingBoxOfPath
    }
}
private enum TextureMemory {
    private static let lock = NSLock()
    private static var scenes = 0, imageBytes = 0
    static func adjust(scenes count: Int, bytes: Int) { lock.lock(); scenes += count; imageBytes += bytes; lock.unlock() }
    static var usage: (scenes: Int, staticBitmapBytes: Int) { lock.lock(); defer { lock.unlock() }; return (scenes, imageBytes) }
}
private final class SceneTextures: NSObject {
    var elevation: CGImage?
    var grayscale: CGImage?
    var threshold: Int?
    var coverage: CGImage?
    let grid: [MapStroke], contours: [MapStroke], terminator: [MapStroke]
    private let bitmapBytes: Int
    init(_ scene: AnnotationScene) {
        elevation = scene.layers.elevation?.cgImage; grayscale = scene.grayscale?.cgImage
        grid = scene.layers.grid.map(MapStroke.init); contours = scene.layers.contours.map(MapStroke.init)
        terminator = scene.layers.terminator.map(MapStroke.init)
        bitmapBytes = [elevation, grayscale].compactMap { $0 }.reduce(0) { $0 + $1.bytesPerRow * $1.height }
        TextureMemory.adjust(scenes: 1, bytes: bitmapBytes)
    }
    deinit { TextureMemory.adjust(scenes: -1, bytes: -bitmapBytes) }
}
private struct CurvedGlyph {
    var path: CGPath
    var text: String
    var point: CGPoint
    var angle: Double
    var size: Double
    var font: String
}
private struct ShapedGlyph { var path: CGPath; var text: String; var x: Double; var y: Double; var font: String; var cluster: Int }
private final class ShapedLine: NSObject { var width: Double = 0; var glyphs: [ShapedGlyph] = [] }
private struct MapInk {
    var contour: String, index: String, grid: String, halo: String, terminator: String
    static func resolve(_ document: MoonDocument) -> MapInk {
        switch document.style.art {
        case "cyanotype": return MapInk(contour: "#a7d2dd", index: "#e3efdf", grid: "#c0e2e7", halo: "#102d48", terminator: "#e5c389")
        case "copperplate": return MapInk(contour: "#8f704e", index: "#7d4e2c", grid: "#875c3a", halo: "#eedfbd", terminator: "#9a4d36")
        case "inkwash": return MapInk(contour: "#536663", index: "#b94d37", grid: "#ac4c38", halo: "#ede7d5", terminator: "#a84335")
        case "redalert": return MapInk(contour: "#536c36", index: "#d8c681", grid: "#c8d5a0", halo: "#17251b", terminator: "#e1a767")
        case "manuscript": return MapInk(contour: "#efcf82", index: "#efcf82", grid: "#f0cc7b", halo: "#17242f", terminator: "#f3a46e")
        case "topographic": return MapInk(contour: "#34250e", index: "#34250e", grid: "#edd99b", halo: "#e7d39c", terminator: "#91d8e5")
        default: return MapInk(contour: "#e4bd73", index: "#e4bd73", grid: "#a7d9ed", halo: "#18232b", terminator: "#f3a46e")
        }
    }
}
private struct LegendInk {
    var background = "#10151d", foreground = "#f0ece1", border = "", sample = "#c5bb82"
    var alpha = 235.0 / 255, serif = true
    static func resolve(_ document: MoonDocument) -> LegendInk {
        switch document.style.art {
        case "topographic": return LegendInk(background: "#372f1b", border: "#968454", alpha: 225.0 / 255, serif: false)
        case "cyanotype": return LegendInk(background: "#0b2943", foreground: "#e3f2ee", border: "#5b8ba1", sample: "#c0e2e7", serif: false)
        case "copperplate": return LegendInk(background: "#ead9b6", foreground: "#412a21", border: "#9a7857", sample: "#7d4e2c")
        case "inkwash": return LegendInk(background: "#e8e5d3", foreground: "#303b3c", border: "#81877d", sample: "#a84335")
        case "redalert": return LegendInk(background: "#1e2d23", foreground: "#f4eccb", border: "#89946a", sample: "#d8c681", serif: false)
        default: return LegendInk()
        }
    }
}

enum SceneRenderer {
    static var textureMemoryUsage: (scenes: Int, staticBitmapBytes: Int) { TextureMemory.usage }
    private struct CaptionKey: Equatable {
        var annotations: [Annotation], size: Double, language: NameLanguage, art: String, weight: String, family: String, calibration: Calibration?
    }
    private struct CaptionGeometry {
        var path: CGPath, bounds: CGRect, pathBound: Bool
    }
    private static let captionLock = NSLock()
    private static var captionSets: [(CaptionKey, [UUID: CaptionGeometry])] = []
    private static func preparedCaptions(_ document: MoonDocument) -> [UUID: CaptionGeometry] {
        let key = CaptionKey(annotations: document.annotations, size: document.settings.fontSize, language: document.settings.language,
                             art: document.style.art, weight: document.style.string("font_weight", "bold"),
                             family: document.style.preferredLabelFamily, calibration: document.calibration)
        captionLock.lock()
        let existing = captionSets.first { $0.0 == key }?.1
        captionLock.unlock()
        if let existing { return existing }
        var prepared: [UUID: CaptionGeometry] = [:]
        for annotation in document.annotations {
            let bound = annotation.visual?.pathGlyphs?.isEmpty == false || (annotation.visual?.baseline?.count ?? 0) > 1
            prepared[annotation.id] = CaptionGeometry(path: captionPath(annotation, document: document), bounds: labelBounds(annotation, document: document),
                                                     pathBound: bound && !curvedGlyphs(annotation, document: document).isEmpty)
        }
        captionLock.lock(); captionSets.insert((key, prepared), at: 0)
        if captionSets.count > 3 { captionSets.removeLast() }; captionLock.unlock()
        return prepared
    }
    private static let features = Dictionary(uniqueKeysWithValues: ((try? Catalog.load()) ?? []).map { ($0.id, $0) })
    private static let textureLock = NSLock()
    private static var latestTextures: (id: UUID, value: SceneTextures)?
    private static let shapedLines = NSCache<NSString, ShapedLine>()
    private static func shaped(_ text: String, font face: NSFont, tracking: Double = 0) -> ShapedLine {
        let cascade = (face.fontDescriptor.object(forKey: .cascadeList) as? [NSFontDescriptor])?.map {
            ($0.object(forKey: .name) as? String) ?? ($0.object(forKey: .family) as? String) ?? ""
        }.joined(separator: ",") ?? ""
        let key = "\(face.fontName)|\(face.pointSize)|\(cascade)|\(tracking)|\(text)" as NSString
        if let result = shapedLines.object(forKey: key) { return result }
        var attributes: [NSAttributedString.Key: Any] = [.font: face]
        if tracking != 0 { attributes[.kern] = tracking * face.pointSize }
        let result = ShapedLine(), line = CTLineCreateWithAttributedString(NSAttributedString(string: text, attributes: attributes))
        result.width = CTLineGetTypographicBounds(line, nil, nil, nil)
        let runs = CTLineGetGlyphRuns(line) as! [CTRun], leftToRight = !runs.contains { CTRunGetStatus($0).contains(.rightToLeft) }
        let string = text as NSString
        func cluster(_ index: Int) -> Int { index < string.length ? string.rangeOfComposedCharacterSequence(at: max(0, index)).location : string.length }
        let starts = Set(runs.flatMap { run -> [Int] in
            var indices = [CFIndex](repeating: 0, count: CTRunGetGlyphCount(run)); CTRunGetStringIndices(run, CFRange(), &indices)
            return indices.map { cluster($0) }
        }).sorted()
        let ends = Dictionary(uniqueKeysWithValues: zip(starts, Array(starts.dropFirst()) + [string.length]))
        var nativeCursor = 0.0, compatibleCursor = 0.0
        var previousCluster: Int?
        for run in runs {
            let count = CTRunGetGlyphCount(run), attributes = CTRunGetAttributes(run) as NSDictionary, ctFont = attributes[kCTFontAttributeName] as! CTFont
            var glyphs = [CGGlyph](repeating: 0, count: count), positions = [CGPoint](repeating: .zero, count: count), advances = [CGSize](repeating: .zero, count: count), indices = [CFIndex](repeating: 0, count: count)
            CTRunGetGlyphs(run, CFRange(), &glyphs); CTRunGetPositions(run, CFRange(), &positions); CTRunGetAdvances(run, CFRange(), &advances); CTRunGetStringIndices(run, CFRange(), &indices)
            let opticalTracking = CaptionFontMetrics.opticalTracking(ctFont)
            for index in 0..<count {
                let x = leftToRight ? compatibleCursor + CaptionFontMetrics.fixed(positions[index].x - nativeCursor) : positions[index].x
                let start = cluster(indices[index]), clusterStart = previousCluster != start
                previousCluster = start
                nativeCursor += advances[index].width
                compatibleCursor += CaptionFontMetrics.fixed(advances[index].width) + (clusterStart ? opticalTracking : 0)
                let path = CTFontCreatePathForGlyph(ctFont, glyphs[index], nil) ?? CGMutablePath()
                let next = ends[start] ?? string.length
                result.glyphs.append(ShapedGlyph(path: path, text: string.substring(with: NSRange(location: start, length: max(0, next - start))), x: x, y: CaptionFontMetrics.fixed(positions[index].y), font: CTFontCopyFamilyName(ctFont) as String, cluster: start))
            }
        }
        if leftToRight { result.width = compatibleCursor }
        shapedLines.countLimit = 1500; shapedLines.setObject(result, forKey: key); return result
    }
    private static func editableFontRuns(_ line: ShapedLine, x: Double, baseline: Double) -> [String] {
        struct Run {
            var text: String, family: String, x: Double, y: Double, lastX: Double
        }
        var seen = Set<Int>(), runs: [Run] = []
        let clusters = line.glyphs.filter { seen.insert($0.cluster).inserted }.sorted { $0.cluster < $1.cluster }
        for glyph in clusters {
            if let last = runs.indices.last, runs[last].family == glyph.font, runs[last].y == glyph.y, glyph.x >= runs[last].lastX {
                runs[last].text += glyph.text; runs[last].lastX = glyph.x
            } else {
                runs.append(Run(text: glyph.text, family: glyph.font, x: glyph.x, y: glyph.y, lastX: glyph.x))
            }
        }
        return runs.enumerated().map { index, run in
            let end = index + 1 < runs.count ? runs[index + 1].x : line.width
            let width = end - run.x
            let length = width > 0 && run.text.count > 1 ? " textLength=\"\(width)\" lengthAdjust=\"spacing\"" : ""
            return "<tspan x=\"\(x + run.x)\" y=\"\(baseline - run.y)\" font-family=\"\(escape(run.family))\"\(length)>\(escape(run.text))</tspan>"
        }
    }
    private static func mapWidth(_ document: MoonDocument, major: Bool, grid: Bool = false) -> Double {
        max(grid ? (major ? 1.8 : 1.25) : (major ? 1.8 : 1.1), Double(min(document.imageWidth, document.imageHeight)) * (grid ? (major ? 0.0022 : 0.0016) : (major ? 0.0018 : 0.0011)))
    }
    private static func stroke(_ geometry: MapStroke, color: String, opacity: Double, width: Double, context: CGContext) {
        guard geometry.bounds.insetBy(dx: -width * 10 - 2, dy: -width * 10 - 2).intersects(context.boundingBoxOfClipPath) else { return }
        context.saveGState(); context.setStrokeColor(AnnotationRenderer.color(color).withAlphaComponent(opacity).cgColor)
        context.setLineWidth(width); context.beginPath(); context.addPath(geometry.path); context.strokePath(); context.restoreGState()
    }
    private static func mapLine(_ geometry: MapStroke, document: MoonDocument, grid: Bool, context: CGContext) {
        let line = geometry.line
        let ink = MapInk.resolve(document), width = mapWidth(document, major: line.major, grid: grid), opacity = document.style.number(grid ? "grid_opacity" : "contour_opacity", grid ? 0.45 : 0.65)
        context.saveGState()
        if grid && !line.major { context.setLineDash(phase: 0, lengths: [width * 7, width * 4]) }
        stroke(geometry, color: ink.halo, opacity: opacity * 0.65, width: width * 1.8, context: context)
        stroke(geometry, color: grid ? ink.grid : line.major ? ink.index : ink.contour, opacity: opacity, width: width, context: context)
        context.restoreGState()
        if grid, let p = line.captionPosition, let text = line.text {
            let size = max(6, Double(min(document.imageWidth, document.imageHeight)) * 0.009)
            (text as NSString).draw(at: CGPoint(x: p.x, y: p.y - size), withAttributes: [.font: NSFont.systemFont(ofSize: size), .foregroundColor: AnnotationRenderer.color(ink.grid).withAlphaComponent(opacity), .strokeColor: AnnotationRenderer.color(ink.halo), .strokeWidth: -3.5])
        }
    }
    static func releaseSceneTextures() {
        textureLock.lock()
        let previous = latestTextures
        latestTextures = nil
        textureLock.unlock()
        withExtendedLifetime(previous) {}
    }
    private static func cached(_ scene: AnnotationScene) -> SceneTextures {
        textureLock.lock()
        let existing = latestTextures?.id == scene.id ? latestTextures?.value : nil
        textureLock.unlock()
        if let existing { return existing }
        let created = SceneTextures(scene)
        textureLock.lock()
        if let latest = latestTextures, latest.id == scene.id { textureLock.unlock(); return latest.value }
        let previous = latestTextures
        latestTextures = (scene.id, created)
        textureLock.unlock()
        // A drawing/export call retains its own snapshot. Finished scenes no
        // longer keep full-size bitmap copies solely for an unused cache key.
        withExtendedLifetime(previous) {}
        return created
    }
    static func draw(image: CGImage, document: MoonDocument, scene: AnnotationScene?, context: CGContext, editing: Bool = false, editingAnnotationID: UUID? = nil, captureUnderlay: (() -> Void)? = nil) {
        let rect = CGRect(x: 0, y: 0, width: image.width, height: image.height)
        let texture = scene.map(cached)
        drawImage(texture?.grayscale ?? image, rect: rect, context: context)
        context.clip(to: rect)
        if let scene {
            context.saveGState()
            if document.style.litMapOnly, let light = scene.layers.lightness, let texture {
                let level = document.style.threshold ?? light.automaticThreshold
                if texture.threshold != level || texture.coverage == nil { texture.coverage = try? light.coverage(threshold: level).cgImage; texture.threshold = level }
                if let coverage = texture.coverage {
                    // Bitmap masks use the same bottom-up Core Graphics image
                    // convention as drawImage, while photograph coordinates
                    // here run downwards. Keep the clip and restore only CTM.
                    let transform = CGAffineTransform(translationX: rect.minX, y: rect.maxY).scaledBy(x: 1, y: -1)
                    context.concatenate(transform)
                    context.clip(to: CGRect(origin: .zero, size: rect.size), mask: coverage)
                    context.concatenate(transform.inverted())
                }
            }
            if document.style.elevationEnabled, let elevation = texture?.elevation {
                context.saveGState(); context.setAlpha(document.style.number("elevation_opacity", 0.35)); drawImage(elevation, rect: rect, context: context); context.restoreGState()
            }
            for line in texture?.grid ?? [] { mapLine(line, document: document, grid: true, context: context) }
            for line in texture?.contours ?? [] { mapLine(line, document: document, grid: false, context: context) }
            context.restoreGState()
            for line in texture?.terminator ?? [] {
                let ink = MapInk.resolve(document), width = max(2.8, Double(min(document.imageWidth, document.imageHeight)) * 0.0028), opacity = document.style.number("terminator_opacity", 1)
                context.saveGState(); context.setLineDash(phase: 0, lengths: [width * 10, width * 5])
                stroke(line, color: ink.halo, opacity: opacity * 0.65, width: width * 1.8, context: context)
                stroke(line, color: ink.terminator, opacity: opacity, width: width, context: context)
                context.restoreGState()
            }
            captureUnderlay?()
            drawLegend(document, scene: scene, context: context)
        }
        drawDecorations(document, scene: scene, context: context, editing: editing, editingAnnotationID: editingAnnotationID)
    }
    static func drawDecorations(_ document: MoonDocument, scene: AnnotationScene?, context: CGContext, editing: Bool = false, editingAnnotationID: UUID? = nil) {
        let rect = CGRect(x: 0, y: 0, width: document.imageWidth, height: document.imageHeight)
        context.saveGState()
        if let excluded = overviewExclusion(document, scene: scene) {
            if excluded.contains(context.boundingBoxOfClipPath) {
                // A tile wholly inside the card's protection area has no
                // visible annotation work. Keep the card as the top layer.
                context.restoreGState()
                if let scene { drawOverview(document, scene: scene, context: context) }
                return
            }
            let path = CGMutablePath(); path.addRect(rect); path.addRect(excluded)
            context.addPath(path); context.clip(using: .evenOdd)
        }
        let visible = document.annotations.filter { AnnotationSceneBuilder.visible($0, document: document, scene: scene) }
        let captions = preparedCaptions(document)
        // Python's Qt scene puts all locator items at z=10 and all captions at
        // z=20. A later crater's rim must never paint over an earlier caption.
        for annotation in visible {
            let visual = annotation.visual, size = document.settings.fontSize * (visual?.fontScale ?? 1)
            var ink = ThemeInk.resolve(document, landing: visual?.landing ?? false)
            if let color = visual?.color { ink.text = color }
            if locatorVisible(annotation, document: document,
                              editing: editing && (editingAnnotationID == nil || editingAnnotationID == annotation.id), pathBound: captions[annotation.id]?.pathBound) {
                    let anchor = CGPoint(x: annotation.anchor.x, y: annotation.anchor.y)
                    let leader = LabelPlacement.leader(anchor: annotation.anchor, rect: captions[annotation.id]?.bounds ?? labelBounds(annotation, document: document), outline: visual?.outline ?? [])
                    drawLine([leader.start, leader.end], color: ink.line, opacity: 1, width: max(1.2, size * 0.035), context: context)
                    context.setFillColor(AnnotationRenderer.color(ink.text).cgColor)
                    let radius = max(2.5, size * 0.06)
                    if visual?.landing == true {
                        let radius = max(3, size * 0.22)
                        drawLine([PixelPoint(anchor.x - radius, anchor.y), PixelPoint(anchor.x + radius, anchor.y)], color: ink.line, opacity: 1, width: max(1.2, size * 0.045), context: context)
                        drawLine([PixelPoint(anchor.x, anchor.y - radius), PixelPoint(anchor.x, anchor.y + radius)], color: ink.line, opacity: 1, width: max(1.2, size * 0.045), context: context)
                    } else if visual?.outline.isEmpty != false { context.fillEllipse(in: CGRect(x: anchor.x - radius, y: anchor.y - radius, width: radius * 2, height: radius * 2)) }
                    for line in visual?.outline ?? [] { drawLine(line, color: ink.line, opacity: 1, width: max(1.2, size * 0.045), context: context) }
            }
        }
        for annotation in visible {
            guard let geometry = captions[annotation.id], geometry.bounds.intersects(context.boundingBoxOfClipPath) else { continue }
            let size = document.settings.fontSize * (annotation.visual?.fontScale ?? 1)
            var ink = ThemeInk.resolve(document, landing: annotation.visual?.landing ?? false)
            if let color = annotation.visual?.color { ink.text = color }
            context.saveGState(); context.setAlpha(document.style.number("label_opacity", 1))
            let path = geometry.path
            // Match 0.12.1: stroke the complete caption first, then fill it.
            // Attributed-string stroke-and-fill paints overlapping CJK strokes separately.
            context.setLineJoin(.round); context.setLineCap(.round)
            context.addPath(path); context.setStrokeColor(AnnotationRenderer.color(ink.halo).cgColor); context.setLineWidth(haloWidth(document, size: size)); context.strokePath()
            if ink.serif { context.addPath(path); context.setStrokeColor(AnnotationRenderer.color(ink.text).cgColor); context.setLineWidth(max(0.35, size * (["copperplate", "inkwash"].contains(document.style.art) ? 0.028 : 0.012))); context.strokePath() }
            context.addPath(path); context.setFillColor(AnnotationRenderer.color(ink.text).cgColor); context.fillPath()
            context.restoreGState()
        }
        context.restoreGState()
        if let scene { drawOverview(document, scene: scene, context: context) }
    }
    private static func haloWidth(_ document: MoonDocument, size: Double) -> Double {
        if !document.style.isArt { return max(2, size * 0.06) }
        return max(2.4, size * (["copperplate", "inkwash"].contains(document.style.art) ? 0.10 : document.style.art == "redalert" ? 0.12 : 0.16))
    }
    private static func locatorVisible(_ annotation: Annotation, document: MoonDocument, editing: Bool = false, pathBound: Bool? = nil) -> Bool {
        guard document.settings.showLeaders else { return false }
        // Python Annotation.update_map_leader: path-bound captions and art
        // labels only expose their locator while dragged; landing sites keep it.
        if editing || annotation.visual?.landing == true { return true }
        guard !document.style.isArt else { return false }
        if let pathBound { return !pathBound }
        let pathBound = annotation.visual?.pathGlyphs?.isEmpty == false || (annotation.visual?.baseline?.count ?? 0) > 1
        // A caption flattened outside the visible disk is a plain caption again.
        return !pathBound || curvedGlyphs(annotation, document: document).isEmpty
    }
    static func configureCaption(_ annotation: Annotation, feature: Feature, document: MoonDocument) -> Annotation {
        guard annotation.text.count > 1, !annotation.text.contains("\n") else { return annotation }
        let paths = LandformPaths.projected(feature: feature, document: document)
        guard !paths.isEmpty else { return annotation }
        let typography = CaptionTypography.resolve(feature: feature, art: document.style.art)
        let bilingual = [.bilingual, .bilingualTraditional].contains(document.settings.language) && !annotation.hasTextEdit && !feature.chinese.isEmpty && annotation.text.contains(" · ")
        let parts: [String]
        if bilingual, let separator = annotation.text.range(of: " · ") { parts = [String(annotation.text[..<separator.lowerBound]), String(annotation.text[separator.upperBound...])] }
        else { parts = [annotation.text] }
        struct Unit { var text: String, width: Double, family: String }
        struct Row { var units: [Unit], size: Double, offset: Double; var geometry: PathCaptionRow { PathCaptionRow(advances: units.map(\.width), size: size, offset: offset) } }
        func rows(_ size: Double) -> [Row] {
            parts.enumerated().map { index, part in
                let rowSize = index == 0 ? size : max(6, (size * 0.82).rounded(.toNearestOrEven)), face = font(document, size: rowSize, italic: typography.italic), line = shaped(part, font: face, tracking: typography.tracking)
                var clusters: [Int: ShapedGlyph] = [:]
                for glyph in line.glyphs where clusters[glyph.cluster] == nil { clusters[glyph.cluster] = glyph }
                let ordered = clusters.keys.sorted().compactMap { clusters[$0] }
                let rtl = part.unicodeScalars.contains { (0x0590...0x08ff).contains($0.value) || (0xfb1d...0xfdff).contains($0.value) || (0xfe70...0xfeff).contains($0.value) }
                let monotonic = zip(ordered, ordered.dropFirst()).allSatisfy { $1.x >= $0.x }
                let units: [Unit]
                if !rtl && monotonic && !ordered.isEmpty {
                    units = ordered.indices.map { i in Unit(text: ordered[i].text, width: (i + 1 < ordered.count ? ordered[i + 1].x : line.width) - ordered[i].x, family: ordered[i].font) }
                } else { units = [Unit(text: part, width: line.width, family: face.familyName ?? "sans-serif")] }
                return Row(units: units, size: rowSize, offset: (bilingual ? (index == 0 ? -0.22 : 0.98) : 0.15) * size)
            }
        }
        var size = document.settings.fontSize * (annotation.visual?.fontScale ?? 1), prepared = rows(size)
        let span = (prepared.map { $0.units.reduce(0) { $0 + $1.width } }.max() ?? 0) / size
        let fitted = LandformPaths.fittedSize(paths: paths, size: size, span: span)
        var placement: PathCaptionPlacement?
        if fitted != size {
            let smaller = rows(fitted)
            if let result = LandformPaths.place(paths: paths, rows: smaller.map(\.geometry)) { size = fitted; prepared = smaller; placement = result }
        }
        if placement == nil { placement = LandformPaths.place(paths: paths, rows: prepared.map(\.geometry)) }
        guard let placement else { return annotation }
        var configured = annotation, visual = annotation.visual ?? AnnotationVisual(), index = 0, glyphs: [CaptionGlyph] = []
        for row in prepared { for unit in row.units {
            let glyph = placement.glyphs[index]; index += 1
            glyphs.append(CaptionGlyph(text: unit.text, point: glyph.point, angle: glyph.angle, scale: row.size / size, advance: unit.width, family: unit.family))
        } }
        visual.fontScale = size / document.settings.fontSize; visual.pathOrigin = placement.origin; visual.pathGlyphs = glyphs; visual.baseline = nil; visual.baselineOrigin = nil
        configured.visual = visual; return configured
    }
    static func captionPath(_ annotation: Annotation, document: MoonDocument, curves: Bool = true, checkDisk: Bool = true) -> CGPath {
        let path = CGMutablePath(), size = document.settings.fontSize * (annotation.visual?.fontScale ?? 1)
        let curved = curves ? curvedGlyphs(annotation, document: document, checkDisk: checkDisk) : []
        if !curved.isEmpty {
            for glyph in curved { let transform = CGAffineTransform(translationX: glyph.point.x, y: glyph.point.y).rotated(by: glyph.angle).scaledBy(x: 1, y: -1); path.addPath(glyph.path, transform: transform) }
        } else {
            let typography = typography(annotation, document: document), face = font(document, size: size, italic: typography.italic)
            for (row, text) in annotation.text.components(separatedBy: "\n").enumerated() {
                let line = shaped(text, font: face, tracking: typography.tracking)
                for glyph in line.glyphs {
                    let transform = CGAffineTransform(a: 1, b: 0, c: 0, d: -1, tx: annotation.position.x + glyph.x, ty: annotation.position.y + size + Double(row) * (face.ascender - face.descender + face.leading) - glyph.y)
                    path.addPath(glyph.path, transform: transform)
                }
            }
        }
        return path
    }
    private static func typography(_ annotation: Annotation, document: MoonDocument) -> CaptionTypography {
        if let kind = annotation.visual?.featureKind {
            return CaptionTypography.resolve(kind: kind, diameter: annotation.visual?.featureDiameter ?? 0, art: document.style.art)
        }
        return annotation.featureID.flatMap { features[$0] }.map { CaptionTypography.resolve(feature: $0, art: document.style.art) } ?? .standard
    }
    static func font(_ document: MoonDocument, size: Double, italic: Bool = false) -> NSFont {
        let ink = ThemeInk.resolve(document)
        let regular = document.style.isArt ? document.style.art != "redalert" : document.style.string("font_weight", "bold") == "normal"
        let traditional = document.settings.language == .traditional || document.settings.language == .bilingualTraditional
        let name = ink.serif ? (document.style.art == "inkwash" ? (traditional ? "Songti TC" : "Songti SC") : "Baskerville") : ["topographic", "cyanotype", "redalert"].contains(document.style.art) ? (regular ? "AvenirNext-Regular" : "AvenirNext-Bold") : (traditional ? "PingFangTC-" : "PingFangSC-") + (regular ? "Regular" : "Semibold")
        var face = NSFont(name: name, size: size) ?? NSFont.systemFont(ofSize: size, weight: regular ? .regular : .semibold)
        if ink.serif, document.style.art != "inkwash" {
            let fallback = [NSFontDescriptor(fontAttributes: [.family: traditional ? "Songti TC" : "Songti SC"])]
            face = NSFont(descriptor: face.fontDescriptor.addingAttributes([.cascadeList: fallback]), size: size) ?? face
        }
        let fallback = italic ? NSFontManager.shared.convert(face, toHaveTrait: .italicFontMask) : face
        return LabelFonts.preferredFace(document.style.preferredLabelFamily, fallback: fallback, regular: regular, italic: italic) ?? fallback
    }
    private static func attributes(_ document: MoonDocument, annotation: Annotation, ink: ThemeInk) -> [NSAttributedString.Key: Any] {
        let size = document.settings.fontSize * (annotation.visual?.fontScale ?? 1)
        return [.font: font(document, size: size), .foregroundColor: AnnotationRenderer.color(ink.text),
                .strokeColor: AnnotationRenderer.color(ink.halo), .strokeWidth: document.style.isArt ? -6 : -3.5]
    }
    static func labelBounds(_ annotation: Annotation, document: MoonDocument) -> CGRect {
        let size = document.settings.fontSize * (annotation.visual?.fontScale ?? 1)
        let padding = max(5, size * 0.04, haloWidth(document, size: size) / 2 + 1)
        var bounds = captionPath(annotation, document: document, checkDisk: false).boundingBoxOfPath
        if annotation.visual?.pathGlyphs?.isEmpty == false || (annotation.visual?.baseline == nil && typography(annotation, document: document).arc != 0) {
            bounds = bounds.union(captionPath(annotation, document: document, curves: false).boundingBoxOfPath)
        }
        return bounds.insetBy(dx: -padding, dy: -padding)
    }
    private static func drawImage(_ image: CGImage, rect: CGRect, context: CGContext, interpolation: CGInterpolationQuality = .high) {
        context.saveGState(); context.translateBy(x: rect.minX, y: rect.maxY); context.scaleBy(x: 1, y: -1)
        context.interpolationQuality = interpolation; context.draw(image, in: CGRect(origin: .zero, size: rect.size)); context.restoreGState()
    }
    static func drawLine(_ points: [PixelPoint], color: String, opacity: Double, width: Double, context: CGContext) {
        guard let first = points.first, points.count > 1 else { return }
        context.saveGState(); context.setStrokeColor(AnnotationRenderer.color(color).withAlphaComponent(opacity).cgColor); context.setLineWidth(width)
        context.beginPath(); context.move(to: CGPoint(x: first.x, y: first.y)); for point in points.dropFirst() { context.addLine(to: CGPoint(x: point.x, y: point.y)) }; context.strokePath(); context.restoreGState()
    }
    static func overviewRect(_ document: MoonDocument) -> CGRect {
        let size = Double(min(document.imageWidth, document.imageHeight)) * 0.25, margin = Double(min(document.imageWidth, document.imageHeight)) * 0.02, height = size * 366 / 320
        let position = document.style.values["overview_position"]?.array.compactMap(\.number) ?? []
        return CGRect(x: min(max(0, position.first ?? margin), Double(document.imageWidth) - size), y: min(max(0, position.count == 2 ? position[1] : margin), Double(document.imageHeight) - height), width: size, height: height)
    }
    static func overviewExclusion(_ document: MoonDocument, scene: AnnotationScene?) -> CGRect? {
        guard document.style.bool("overview_enabled"), scene?.overview != nil else { return nil }
        // Rims describe fixed lunar geometry. Keep the visible arc and reserve
        // the locator's current position, including a small border clearance.
        let padding = max(2, Double(min(document.imageWidth, document.imageHeight)) * 0.001)
        return overviewRect(document).insetBy(dx: -padding, dy: -padding)
    }
    static func legendRect(_ document: MoonDocument) -> CGRect {
        let unit = Double(min(document.imageWidth, document.imageHeight)) / 100
        let width = min(30 * unit, Double(document.imageWidth) - 4 * unit), height = 6 * unit
        let position = document.style.values["legend_position"]?.array.compactMap(\.number) ?? []
        return CGRect(x: min(max(0, position.first ?? unit * 2), Double(document.imageWidth) - width), y: min(max(0, position.count == 2 ? position[1] : Double(document.imageHeight) - unit * 8), Double(document.imageHeight) - height), width: width, height: height)
    }
    static func drawOverview(_ document: MoonDocument, scene: AnnotationScene, context: CGContext, interactiveZoom: Bool = false) {
        guard document.style.bool("overview_enabled"), let model = scene.overview else { return }
        let rect = overviewRect(document), transform = context.userSpaceToDeviceSpaceTransform
        guard rect.intersects(context.boundingBoxOfClipPath) else { return }
        let density = max(hypot(transform.a, transform.b), hypot(transform.c, transform.d))
        let requested = max(1, rect.width * density)
        let exponent = ceil(log2(requested) * 4) / 4
        let width = max(1, Int(ceil(interactiveZoom ? pow(2, exponent) : requested)))
        let height = max(1, Int(ceil(interactiveZoom ? Double(width) * 366 / 320 : rect.height * density)))
        guard let card = try? OverviewCard.bitmap(model, style: document.style.art, sceneID: scene.id,
            width: width, height: height) else { return }
        context.saveGState(); context.clip(to: rect)
        drawImage(card, rect: rect, context: context, interpolation: interactiveZoom ? .medium : .none)
        context.restoreGState()
    }
    private static let elevationStops = [-9.0, -4, -1.5, 0, 2, 5, 9].map { CGFloat(($0 + 9) / 18) }
    private static func legendVisible(_ document: MoonDocument, _ scene: AnnotationScene) -> Bool {
        (document.style.elevationEnabled && scene.layers.elevation != nil) || (document.style.contourEnabled && scene.layers.raster != nil)
    }
    static func visibleLegendRect(_ document: MoonDocument, scene: AnnotationScene?) -> CGRect? {
        guard let scene, legendVisible(document, scene) else { return nil }
        return legendRect(document)
    }
    private static func legendTitle(_ document: MoonDocument, _ scene: AnnotationScene) -> String {
        if document.style.contourEnabled {
            if let interval = scene.layers.contourInterval ?? document.style.contourInterval { return "LOLA · km · Δh = \(String(format: "%g", interval)) km" }
            return "LOLA · km"
        }
        return "LOLA · km (R = 1737.4 km)"
    }
    private static func legendIndex(_ document: MoonDocument, _ scene: AnnotationScene) -> String {
        let prefix = (scene.layers.contourInterval ?? document.style.contourInterval).map { "Index: \(String(format: "%g", $0 * 5)) km · " } ?? ""
        return prefix + "R = 1737.4 km"
    }
    static func drawLegend(_ document: MoonDocument, scene: AnnotationScene, context: CGContext) {
        guard legendVisible(document, scene) else { return }
        let rect = legendRect(document), u = rect.height / 6, ink = LegendInk.resolve(document)
        context.saveGState(); context.setFillColor(AnnotationRenderer.color(ink.background).withAlphaComponent(ink.alpha).cgColor)
        let box = CGPath(roundedRect: rect, cornerWidth: u * 0.4, cornerHeight: u * 0.4, transform: nil)
        context.addPath(box); context.fillPath()
        if !ink.border.isEmpty { context.addPath(box); context.setStrokeColor(AnnotationRenderer.color(ink.border).cgColor); context.setLineWidth(max(0.5, u * 0.045)); context.strokePath() }
        let size = max(1, u.rounded(.toNearestOrEven)), face = ink.serif ? NSFont(name: "Times", size: size) ?? NSFont.systemFont(ofSize: size) : NSFont.systemFont(ofSize: size)
        let attributes: [NSAttributedString.Key: Any] = [.font: face, .foregroundColor: AnnotationRenderer.color(ink.foreground)]
        func text(_ value: String, _ x: Double, _ y: Double, alignment: Double = 0) {
            let caption = NSAttributedString(string: value, attributes: attributes)
            caption.draw(at: CGPoint(x: x - caption.size().width * alignment, y: y - face.ascender))
        }
        text(legendTitle(document, scene), rect.minX + u, rect.minY + u * 1.5)
        if document.style.elevationEnabled {
            let palette = MapBuilder.palettes[document.style.string("elevation_palette", "terrain")] ?? MapBuilder.palettes["terrain"]!
            if let gradient = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB), colors: palette.map { AnnotationRenderer.color($0).cgColor } as CFArray, locations: elevationStops) {
                let bar = CGRect(x: rect.minX + u, y: rect.minY + u * 2.2, width: rect.width - 2 * u, height: u)
                context.saveGState(); context.clip(to: bar); context.drawLinearGradient(gradient, start: CGPoint(x: bar.minX, y: bar.midY), end: CGPoint(x: bar.maxX, y: bar.midY), options: []); context.restoreGState()
            }
            text("≤ −9", rect.minX + u, rect.minY + u * 4.8)
            text("0", rect.midX, rect.minY + u * 4.8, alignment: 0.5)
            text("≥ +9", rect.maxX - u, rect.minY + u * 4.8, alignment: 1)
        } else {
            drawLine([PixelPoint(rect.minX + u, rect.minY + u * 2.7), PixelPoint(rect.maxX - u, rect.minY + u * 2.7)], color: ink.sample, opacity: 1, width: max(1, u * 0.12), context: context)
            text(legendIndex(document, scene), rect.minX + u, rect.minY + u * 4.8)
        }
        context.restoreGState()
    }
    private static func curvedGlyphs(_ annotation: Annotation, document: MoonDocument, checkDisk: Bool = true) -> [CurvedGlyph] {
        let size = document.settings.fontSize * (annotation.visual?.fontScale ?? 1), typography = typography(annotation, document: document)
        var result: [CurvedGlyph] = []
        if let glyphs = annotation.visual?.pathGlyphs, !glyphs.isEmpty {
            if checkDisk, let camera = document.calibration {
                let padding = haloWidth(document, size: size) / 2
                for glyph in glyphs where !glyph.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    let angle = glyph.angle * .pi / 180, rowSize = size * glyph.scale
                    for x in [-padding, glyph.advance + padding] { for y in [-rowSize - padding, rowSize * 0.25 + padding] {
                        let p = PixelPoint(annotation.position.x + glyph.point.x + x * cos(angle) - y * sin(angle), annotation.position.y + glyph.point.y + x * sin(angle) + y * cos(angle))
                        if !camera.geometry.unproject(camera.modelPoint(p)).visible { return [] }
                    } }
                }
            }
            for glyph in glyphs {
                let rowSize = size * glyph.scale, angle = glyph.angle * .pi / 180, line = shaped(glyph.text, font: font(document, size: rowSize, italic: typography.italic), tracking: typography.tracking)
                for part in line.glyphs {
                    let x = part.x, y = -part.y
                    let point = CGPoint(x: annotation.position.x + glyph.point.x + x * cos(angle) - y * sin(angle), y: annotation.position.y + glyph.point.y + x * sin(angle) + y * cos(angle))
                    result.append(CurvedGlyph(path: part.path, text: part.text, point: point, angle: angle, size: rowSize, font: part.font))
                }
            }
            return result
        }
        guard var points = annotation.visual?.baseline, points.count > 1 else {
            guard typography.arc != 0, annotation.text.count > 1 else { return [] }
            let width = typography.span(annotation.text) * size, rise = width * typography.arc, face = font(document, size: size, italic: typography.italic)
            var cursor = 0.0
            for character in annotation.text.unicodeScalars {
                let advance = CaptionTypography.advance(character) * size, center = cursor + advance / 2, ratio = 2 * center / max(1, width) - 1
                let angle = atan(4 * rise / max(1, width) * ratio), baseline = size - rise * (1 - ratio * ratio)
                for glyph in shaped(String(character), font: face).glyphs {
                    let x = glyph.x - advance / 2, y = -glyph.y
                    let point = CGPoint(x: annotation.position.x + center + cos(angle) * x - sin(angle) * y, y: annotation.position.y + baseline + sin(angle) * x + cos(angle) * y)
                    result.append(CurvedGlyph(path: glyph.path, text: glyph.text, point: point, angle: angle, size: size, font: glyph.font))
                }
                cursor += advance + size * typography.tracking
            }
            return !checkDisk || captionOnDisk(result, document: document) ? result : []
        }
        if let origin = annotation.visual?.baselineOrigin {
            let dx = annotation.position.x - origin.x, dy = annotation.position.y - origin.y
            points = points.map { PixelPoint($0.x + dx, $0.y + dy) }
        }
        var lengths = [0.0]
        for (a, b) in zip(points, points.dropFirst()) { lengths.append(lengths.last! + hypot(b.x - a.x, b.y - a.y)) }
        let total = lengths.last!
        func location(_ distance: Double) -> (CGPoint, Double) {
            let distance = min(total, max(0, distance)), upper = min(points.count - 1, lengths.firstIndex(where: { $0 >= distance }) ?? points.count - 1), lower = max(0, upper - 1)
            let a = points[lower], b = points[upper], f = (distance - lengths[lower]) / max(1e-8, lengths[upper] - lengths[lower])
            return (CGPoint(x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f), atan2(b.y - a.y, b.x - a.x))
        }
        let hasChineseName = annotation.visual?.hasChineseName ?? (annotation.featureID.flatMap { features[$0] }?.chinese.isEmpty == false)
        let bilingual = [.bilingual, .bilingualTraditional].contains(document.settings.language) && !annotation.hasTextEdit && hasChineseName && annotation.text.contains(" · ")
        let rows = bilingual ? annotation.text.components(separatedBy: " · ") : annotation.text.components(separatedBy: "\n")
        for (row, text) in rows.enumerated() {
            let fontSize = row == 0 ? size : max(6, (size * 0.82).rounded(.toNearestOrEven)), face = font(document, size: fontSize, italic: typography.italic)
            let line = shaped(text, font: face, tracking: typography.tracking), offset = max(0, (total - line.width) / 2)
            for glyph in line.glyphs {
                    let (point, angle) = location(offset + glyph.x)
                    let normal = (bilingual ? (row == 0 ? -0.22 : 0.98) : 0.15) * size - glyph.y
                    let position = CGPoint(x: point.x - sin(angle) * normal, y: point.y + cos(angle) * normal)
                    result.append(CurvedGlyph(path: glyph.path, text: glyph.text, point: position, angle: angle, size: fontSize, font: glyph.font))
            }
        }
        return !checkDisk || captionOnDisk(result, document: document) ? result : []
    }
    private static func captionOnDisk(_ glyphs: [CurvedGlyph], document: MoonDocument) -> Bool {
        guard let camera = document.calibration else { return true }
        return glyphs.allSatisfy { glyph in
            if glyph.path.isEmpty { return true }
            let box = glyph.path.boundingBoxOfPath, padding = haloWidth(document, size: glyph.size) / 2
            return [box.minX - padding, box.maxX + padding].allSatisfy { x in [box.minY - padding, box.maxY + padding].allSatisfy { y in
                let pixel = PixelPoint(glyph.point.x + cos(glyph.angle) * x + sin(glyph.angle) * y, glyph.point.y + sin(glyph.angle) * x - cos(glyph.angle) * y)
                return camera.geometry.unproject(camera.modelPoint(pixel)).visible
            } }
        }
    }
}

extension SceneRenderer {
    private static func escape(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;").replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
    }
    static func svg(image: CGImage, document: MoonDocument, scene: AnnotationScene?, to url: URL) throws {
        func dataURL(_ image: CGImage) throws -> String {
            let data = NSMutableData()
            guard let destination = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else { throw MoonError.invalid("无法创建 SVG 底图。") }
            CGImageDestinationAddImage(destination, image, nil)
            guard CGImageDestinationFinalize(destination) else { throw MoonError.invalid("SVG 底图编码失败。") }
            return "data:image/png;base64," + (data as Data).base64EncodedString()
        }
        func path(_ points: [PixelPoint]) -> String {
            points.enumerated().map { index, point in String(format: "%@ %.4f,%.4f", index == 0 ? "M" : "L", point.x, point.y) }.joined(separator: " ")
        }
        func line(_ points: [PixelPoint], color: String, width: Double, opacity: Double = 1, dash: String = "") -> String {
            "<path d=\"\(path(points))\" fill=\"none\" stroke=\"\(escape(color))\" stroke-width=\"\(width)\" opacity=\"\(opacity)\"\(dash.isEmpty ? "" : " stroke-dasharray=\"\(dash)\"")/>"
        }
        func bitmap(_ image: CGImage, rect: CGRect, opacity: Double = 1) throws -> String {
            "<image x=\"\(rect.minX)\" y=\"\(rect.minY)\" width=\"\(rect.width)\" height=\"\(rect.height)\" opacity=\"\(opacity)\" xlink:href=\"\(try dataURL(image))\"/>"
        }
        let rect = CGRect(x: 0, y: 0, width: image.width, height: image.height), texture = scene.map(cached)
        var lines = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<svg xmlns=\"http://www.w3.org/2000/svg\" xmlns:xlink=\"http://www.w3.org/1999/xlink\" width=\"\(image.width)\" height=\"\(image.height)\" viewBox=\"0 0 \(image.width) \(image.height)\">",
                     try bitmap(texture?.grayscale ?? image, rect: rect)]
        if let scene {
            let mapInk = MapInk.resolve(document)
            func mapPath(_ item: MapLine, grid: Bool) -> String {
                let width = mapWidth(document, major: item.major, grid: grid), opacity = document.style.number(grid ? "grid_opacity" : "contour_opacity", grid ? 0.45 : 0.65)
                let dash = grid && !item.major ? "\(width * 7),\(width * 4)" : ""
                var content = line(item.points, color: mapInk.halo, width: width * 1.8, opacity: opacity * 0.65, dash: dash) + line(item.points, color: grid ? mapInk.grid : item.major ? mapInk.index : mapInk.contour, width: width, opacity: opacity, dash: dash)
                if grid, let text = item.text, let p = item.captionPosition {
                    let size = max(6, Double(min(document.imageWidth, document.imageHeight)) * 0.009)
                    content += "<text x=\"\(p.x)\" y=\"\(p.y)\" font-family=\"sans-serif\" font-size=\"\(size)\" fill=\"\(mapInk.grid)\" stroke=\"\(mapInk.halo)\" stroke-width=\"\(size * 0.035)\" paint-order=\"stroke fill\" opacity=\"\(opacity)\">\(escape(text))</text>"
                }
                return content
            }
            var masked = false
            if document.style.litMapOnly, let light = scene.layers.lightness {
                let alpha = try light.coverage(threshold: document.style.threshold)
                lines.append("<defs><mask id=\"photo-light\" mask-type=\"alpha\" maskUnits=\"userSpaceOnUse\" x=\"0\" y=\"0\" width=\"\(image.width)\" height=\"\(image.height)\">\(try bitmap(alpha.cgImage, rect: rect))</mask></defs>")
                lines.append("<g mask=\"url(#photo-light)\">"); masked = true
            } else { lines.append("<g>") }
            if document.style.elevationEnabled, let elevation = texture?.elevation { lines.append(try bitmap(elevation, rect: rect, opacity: document.style.number("elevation_opacity", 0.35))) }
            for item in scene.layers.grid { lines.append(mapPath(item, grid: true)) }
            for item in scene.layers.contours { lines.append(mapPath(item, grid: false)) }
            lines.append("</g>")
            _ = masked
            for item in scene.layers.terminator {
                let width = max(2.8, Double(min(document.imageWidth, document.imageHeight)) * 0.0028), opacity = document.style.number("terminator_opacity", 1), dash = "\(width * 10),\(width * 5)"
                lines.append(line(item.points, color: mapInk.halo, width: width * 1.8, opacity: opacity * 0.65, dash: dash))
                lines.append(line(item.points, color: mapInk.terminator, width: width, opacity: opacity, dash: dash))
            }
            if legendVisible(document, scene) {
                let box = legendRect(document), u = box.height / 6, ink = LegendInk.resolve(document)
                let border = ink.border.isEmpty ? "" : " stroke=\"\(ink.border)\" stroke-width=\"\(max(0.5, u * 0.045))\""
                lines.append("<g id=\"elevation-legend\" font-family=\"\(ink.serif ? "serif" : "sans-serif")\" font-size=\"\(max(1, u.rounded(.toNearestOrEven)))\" fill=\"\(ink.foreground)\"><rect x=\"\(box.minX)\" y=\"\(box.minY)\" width=\"\(box.width)\" height=\"\(box.height)\" rx=\"\(u * 0.4)\" fill=\"\(ink.background)\" fill-opacity=\"\(ink.alpha)\"\(border)/>")
                lines.append("<text x=\"\(box.minX + u)\" y=\"\(box.minY + u * 1.5)\">\(escape(legendTitle(document, scene)))</text>")
                if document.style.elevationEnabled {
                    let colors = MapBuilder.palettes[document.style.string("elevation_palette", "terrain")] ?? MapBuilder.palettes["terrain"]!
                    let stops = colors.indices.map { "<stop offset=\"\(elevationStops[$0])\" stop-color=\"\(colors[$0])\"/>" }.joined()
                    lines.append("<defs><linearGradient id=\"elevation-ramp\">\(stops)</linearGradient></defs><rect x=\"\(box.minX + u)\" y=\"\(box.minY + u * 2.2)\" width=\"\(box.width - 2 * u)\" height=\"\(u)\" fill=\"url(#elevation-ramp)\"/>")
                    for (text, x, anchor) in [("≤ −9", box.minX + u, "start"), ("0", box.midX, "middle"), ("≥ +9", box.maxX - u, "end")] { lines.append("<text x=\"\(x)\" y=\"\(box.minY + u * 4.8)\" text-anchor=\"\(anchor)\">\(text)</text>") }
                } else {
                    lines.append(line([PixelPoint(box.minX + u, box.minY + u * 2.7), PixelPoint(box.maxX - u, box.minY + u * 2.7)], color: ink.sample, width: max(1, u * 0.12)))
                    lines.append("<text x=\"\(box.minX + u)\" y=\"\(box.minY + u * 4.8)\">\(escape(legendIndex(document, scene)))</text>")
                }
                lines.append("</g>")
            }
        }
        let excluded = overviewExclusion(document, scene: scene)
        if let excluded {
            // Opposite winding also preserves the hole in native SVG readers
            // that use the nonzero rule for clip paths.
            let boundary = "M 0,0 H \(image.width) V \(image.height) H 0 Z M \(excluded.minX),\(excluded.minY) V \(excluded.maxY) H \(excluded.maxX) V \(excluded.minY) Z"
            lines.append("<defs><clipPath id=\"annotation-overview-clip\" clipPathUnits=\"userSpaceOnUse\"><path d=\"\(boundary)\" clip-rule=\"evenodd\"/></clipPath></defs><g clip-path=\"url(#annotation-overview-clip)\">")
        }
        let visible = document.annotations.filter { AnnotationSceneBuilder.visible($0, document: document, scene: scene) }
        lines.append("<g id=\"annotation-locators\">")
        for annotation in visible {
            let visual = annotation.visual, size = document.settings.fontSize * (visual?.fontScale ?? 1), bounds = labelBounds(annotation, document: document)
            var appearance = ThemeInk.resolve(document, landing: visual?.landing ?? false)
            appearance.text = visual?.color ?? appearance.text
            lines.append("<g id=\"locator-\(annotation.id.uuidString)\">")
            if locatorVisible(annotation, document: document) {
                let leader = LabelPlacement.leader(anchor: annotation.anchor, rect: bounds, outline: visual?.outline ?? [])
                lines.append(line([leader.start, leader.end], color: appearance.line, width: max(1.2, size * 0.035)))
                if visual?.landing == true {
                    let r = max(3, size * 0.22), x = annotation.anchor.x, y = annotation.anchor.y
                    lines.append(line([PixelPoint(x - r, y), PixelPoint(x + r, y)], color: appearance.line, width: max(1.2, size * 0.045)))
                    lines.append(line([PixelPoint(x, y - r), PixelPoint(x, y + r)], color: appearance.line, width: max(1.2, size * 0.045)))
                } else if visual?.outline.isEmpty != false { lines.append("<circle cx=\"\(annotation.anchor.x)\" cy=\"\(annotation.anchor.y)\" r=\"\(max(2.5, size * 0.06))\" fill=\"\(appearance.text)\"/>") }
                for outline in visual?.outline ?? [] { lines.append(line(outline, color: appearance.line, width: max(1.2, size * 0.045))) }
            }
            lines.append("</g>")
        }
        lines.append("</g>")
        for annotation in visible {
            let visual = annotation.visual, size = document.settings.fontSize * (visual?.fontScale ?? 1)
            var appearance = ThemeInk.resolve(document, landing: visual?.landing ?? false)
            appearance.text = visual?.color ?? appearance.text
            lines.append("<g id=\"label-\(annotation.id.uuidString)\">")
            let opacity = document.style.number("label_opacity", 1), glyphs = curvedGlyphs(annotation, document: document)
            let typography = typography(annotation, document: document)
            let weight = document.style.isArt ? (document.style.art == "redalert" ? "bold" : "normal") : document.style.string("font_weight", "bold")
            let textStyle = "font-weight=\"\(weight)\" font-style=\"\(typography.italic ? "italic" : "normal")\""
            var captions: [String] = []
            if !glyphs.isEmpty {
                for glyph in glyphs { captions.append("<text x=\"\(glyph.point.x)\" y=\"\(glyph.point.y)\" transform=\"rotate(\(glyph.angle * 180 / .pi),\(glyph.point.x),\(glyph.point.y))\" font-family=\"\(escape(glyph.font))\" font-size=\"\(glyph.size)\" \(textStyle)>\(escape(glyph.text))</text>") }
            } else {
                let face = font(document, size: size, italic: typography.italic)
                let family = (face.familyName ?? "sans-serif") + (appearance.serif && document.style.art != "inkwash" ? (document.settings.language == .traditional || document.settings.language == .bilingualTraditional ? ",Songti TC,serif" : ",Songti SC,serif") : "")
                captions.append("<text font-family=\"\(escape(family))\" font-size=\"\(size)\" \(textStyle) xml:space=\"preserve\" aria-label=\"\(escape(annotation.text))\">")
                for (row, text) in annotation.text.components(separatedBy: "\n").enumerated() {
                    let baseline = annotation.position.y + size + Double(row) * (face.ascender - face.descender + face.leading), line = shaped(text, font: face, tracking: typography.tracking)
                    if !document.style.preferredLabelFamily.isEmpty {
                        captions += editableFontRuns(line, x: annotation.position.x, baseline: baseline)
                    } else if annotation.featureID != nil {
                        var emitted = Set<Int>()
                        for glyph in line.glyphs where emitted.insert(glyph.cluster).inserted {
                            captions.append("<tspan x=\"\(annotation.position.x + glyph.x)\" y=\"\(baseline - glyph.y)\" font-family=\"\(escape(glyph.font))\">\(escape(glyph.text))</tspan>")
                        }
                    } else {
                        captions.append("<tspan x=\"\(annotation.position.x)\" y=\"\(baseline)\" textLength=\"\(line.width)\" lengthAdjust=\"spacing\">\(escape(text))</tspan>")
                    }
                }
                captions.append("</text>")
            }
            let content = captions.joined(), faceWidth = appearance.serif ? max(0.35, size * (["copperplate", "inkwash"].contains(document.style.art) ? 0.028 : 0.012)) : 0
            lines.append("<g class=\"caption\" opacity=\"\(opacity)\" stroke-linejoin=\"round\" stroke-linecap=\"round\"><g fill=\"none\" stroke=\"\(escape(appearance.halo))\" stroke-width=\"\(haloWidth(document, size: size))\">\(content)</g><g fill=\"\(escape(appearance.text))\" stroke=\"\(faceWidth > 0 ? escape(appearance.text) : "none")\" stroke-width=\"\(faceWidth)\">\(content)</g>")
            lines.append("</g></g>")
        }
        if excluded != nil { lines.append("</g>") }
        if document.style.bool("overview_enabled"), let model = scene?.overview {
            let box = overviewRect(document)
            lines.append("<g id=\"photo-field-overview\" transform=\"translate(\(box.minX) \(box.minY)) scale(\(box.width / 320))\">")
            lines.append(try OverviewCard.markup(model, style: document.style.art))
            lines.append("</g>")
        }
        lines.append("</svg>")
        try lines.joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
    }
}
