// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import MoonCore

private enum CanvasRasterMemory {
    private static let lock = NSLock()
    private static var bytes = 0
    static func adjust(_ value: Int) { lock.lock(); bytes += value; lock.unlock() }
    static var usage: Int { lock.lock(); defer { lock.unlock() }; return bytes }
}

/// Display-only raster reuse in photograph coordinates. Panning changes the
/// transform, not the content. Exports continue to use SceneRenderer directly.
@MainActor
final class CanvasRenderCache {
    private struct Key: Equatable {
        var document: MoonDocument
        var sceneID: UUID?
        var editing: Bool
        var editingAnnotationID: UUID?
    }
    private struct Overlays: Equatable {
        var legend: CGRect? = nil
        func changedRegions(from previous: Overlays) -> [CGRect] {
            var regions: [CGRect?] = []
            if legend != previous.legend { regions += [previous.legend, legend] }
            return regions.compactMap { $0 }
        }
    }
    private final class Tile: NSObject {
        let image: CGImage, overlays: Overlays
        let rect: CGRect
        let underlay: CGImage?
        var displayedOverlays: Overlays
        var patches: [Tile] = []
        let bitmapBytes: Int
        var cacheCost: Int { bitmapBytes + patches.reduce(0) { $0 + $1.cacheCost } }
        init(_ image: CGImage, rect: CGRect, overlays: Overlays = Overlays(), underlay: CGImage? = nil) {
            self.image = image; self.rect = rect; self.overlays = overlays; displayedOverlays = overlays; self.underlay = underlay
            bitmapBytes = image.bytesPerRow * image.height + (underlay.map { $0.bytesPerRow * $0.height } ?? 0)
            CanvasRasterMemory.adjust(bitmapBytes)
        }
        deinit { CanvasRasterMemory.adjust(-bitmapBytes) }
    }
    private var key: Key?
    private var source: CGImage?
    private var full: Tile?
    private var fullDensity: CGFloat?
    private var tileDensity: CGFloat?
    private var presentationDensity: CGFloat?
    private let tiles = NSCache<NSString, Tile>()
    private var visibleTiles: [String: Tile] = [:]
    private let maximumRasterPixels: Int
    private let tilePixels: Int
    private(set) var rasterizationCount = 0
    private(set) var overlayUpdateCount = 0
    private(set) var needsRefinement = false
    var cachedTileDensity: CGFloat? { tileDensity }
    var cachedPixelSize: CGSize? { full.map { CGSize(width: $0.image.width, height: $0.image.height) } }
    static var retainedBitmapBytes: Int { CanvasRasterMemory.usage }

    init(maximumRasterPixels: Int = 12_000_000, tilePixels: Int = 768) {
        self.maximumRasterPixels = max(1, maximumRasterPixels)
        self.tilePixels = max(16, tilePixels)
        tiles.totalCostLimit = self.maximumRasterPixels * 4
    }
    func clear() { key = nil; source = nil; full = nil; fullDensity = nil; tileDensity = nil; visibleTiles = [:]; tiles.removeAllObjects() }

