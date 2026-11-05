// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
@testable import MoonCore
@testable import MoonEditor

final class CanvasPerformanceTests: XCTestCase {
    private enum Gesture: String {
        case pan = "PAN", zoom = "ZOOM", legend = "LEGEND", overview = "OVERVIEW", settlingZoom = "SETTLING_ZOOM"
        var positionKey: String? { self == .legend ? "legend_position" : self == .overview ? "overview_position" : nil }
    }
    func testRepeatedPanningFramesMeetInteractiveBudget() async throws {
        try await benchmark(.pan)
    }
    func testContinuousZoomFramesMeetInteractiveBudget() async throws {
        try await benchmark(.zoom)
    }
    func testLegendDraggingFramesMeetInteractiveBudget() async throws { try await benchmark(.legend) }
    func testOverviewDraggingFramesMeetInteractiveBudget() async throws { try await benchmark(.overview) }
    func testZoomRefinementFramesMeetInteractiveBudget() async throws { try await benchmark(.settlingZoom) }
    private func benchmark(_ gesture: Gesture) async throws {
        guard let path = ProcessInfo.processInfo.environment["MOON_SWIFT_BENCHMARK_PROJECT"] else {
            throw XCTSkip("Set MOON_SWIFT_BENCHMARK_PROJECT to run the real-photo pan benchmark")
        }
        var document = try ProjectIO.read(URL(fileURLWithPath: path)).document
        let images = try PhotoIO.open(URL(fileURLWithPath: document.imagePath))
        let photo = try PhotoPixels(images.raw)
        document.imageWidth = photo.width; document.imageHeight = photo.height
        if let art = ProcessInfo.processInfo.environment["MOON_SWIFT_BENCHMARK_ART"] { document.changeStyle { $0.applyArt(art) } }
        let dem = try Catalog.resource("LDEM_16", "LBL").map { try ElevationMap(url: $0) }
        let result = try AnnotationSceneBuilder.build(document: document, photo: photo, features: Catalog.load(), dem: dem, task: ComputeTask(),
            measure: AnnotationRenderer.measure, captionBounds: SceneRenderer.labelBounds,
            configureCaption: { SceneRenderer.configureCaption($0, feature: $1, document: $2) }, displayPhoto: PhotoPixels(images.display))
        let (timings, retainedBitmapBytes) = try await MainActor.run {
            _ = NSApplication.shared
            let previousBitmapBytes = CanvasRenderCache.retainedBitmapBytes
            var snapshot = result.0, scene = result.1
            switch ProcessInfo.processInfo.environment["MOON_SWIFT_BENCHMARK_VARIANT"] {
            case "no_overview": scene.overview = nil
            case "no_map": scene.layers.elevation = nil; scene.layers.contours = []; scene.layers.grid = []; scene.layers.terminator = []; scene.layers.raster = nil
            case "no_labels": snapshot.annotations = []
            case "photo_only": snapshot.annotations = []; scene = AnnotationScene()
            default: break
            }
            let model = EditorModel(); model.document = snapshot; model.appliedDocument = snapshot
            model.image = images.raw; model.displayImage = images.display; model.scene = scene; model.panelTab = 1
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 1400, height: 900)); canvas.model = model
            let window = NSWindow(contentRect: canvas.frame, styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = canvas; defer { window.close() }
            canvas.fitImage()
            if let text = ProcessInfo.processInfo.environment["MOON_SWIFT_BENCHMARK_ZOOM"], let zoom = Double(text) {
                canvas.zoom(to: zoom, at: CGPoint(x: canvas.bounds.midX, y: canvas.bounds.midY))
            }
            canvas.finishZoomInteraction()
            @MainActor func overlayRect(_ document: MoonDocument) -> CGRect {
                gesture == .overview ? SceneRenderer.overviewExclusion(document, scene: scene) ?? .zero : SceneRenderer.legendRect(document)
            }
            if gesture.positionKey != nil {
                // Keep the dragged overlay visible in magnified views.
                let rect = overlayRect(snapshot), target = gesture == .overview ? CGPoint(x: 700, y: 450) : CGPoint(x: 350, y: 750)
                canvas.origin = CGPoint(x: target.x - rect.midX * canvas.scale, y: target.y - rect.midY * canvas.scale)
            }
            let context = try XCTUnwrap(CGContext(data: nil, width: 2800, height: 1800, bitsPerComponent: 8, bytesPerRow: 2800 * 4,
                space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            context.translateBy(x: 0, y: 1800); context.scaleBy(x: 2, y: -2)
            NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
            defer { NSGraphicsContext.restoreGraphicsState() }
            autoreleasepool { canvas.draw(canvas.bounds) }
            for _ in 0..<120 where canvas.displayNeedsRefinement { autoreleasepool { canvas.draw(canvas.bounds) } }
            XCTAssertFalse(canvas.displayNeedsRefinement, "The stationary art view must finish refining")
            @MainActor func mouse(_ type: NSEvent.EventType, _ x: Double, _ y: Double) throws -> NSEvent {
                try XCTUnwrap(NSEvent.mouseEvent(with: type, location: canvas.convert(CGPoint(x: x, y: y), to: nil), modifierFlags: gesture.positionKey != nil ? .command : [], timestamp: 0,
                    windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1))
            }
            let overlay = overlayRect(snapshot)
            let start = gesture.positionKey != nil ? CGPoint(x: canvas.origin.x + overlay.midX * canvas.scale, y: canvas.origin.y + overlay.midY * canvas.scale) : CGPoint(x: 10, y: 10)
            if gesture == .legend { XCTAssertNotNil(scene.layers.raster); XCTAssertTrue(snapshot.style.elevationEnabled || snapshot.style.contourEnabled) }
            if gesture == .overview { XCTAssertNotNil(scene.overview); XCTAssertTrue(snapshot.style.bool("overview_enabled")) }
            if gesture == .pan || gesture.positionKey != nil { canvas.mouseDown(with: try mouse(.leftMouseDown, start.x, start.y)) }
            let initialScale = canvas.scale
            var values: [Double] = []
            for index in 0..<12 {
                let frameStart = ProcessInfo.processInfo.systemUptime
                try autoreleasepool {
                    let previousOverlay = model.displayDocument.map(overlayRect)
                    if gesture == .zoom || gesture == .settlingZoom {
                        canvas.zoom(to: initialScale * pow(1.035, Double(index + 1)), at: CGPoint(x: 700, y: 450))
                        if gesture == .settlingZoom { canvas.finishZoomInteraction() }
                    } else { canvas.mouseDragged(with: try mouse(.leftMouseDragged, start.x + 10 + Double(index) * 3, start.y + 10 + Double(index) * 2)) }
                    var dirty = canvas.bounds
                    if gesture.positionKey != nil, let previousOverlay, let current = model.displayDocument {
                        let damage = previousOverlay.union(overlayRect(current)), padding = max(4, canvas.scale * 2)
                        dirty = CGRect(x: canvas.origin.x + damage.minX * canvas.scale, y: canvas.origin.y + damage.minY * canvas.scale,
                                       width: damage.width * canvas.scale, height: damage.height * canvas.scale).insetBy(dx: -padding, dy: -padding)
                    }
                    canvas.draw(dirty); context.flush()
                }
                values.append((ProcessInfo.processInfo.systemUptime - frameStart) * 1000)
            }
            if gesture == .pan || gesture.positionKey != nil { canvas.mouseUp(with: try mouse(.leftMouseUp, start.x + 43, start.y + 32)) }
            if let key = gesture.positionKey {
                XCTAssertNotEqual(model.document?.style.values[key], snapshot.style.values[key], "Exercise the real overlay-drag route")
                XCTAssertEqual(model.scene?.id, scene.id)
            }
            return (values.sorted(), CanvasRenderCache.retainedBitmapBytes - previousBitmapBytes)
        }
        let median = timings[timings.count / 2], p90 = timings[Int(Double(timings.count - 1) * 0.9)]
        print(String(format: "\(gesture.rawValue)_BENCHMARK median=%.2f ms p90=%.2f ms min=%.2f ms", median, p90, timings.first!))
        print(String(format: "\(gesture.rawValue)_CANVAS_STORAGE retained=%.2f MiB", Double(retainedBitmapBytes) / (1024 * 1024)))
        let outputKey = gesture == .pan ? "MOON_SWIFT_BENCHMARK_RESULT" : "MOON_SWIFT_BENCHMARK_\(gesture.rawValue)_RESULT"
        if let output = ProcessInfo.processInfo.environment[outputKey] {
            let data = try JSONSerialization.data(withJSONObject: ["median_ms": median, "p90_ms": p90, "samples_ms": timings, "retained_bitmap_bytes": retainedBitmapBytes], options: [.prettyPrinted, .sortedKeys])
            try data.write(to: URL(fileURLWithPath: output), options: .atomic)
        }
        let frameBudget = gesture == .overview ? 1000.0 / 60 : 1000.0 / 30
        XCTAssertLessThan(median, frameBudget, "Interactive redraws exceed their frame budget")
        XCTAssertLessThan(p90, gesture == .overview ? 25 : 50, "Cache transitions must not introduce long redraw stalls")
    }
}
