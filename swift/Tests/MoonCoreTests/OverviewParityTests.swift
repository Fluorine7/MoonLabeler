// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class OverviewParityTests: XCTestCase {
    struct Oracle: Decodable { var geometry: MoonGeometry, matrix: [[Double]], center: [Double], north: [Double]?, south: [Double]?, north_bearing: [Double], bounds: [Double] }
    func testNorthernPhotoKeepsTheActualObservedGlobe() throws {
        let data = try Data(contentsOf: XCTUnwrap(Bundle.module.url(forResource: "overview-0122-oracle", withExtension: "json")))
        let expected = try JSONDecoder().decode(Oracle.self, from: data)
        var document = MoonDocument(imagePath: "0708.jpg"); document.imageWidth = 2800; document.imageHeight = 1866
        document.calibration = Calibration(geometry: expected.geometry, matrix: expected.matrix)
        let actual = try XCTUnwrap(OverviewBuilder.build(document: document, task: ComputeTask()))
        XCTAssertEqual(actual.latitude, expected.center[0], accuracy: 1e-8); XCTAssertEqual(actual.longitude, expected.center[1], accuracy: 1e-8)
        XCTAssertNil(actual.north, "The north pole is behind the observed globe, despite the photo being northern")
        let south = try XCTUnwrap(actual.south), target = try XCTUnwrap(expected.south)
        XCTAssertEqual(south.x, target[0], accuracy: 1e-8); XCTAssertEqual(south.y, target[1], accuracy: 1e-8)
        let points = actual.footprint.flatMap { $0 }
        let bounds = [points.map(\.x).min()!, points.map(\.y).min()!, points.map(\.x).max()!, points.map(\.y).max()!]
        for (a,b) in zip(bounds,expected.bounds) { XCTAssertEqual(a,b,accuracy:1.5) }
    }
}
