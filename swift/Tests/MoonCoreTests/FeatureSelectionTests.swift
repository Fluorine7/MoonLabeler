// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class FeatureSelectionTests: XCTestCase {
    func testOlderNativeProjectsKeepTheirAllTypesMeaning() throws {
        var document = try document(kind: "全部")
        document.settings.allKinds = nil
        let data = try JSONEncoder().encode(document)
        let reopened = try JSONDecoder().decode(MoonDocument.self, from: data)
        XCTAssertTrue(reopened.settings.includes(kind: "Mare, maria"))
        XCTAssertTrue(reopened.settings.includes(kind: "Future type"))
    }
    private func document(kind: Any) throws -> MoonDocument {
        let demo = try ProjectIO.read(Catalog.demoURL).document
        var root = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: Catalog.demoURL)) as? [String: Any])
        var style = try XCTUnwrap(root["style"] as? [String: Any]); style["kind"] = kind; root["style"] = style
        root["image_path"] = demo.imagePath
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".moonlabel")
        defer { try? FileManager.default.removeItem(at: url) }
        try JSONSerialization.data(withJSONObject: root).write(to: url)
        var result = try ProjectIO.read(url).document
        let photo = try PhotoPixels.load(URL(fileURLWithPath: demo.imagePath))
        result.imageWidth = photo.width; result.imageHeight = photo.height
        return result
    }

    func testEmptyPythonSelectionShowsNoTerrainButKeepsLandingSites() throws {
        let document = try document(kind: [String]()), features = try Catalog.load()
        let photo = try PhotoPixels.load(URL(fileURLWithPath: document.imagePath)), camera = try XCTUnwrap(document.calibration)
        let ranked = try FeatureRanking.rank(features: features, document: document, photo: photo, overrides: [:], anchor: { camera.project($0).point }, task: ComputeTask())
        XCTAssertTrue(ranked.isEmpty, "Python kind=[] means no terrain types, not all types")
        XCTAssertTrue(LabelLayout.generate(document: document, features: features).isEmpty)
        let withLandings = LabelLayout.generate(document: document, features: features + (try AnnotationSceneBuilder.landings()))
        XCTAssertFalse(withLandings.isEmpty)
        XCTAssertTrue(withLandings.allSatisfy { $0.featureID?.hasPrefix("landing:") == true })
    }

    func testTypeSelectionsRoundTripWithoutDiscardingEditsOrUnknownTypes() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        for (index, kind) in ["全部" as Any, [String](), ["Crater, craters", "Mare, maria"], ["Future type"]].enumerated() {
            var original = try document(kind: kind)
            original.state.legacy["labels"] = .object(["1296": .object(["text": .string("手工名称"), "position": .array([.number(30), .number(60)])])])
            let native = directory.appendingPathComponent("types-\(index).moonswift"), legacy = directory.appendingPathComponent("types-\(index).moonlabel")
            try ProjectIO.write(original, to: native)
            let reopened = try ProjectIO.read(native).document
            try ProjectCompatibility.writeLegacy(reopened, to: legacy)
            let root = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: legacy)) as? [String: Any])
            let style = try XCTUnwrap(root["style"] as? [String: Any])
            XCTAssertEqual(try JSONSerialization.data(withJSONObject: style["kind"]!, options: [.fragmentsAllowed, .sortedKeys]),
                           try JSONSerialization.data(withJSONObject: kind, options: [.fragmentsAllowed, .sortedKeys]))
            XCTAssertEqual(reopened.calibration, original.calibration)
            XCTAssertEqual(reopened.state.legacy["labels"], original.state.legacy["labels"])
        }
    }
}
