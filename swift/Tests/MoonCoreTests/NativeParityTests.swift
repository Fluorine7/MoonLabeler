// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class NativeParityTests: XCTestCase {
    struct ManualOracle: Decodable {
        var shape: String, ids: [String], target: [[Double]], matrix: [[Double]], rms: Double, anchors: [[Double]], point_ids: [String], rim_ids: [String]
    }
    func testManualDEMRefitAndPortableAnchorsMatchPython0121() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "manual-relief-0121-oracle", withExtension: "json"))
        let cases = try JSONDecoder().decode([ManualOracle].self, from: Data(contentsOf: url))
        let dem = try ElevationMap(url: XCTUnwrap(Catalog.resource("LDEM_16", "LBL"))), features = try Catalog.load()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".moonswift")
        defer { try? FileManager.default.removeItem(at: file) }
        for oracle in cases {
            var document = try ProjectIO.read(Catalog.demoURL).document
            document.imageWidth = 1600; document.imageHeight = 1450
            document.changeStyle { $0.set("crater_outline_shape", oracle.shape) }
            document.state.anchors = zip(oracle.ids, oracle.target).map { ControlPoint(id: $0.0, point: PixelPoint($0.1[0], $0.1[1])) }
            document.state.anchors.insert(ControlPoint(id: "disabled-unknown", point: PixelPoint(0, 0), enabled: false), at: 1)
            let solved = try ManualCalibration.solve(document: document, features: features, dem: dem, task: ComputeTask())
            XCTAssertEqual(solved.0.state.projectionSurface, "terrain")
            let camera = try XCTUnwrap(solved.0.calibration), surface = try AnnotationSurface(document: solved.0)
            for row in 0..<2 { for column in 0..<3 { XCTAssertEqual(camera.matrix[row][column], oracle.matrix[row][column], accuracy: 0.001) } }
            XCTAssertEqual(solved.1.rms, oracle.rms, accuracy: 0.001)
            let snapshot = try XCTUnwrap(solved.0.state.legacy["annotation_relief"])
            XCTAssertEqual(snapshot.object["points"]?.object.keys.sorted(), oracle.point_ids)
            XCTAssertEqual(snapshot.object["rims"]?.object.keys.sorted(), oracle.rim_ids)
            try ProjectIO.write(solved.0, to: file)
            let restored = try AnnotationSurface(document: ProjectIO.read(file).document)
            for (index, id) in oracle.ids.enumerated() {
                let feature = try XCTUnwrap(features.first { $0.id == id }), point = surface.position(feature).point
                XCTAssertEqual(point.x, oracle.anchors[index][0], accuracy: 0.001); XCTAssertEqual(point.y, oracle.anchors[index][1], accuracy: 0.001)
                XCTAssertEqual(restored.position(feature).point, point)
            }
            let sphere = try ManualCalibration.solve(document: document, features: features, dem: nil, task: ComputeTask())
            XCTAssertEqual(sphere.0.state.projectionSurface, "sphere"); XCTAssertNil(sphere.0.state.legacy["annotation_relief"])
        }
    }
    struct GeometryCase: Decodable { var utc: String; var latitude: Double?; var longitude: Double?; var geometry: MoonGeometry }
    func testCSPICEAndSkyfieldUseTheSameDE421View() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "geometry-oracle", withExtension: "json"))
        let cases = try JSONDecoder().decode([GeometryCase].self, from: Data(contentsOf: url))
        for item in cases {
            let result = try NativeCompute.ephemeris(utc: item.utc, latitude: item.latitude, longitude: item.longitude)
            for (native, python) in zip(result.native.prefix(12), item.geometry.native.prefix(12)) {
                XCTAssertEqual(native, python, accuracy: 2e-7, item.utc)
            }
            XCTAssertEqual(result.distanceKM, item.geometry.distanceKM, accuracy: 0.002)
        }
    }
    func testManualSimilarityReportsMirrorsAndAnOutlier() throws {
        let source = [PixelPoint(0, 0), PixelPoint(1, 0), PixelPoint(0, 1), PixelPoint(1, 1), PixelPoint(0.4, 0.7)]
        let target = source.map { PixelPoint(400 - $0.x * 120 - $0.y * 10, 250 - $0.x * 10 + $0.y * 120) }
        let result = try NativeCompute.fit(source: source, target: target)
        XCTAssertLessThan(result.rms, 1e-9)
        XCTAssertLessThan(result.matrix[0][0] * result.matrix[1][1] - result.matrix[0][1] * result.matrix[1][0], 0)
        var incorrect = target; incorrect[4].x += 45
        let report = try NativeCompute.fit(source: source, target: incorrect)
        XCTAssertEqual(report.suspect, 4)
        XCTAssertThrowsError(try NativeCompute.fit(source: [PixelPoint(0, 0), PixelPoint(0.1, 0), PixelPoint(1, 0)], target: Array(target.prefix(3))))
    }
    func testFilenameTimeAndTraditionalNames() {
        let date = UTCClock.filenameDate("2026-08-31-2137_7-Moon_lapl3.tif")
        XCTAssertEqual(date.map(UTCClock.string), "2026-08-31T21:37:42Z")
        XCTAssertEqual(ChineseConversion.traditional("月面地形与阿波罗"), "月面地形與阿波羅")
    }
    func testLegacyMetadataSurvivesNativeEditing() throws {
        let opened = try ProjectIO.read(Catalog.demoURL)
        XCTAssertEqual(opened.document.state.anchors.count, 4)
        XCTAssertEqual(opened.document.style.number("font_percent", 0), 1.5)
        XCTAssertEqual(opened.document.state.utc, "2026-09-26T12:00:00+00:00")
    }
}
