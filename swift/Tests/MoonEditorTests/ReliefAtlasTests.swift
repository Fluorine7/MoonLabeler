// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import XCTest
@testable import MoonCore
@testable import MoonEditor

final class ReliefAtlasTests: XCTestCase {
    @MainActor func testChoosingAnAtlasKeepsTheAppliedMapUntilRegeneration() throws {
        let model = EditorModel()
        var applied = try ProjectIO.read(Catalog.demoURL).document
        applied.changeStyle {
            $0.applyArt("manuscript")
            $0.set("map_light_mask", false)
        }
        model.document = applied; model.appliedDocument = applied
        model.edit { $0.changeStyle { $0.applyArt("relief_atlas") } }
        model.edit { $0.changeStyle { $0.set("map_light_threshold", 21.0) } }

        XCTAssertTrue(model.hasPendingStyle)
        XCTAssertTrue(model.document?.style.litMapOnly == true)
        let displayed = try XCTUnwrap(model.displayDocument)
        XCTAssertEqual(displayed.style.art, "manuscript")
        XCTAssertEqual(displayed.style.number("elevation_opacity", 0), 0.72)
        XCTAssertEqual(displayed.style.number("contour_opacity", 0), 0.48)
        XCTAssertFalse(displayed.style.litMapOnly)
        XCTAssertEqual(displayed.style.threshold, 21)
    }

    func testReliefColorsMatchPythonAndFollowTheLocalHeightRange() {
        let width = 17, height = 11
        var heights: [Float] = [], rgba: [UInt8] = []
        for y in 0..<height {
            for x in 0..<width {
                let elevation = -4.5 + 0.14 * Double(x) + 0.19 * Double(y) + 0.017 * Double((x * 3 + y * 7) % 13)
                heights.append(x < 2 && y < 3 ? .nan : Float(elevation))
                rgba += [UInt8((x * 23 + y * 71) % 256), UInt8((x * 11 + y * 13) % 256), UInt8((x * 19 + y * 29) % 256), 255]
            }
        }
        heights[5 * width + 8] -= 0.85
        heights[10 * width + 16] += 6
        let raster = HeightRaster(width: width, height: height, photoWidth: width, photoHeight: height,
                                  values: heights, resolutionKM: 1)
        let photo = PhotoPixels(width: width, height: height, rgba: rgba)
        var style = ProjectStyle(); style.applyArt("relief_atlas")
        let shaded = MapBuilder.colorize(raster, palette: "relief_atlas", photo: photo, style: style)
        let untextured = MapBuilder.colorize(raster, palette: "relief_atlas", style: style)
        // Python 0.12.5 colorize_elevation outputs for the same Float32 raster.
        let probes: [(Int, Int, [Int], [Int])] = [
            (3, 0, [42, 64, 113], [67, 86, 129]),
            (4, 2, [106, 130, 169], [93, 120, 162]),
            (8, 5, [77, 119, 173], [102, 139, 184]),
            (9, 5, [207, 228, 190], [213, 231, 197]),
            (12, 9, [204, 167, 133], [197, 157, 118]),
            (16, 10, [170, 120, 106], [174, 128, 114]),
        ]
        for (x, y, expected, bare) in probes {
            let index = (y * width + x) * 4
            for channel in 0..<3 {
                XCTAssertLessThanOrEqual(abs(Int(shaded.rgba[index + channel]) - expected[channel]), 1)
                XCTAssertLessThanOrEqual(abs(Int(untextured.rgba[index + channel]) - bare[channel]), 1)
            }
        }
        var offset = raster; offset.values = heights.map { $0 + 5 }
        let shifted = MapBuilder.colorize(offset, palette: "relief_atlas", photo: photo, style: style)
        XCTAssertLessThanOrEqual(zip(shaded.rgba, shifted.rgba).map { abs(Int($0) - Int($1)) }.max() ?? 0, 1)
        for i in heights.indices { XCTAssertEqual(shaded.rgba[i * 4 + 3], heights[i].isFinite ? 255 : 0) }
    }

