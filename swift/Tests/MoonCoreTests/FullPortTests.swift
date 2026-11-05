// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class FullPortTests: XCTestCase {
    func testAutomaticCraterEvidenceBecomesReviewableAnchorsAndPriorities() throws {
        let features = try Catalog.load()
        let main = try XCTUnwrap(features.first { $0.name == "Tycho" })
        let satellite = try XCTUnwrap(features.first { $0.name == "Tycho A" })
        let manual = try XCTUnwrap(features.first { $0.name == "Copernicus" })
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = 1600; document.imageHeight = 1450
        let camera = try XCTUnwrap(document.calibration)
        document.state.anchors = [ControlPoint(id: manual.id, point: PixelPoint(11, 22)), ControlPoint(id: main.id, point: PixelPoint(1, 2), enabled: false, source: "automatic"), ControlPoint(id: "stale-auto", point: PixelPoint(3, 4), source: "automatic")]
        document.state.legacy["labels"] = .object([main.id: .object(["text": .string("手工名称")])])
        let result = IdentificationResult(calibration: camera, method: "verified crater pattern", rms: 2, matches: 3, coverage: 0.7,
            identifiedCraters: [IdentifiedCrater(feature: main, center: PixelPoint(100, 120)), IdentifiedCrater(feature: satellite, center: PixelPoint(130, 140)), IdentifiedCrater(feature: manual, center: PixelPoint(150, 160))])
        try document.applyIdentification(result)
        XCTAssertEqual(document.state.anchors.count, 3)
        XCTAssertEqual(document.state.anchors.first { $0.id == manual.id }?.point, PixelPoint(11, 22))
        let automatic = try XCTUnwrap(document.state.anchors.first { $0.id == main.id })
        XCTAssertEqual(automatic.source, "automatic"); XCTAssertEqual(automatic.point, PixelPoint(100, 120)); XCTAssertEqual(automatic.enabled, false)
        XCTAssertEqual(document.state.anchors.first { $0.id == satellite.id }?.enabled, true)
        XCTAssertEqual(document.state.legacy["labels"]?.object[main.id]?.object["force"]?.bool, true)
        XCTAssertEqual(document.state.legacy["labels"]?.object[main.id]?.object["text"]?.string, "手工名称")
        XCTAssertNil(document.state.legacy["labels"]?.object[satellite.id]?.object["force"])
        XCTAssertEqual(document.state.legacy["automatic_recognition"]?.object["matched_names"]?.array.count, 3)
        XCTAssertEqual(document.referenceReport(features: features)?.residuals.count, 2)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let output = directory.appendingPathComponent("automatic.moonlabel")
        try ProjectCompatibility.writeLegacy(document, to: output)
        XCTAssertEqual(try ProjectIO.read(output).document.state.anchors, document.state.anchors)
    }
    func testAcceptedIdentificationRefreshesPoseDependentStateAndFilter() throws {
        var document = try ProjectIO.read(Catalog.demoURL).document
        var camera = try XCTUnwrap(document.calibration)
        camera.matrix = [[7000, 0, 1400], [0, 7000, 933]]
        document.settings.minimumDiameter = 40
        let edits: JSONValue = .object(["123": .object(["text": .string("保留改名")])])
        document.state.legacy["labels"] = edits
        document.state.legacy["annotation_relief"] = .object(["old": .bool(true)])
        document.state.legacy["terrain_rims"] = .object(["old": .bool(true)])
        document.state.legacy["automatic_recognition"] = .object(["old": .bool(true)])
        let result = IdentificationResult(calibration: camera, method: "validated image fit", rms: 2.4, matches: 459, coverage: 0.57, details: ["relief_aware": .bool(true)])
        try document.applyIdentification(result)
        XCTAssertEqual(document.settings.minimumDiameter, 5)
        XCTAssertEqual(document.state.geometry, camera.geometry)
        XCTAssertEqual(document.state.utc, camera.geometry.utc)
        XCTAssertEqual(document.state.projectionSurface, "terrain")
        XCTAssertNil(document.state.legacy["annotation_relief"])
        XCTAssertNil(document.state.legacy["terrain_rims"])
        XCTAssertNil(document.state.legacy["automatic_recognition"]?.object["old"])
        XCTAssertEqual(document.state.legacy["labels"], edits)
        document.settings.minimumDiameter = 100
        camera.matrix = [[1000, 0, 1400], [0, 1000, 933]]
        try document.applyIdentification(IdentificationResult(calibration: camera, method: "wide image", rms: 1, matches: 20, coverage: 0.8))
        XCTAssertEqual(document.settings.minimumDiameter, 15 * moonRadius / 1000, accuracy: 1e-9)
    }
    func testJPEGUsesThePhotographicRegistrationDecoder() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "decoder-oracle", withExtension: "jpg"))
        let oracle = try JSONDecoder().decode([UInt8].self, from: Data(contentsOf: XCTUnwrap(Bundle.module.url(forResource: "decoder-oracle", withExtension: "json"))))
        let photo = try PhotoPixels.load(url)
        XCTAssertEqual(photo.width, 48); XCTAssertEqual(photo.height, 32)
        XCTAssertEqual(photo.rgba.enumerated().filter { $0.offset % 4 != 3 }.map(\.element), oracle)
    }
    func testFITSScalingAndBottomUpOrientation() throws {
        func card(_ key: String, _ value: String) -> String { String((key.padding(toLength: 8, withPad: " ", startingAt: 0) + "= " + value).padding(toLength: 80, withPad: " ", startingAt: 0).prefix(80)) }
        let cards = [card("SIMPLE", "T"), card("BITPIX", "16"), card("NAXIS", "2"), card("NAXIS1", "4"), card("NAXIS2", "2"), card("BSCALE", "2"), card("BZERO", "32768"), "END".padding(toLength: 80, withPad: " ", startingAt: 0)]
        var bytes = Data(cards.joined().padding(toLength: 2880, withPad: " ", startingAt: 0).utf8)
        for value in 0..<8 { var big = Int16(value).bigEndian; withUnsafeBytes(of: &big) { bytes.append(contentsOf: $0) } }
        bytes.append(Data(repeating: 0, count: 2880 - 16))
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".fits")
        defer { try? FileManager.default.removeItem(at: url) }; try bytes.write(to: url)
        let result = try PhotoPixels.load(url)
        XCTAssertEqual(result.width, 4); XCTAssertEqual(result.height, 2)
        XCTAssertGreaterThan(result.rgba[0], result.rgba[4 * 4]); XCTAssertEqual(result.rgba[3 * 4], 255)
        XCTAssertEqual(result.rgba[4 * 4], 0)
    }
    func testNPZCoordinatesAndMetalReferenceAgainstCPU() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "synthetic-dem", withExtension: "npz")), dem = try ElevationMap(url: url)
        XCTAssertEqual(dem.sample(89.5, -179.5), 0.5 * sin(89.5 * .pi / 180) + 0.2 * cos(-179.5 * 3 * .pi / 180) * cos(89.5 * .pi / 180), accuracy: 1e-6)
        XCTAssertEqual(dem.sample(10, -180), dem.sample(10, 180), accuracy: 1e-9)
        guard MetalTerrainRenderer.available else { throw XCTSkip("No Metal device is exposed to this test process") }
        let geometry = try NativeCompute.ephemeris(utc: "2026-09-26T12:00:00Z"), task = ComputeTask()
        let previous = UserDefaults.standard.string(forKey: "moon-swift-compute")
        defer { UserDefaults.standard.set(previous, forKey: "moon-swift-compute") }
        UserDefaults.standard.set("auto", forKey: "moon-swift-compute")
        let gpu = try XCTUnwrap(MetalTerrainRenderer.render(dem: dem, geometry: geometry, size: 512, task: task), MetalTerrainRenderer.diagnostic)
        UserDefaults.standard.set("cpu", forKey: "moon-swift-compute")
        let cpu = try ReferenceRenderer.terrain(dem: dem, geometry: geometry, size: 512, task: task)
        let differences = zip(gpu.image.gray, cpu.image.gray).map { abs(Int($0) - Int($1)) }
        XCTAssertLessThan(Double(differences.reduce(0, +)) / Double(differences.count), 0.1)
        XCTAssertLessThanOrEqual(differences.max()!, 1)
    }
    func testLayoutResetKeepsTextAndLandingSitesIgnoreDiameterFilter() throws {
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = 1600; document.imageHeight = 1450
        let features = try Catalog.load(), all = features + (try AnnotationSceneBuilder.landings())
        document.style.set("show_landing_sites", true)
        document.annotations = LabelLayout.generate(document: document, features: all)
        XCTAssertTrue(document.annotations.contains { $0.featureID?.hasPrefix("landing:") == true })
        let index = try XCTUnwrap(document.annotations.firstIndex { $0.featureID == "1296" })
        let id = document.annotations[index].id
        document.annotations[index].text = "Custom Copernicus"; document.annotations[index].textEdited = true
        document.annotations[index].position = PixelPoint(10, 10); document.annotations[index].positionEdited = true; document.annotations[index].automatic = false
        ProjectCompatibility.resetAnnotations(&document, layoutOnly: true)
        document.annotations = LabelLayout.generate(document: document, features: all)
        let edited = try XCTUnwrap(document.annotations.first { $0.id == id })
        XCTAssertEqual(edited.text, "Custom Copernicus"); XCTAssertNotEqual(edited.position, PixelPoint(10, 10))
        ProjectCompatibility.resetAnnotations(&document, layoutOnly: false)
        XCTAssertTrue(document.annotations.isEmpty); XCTAssertTrue(ProjectCompatibility.labelOverrides(document).isEmpty)
    }
    func testPhotoCoverageRetainsEnclosedDarkCraterFloors() throws {
        var pixels = [UInt8](repeating: 255, count: 128 * 128 * 4)
        for y in 0..<128 { for x in 0..<128 {
            let inDisk = hypot(Double(x - 64), Double(y - 64)) < 54, inFloor = hypot(Double(x - 64), Double(y - 64)) < 18
            let gray: UInt8 = inDisk && !inFloor ? 150 : 0
            for c in 0..<3 { pixels[(y * 128 + x) * 4 + c] = gray }
        } }
        let field = try PhotoLightness(photo: PhotoPixels(width: 128, height: 128, rgba: pixels), calibration: nil)
        let coverage = try field.coverage(threshold: 45)
        XCTAssertGreaterThan(coverage.rgba[(64 * 128 + 64) * 4 + 3], 240)
        XCTAssertLessThan(coverage.rgba[3], 10)
        XCTAssertEqual(coverage.rgba[(64 * 128 + 64) * 4], coverage.rgba[(64 * 128 + 64) * 4 + 3])
    }
    func testLegacyUnknownFieldsAndFreeTextRoundTrip() throws {
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = 1600; document.imageHeight = 1450
        document.state.legacy["future_metadata"] = .object(["value": .number(42)])
        document.annotations = [Annotation(text: "Free & <text>", anchor: PixelPoint(10, 20), position: PixelPoint(30, 40))]
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".moonlabel")
        defer { try? FileManager.default.removeItem(at: url) }
        try ProjectCompatibility.writeLegacy(document, to: url)
        let loaded = try ProjectIO.read(url).document
        XCTAssertEqual(loaded.state.legacy["future_metadata"], document.state.legacy["future_metadata"])
        XCTAssertEqual(loaded.annotations, document.annotations)
    }
}