    func draw(image: CGImage, document displayedDocument: MoonDocument, scene: AnnotationScene?, context: CGContext, editing: Bool, editingAnnotationID: UUID? = nil, interactiveZoom: Bool = false, viewport: CGRect? = nil) {
        needsRefinement = false
        let frameStart = ProcessInfo.processInfo.systemUptime
        // AppKit's CTM omits the backing-store transform on a Retina window.
        let transform = context.userSpaceToDeviceSpaceTransform
        let density = max(hypot(transform.a, transform.b), hypot(transform.c, transform.d))
        guard density.isFinite, density > 0 else { return }
        let scalingCard = interactiveZoom || (presentationDensity != nil && presentationDensity != density)
        presentationDensity = density
        let photo = CGRect(x: 0, y: 0, width: image.width, height: image.height)
        context.clip(to: photo)
        let visible = context.boundingBoxOfClipPath.intersection(photo)
        guard !visible.isEmpty, !visible.isNull else { return }
        let overview = SceneRenderer.overviewExclusion(displayedDocument, scene: scene)
        var usesCache = true
        defer {
            if usesCache, let overview, let scene, overview.intersects(context.boundingBoxOfClipPath) {
                context.saveGState(); context.clip(to: overview)
                SceneRenderer.drawLegend(displayedDocument, scene: scene, context: context)
                context.restoreGState()
                SceneRenderer.drawOverview(displayedDocument, scene: scene, context: context, interactiveZoom: scalingCard)
            }
        }
        var document = displayedDocument
        document.changeStyle { $0.set("overview_enabled", false) }
        var content = document
        content.changeStyle { $0.values.removeValue(forKey: "legend_position"); $0.values.removeValue(forKey: "overview_position") }
        let next = Key(document: content, sceneID: scene?.id, editing: editing, editingAnnotationID: editingAnnotationID)
        if source !== image || key != next {
            clear(); source = image; key = next
        }
        let pixels = ceil(photo.width * density) * ceil(photo.height * density)
        let art = document.style.isArt
        let hasUnderlay = scene?.overview != nil || overlayRects(document, scene: scene) != Overlays()
        let rasterPixelBudget = max(1, maximumRasterPixels / (hasUnderlay ? 2 : 1))
        if interactiveZoom {
            if full == nil {
                let previewDensity = min(density, sqrt(Double(max(1, rasterPixelBudget / 3)) / (photo.width * photo.height)))
                full = raster(photo, density: previewDensity, image: image, document: document, scene: scene, editing: editing, editingAnnotationID: editingAnnotationID)
                fullDensity = previewDensity
                updateTileBudget()
            }
            if let full, let refreshed = refreshingOverlays(full, document: document, scene: scene, editing: editing, editingAnnotationID: editingAnnotationID) {
                self.full = refreshed; present(refreshed, overview: overview, context: context); return
            }
        }
        let reusableFull = fullDensity.map { art ? $0 >= density : $0 == density } ?? false
        if pixels <= Double(rasterPixelBudget) && (!art || full == nil || reusableFull) {
            if full == nil || !reusableFull {
                tiles.removeAllObjects(); visibleTiles = [:]; tileDensity = nil
                let target = art ? min(density * 1.25, sqrt(Double(rasterPixelBudget) / (photo.width * photo.height))) : density
                full = raster(photo, density: target, image: image, document: document, scene: scene, editing: editing, editingAnnotationID: editingAnnotationID)
                fullDensity = target
                updateTileBudget()
            }
            if let full, let refreshed = refreshingOverlays(full, document: document, scene: scene, editing: editing, editingAnnotationID: editingAnnotationID) {
                self.full = refreshed; present(refreshed, overview: overview, context: context); return
            }
        } else {
            // Zoom gestures use the preview above. Once settled, match the
            // actual backing density so each drag frame can copy sharp tiles
            // without resampling every art/underlay pixel again.
            let target = density
            if tileDensity != target { tiles.removeAllObjects(); visibleTiles = [:]; tileDensity = target }
            if art && full == nil {
                let preview = min(density, sqrt(Double(max(1, rasterPixelBudget / 6)) / (photo.width * photo.height)))
                full = raster(photo, density: preview, image: image, document: document, scene: scene, editing: editing, editingAnnotationID: editingAnnotationID)
                fullDensity = preview
            }
            trimZoomPreview()
            updateTileBudget()
            let span = CGFloat(art ? min(tilePixels, 384) : tilePixels) / target
            let firstX = max(0, Int(floor(visible.minX / span))), lastX = max(firstX, Int(ceil(visible.maxX / span)) - 1)
            let firstY = max(0, Int(floor(visible.minY / span))), lastY = max(firstY, Int(ceil(visible.maxY / span)) - 1)
            context.saveGState(); context.clip(to: photo)
            defer { context.restoreGState() }
            var generated = false
            let retainedRegion = viewport?.intersection(photo) ?? visible
            var nextVisible = visibleTiles.filter { $0.value.rect.intersects(retainedRegion) }
            for y in firstY...lastY { for x in firstX...lastX {
                let name = "\(x):\(y)"
                let core = CGRect(x: CGFloat(x) * span, y: CGFloat(y) * span, width: span, height: span)
                var tile = visibleTiles[name] ?? tiles.object(forKey: name as NSString)
                // Refine art tiles over successive display turns. Existing
                // high-resolution tiles remain usable while input continues.
                if tile == nil && art && full != nil && generated && ProcessInfo.processInfo.systemUptime - frameStart >= 0.008 {
                    if let preview = full, let refreshed = refreshingOverlays(preview, document: document, scene: scene, editing: editing, editingAnnotationID: editingAnnotationID) {
                        full = refreshed
                        context.saveGState(); context.setShouldAntialias(false); context.clip(to: core)
                        present(refreshed, overview: overview, context: context); context.restoreGState()
                    }
                    needsRefinement = true; continue
                }
                if tile == nil {
                    // Guard pixels keep interpolation from sampling transparent
                    // edges between adjacent tiles, including bucketed scales.
                    let guardBand: CGFloat = art ? 4 : 2
                    tile = raster(core.insetBy(dx: -guardBand / target, dy: -guardBand / target), density: target,
                                  image: image, document: document, scene: scene, editing: editing, editingAnnotationID: editingAnnotationID)
                    generated = true
                }
                guard let tile, let refreshed = refreshingOverlays(tile, document: document, scene: scene, editing: editing, editingAnnotationID: editingAnnotationID) else {
                    usesCache = false; SceneRenderer.draw(image: image, document: displayedDocument, scene: scene, context: context, editing: editing, editingAnnotationID: editingAnnotationID); return
                }
                nextVisible[name] = refreshed
                tiles.setObject(refreshed, forKey: name as NSString, cost: refreshed.cacheCost)
                context.saveGState(); context.setShouldAntialias(false); context.clip(to: core)
                present(refreshed, overview: overview, context: context); context.restoreGState()
            } }
            // NSCache may discard an object as soon as it is inserted. Retain
            // the current viewport so refinement cannot restart indefinitely.
            visibleTiles = nextVisible
            return
        }
        usesCache = false; SceneRenderer.draw(image: image, document: displayedDocument, scene: scene, context: context, editing: editing, editingAnnotationID: editingAnnotationID)
    }

