// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class PathParityTests: XCTestCase {
    func testComputeEnvironmentOverridesLocalPreference() {
        XCTAssertEqual(ComputePolicy(preference: "cpu", environment: ["MOONLABELER_COMPUTE": "AUTO"]).mode, "auto")
        XCTAssertEqual(ComputePolicy(preference: "auto", environment: ["MOONLABELER_COMPUTE": "cpu", "MOON_SWIFT_COMPUTE": "auto"]).mode, "cpu")
        XCTAssertEqual(ComputePolicy(preference: "cpu", environment: ["MOONLABELER_COMPUTE": "metal"]).mode, "auto")
        XCTAssertNil(ComputePolicy(preference: "cpu", environment: ["MOONLABELER_COMPUTE": "invalid"]).overrideVariable)
        XCTAssertEqual(ComputePolicy(preference: "cpu", environment: [:]).mode, "cpu")
    }
    func testSavedReferenceHasItsOwnCoordinateStateAndRejectsCoarseMatching() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        var original = try ProjectIO.read(Catalog.demoURL).document
        original.state.legacy["labels"] = .object(["stale": .object([:])]); original.state.projectionSurface = "terrain"
        let geometry = try XCTUnwrap(original.calibration?.geometry)
        let image = PhotoPixels(width: 128, height: 128, rgba: [UInt8](repeating: 255, count: 128 * 128 * 4))
        var reference = TerrainReference(image: image, matrix: [[60, 0, 64], [0, 60, 64]], validFraction: 1, resolutionKM: 1.9)
        let png = directory.appendingPathComponent("reference.png")
        try ReferenceIO.save(reference, geometry: geometry, state: original.state, to: png)
        let project = png.deletingPathExtension().appendingPathExtension("moonlabel"), opened = try ProjectIO.read(project), saved = opened.document
        XCTAssertTrue(saved.state.anchors.isEmpty); XCTAssertTrue(saved.annotations.isEmpty)
        XCTAssertNil(saved.state.legacy["annotation_relief"]); XCTAssertEqual(saved.state.projectionSurface, "sphere")
        XCTAssertEqual(saved.calibration?.matrix, reference.matrix); XCTAssertEqual(opened.expectedSize, [128, 128])
        XCTAssertEqual(try ReferenceIO.local(project, utc: geometry.utc).1.imageWidth, 128)
        XCTAssertEqual(saved.state.terrainSettings, original.state.terrainSettings)
        reference.widthKM = 100
        XCTAssertThrowsError(try RecognitionEngine.matchReference(reference: reference, geometry: geometry, photo: image, mask: nil, task: ComputeTask())) { error in
            XCTAssertTrue(error.localizedDescription.contains("64"))
        }
    }
    struct Oracle: Decodable {
        struct Case: Decodable { var paths: [[[Double]]], rows: [PathCaptionRow], origin: [Double]?, glyphs: [[Double]]? }
        struct Projection: Decodable { var id: String, paths: [[[Double]]] }
        var cases: [Case], projections: [Projection]
    }
    func testCurvatureAndBilingualArcLengthsMatchPython0121() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "path-0121-oracle", withExtension: "json"))
        let oracle = try JSONDecoder().decode(Oracle.self, from: Data(contentsOf: url))
        for item in oracle.cases {
            let actual = LandformPaths.place(paths: item.paths.map { $0.map { PixelPoint($0[0], $0[1]) } }, rows: item.rows)
            guard let origin = item.origin, let glyphs = item.glyphs else { XCTAssertNil(actual); continue }
            let placed = try XCTUnwrap(actual)
            XCTAssertEqual(placed.origin.x, origin[0], accuracy: 1e-8); XCTAssertEqual(placed.origin.y, origin[1], accuracy: 1e-8)
            XCTAssertEqual(placed.glyphs.count, glyphs.count)
            for (glyph, expected) in zip(placed.glyphs, glyphs) {
                XCTAssertEqual(glyph.point.x, expected[0], accuracy: 1e-8); XCTAssertEqual(glyph.point.y, expected[1], accuracy: 1e-8)
                XCTAssertEqual(glyph.angle, expected[2], accuracy: 1e-8)
            }
        }
        var document = try ProjectIO.read(Catalog.demoURL).document; document.imageWidth = 1600; document.imageHeight = 1450
        document.changeStyle { $0.set("follow_feature_paths", true) }
        let features = try Catalog.load()
        for item in oracle.projections {
            let paths = LandformPaths.projected(feature: try XCTUnwrap(features.first { $0.id == item.id }), document: document)
            XCTAssertEqual(paths.map(\.count), item.paths.map(\.count))
            for (line, expected) in zip(paths, item.paths) { for (point, target) in zip(line, expected) {
                XCTAssertEqual(point.x, target[0], accuracy: 1e-8); XCTAssertEqual(point.y, target[1], accuracy: 1e-8)
            } }
        }
    }
    func testCandidateCSVPreservesOriginalUnitsAndUTF8() throws {
        var candidate = CraterCandidate(id: 9, center: PixelPoint(123.4567, 98.7654), major: 30.25, minor: 24.5, angle: -17.25, support: .nan)
        candidate.method = "manual"
        let data = CraterCSV.data(candidates: [candidate], imageName: "月面,\"原图\".tif")
        XCTAssertEqual(data.prefix(3), Data([0xef, 0xbb, 0xbf]))
        let text = try XCTUnwrap(String(data: data.dropFirst(3), encoding: .utf8))
        XCTAssertTrue(text.hasPrefix("image,candidate,center_x_px,center_y_px,semimajor_px,semiminor_px,angle_deg,edge_support,method\r\n"))
        XCTAssertTrue(text.contains("\"月面,\"\"原图\"\".tif\",1,123.457,98.765,30.250,24.500,-17.250,,manual\r\n"))
    }
}
