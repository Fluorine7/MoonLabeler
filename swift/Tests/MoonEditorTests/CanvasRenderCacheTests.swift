// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
import Combine
@testable import MoonCore
@testable import MoonEditor

final class CanvasRenderCacheTests: XCTestCase {
    @MainActor
    private func fixture() throws -> (PhotoPixels, MoonDocument, AnnotationScene) {
        let width = 128, height = 96
        var rgba = [UInt8](repeating: 255, count: width * height * 4)
        for y in 0..<height { for x in 0..<width {
            for channel in 0..<3 { rgba[(y * width + x) * 4 + channel] = y < 40 ? 0 : 160 }
        } }
        let photo = PhotoPixels(width: width, height: height, rgba: rgba)
        var document = MoonDocument(imagePath: "cache.png")
        document.imageWidth = width; document.imageHeight = height; document.settings.fontSize = 12
        document.changeStyle { $0.set("elevation_enabled", true); $0.set("elevation_opacity", 1.0); $0.set("map_light_mask", true); $0.set("map_light_threshold", 22.0) }
        document.annotations = [Annotation(text: "月 · Moon", anchor: PixelPoint(20, 65), position: PixelPoint(40, 55))]
        var scene = AnnotationScene()
        scene.layers.lightness = try PhotoLightness(photo: photo, calibration: nil)
        scene.layers.elevation = PhotoPixels(width: width, height: height, rgba: Array(repeating: [UInt8(0), 255, 0, 255], count: width * height).flatMap { $0 })
        return (photo, document, scene)
    }
    @MainActor
    private func overviewFixture() throws -> (PhotoPixels, MoonDocument, AnnotationScene) {
        let (photo, original, initialScene) = try fixture()
        var document = original, scene = initialScene
        document.changeStyle { $0.set("overview_enabled", true); $0.values["overview_position"] = .array([.number(4), .number(4)]) }
        scene.overview = PhotoOverview(image: photo, footprint: [], grid: [], latitude: 0, longitude: 0, north: nil, south: nil, earth: nil)
        return (photo, document, scene)
    }
    @MainActor
    private func render(_ photo: CGImage, document: MoonDocument, scene: AnnotationScene?, cache: CanvasRenderCache?,
                        origin: CGPoint = .zero, scale: CGFloat = 1, editing: Bool = false, interactiveZoom: Bool = false) throws -> PhotoPixels {
        let context = try XCTUnwrap(CGContext(data: nil, width: 320, height: 240, bitsPerComponent: 8, bytesPerRow: 1280,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.translateBy(x: 0, y: 240); context.scaleBy(x: 2, y: -2)
        context.translateBy(x: origin.x, y: origin.y); context.scaleBy(x: scale, y: scale)
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
        defer { NSGraphicsContext.restoreGraphicsState() }
        if let cache { cache.draw(image: photo, document: document, scene: scene, context: context, editing: editing, interactiveZoom: interactiveZoom) }
        else { SceneRenderer.draw(image: photo, document: document, scene: scene, context: context, editing: editing) }
        return try PhotoPixels(XCTUnwrap(context.makeImage()), flatten: false)
    }
    @MainActor
    private func assertPixels(_ actual: PhotoPixels, _ expected: PhotoPixels, file: StaticString = #filePath, line: UInt = #line) {
        let errors = zip(actual.rgba, expected.rgba).map { abs(Int($0) - Int($1)) }
        XCTAssertLessThan(Double(errors.reduce(0, +)) / Double(errors.count), 0.5, file: file, line: line)
        XCTAssertLessThan(Double(errors.filter { $0 > 4 }.count) / Double(errors.count), 0.002, file: file, line: line)
    }
    func testPanningReusesTheRasterAndMatchesTheDirectRenderer() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let (photo, document, scene) = try fixture(), image = photo.cgImage, cache = CanvasRenderCache()
            for origin in [CGPoint.zero, CGPoint(x: 12, y: 8), CGPoint(x: -20, y: -16)] {
                let direct = try render(image, document: document, scene: scene, cache: nil, origin: origin)
                let displayed = try render(image, document: document, scene: scene, cache: cache, origin: origin)
                assertPixels(displayed, direct)
            }
            XCTAssertEqual(cache.rasterizationCount, 1, "Panning must not rasterize the scene again")
        }
    }
    func testZoomedCanvasCannotPaintOverTheSurroundingInterface() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            var document = MoonDocument(imagePath: "green.png")
            document.imageWidth = 128; document.imageHeight = 96
            model.document = document
            model.image = PhotoPixels(width: 128, height: 96,
                rgba: Array(repeating: [UInt8(0), 255, 0, 255], count: 128 * 96).flatMap { $0 }).cgImage
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 80, height: 60)); canvas.model = model
            canvas.zoom(to: 2, at: CGPoint(x: 40, y: 30)); canvas.finishZoomInteraction()
            let context = try XCTUnwrap(CGContext(data: nil, width: 200, height: 160, bitsPerComponent: 8, bytesPerRow: 800,
                space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            context.setFillColor(NSColor.white.cgColor); context.fill(CGRect(x: 0, y: 0, width: 200, height: 160))
            context.translateBy(x: 40, y: 110); context.scaleBy(x: 1, y: -1)
            NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
            canvas.draw(canvas.bounds); NSGraphicsContext.restoreGraphicsState()
            let pixels = try PhotoPixels(XCTUnwrap(context.makeImage()))
            XCTAssertEqual(Array(pixels.rgba[(80 * 200 + 80) * 4..<(80 * 200 + 80) * 4 + 4]), [0, 255, 0, 255])
            for y in 0..<160 { for x in 0..<200 where !(40..<120).contains(x) || !(50..<110).contains(y) {
                XCTAssertEqual(Array(pixels.rgba[(y * 200 + x) * 4..<(y * 200 + x) * 4 + 4]), [255, 255, 255, 255])
            } }
        }
    }
    func testRetinaFocusContextMatchesDirectRendering() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let (photo, document, scene) = try fixture(), source = photo.cgImage
            let cache = CanvasRenderCache(), view = RetinaCacheProbe(frame: CGRect(x: 0, y: 0, width: 160, height: 120))
            var expected = CGSize.zero
            view.paint = { context in
                let transform = context.userSpaceToDeviceSpaceTransform
                let density = max(hypot(transform.a, transform.b), hypot(transform.c, transform.d))
                expected = CGSize(width: ceil(CGFloat(source.width) * density), height: ceil(CGFloat(source.height) * density))
                cache.draw(image: source, document: document, scene: scene, context: context, editing: false)
            }
            let window = NSWindow(contentRect: view.frame, styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = view
            defer { window.close() }
            window.orderFront(nil); window.display(); view.display()
            guard window.backingScaleFactor > 1, expected.width > CGFloat(source.width) else { throw XCTSkip("A Retina window context is not exposed to this test process") }
            let actual = try XCTUnwrap(cache.cachedPixelSize)
            XCTAssertGreaterThanOrEqual(actual.width, expected.width)
            XCTAssertGreaterThanOrEqual(actual.height, expected.height)
        }
    }
    func testLiveChangesInvalidateTheDisplayWithoutMutatingTheScene() async throws {
        try await MainActor.run {
            let (photo, initial, scene) = try fixture(), image = photo.cgImage, cache = CanvasRenderCache()
            var document = initial
            _ = try render(image, document: document, scene: scene, cache: cache)
            document.changeStyle { $0.set("map_light_threshold", 220.0) }
            let dimmed = try render(image, document: document, scene: scene, cache: cache)
            assertPixels(dimmed, try render(image, document: document, scene: scene, cache: nil))
            XCTAssertEqual(dimmed.rgba[(160 * 320 + 40) * 4 + 1], 160)
            document.changeStyle { $0.set("map_light_threshold", "auto"); $0.set("label_opacity", 0.4) }
            document.annotations[0].text = "已改名"; document.annotations[0].position = PixelPoint(35, 64)
            assertPixels(try render(image, document: document, scene: scene, cache: cache), try render(image, document: document, scene: scene, cache: nil))
            document.annotations = []
            assertPixels(try render(image, document: document, scene: scene, cache: cache), try render(image, document: document, scene: scene, cache: nil))
            XCTAssertEqual(cache.rasterizationCount, 4)
            XCTAssertEqual(scene.layers.lightness?.automaticThreshold, try PhotoLightness(photo: photo, calibration: nil).automaticThreshold)
            XCTAssertEqual(photo.rgba, try PhotoPixels(image).rgba)
        }
    }
    func testZoomAndSourceChangesRefreshTheRaster() async throws {
        try await MainActor.run {
            let (photo, document, scene) = try fixture(), cache = CanvasRenderCache(), image = photo.cgImage
            _ = try render(image, document: document, scene: scene, cache: cache)
            assertPixels(try render(image, document: document, scene: scene, cache: cache, scale: 1.5), try render(image, document: document, scene: scene, cache: nil, scale: 1.5))
            XCTAssertEqual(cache.rasterizationCount, 2)
            let replacement = PhotoPixels(width: 128, height: 96, rgba: [UInt8](repeating: 255, count: 128 * 96 * 4)).cgImage
            assertPixels(try render(replacement, document: document, scene: scene, cache: cache), try render(replacement, document: document, scene: scene, cache: nil))
            var replacedScene = scene; replacedScene.id = UUID(); replacedScene.layers.elevation = nil
            assertPixels(try render(replacement, document: document, scene: replacedScene, cache: cache), try render(replacement, document: document, scene: replacedScene, cache: nil))
            XCTAssertEqual(cache.rasterizationCount, 4)
        }
    }
    func testContinuousZoomReusesTheFrameAndRefinesAtRest() async throws {
        try await MainActor.run {
            let (photo, document, scene) = try fixture(), cache = CanvasRenderCache(), image = photo.cgImage
            _ = try render(image, document: document, scene: scene, cache: cache)
            for scale in [1.1, 1.2, 1.3, 1.4, 1.5] {
                _ = try render(image, document: document, scene: scene, cache: cache, scale: scale, interactiveZoom: true)
            }
            XCTAssertEqual(cache.rasterizationCount, 1)
            assertPixels(try render(image, document: document, scene: scene, cache: cache, scale: 1.5),
                         try render(image, document: document, scene: scene, cache: nil, scale: 1.5))
            XCTAssertEqual(cache.rasterizationCount, 2)
        }
    }
    func testZoomPreviewSurvivesTileModeAndReturnsToFullResolution() async throws {
        try await MainActor.run {
            let (photo, initial, _) = try fixture(), cache = CanvasRenderCache(maximumRasterPixels: 60_000, tilePixels: 32), image = photo.cgImage
            var document = initial; document.annotations = []
            let scene = AnnotationScene()
            _ = try render(image, document: document, scene: scene, cache: cache)
            XCTAssertEqual(cache.cachedPixelSize?.width, 256)
            _ = try render(image, document: document, scene: scene, cache: cache, scale: 2)
            XCTAssertLessThan(cache.cachedPixelSize?.width ?? 256, 256)
            let preview = try render(image, document: document, scene: scene, cache: cache, interactiveZoom: true)
            XCTAssertEqual(preview.rgba[(20 * 320 + 20) * 4], 0)
            XCTAssertEqual(Int(preview.rgba[(160 * 320 + 20) * 4]), 160, accuracy: 1)
            assertPixels(try render(image, document: document, scene: scene, cache: cache),
                         try render(image, document: document, scene: scene, cache: nil))
            XCTAssertEqual(cache.cachedPixelSize?.width, 256)
        }
    }
    func testZoomInteractionEndsAfterTheLastEvent() async throws {
        let canvas = await MainActor.run {
            let model = EditorModel()
            model.image = PhotoPixels(width: 80, height: 60, rgba: [UInt8](repeating: 255, count: 80 * 60 * 4)).cgImage
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 240, height: 160)); canvas.model = model
            canvas.zoom(to: 0.8, at: CGPoint(x: 120, y: 80)); canvas.zoom(to: 1.2, at: CGPoint(x: 120, y: 80))
            XCTAssertTrue(canvas.isZooming)
            return (canvas, model)
        }
        try await Task.sleep(for: .milliseconds(250))
        await MainActor.run { XCTAssertFalse(canvas.0.isZooming); _ = canvas.1 }
    }
    func testZoomTilesHaveNoSeamsAndReuseOverlapWhenPanning() async throws {
        try await MainActor.run {
            let (photo, initial, scene) = try fixture(), image = photo.cgImage
            var document = initial; document.annotations = []; document.changeStyle { $0.set("map_light_mask", false) }
            let cache = CanvasRenderCache(maximumRasterPixels: 150_000, tilePixels: 64)
            for origin in [CGPoint(x: -9.3, y: -51.7), CGPoint(x: -10.3, y: -52.7)] {
                assertPixels(try render(image, document: document, scene: scene, cache: cache, origin: origin, scale: 2),
                             try render(image, document: document, scene: scene, cache: nil, origin: origin, scale: 2))
            }
            let before = cache.rasterizationCount
            _ = try render(image, document: document, scene: scene, cache: cache, origin: CGPoint(x: -9.3, y: -51.7), scale: 2)
            XCTAssertEqual(cache.rasterizationCount, before)
            document.annotations = initial.annotations
            assertPixels(try render(image, document: document, scene: scene, cache: cache, origin: CGPoint(x: -10, y: -52), scale: 2),
                         try render(image, document: document, scene: scene, cache: nil, origin: CGPoint(x: -10, y: -52), scale: 2))
        }
    }
    func testPanningUpdatesViewportWithoutPublishingInspectorChanges() async throws {
        await MainActor.run {
            let model = EditorModel(); model.zoomLabel = "100%"
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 240, height: 160)); canvas.model = model
            var updates = 0
            let subscription = model.objectWillChange.sink { updates += 1 }
            canvas.origin = CGPoint(x: 10, y: 20); canvas.publishZoom()
            XCTAssertEqual(model.viewport, CGRect(x: -10, y: -20, width: 240, height: 160))
            XCTAssertEqual(updates, 0, "A pan must not rebuild the SwiftUI inspector")
            _ = subscription
        }
    }
    func testMovingLegendPatchesTheCacheWithoutLeavingOldPixels() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let (photo, initial, scene) = try fixture(), image = photo.cgImage, cache = CanvasRenderCache()
            var document = initial
            for position in [nil, [8.0, 74.0], [12.0, 70.0], [80.0, 12.0], nil] as [[Double]?] {
                document.changeStyle { $0.values["legend_position"] = position.map { .array($0.map(JSONValue.number)) } }
                assertPixels(try render(image, document: document, scene: scene, cache: cache),
                             try render(image, document: document, scene: scene, cache: nil))
            }
            XCTAssertEqual(cache.rasterizationCount, 1)
            XCTAssertEqual(cache.overlayUpdateCount, 3, "Returning to the original legend reuses its original pixels")

            let artCache = CanvasRenderCache()
            document.changeStyle { $0.set("art_style", "manuscript") }
            for position in [[4.0, 74.0], [12.0, 70.0], [80.0, 12.0]] {
                document.changeStyle { $0.values["legend_position"] = .array(position.map(JSONValue.number)) }
                assertPixels(try render(image, document: document, scene: scene, cache: artCache),
                             try render(image, document: document, scene: scene, cache: CanvasRenderCache()))
            }
            XCTAssertEqual(artCache.rasterizationCount, 1)

            let transparent = PhotoPixels(width: 128, height: 96, rgba: [UInt8](repeating: 0, count: 128 * 96 * 4)).cgImage
            document.annotations = []; document.changeStyle { $0.set("art_style", "standard"); $0.set("elevation_opacity", 0.0) }
            for position in [[4.0, 4.0], [70.0, 70.0], [4.0, 4.0]] {
                document.changeStyle { $0.values["legend_position"] = .array(position.map(JSONValue.number)) }
                assertPixels(try render(transparent, document: document, scene: scene, cache: cache),
                             try render(transparent, document: document, scene: scene, cache: nil))
            }
        }
    }
    func testLegendChangesRefreshTilesWhenTheyReturnToView() async throws {
        try await MainActor.run {
            let (photo, initial, scene) = try fixture(), image = photo.cgImage
            let cache = CanvasRenderCache(maximumRasterPixels: 150_000, tilePixels: 64)
            var document = initial
            _ = try render(image, document: document, scene: scene, cache: cache, origin: CGPoint(x: 0, y: -170), scale: 3)
            document.changeStyle { $0.values["legend_position"] = .array([.number(65), .number(10)]) }
            for origin in [CGPoint.zero, CGPoint(x: -150, y: 0), CGPoint(x: 0, y: -170)] {
                assertPixels(try render(image, document: document, scene: scene, cache: cache, origin: origin, scale: 3),
                             try render(image, document: document, scene: scene, cache: nil, origin: origin, scale: 3))
            }
        }
    }
    func testLegendDragPreviewsWithoutPublishingAndCommitsOneUndoStep() async throws { try await verifyOverlayDrag("legend_position") }
    func testOverviewDragPreviewsWithoutPublishingAndCommitsOneUndoStep() async throws { try await verifyOverlayDrag("overview_position") }
    private func verifyOverlayDrag(_ key: String) async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let (photo, document, scene) = try key == "overview_position" ? overviewFixture() : fixture()
            let model = EditorModel(); model.document = document; model.appliedDocument = document; model.image = photo.cgImage; model.scene = scene
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 160, height: 120)); canvas.model = model
            let window = NSWindow(contentRect: canvas.frame, styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = canvas; defer { window.close() }
            canvas.zoom(to: 1, at: .zero); canvas.finishZoomInteraction(); canvas.origin = .zero
            let rect = key == "overview_position" ? SceneRenderer.overviewRect(document) : SceneRenderer.legendRect(document)
            let start = CGPoint(x: rect.midX, y: rect.midY)
            func mouse(_ type: NSEvent.EventType, _ delta: Double) throws -> NSEvent {
                try XCTUnwrap(NSEvent.mouseEvent(with: type, location: canvas.convert(CGPoint(x: start.x + delta, y: start.y - delta), to: nil),
                    modifierFlags: .command, timestamp: 0, windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1))
            }
            var updates = 0
            let subscription = model.$document.dropFirst().sink { _ in updates += 1 }
            canvas.mouseDown(with: try mouse(.leftMouseDown, 0))
            for delta in [4.0, 8.0, 12.0] { canvas.mouseDragged(with: try mouse(.leftMouseDragged, delta)) }
            XCTAssertEqual(model.document, document); XCTAssertEqual(updates, 0)
            let displayed = try XCTUnwrap(model.displayDocument)
            XCTAssertNotEqual(key == "overview_position" ? SceneRenderer.overviewRect(displayed) : SceneRenderer.legendRect(displayed), rect)
            XCTAssertEqual(model.scene?.id, scene.id)
            canvas.mouseUp(with: try mouse(.leftMouseUp, 12))
            XCTAssertEqual(updates, 1); XCTAssertNil(model.overlayPreview)
            model.undo(); XCTAssertEqual(model.document, document)
            let beforeCancel = updates
            canvas.mouseDown(with: try mouse(.leftMouseDown, 0)); canvas.mouseDragged(with: try mouse(.leftMouseDragged, 16)); canvas.cancelInteraction()
            XCTAssertEqual(model.document, document); XCTAssertEqual(updates, beforeCancel); XCTAssertNil(model.overlayPreview)
            _ = subscription
        }
    }
    func testOverviewAndLegendMovesComposeCorrectlyIncludingOverlaps() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let (photo, initial, scene) = try overviewFixture()
            for transparent in [false, true] {
                let image = transparent ? PhotoPixels(width: 128, height: 96, rgba: [UInt8](repeating: 0, count: 128 * 96 * 4)).cgImage : photo.cgImage
                let cache = CanvasRenderCache()
                var document = initial
                document.changeStyle { $0.set("art_style", "manuscript"); if transparent { $0.set("elevation_opacity", 0.0) } }
                for points in [[4.0, 4.0, 4.0, 80.0], [60.0, 44.0, 64.0, 50.0], [61.0, 42.0, 64.0, 50.0], [61.0, 42.0, 2.0, 80.0], [4.0, 4.0, 4.0, 80.0]] {
                    document.changeStyle {
                        $0.values["overview_position"] = .array(points.prefix(2).map(JSONValue.number))
                        $0.values["legend_position"] = .array(points.suffix(2).map(JSONValue.number))
                    }
                    assertPixels(try render(image, document: document, scene: scene, cache: cache),
                                 try render(image, document: document, scene: scene, cache: CanvasRenderCache()))
                }
                XCTAssertEqual(cache.rasterizationCount, 1, "Moving overlays must preserve the map raster")
                XCTAssertEqual(document.annotations, initial.annotations)
            }
        }
    }
    func testMovingOverviewRefreshesTilesAfterPanningBackToThem() async throws {
        try await MainActor.run {
            let (photo, initial, scene) = try overviewFixture(), image = photo.cgImage
            let cache = CanvasRenderCache(maximumRasterPixels: 150_000, tilePixels: 64)
            var document = initial
            _ = try render(image, document: document, scene: scene, cache: cache, scale: 3)
            document.changeStyle { $0.values["overview_position"] = .array([.number(60), .number(40)]) }
            for origin in [CGPoint(x: -180, y: -120), .zero] {
                assertPixels(try render(image, document: document, scene: scene, cache: cache, origin: origin, scale: 3),
                             try render(image, document: document, scene: scene, cache: nil, origin: origin, scale: 3))
            }
        }
    }
    func testFullArtBudgetIncludesTheProtectionUnderlay() async throws {
        try await MainActor.run {
            let (photo, initial, scene) = try fixture(), pixelBudget = 100_000
            var document = initial; document.changeStyle { $0.set("art_style", "manuscript") }
            let baseline = CanvasRenderCache.retainedBitmapBytes
            let cache = CanvasRenderCache(maximumRasterPixels: pixelBudget)
            _ = try render(photo.cgImage, document: document, scene: scene, cache: cache)
            XCTAssertNotNil(cache.cachedPixelSize)
            let retained = CanvasRenderCache.retainedBitmapBytes - baseline
            print("FULL_CANVAS_STORAGE retained_bitmap_bytes=\(retained) budget_bytes=\(pixelBudget * 4)")
            XCTAssertLessThanOrEqual(retained, pixelBudget * 4 + 10_000)
            cache.clear(); XCTAssertEqual(CanvasRenderCache.retainedBitmapBytes, baseline)
        }
    }
    func testArtTileBudgetIncludesUnderlaysAfterPanning() async throws {
        try await MainActor.run {
            let (_, original, _) = try fixture(), side = 512, pixelBudget = 400_000
            let photo = PhotoPixels(width: side, height: side, rgba: [UInt8](repeating: 255, count: side * side * 4)), image = photo.cgImage
            var document = original; document.imageWidth = side; document.imageHeight = side
            document.changeStyle { $0.set("art_style", "manuscript"); $0.set("map_light_mask", false) }
            var scene = AnnotationScene(); scene.grayscale = photo; scene.layers.elevation = photo
            let baseline = CanvasRenderCache.retainedBitmapBytes
            let cache = CanvasRenderCache(maximumRasterPixels: pixelBudget, tilePixels: 64)
            for x in [0.0, -200.0, -500.0, -800.0] {
                for _ in 0..<80 {
                    try autoreleasepool { _ = try render(image, document: document, scene: scene, cache: cache, origin: CGPoint(x: x, y: 0), scale: 2) }
                    if !cache.needsRefinement { break }
                }
                XCTAssertFalse(cache.needsRefinement, "The current viewport must retain its sharp tiles")
            }
            let retained = CanvasRenderCache.retainedBitmapBytes - baseline
            print("CANVAS_STORAGE retained_bitmap_bytes=\(retained) budget_bytes=\(pixelBudget * 4)")
            XCTAssertLessThanOrEqual(retained, pixelBudget * 4 + 100_000, "The budget must include underlays, preview and offscreen tiles")
            cache.clear()
            XCTAssertEqual(CanvasRenderCache.retainedBitmapBytes, baseline)
        }
    }
    func testArtZoomReusesOversampledRetinaContentAndRefinesVisibleTiles() async throws {
        try await MainActor.run {
            let (photo, initial, scene) = try fixture(), image = photo.cgImage, cache = CanvasRenderCache(maximumRasterPixels: 200_000, tilePixels: 64)
            var document = initial; document.changeStyle { $0.set("art_style", "manuscript") }
            _ = try render(image, document: document, scene: scene, cache: cache)
            XCTAssertGreaterThanOrEqual(cache.cachedPixelSize?.width ?? 0, 256)
            for scale in [1.05, 1.1, 1.2] { _ = try render(image, document: document, scene: scene, cache: cache, scale: scale) }
            XCTAssertEqual(cache.rasterizationCount, 1, "Small art zoom changes must reuse a sharp backing-resolution cache")
            let origin = CGPoint(x: -18, y: -125), scale = 3.0
            var final: PhotoPixels?
            for _ in 0..<80 {
                final = try render(image, document: document, scene: scene, cache: cache, origin: origin, scale: scale)
                if !cache.needsRefinement { break }
            }
            XCTAssertFalse(cache.needsRefinement, "Visible tiles must finish refining")
            XCTAssertEqual(cache.cachedTileDensity ?? 0, 6, accuracy: 1e-12, "Settled art tiles must match the actual Retina density")
            let direct = try render(image, document: document, scene: scene, cache: nil, origin: origin, scale: scale)
            let errors = zip(try XCTUnwrap(final).rgba, direct.rgba).map { abs(Int($0) - Int($1)) }
            XCTAssertLessThan(Double(errors.reduce(0, +)) / Double(errors.count), 1.0, "Art refinement must preserve detail and geometry")
            XCTAssertEqual(document.annotations, initial.annotations); XCTAssertEqual(document.calibration, initial.calibration)
        }
    }
    func testPartialLegendRepaintsMatchACompleteArtCanvas() async throws { try await verifyPartialOverlayRepaints("legend_position") }
    func testPartialOverviewRepaintsMatchACompleteArtCanvas() async throws { try await verifyPartialOverlayRepaints("overview_position") }
    private func verifyPartialOverlayRepaints(_ key: String) async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let (photo, initial, scene) = try key == "overview_position" ? overviewFixture() : fixture()
            var document = initial; document.changeStyle { $0.set("art_style", "manuscript") }
            let image = photo.cgImage
            @MainActor func canvas(_ document: MoonDocument) -> (MoonCanvas, EditorModel) {
                let model = EditorModel(); model.document = document; model.appliedDocument = document; model.image = image; model.scene = scene
                let view = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 160, height: 120)); view.model = model
                view.zoom(to: 1, at: .zero); view.finishZoomInteraction(); view.origin = .zero
                return (view, model)
            }
            func buffer() throws -> CGContext {
                let result = try XCTUnwrap(CGContext(data: nil, width: 320, height: 240, bitsPerComponent: 8, bytesPerRow: 1280,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
                result.translateBy(x: 0, y: 240); result.scaleBy(x: 2, y: -2); return result
            }
            let (view, model) = canvas(document), incremental = try buffer()
            NSGraphicsContext.saveGraphicsState(); defer { NSGraphicsContext.restoreGraphicsState() }
            NSGraphicsContext.current = NSGraphicsContext(cgContext: incremental, flipped: true)
            view.draw(view.bounds)
            func bounds(_ document: MoonDocument) -> CGRect {
                key == "overview_position" ? SceneRenderer.overviewExclusion(document, scene: scene) ?? .zero : SceneRenderer.legendRect(document)
            }
            for position in [[8.0, 74.0], [12.0, 70.0], [80.0, 12.0]] {
                let previous = bounds(try XCTUnwrap(model.displayDocument))
                model.overlayPreview = .init(key: key, position: PixelPoint(position[0], position[1]))
                let current = bounds(try XCTUnwrap(model.displayDocument))
                view.draw(previous.union(current).insetBy(dx: -4, dy: -4))
            }
            let actual = try PhotoPixels(XCTUnwrap(incremental.makeImage()), flatten: false)
            let (fresh, retainedModel) = canvas(try XCTUnwrap(model.displayDocument)), complete = try buffer()
            NSGraphicsContext.current = NSGraphicsContext(cgContext: complete, flipped: true); fresh.draw(fresh.bounds)
            let expected = try PhotoPixels(XCTUnwrap(complete.makeImage()), flatten: false)
            if let directory = ProcessInfo.processInfo.environment["MOON_SWIFT_PIXEL_ARTIFACTS"] {
                try Data(actual.rgba).write(to: URL(fileURLWithPath: directory).appendingPathComponent("partial-actual.rgba"))
                try Data(expected.rgba).write(to: URL(fileURLWithPath: directory).appendingPathComponent("partial-expected.rgba"))
            }
            assertPixels(actual, expected)
            XCTAssertEqual(model.document, document); _ = retainedModel
        }
    }
    func testCoalescedZoomPublishesTheLatestScaleAfterARoundTrip() async throws {
        let model = await MainActor.run {
            let model = EditorModel(); model.zoomLabel = "100%"
            model.image = PhotoPixels(width: 80, height: 60, rgba: [UInt8](repeating: 255, count: 80 * 60 * 4)).cgImage
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 240, height: 160)); canvas.model = model
            canvas.zoom(to: 0.5, at: CGPoint(x: 120, y: 80))
            canvas.zoom(to: 1, at: CGPoint(x: 120, y: 80))
            return (model, canvas)
        }
        try await Task.sleep(for: .milliseconds(20))
        await MainActor.run { XCTAssertEqual(model.0.zoomLabel, "100%"); XCTAssertEqual(model.0.viewport.width, 240); _ = model.1 }
    }
}

@MainActor
private final class RetinaCacheProbe: NSView {
    var paint: ((CGContext) -> Void)?
    override var isFlipped: Bool { true }
    override func draw(_ dirtyRect: NSRect) { if let context = NSGraphicsContext.current?.cgContext { paint?(context) } }
}