    private func updateTileBudget() {
        let used = full?.cacheCost ?? 0
        tiles.totalCostLimit = max((tilePixels + 4) * (tilePixels + 4) * 4, maximumRasterPixels * 4 - used)
    }
    private func trimZoomPreview() {
        guard let full else { return }
        let layers = full.underlay == nil ? 1 : 2
        let pixels = full.image.width * full.image.height, budget = max(1, maximumRasterPixels / (6 * layers))
        guard pixels > budget else { return }
        let ratio = sqrt(Double(budget) / Double(pixels))
        let width = max(1, Int(Double(full.image.width) * ratio)), height = max(1, Int(Double(full.image.height) * ratio))
        guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return }
        context.interpolationQuality = .high; context.draw(full.image, in: CGRect(x: 0, y: 0, width: width, height: height))
        if let image = context.makeImage() {
            var underlay: CGImage?
            if let original = full.underlay {
                context.clear(CGRect(x: 0, y: 0, width: width, height: height))
                context.draw(original, in: CGRect(x: 0, y: 0, width: width, height: height)); underlay = context.makeImage()
            }
            self.full = Tile(image, rect: full.rect, overlays: full.overlays, underlay: underlay); fullDensity = nil
        }
    }

    private func raster(_ rect: CGRect, density: CGFloat, image: CGImage, document: MoonDocument, scene: AnnotationScene?, editing: Bool, editingAnnotationID: UUID?) -> Tile? {
        let width = max(1, Int(ceil(rect.width * density))), height = max(1, Int(ceil(rect.height * density)))
        let extent = CGRect(x: rect.minX, y: rect.minY, width: CGFloat(width) / density, height: CGFloat(height) / density)
        guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                                      space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        context.translateBy(x: -extent.minX * density, y: extent.maxY * density)
        context.scaleBy(x: density, y: -density)
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
        var underlay: CGImage?
        let overlays = overlayRects(document, scene: scene)
        let needsUnderlay = overlays != Overlays() || scene?.overview != nil
        SceneRenderer.draw(image: image, document: document, scene: scene, context: context, editing: editing, editingAnnotationID: editingAnnotationID,
                           captureUnderlay: { if needsUnderlay { underlay = context.makeImage() } })
        NSGraphicsContext.restoreGraphicsState()
        guard let result = context.makeImage(), !needsUnderlay || underlay != nil else { return nil }
        rasterizationCount += 1
        return Tile(result, rect: extent, overlays: overlays, underlay: underlay)
    }
    private func overlayRects(_ document: MoonDocument, scene: AnnotationScene?) -> Overlays {
        Overlays(legend: SceneRenderer.visibleLegendRect(document, scene: scene))
    }
    private func refreshingOverlays(_ tile: Tile, document: MoonDocument, scene: AnnotationScene?, editing: Bool, editingAnnotationID: UUID?) -> Tile? {
        let overlays = overlayRects(document, scene: scene)
        guard tile.displayedOverlays != overlays else { return tile }
        if tile.overlays == overlays {
            tile.patches = []; tile.displayedOverlays = overlays; return tile
        }
        let sx = CGFloat(tile.image.width) / tile.rect.width, sy = CGFloat(tile.image.height) / tile.rect.height
        let padding = max(2, 2 / min(sx, sy))
        func aligned(_ rect: CGRect) -> CGRect {
            let region = rect.insetBy(dx: -padding, dy: -padding).intersection(tile.rect)
            guard !region.isEmpty, !region.isNull else { return .null }
            // Align the patch to the original raster's pixel grid. Keep the
            // immutable base; only these small images change during a drag.
            let x = floor((region.minX - tile.rect.minX) * sx), y = floor((region.minY - tile.rect.minY) * sy)
            let right = ceil((region.maxX - tile.rect.minX) * sx), bottom = ceil((region.maxY - tile.rect.minY) * sy)
            return CGRect(x: tile.rect.minX + x / sx, y: tile.rect.minY + y / sy, width: (right - x) / sx, height: (bottom - y) / sy)
        }
        var regions: [CGRect] = []
        for rectangle in overlays.changedRegions(from: tile.overlays).map(aligned) where !rectangle.isNull && !rectangle.isEmpty {
            var merged = rectangle, index = 0
            while index < regions.count {
                if merged.intersects(regions[index]) { merged = merged.union(regions.remove(at: index)); index = 0 }
                else { index += 1 }
            }
            regions.append(merged)
        }
        let changed = overlays.changedRegions(from: tile.displayedOverlays).map(aligned)
        var patches: [Tile] = []
        for region in regions {
            if let existing = tile.patches.first(where: { $0.rect == region }), !changed.contains(where: { $0.intersects(region) }) {
                patches.append(existing); continue
            }
            guard let base = tile.underlay, let scene else { return nil }
            let width = max(1, Int((region.width * sx).rounded())), height = max(1, Int((region.height * sy).rounded()))
            guard let buffer = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
            buffer.translateBy(x: -region.minX * sx, y: region.maxY * sy); buffer.scaleBy(x: sx, y: -sy)
            blitImage(base, rect: tile.rect, context: buffer)
            NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: buffer, flipped: true)
            SceneRenderer.drawLegend(document, scene: scene, context: buffer)
            SceneRenderer.drawDecorations(document, scene: scene, context: buffer, editing: editing, editingAnnotationID: editingAnnotationID)
            NSGraphicsContext.restoreGraphicsState()
            guard let result = buffer.makeImage() else { return nil }
            patches.append(Tile(result, rect: region))
        }
        tile.patches = patches; tile.displayedOverlays = overlays
        overlayUpdateCount += 1
        return tile
    }
    private func present(_ tile: Tile, overview: CGRect?, context: CGContext) {
        let visible = context.boundingBoxOfClipPath.intersection(tile.rect)
        guard let overview, let underlay = tile.underlay, overview.intersects(visible) else { blit(tile, context: context); return }
        if overview.contains(visible) { blitImage(underlay, rect: tile.rect, context: context); return }
        // Labels and map pixels remain stationary. Replace the annotation
        // layer only inside the moving card's protection area, then draw the
        // card once in the destination context at its actual Retina scale.
        context.saveGState(); exclude(overview, within: tile.rect, context: context)
        blit(tile, context: context); context.restoreGState()
        context.saveGState(); context.clip(to: overview)
        blitImage(underlay, rect: tile.rect, context: context); context.restoreGState()
    }
    private func blit(_ tile: Tile, context: CGContext) {
        guard !tile.patches.isEmpty else { blitImage(tile, context: context); return }
        context.saveGState()
        for patch in tile.patches { exclude(patch.rect, within: tile.rect, context: context) }
        blitImage(tile, context: context); context.restoreGState()
        for patch in tile.patches { blitImage(patch, context: context) }
    }
    private func exclude(_ rect: CGRect, within extent: CGRect, context: CGContext) {
        let intersection = rect.intersection(extent)
        guard !intersection.isEmpty, !intersection.isNull else { return }
        let path = CGMutablePath(); path.addRect(extent); path.addRect(intersection)
        context.setShouldAntialias(false); context.addPath(path); context.clip(using: .evenOdd)
    }
    private func blitImage(_ tile: Tile, context: CGContext) {
        blitImage(tile.image, rect: tile.rect, context: context)
    }
    private func blitImage(_ image: CGImage, rect: CGRect, context: CGContext) {
        context.saveGState()
        context.translateBy(x: rect.minX, y: rect.maxY); context.scaleBy(x: 1, y: -1)
        // Art caches are already sampled at or above the backing resolution.
        // Bilinear presentation avoids a second expensive bicubic reduction on
        // every gesture frame; sharp tiles still replace magnified previews.
        context.interpolationQuality = .medium
        context.draw(image, in: CGRect(origin: .zero, size: rect.size))
        context.restoreGState()
    }
}
