// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
import ImageIO
@testable import MoonCore
@testable import MoonEditor

final class SceneMemoryTests: XCTestCase {
    func testRetiredOverviewSourcesAreReleased() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let pixels = PhotoPixels(width: 32, height: 32, rgba: [UInt8](repeating: 255, count: 32 * 32 * 4))
            let overview = PhotoOverview(image: pixels, footprint: [], grid: [], latitude: 0, longitude: 0, north: nil, south: nil, earth: nil)
            var references: [WeakOverviewSource] = []
            for _ in 0..<24 {
                try autoreleasepool {
                    let source = try OverviewCard.image(overview, style: "manuscript", sceneID: UUID())
                    references.append(WeakOverviewSource(source))
                }
            }
            let retained = references.filter { $0.image != nil }.count
            print("OVERVIEW_STORAGE retained_sources=\(retained)")
            XCTAssertLessThanOrEqual(retained, 8, "Opening/regenerating scenes must not retain every obsolete SVG image")
        }
    }
    func testOpeningANewUncalibratedPhotoReleasesThePreviousScene() async throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".png")
        defer { try? FileManager.default.removeItem(at: url) }
        let (model, overviewSource) = try await MainActor.run {
            _ = NSApplication.shared
            let pixels = PhotoPixels(width: 64, height: 64, rgba: [UInt8](repeating: 255, count: 64 * 64 * 4)), image = pixels.cgImage
            var document = MoonDocument(imagePath: "retired.png"); document.imageWidth = 64; document.imageHeight = 64
            var scene = AnnotationScene(); scene.grayscale = pixels
            try autoreleasepool {
                let context = try XCTUnwrap(CGContext(data: nil, width: 64, height: 64, bitsPerComponent: 8, bytesPerRow: 256,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
                NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
                SceneRenderer.draw(image: image, document: document, scene: scene, context: context)
                NSGraphicsContext.restoreGraphicsState(); context.flush()
            }
            XCTAssertGreaterThan(SceneRenderer.textureMemoryUsage.staticBitmapBytes, 0)
            let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil))
            CGImageDestinationAddImage(destination, image, nil); XCTAssertTrue(CGImageDestinationFinalize(destination))
            let overview = PhotoOverview(image: pixels, footprint: [], grid: [], latitude: 0, longitude: 0, north: nil, south: nil, earth: nil)
            let overviewSource = try autoreleasepool {
                WeakOverviewSource(try OverviewCard.image(overview, style: "standard", sceneID: UUID()))
            }
            XCTAssertNotNil(overviewSource.image)
            let model = EditorModel(); model.requestOpen(url); return (model, overviewSource)
        }
        for _ in 0..<300 {
            if await MainActor.run(body: { !model.busy && model.image != nil }) { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        await MainActor.run {
            XCTAssertNotNil(model.image); XCTAssertNil(model.scene)
            XCTAssertEqual(SceneRenderer.textureMemoryUsage.staticBitmapBytes, 0, "A new uncalibrated photo must release the retired scene's display images")
            XCTAssertNil(overviewSource.image, "Opening a photo must also release the old overview source")
        }
    }
    func testRetiredScenesDoNotPinFullSizeDisplayBitmaps() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let side = 1024
            var rgba = [UInt8](repeating: 96, count: side * side * 4)
            for index in stride(from: 3, to: rgba.count, by: 4) { rgba[index] = 255 }
            let pixels = PhotoPixels(width: side, height: side, rgba: rgba), image = pixels.cgImage
            var document = MoonDocument(imagePath: "scene-memory.png")
            document.imageWidth = side; document.imageHeight = side
            document.changeStyle { $0.set("art_style", "manuscript"); $0.set("elevation_enabled", true) }
            for _ in 0..<5 {
                try autoreleasepool {
                    var scene = AnnotationScene(); scene.grayscale = pixels; scene.layers.elevation = pixels
                    let context = try XCTUnwrap(CGContext(data: nil, width: 96, height: 96, bitsPerComponent: 8, bytesPerRow: 384,
                        space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
                    context.translateBy(x: 0, y: 96); context.scaleBy(x: 96.0 / Double(side), y: -96.0 / Double(side))
                    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
                    SceneRenderer.draw(image: image, document: document, scene: scene, context: context)
                    NSGraphicsContext.restoreGraphicsState(); context.flush()
                }
            }
            let usage = SceneRenderer.textureMemoryUsage, oneScene = side * side * 4 * 2
            print("SCENE_STORAGE scenes=\(usage.scenes) static_bitmap_bytes=\(usage.staticBitmapBytes)")
            XCTAssertLessThanOrEqual(usage.scenes, 1, "Completed old scenes must not pin their full-size bitmap copies")
            XCTAssertLessThanOrEqual(usage.staticBitmapBytes, oneScene)
        }
    }
}

private final class WeakOverviewSource {
    weak var image: NSImage?
    init(_ image: NSImage) { self.image = image }
}