    func testReliefAtlasExportsThePhotoFrameWithFineContoursAndItalicLabels() throws {
        let dem = try ElevationMap(url: XCTUnwrap(DataStore.bundledDEM))
        var document = try ProjectIO.read(Catalog.demoURL).document
        let photo = try PhotoPixels.load(URL(fileURLWithPath: document.imagePath))
        document.imageWidth = photo.width; document.imageHeight = photo.height
        document.settings.fontSize = 22; document.settings.language = .bilingual
        document.settings.minimumDiameter = 0; document.settings.allKinds = true
        document.changeStyle {
            $0.applyArt("relief_atlas")
            $0.set("follow_feature_paths", true)
            $0.set("illuminated_only", false)
        }
        document.state.legacy["labels"] = .object([:])
        let flat = Annotation(text: "月溪 · Reference", anchor: PixelPoint(640, 200), position: PixelPoint(650, 220))
        document.annotations = [flat]
        let feature = try XCTUnwrap(Catalog.load().first { $0.name == "Montes Haemus" })
        let (rendered, scene) = try AnnotationSceneBuilder.build(document: document, photo: photo, features: [feature], dem: dem,
            task: ComputeTask(), measure: AnnotationRenderer.measure, captionBounds: AnnotationRenderer.placementBounds,
            configureCaption: AnnotationRenderer.configureCaption)
        XCTAssertEqual(rendered.calibration, document.calibration)
        XCTAssertTrue(rendered.style.litMapOnly)
        XCTAssertNotNil(scene.layers.elevation)
        XCTAssertTrue(scene.layers.contours.contains { $0.major })
        XCTAssertTrue(scene.layers.contours.contains { !$0.major })
        XCTAssertNil(SceneRenderer.visibleLegendRect(rendered, scene: scene))
        XCTAssertFalse(try XCTUnwrap(rendered.annotations.first { $0.featureID == feature.id }?.visual?.pathGlyphs).isEmpty)

        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let png = directory.appendingPathComponent("atlas.png"), svg = directory.appendingPathComponent("atlas.svg")
        try PhotoIO.png(image: photo.cgImage, document: rendered, scene: scene, to: png)
        let bitmap = try PhotoPixels.load(png)
        XCTAssertEqual(bitmap.width, photo.width); XCTAssertEqual(bitmap.height, photo.height)
        try AnnotationRenderer.svg(image: photo.cgImage, document: rendered, scene: scene, to: svg)
        let xml = try XMLDocument(contentsOf: svg, options: [.nodePreserveWhitespace])
        XCTAssertEqual(xml.rootElement()?.attribute(forName: "viewBox")?.stringValue, "0 0 \(photo.width) \(photo.height)")
        XCTAssertTrue(try xml.nodes(forXPath: "//*[@id='elevation-legend']").isEmpty)
        XCTAssertFalse(try xml.nodes(forXPath: "//*[@id='photo-light']").isEmpty)
        let contours = try xml.nodes(forXPath: "//*[@id='elevation-contours']/*").compactMap { $0 as? XMLElement }
        let minor = contours.filter { $0.attribute(forName: "stroke")?.stringValue == "#283e3c" }
        let index = contours.filter { $0.attribute(forName: "stroke")?.stringValue == "#232c3e" }
        let edges = contours.filter { $0.attribute(forName: "stroke")?.stringValue == "#d9d7b5" }
        XCTAssertFalse(minor.isEmpty); XCTAssertEqual(index.count, edges.count)
        let width = try XCTUnwrap(minor.first?.attribute(forName: "stroke-width")?.stringValue.flatMap(Double.init))
        XCTAssertEqual(width, max(0.38, Double(min(photo.width, photo.height)) * 0.00042), accuracy: 1e-9)
        let pathLabels = try xml.nodes(forXPath: "//*[local-name()='text'][@font-style='italic'][@transform]")
        XCTAssertFalse(pathLabels.isEmpty)
        let mixed = try XCTUnwrap(xml.nodes(forXPath: "//*[@id='label-\(flat.id.uuidString)']//*[local-name()='text'][@font-style='italic']").first)
        XCTAssertEqual(mixed.stringValue, flat.text)

        let legacy = directory.appendingPathComponent("atlas.moonlabel")
        try ProjectCompatibility.writeLegacy(rendered, to: legacy)
        let reopened = try ProjectIO.read(legacy).document
        XCTAssertTrue(reopened.style.isReliefAtlas)
        XCTAssertEqual(reopened.style.string("elevation_palette"), "relief_atlas")
        XCTAssertEqual(reopened.style.number("elevation_opacity", 0), 0.96)
        XCTAssertEqual(reopened.style.number("contour_opacity", 0), 0.72)
    }
}
