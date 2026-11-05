// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class LayoutParityTests: XCTestCase {
    struct Oracle: Decodable {
        var width: Double, height: Double, gap: Double, maximum: Int
        var obstacles: [[Double]], requests: [PlacementRequest], placements: [String: [Double]], omitted: [String]
    }
    func testPositionsAndOmissionsMatchPython0121() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "layout-0121-oracle", withExtension: "json"))
        for item in try JSONDecoder().decode([Oracle].self, from: Data(contentsOf: url)) {
            var iterator = item.requests.makeIterator()
            let actual = LabelPlacement.arrange(next: { iterator.next() }, width: item.width, height: item.height, gap: item.gap, maximum: item.maximum,
                                               obstacles: item.obstacles.map { CGRect(x: $0[0], y: $0[1], width: $0[2], height: $0[3]) })
            XCTAssertEqual(Set(actual.placements.keys), Set(item.placements.keys))
            XCTAssertEqual(actual.omitted, Set(item.omitted))
            for (id, p) in item.placements {
                let rect = try XCTUnwrap(actual.placements[id]); XCTAssertEqual(rect.minX, p[0], accuracy: 1e-9); XCTAssertEqual(rect.minY, p[1], accuracy: 1e-9)
            }
        }
    }
    func testBilingualCaptionKeeps0121SingleLine() throws {
        let feature = try XCTUnwrap(Catalog.load().first { $0.name == "Copernicus" })
        XCTAssertEqual(feature.caption(.bilingual), "哥白尼 · Copernicus")
        XCTAssertFalse(feature.caption(.bilingual).contains("\n"))
    }
    func testLegacyPathDefaultKeepsExistingLayout() throws {
        var root = try JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: Catalog.demoURL)).object
        var style = root["style"]?.object ?? [:]; style.removeValue(forKey: "follow_feature_paths"); root["style"] = .object(style)
        XCTAssertFalse(try ProjectCompatibility.importState(root: root, relativeTo: Catalog.demoURL).style.bool("follow_feature_paths", true))
        style["follow_feature_paths"] = .bool(true); root["style"] = .object(style)
        XCTAssertTrue(try ProjectCompatibility.importState(root: root, relativeTo: Catalog.demoURL).style.bool("follow_feature_paths"))
    }
    func testArtworkTypeSizesMatchPython0121() throws {
        // Values from 0.12.1 Project._base_label_font_sizes with its demo camera.
        let expected: [(String, [Double])] = [("3678", [23,24,26,26,27]), ("4395", [29,30,32,34,33]), ("4004", [17,54,54,54,54]), ("6290", [51,54,54,54,54]), ("3691", [16,17,19,19,19]), ("1296", [64,64,64,64,64]), ("5064", [51,54,54,54,54]), ("8319", [44,45,45,45,46])]
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = 1600; document.imageHeight = 1450; document.settings.fontSize = 64
        let features = try Catalog.load()
        for (index, art) in ["manuscript", "cyanotype", "copperplate", "inkwash", "redalert"].enumerated() {
            document.changeStyle { $0.set("art_style", art) }
            for (id, sizes) in expected { XCTAssertEqual(LabelSizing.size(try XCTUnwrap(features.first { $0.id == id }), document: document), sizes[index], "\(art): \(id)") }
        }
    }
    struct RankingOracle: Decodable { var ids: [String]; var positions: [String: [Double]]; var sizes: [String: Double] }
    func testPhotographicRankingAndFontTiersMatchPython0121() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "ranking-0121-oracle", withExtension: "json"))
        let oracle = try JSONDecoder().decode(RankingOracle.self, from: Data(contentsOf: url))
        var document = try ProjectIO.read(Catalog.demoURL).document
        let photo = try PhotoPixels.load(URL(fileURLWithPath: document.imagePath))
        document.imageWidth = photo.width; document.imageHeight = photo.height
        document.settings.fontSize = LabelSizing.tierSizes(document)[0]
        let camera = try XCTUnwrap(document.calibration)
        let ranked = try FeatureRanking.rank(features: Catalog.load(), document: document, photo: photo, overrides: ProjectCompatibility.labelOverrides(document), anchor: { camera.project($0).point }, task: ComputeTask())
        XCTAssertEqual(ranked.map { $0.feature.id }, oracle.ids)
        for item in ranked {
            let position = try XCTUnwrap(oracle.positions[item.feature.id]); XCTAssertEqual(item.anchor.x, position[0], accuracy: 1e-8); XCTAssertEqual(item.anchor.y, position[1], accuracy: 1e-8)
            XCTAssertEqual(LabelSizing.size(item.feature, document: document), try XCTUnwrap(oracle.sizes[item.feature.id]), accuracy: 1e-8)
        }
    }
}
