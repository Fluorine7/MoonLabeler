// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class ProjectTests: XCTestCase {
    func demo() throws -> MoonDocument {
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = 1600; document.imageHeight = 1450
        return document
    }

    func testProjectionMatchesExistingPythonDemoAnchors() throws {
        let document = try demo(), catalog = try Catalog.load()
        // Reference values from geometry.py + the existing demo's affine matrix.
        let expected: [(String, Double, Double)] = [
            ("1296", 712.5268405238397, 525.188397024805),
            ("6163", 620.0905686625013, 1022.0689753354137),
            ("4757", 951.6381755377242, 255.5236085048519),
            ("1236", 576.5029537859118, 1115.3814448460166),
        ]
        for (id, x, y) in expected {
            let feature = try XCTUnwrap(catalog.first { $0.id == id })
            let result = try XCTUnwrap(document.calibration).project(feature)
            XCTAssertTrue(result.visible)
            XCTAssertEqual(result.point.x, x, accuracy: 1e-9)
            XCTAssertEqual(result.point.y, y, accuracy: 1e-9)
        }
    }

    func testHiddenAndEditedLabelsSurviveRegeneration() throws {
        var document = try demo()
        let catalog = try Catalog.load()
        let overrides: [String: LegacyOverride] = [
            "1296": LegacyOverride(text: "自定义 · Copernicus", position: PixelPoint(30, 50), hidden: false, force: true),
            "6163": LegacyOverride(text: nil, position: nil, hidden: true, force: true),
        ]
        document.annotations = LabelLayout.generate(document: document, features: catalog, overrides: overrides)
        XCTAssertEqual(document.annotations.first { $0.featureID == "1296" }?.position, PixelPoint(30, 50))
        XCTAssertTrue(try XCTUnwrap(document.annotations.first { $0.featureID == "6163" }).hidden)
        document.settings.language = .english
        let updated = LabelLayout.generate(document: document, features: catalog)
        XCTAssertEqual(updated.first { $0.featureID == "1296" }?.text, "自定义 · Copernicus")
        XCTAssertTrue(try XCTUnwrap(updated.first { $0.featureID == "6163" }).hidden)
        XCTAssertLessThanOrEqual(updated.filter { !$0.hidden }.count, document.settings.maximumLabels)
    }

    func testPortableSaveRoundTripAndOriginalRemainsUntouched() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let originalData = try Data(contentsOf: Catalog.demoURL)
        var document = try demo()
        document.imagePath = directory.appendingPathComponent("照片.png").path
        document.annotations = [Annotation(text: "第谷 & Tycho", anchor: PixelPoint(300, 400), position: PixelPoint(350, 420))]
        let target = directory.appendingPathComponent("试用.moonswift")
        try ProjectIO.write(document, to: target)
        let saved = try JSONSerialization.jsonObject(with: Data(contentsOf: target)) as! [String: Any]
        XCTAssertEqual(saved["imagePath"] as? String, "照片.png")
        XCTAssertEqual(try ProjectIO.read(target).document, document)
        XCTAssertThrowsError(try ProjectIO.write(document, to: Catalog.demoURL))
        XCTAssertEqual(try Data(contentsOf: Catalog.demoURL), originalData)
    }

    func testInvalidNativeAndLegacyValuesAreRejected() throws {
        var document = try demo()
        document.annotations = [Annotation(text: "bad", anchor: PixelPoint(.nan, 0), position: PixelPoint(0, 0))]
        XCTAssertThrowsError(try document.validate())
        document.annotations = []
        document.calibration?.matrix = [[0, 0, 0], [0, 0, 0]]
        XCTAssertThrowsError(try document.validate())
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        var root = try JSONSerialization.jsonObject(with: Data(contentsOf: Catalog.demoURL)) as! [String: Any]
        root["style"] = ["font_size": true]
        let target = directory.appendingPathComponent("bad.moonlabel")
        try JSONSerialization.data(withJSONObject: root).write(to: target)
        XCTAssertThrowsError(try ProjectIO.read(target))
        root["version"] = 99
        try JSONSerialization.data(withJSONObject: root).write(to: target)
        XCTAssertThrowsError(try ProjectIO.read(target))
    }

    func testFarSideFeaturesAreExcludedAndLensDistortionIsApplied() throws {
        var document = try demo()
        let catalog = try Catalog.load(), copernicus = try XCTUnwrap(catalog.first { $0.id == "1296" })
        let original = try XCTUnwrap(document.calibration).project(copernicus).point
        document.calibration?.distortion = LensDistortion(center: [800, 700], scale: 1000, k: 0.2)
        let result = try XCTUnwrap(document.calibration).project(copernicus).point
        let dx = (original.x - 800) / 1000, dy = (original.y - 700) / 1000
        XCTAssertEqual(result.x, original.x + 0.2 * dx * (dx * dx + dy * dy) * 1000, accuracy: 1e-10)
        let labels = LabelLayout.generate(document: document, features: catalog)
        XCTAssertFalse(labels.isEmpty)
        for label in labels {
            let feature = try XCTUnwrap(catalog.first { $0.id == label.featureID })
            XCTAssertTrue(try XCTUnwrap(document.calibration).project(feature).visible)
        }
    }
}
