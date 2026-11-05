// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
@testable import MoonCore
@testable import MoonEditor

final class OverviewCollisionTests: XCTestCase {
    struct DecorationOracle: Decodable {
        var caption_z: Double, locator_z: Double, order_changed_pixels: Int, rim_leader: [Double]
        var locators: [String: Bool]
    }
    private func decorationOracle() throws -> DecorationOracle {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "decoration-python-oracle", withExtension: "json"))
        return try JSONDecoder().decode(DecorationOracle.self, from: Data(contentsOf: url))
    }
    @MainActor
    private func fixture() -> (CGImage, MoonDocument, AnnotationScene) {
        let image = PhotoPixels(width: 360, height: 480,
            rgba: Array(repeating: [UInt8(40), 40, 40, 255], count: 360 * 480).flatMap { $0 }).cgImage
        var document = MoonDocument(imagePath: "overview-collision.png")
        document.imageWidth = 360; document.imageHeight = 480; document.settings.fontSize = 14
        document.changeStyle { $0.set("overview_enabled", true); $0.values["overview_position"] = .array([.number(16), .number(350)]) }
        var annotation = Annotation(text: "Crater", anchor: PixelPoint(104, 395), position: PixelPoint(220, 250))
        annotation.visual = AnnotationVisual()
        annotation.visual?.outline = [(0...128).map { index in
            let angle = Double(index) * 2 * .pi / 128
            return PixelPoint(104 + 90 * cos(angle), 395 + 35 * sin(angle))
        }]
        document.annotations = [annotation]
        let globe = PhotoPixels(width: 64, height: 64,
            rgba: Array(repeating: [UInt8(100), 100, 100, 255], count: 64 * 64).flatMap { $0 })
        let overview = PhotoOverview(image: globe, footprint: [], grid: [], latitude: -75, longitude: 9,
                                     north: nil, south: nil, earth: nil)
        return (image, document, AnnotationScene(overview: overview))
    }
    @MainActor
    private func render(_ format: String, image: CGImage, document: MoonDocument, scene: AnnotationScene, cache: CanvasRenderCache? = nil,
                        editing: Bool = false, editingAnnotationID: UUID? = nil) throws -> PhotoPixels {
        if format == "canvas" {
            let context = try XCTUnwrap(CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                bytesPerRow: image.width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            context.translateBy(x: 0, y: CGFloat(image.height)); context.scaleBy(x: 1, y: -1)
            NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
            defer { NSGraphicsContext.restoreGraphicsState() }
            (cache ?? CanvasRenderCache()).draw(image: image, document: document, scene: scene, context: context, editing: editing, editingAnnotationID: editingAnnotationID)
            return try PhotoPixels(XCTUnwrap(context.makeImage()))
        }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + "." + format)
        defer { try? FileManager.default.removeItem(at: url) }
        if format == "png" { try PhotoIO.png(image: image, document: document, scene: scene, to: url); return try PhotoPixels.load(url) }
        try SceneRenderer.svg(image: image, document: document, scene: scene, to: url)
        return try PhotoPixels(XCTUnwrap(NSImage(contentsOf: url)?.cgImage(forProposedRect: nil, context: nil, hints: nil)))
    }
    @MainActor
    private func pathCaption() -> Annotation {
        var result = Annotation(text: "AB", anchor: PixelPoint(60, 120), position: PixelPoint(170, 160))
        result.visual = AnnotationVisual()
        result.visual?.pathGlyphs = [
            CaptionGlyph(text: "A", point: PixelPoint(0, 18), angle: 10, scale: 1, advance: 12, family: "PingFang SC"),
            CaptionGlyph(text: "B", point: PixelPoint(14, 20), angle: 10, scale: 1, advance: 12, family: "PingFang SC")]
        return result
    }
    func testPathCaptionLocatorsMatchPythonForPreviewAndExports() async throws {
        let expected = try decorationOracle().locators
        try await MainActor.run {
            let (image, original, scene) = fixture()
            for name in ["plain", "shape", "manual_shape", "art_plain", "art_landing", "legacy_shape"] {
                var document = original; document.changeStyle { $0.set("overview_enabled", false); $0.set("show_landing_sites", true) }
                var annotation = pathCaption()
                if ["plain", "art_plain", "art_landing"].contains(name) { annotation.visual?.pathGlyphs = [] }
                if name == "manual_shape" { annotation.automatic = false; annotation.positionEdited = true }
                if name == "legacy_shape" {
                    annotation.visual?.pathGlyphs = []; annotation.visual?.baseline = [PixelPoint(170,160), PixelPoint(220,175)]
                }
                if name.hasPrefix("art_") { document.changeStyle { $0.set("art_style", "manuscript") } }
                if name == "art_landing" { annotation.visual?.landing = true }
                document.annotations = [annotation]
                var noLocators = document; noLocators.settings.showLeaders = false
                let show = try XCTUnwrap(expected[["manual_shape", "legacy_shape"].contains(name) ? "shape" : name])
                for format in ["canvas", "png", "svg"] {
                    let actual = try render(format, image: image, document: document, scene: scene)
                    let baseline = try render(format, image: image, document: noLocators, scene: scene)
                    let changed = differences(actual, baseline, in: CGRect(x: 45, y: 105, width: 30, height: 30))
                    if show { XCTAssertGreaterThan(changed, 2, "\(name), \(format): keep the Python locator") }
                    else { XCTAssertTrue(actual.rgba == baseline.rgba, "\(name), \(format): path captions must not have permanent leaders or dots") }
                }
            }
        }
    }
    func testFlattenedPathCaptionRestoresThePlainPythonLocator() async throws {
        let expected = try XCTUnwrap(decorationOracle().locators["plain"])
        XCTAssertTrue(expected)
        try await MainActor.run {
            let (image, original, scene) = fixture()
            var document = original; document.changeStyle { $0.set("overview_enabled", false) }
            document.calibration = Calibration(geometry: MoonGeometry(native: [1,0,0, 0,1,0, 0,0,1, 1,0,0, 384400], utc: "2025-09-14T15:00:00Z"), matrix: [[60,0,180],[0,-60,240]])
            var annotation = pathCaption(); annotation.position = PixelPoint(300, 400)
            document.annotations = [annotation]
            var noLocators = document; noLocators.settings.showLeaders = false
            for format in ["canvas", "png", "svg"] {
                let actual = try render(format, image: image, document: document, scene: scene)
                let baseline = try render(format, image: image, document: noLocators, scene: scene)
                XCTAssertGreaterThan(differences(actual, baseline, in: CGRect(x: 45, y: 105, width: 30, height: 30)), 2,
                                     "\(format): a caption flattened outside the lunar disk uses the plain locator policy")
            }
        }
    }
    func testOnlyTheDraggedPathCaptionTemporarilyShowsALocator() async throws {
        let expected = try decorationOracle().locators
        XCTAssertEqual(expected["dragged_shape"], true); XCTAssertEqual(expected["exported_dragged_shape"], false)
        try await MainActor.run {
            let (image, original, scene) = fixture(), cache = CanvasRenderCache()
            var document = original; document.changeStyle { $0.set("overview_enabled", false) }
            let first = pathCaption()
            var second = pathCaption(); second.anchor = PixelPoint(60, 300); second.position = PixelPoint(170, 340)
            document.annotations = [first, second]
            var noLocators = document; noLocators.settings.showLeaders = false
            let baseline = try render("canvas", image: image, document: noLocators, scene: scene)
            let a = try render("canvas", image: image, document: document, scene: scene, cache: cache, editing: true, editingAnnotationID: first.id)
            let b = try render("canvas", image: image, document: document, scene: scene, cache: cache, editing: true, editingAnnotationID: second.id)
            let firstBox = CGRect(x: 45, y: 105, width: 30, height: 30), secondBox = CGRect(x: 45, y: 285, width: 30, height: 30)
            XCTAssertGreaterThan(differences(a, baseline, in: firstBox), 2); XCTAssertEqual(differences(a, baseline, in: secondBox), 0)
            XCTAssertEqual(differences(b, baseline, in: firstBox), 0); XCTAssertGreaterThan(differences(b, baseline, in: secondBox), 2)
            let released = try render("canvas", image: image, document: document, scene: scene, cache: cache)
            XCTAssertTrue(released.rgba == baseline.rgba)
            XCTAssertEqual(cache.rasterizationCount, 3, "Changing the dragged label must invalidate the temporary locator cache")
            for format in ["png", "svg"] {
                let exported = try render(format, image: image, document: document, scene: scene, editing: true, editingAnnotationID: first.id)
                let clean = try render(format, image: image, document: noLocators, scene: scene)
                XCTAssertTrue(exported.rgba == clean.rgba, "\(format): exports must omit temporary drag locators")
            }
        }
    }
    private func differences(_ actual: PhotoPixels, _ expected: PhotoPixels, in rect: CGRect) -> Int {
        let sx = Double(actual.width) / 360, sy = Double(actual.height) / 480
        var count = 0
        for y in Int(ceil(rect.minY * sy))..<Int(floor(rect.maxY * sy)) {
            for x in Int(ceil(rect.minX * sx))..<Int(floor(rect.maxX * sx)) {
                let i = (y * actual.width + x) * 4
                if (0..<3).contains(where: { abs(Int(actual.rgba[i + $0]) - Int(expected.rgba[i + $0])) > 3 }) { count += 1 }
            }
        }
        return count
    }
    func testMovedOverviewStaysClearOfCraterRimsAndLeaders() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let (image, document, scene) = fixture()
            var empty = document; empty.annotations = []
            let card = SceneRenderer.overviewRect(document)
            for format in ["canvas", "png", "svg"] {
                let baseline = try render(format, image: image, document: empty, scene: scene)
                let actual = try render(format, image: image, document: document, scene: scene)
                XCTAssertEqual(actual.width, baseline.width); XCTAssertEqual(actual.height, baseline.height)
                XCTAssertEqual(differences(actual, baseline, in: card.insetBy(dx: 2, dy: 2)), 0,
                               "\(format): crater rims and leaders must not appear inside the moved overview")
                XCTAssertGreaterThan(differences(actual, baseline, in: CGRect(x: 190, y: 390, width: 8, height: 10)), 2,
                                     "\(format): keep the crater rim outside the overview")
            }
        }
    }
    func testCaptionAndRimLayerOrderMatchesThePythonScene() async throws {
        let oracle = try decorationOracle()
        XCTAssertGreaterThan(oracle.caption_z, oracle.locator_z)
        try await MainActor.run {
            _ = NSApplication.shared
            let (image, original, scene) = fixture()
            var document = original; document.settings.fontSize = 24
            document.changeStyle { $0.set("overview_enabled", false) }
            let caption = Annotation(text: "XXXXXX", anchor: PixelPoint(50, 200), position: PixelPoint(100, 160))
            var crater = Annotation(text: "Crater", anchor: PixelPoint(170, 220), position: PixelPoint(20, 30))
            crater.visual = AnnotationVisual()
            crater.visual?.outline = [(0...128).map { index in
                let angle = Double(index) * 2 * .pi / 128
                return PixelPoint(170 + 120 * cos(angle), 220 + 50 * sin(angle))
            }]
            document.annotations = [caption, crater]
            var reversed = document; reversed.annotations.reverse()
            let target = SceneRenderer.labelBounds(caption, document: document)
            for format in ["canvas", "png", "svg"] {
                let actual = try render(format, image: image, document: document, scene: scene)
                let reordered = try render(format, image: image, document: reversed, scene: scene)
                XCTAssertEqual(differences(actual, reordered, in: target), oracle.order_changed_pixels,
                               "\(format): Python paints every caption above every crater rim, regardless of insertion order")
            }
        }
    }
    func testRenderedLeadersStartAtThePythonRimIntersection() async throws {
        let oracle = try decorationOracle()
        try await MainActor.run {
            let (image, original, scene) = fixture()
            var document = original; document.settings.fontSize = 14
            document.changeStyle { $0.set("overview_enabled", false) }
            var annotation = Annotation(text: "Crater", anchor: PixelPoint(100, 100), position: PixelPoint(0, 0))
            let bounds = SceneRenderer.labelBounds(annotation, document: document)
            annotation.position = PixelPoint(150 - bounds.minX, 100 - bounds.midY)
            annotation.visual = AnnotationVisual()
            annotation.visual?.outline = [[PixelPoint(80, 80), PixelPoint(120, 80), PixelPoint(120, 120), PixelPoint(80, 120), PixelPoint(80, 80)]]
            document.annotations = [annotation]
            var empty = document; empty.annotations = []
            for format in ["canvas", "png", "svg"] {
                let actual = try render(format, image: image, document: document, scene: scene)
                let baseline = try render(format, image: image, document: empty, scene: scene)
                XCTAssertEqual(differences(actual, baseline, in: CGRect(x: 95, y: 95, width: 15, height: 10)), 0,
                               "\(format): the leader must not cross the crater interior")
                XCTAssertGreaterThan(differences(actual, baseline, in: CGRect(x: 130, y: 95, width: 10, height: 10)), 2,
                                     "\(format): retain the leader outside the crater rim")
            }
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".svg")
            defer { try? FileManager.default.removeItem(at: url) }
            try SceneRenderer.svg(image: image, document: document, scene: scene, to: url)
            let expected = String(format: "d=\"M %.4f,%.4f L %.4f,%.4f\"", oracle.rim_leader[0], oracle.rim_leader[1], oracle.rim_leader[2], oracle.rim_leader[3])
            XCTAssertTrue(try String(contentsOf: url, encoding: .utf8).contains(expected))
        }
    }
    func testMovingAndHidingTheOverviewRefreshesTheExistingCanvasCache() async throws {
        try await MainActor.run {
            let (image, original, scene) = fixture(), cache = CanvasRenderCache()
            let first = try render("canvas", image: image, document: original, scene: scene, cache: cache)
            var moved = original
            moved.changeStyle { $0.values["overview_position"] = .array([.number(240), .number(30)]) }
            let exposed = try render("canvas", image: image, document: moved, scene: scene, cache: cache)
            var hidden = original; hidden.changeStyle { $0.set("overview_enabled", false) }
            let complete = try render("canvas", image: image, document: hidden, scene: scene, cache: cache)
            let oldCard = SceneRenderer.overviewRect(original).insetBy(dx: 2, dy: 2)
            XCTAssertEqual(differences(exposed, complete, in: oldCard), 0, "Moving the card must reveal the complete old rim")
            XCTAssertGreaterThan(differences(first, complete, in: oldCard), 20)
            XCTAssertEqual(try render("canvas", image: image, document: original, scene: scene, cache: cache).rgba, first.rgba)
            XCTAssertEqual(cache.rasterizationCount, 1, "Moving, hiding and restoring the card reuse the same map and label rasters")
            XCTAssertEqual(moved.annotations, original.annotations, "Moving the overview must not alter lunar geometry or user edits")
            var unavailable = scene; unavailable.overview = nil
            let withoutModel = try render("canvas", image: image, document: original, scene: unavailable)
            XCTAssertEqual(withoutModel.rgba, complete.rgba, "Do not leave a clipping hole when the overview is unavailable")
        }
    }
    func testArtOverviewMotionReusesTheRasterAndMatchesFreshRendering() async throws {
        try await MainActor.run {
            let (image, initial, scene) = fixture(), cache = CanvasRenderCache()
            var document = initial; document.changeStyle { $0.set("art_style", "manuscript") }
            let original = document
            for point in [[16.0, 350.0], [20.0, 346.0], [240.0, 30.0], [16.0, 350.0]] {
                document.changeStyle { $0.values["overview_position"] = .array(point.map(JSONValue.number)) }
                let actual = try render("canvas", image: image, document: document, scene: scene, cache: cache)
                let expected = try render("canvas", image: image, document: document, scene: scene)
                let errors = zip(actual.rgba, expected.rgba).map { abs(Int($0) - Int($1)) }
                XCTAssertLessThan(Double(errors.reduce(0, +)) / Double(errors.count), 0.5)
            }
            XCTAssertEqual(cache.rasterizationCount, 1, "Moving only the overview must reuse the art/map raster")
            XCTAssertEqual(document.annotations, original.annotations)
            XCTAssertEqual(document.calibration, original.calibration)
        }
    }
    func testRegenerationUsesTheMovedOverviewAndKeepsTheActualCraterRim() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let (image, original, scene) = fixture(), photo = try PhotoPixels(image)
            var document = original; document.annotations = []
            document.calibration = Calibration(geometry: MoonGeometry(native: [1,0,0, 0,1,0, 0,0,1, 1,0,0, 384400], utc: "2025-09-14T15:00:00Z"),
                                               matrix: [[200,0,104],[0,-200,395]])
            document.state.projectionSurface = "sphere"
            document.changeStyle { $0.set("illuminated_only", false); $0.values["overview_position"] = .array([.number(240), .number(30)]) }
            let feature = Feature(id: "collision-crater", name: "Tycho", chinese: "第谷", latitude: 0, longitude: 0, diameter: 300, kind: "Crater, craters")
            func regenerate(_ document: MoonDocument) throws -> (MoonDocument, AnnotationScene) {
                try AnnotationSceneBuilder.build(document: document, photo: photo, features: [feature], dem: nil, task: ComputeTask(),
                    measure: AnnotationRenderer.measure, captionBounds: SceneRenderer.labelBounds,
                    configureCaption: { SceneRenderer.configureCaption($0, feature: $1, document: $2) }, reusingScene: scene)
            }
            let before = try regenerate(document)
            let rim = try XCTUnwrap(before.0.annotations.first?.visual?.outline)
            XCTAssertFalse(rim.isEmpty)
            let model = EditorModel(); model.document = before.0; model.appliedDocument = before.0
            model.image = image; model.scene = before.1; model.panelTab = 1
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 360, height: 480)); canvas.model = model
            let window = NSWindow(contentRect: canvas.frame, styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = canvas; defer { window.close() }
            let old = SceneRenderer.overviewRect(before.0), target = SceneRenderer.overviewRect(original)
            let start = CGPoint(x: old.midX, y: old.midY), end = CGPoint(x: target.midX, y: target.midY)
            func event(_ type: NSEvent.EventType, _ point: CGPoint) throws -> NSEvent {
                try XCTUnwrap(NSEvent.mouseEvent(with: type, location: canvas.convert(point, to: nil), modifierFlags: .command,
                    timestamp: 0, windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1))
            }
            canvas.mouseDown(with: try event(.leftMouseDown, start))
            canvas.mouseDragged(with: try event(.leftMouseDragged, end))
            canvas.mouseUp(with: try event(.leftMouseUp, end))
            document = try XCTUnwrap(model.displayDocument)
            XCTAssertEqual(SceneRenderer.overviewRect(document), target, "The real Cmd-drag must update the live overview position")
            let after = try regenerate(document), annotation = try XCTUnwrap(after.0.annotations.first)
            XCTAssertEqual(annotation.visual?.outline, rim)
            XCTAssertFalse(SceneRenderer.labelBounds(annotation, document: after.0).intersects(SceneRenderer.overviewRect(after.0)))
            var empty = after.0; empty.annotations = []
            let baseline = try render("png", image: image, document: empty, scene: after.1)
            let actual = try render("png", image: image, document: after.0, scene: after.1)
            XCTAssertEqual(differences(actual, baseline, in: SceneRenderer.overviewRect(after.0).insetBy(dx: 2, dy: 2)), 0)
            XCTAssertEqual(after.0.calibration, before.0.calibration)
        }
    }
}
