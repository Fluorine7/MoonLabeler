// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class EyepieceParityTests: XCTestCase {
    private struct Oracle: Decodable { var cases: [Case] }
    private struct Case: Decodable { var photo: String, utc: String, method: String, rms: Double, inliers: Int, limbP95: Double, probes: [[Double]] }
    private struct MatchOracle: Decodable { var cases: [MatchCase] }
    private struct MatchCase: Decodable {
        var photo: String, geometry: MoonGeometry, projection: [[Double]], matrix: [[Double]], source: [[Double]], target: [[Double]]
        var sourceMatches: [[Double]], targetMatches: [[Double]], coverage: Double, rms: Double, mirrored: Bool, limb: [Double]
        var accepted: Bool, expectedRMS: Double, expectedInliers: Int
    }
    func testPaddedPhoneCrescentMatchesPython() throws { try verify("2502041049.jpg") }
    func testPhonePhotoRequiringAlignedRematchMatchesPython() throws { try verify("2305271151.jpg") }
    func testPreviouslyWorkingPhonePhotoStillMatchesPython() throws { try verify("2507041216.jpg") }
    func testAlbedoReferenceMatchesPythonPixels() throws {
        let oracle = try matchesOracle().cases[0]
        let actual = try ReferenceRenderer.atlas(geometry: oracle.geometry, size: 256, task: ComputeTask()).image
        let expected = try PhotoPixels.load(XCTUnwrap(Bundle.module.url(forResource: "albedo-python-256", withExtension: "png")))
        let different = zip(actual.rgba, expected.rgba).filter { $0 != $1 }.count
        XCTAssertEqual(different, 0, "Reference sampling and lighting must match Python before extracting SIFT features")
    }
    func testFrozenMatchesKeepPythonOpticalAcceptanceAndRejection() throws {
        for oracle in try matchesOracle().cases {
            let photo = try localPhoto(oracle.photo)
            let points: ([[Double]]) -> [PixelPoint] = { $0.map { PixelPoint($0[0], $0[1]) } }
            let match = RegistrationResult(matrix: oracle.matrix, rms: oracle.rms, coverage: oracle.coverage, matches: oracle.sourceMatches.count,
                                           source: points(oracle.source), target: points(oracle.target), sourceMatches: points(oracle.sourceMatches),
                                           targetMatches: points(oracle.targetMatches), mirrored: oracle.mirrored)
            let reference = TerrainReference(image: photo, matrix: oracle.projection, validFraction: 1, resolutionKM: 0)
            let identify = { try RecognitionEngine.optical(photo: photo, geometry: oracle.geometry, reference: reference, match: match, mask: nil, limb: oracle.limb, task: ComputeTask()) }
            if oracle.accepted {
                let actual = try identify()
                XCTAssertEqual(actual.rms, oracle.expectedRMS, accuracy: 0.00001)
                XCTAssertEqual(actual.matches, oracle.expectedInliers)
            } else {
                XCTAssertThrowsError(try identify()) { error in
                    XCTAssertTrue(error.localizedDescription.contains("分区预测不稳定"), "The unvalidated first pass must still be rejected: \(error)")
                }
            }
        }
    }
    private func matchesOracle() throws -> MatchOracle {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "eyepiece-matches-python", withExtension: "json"))
        return try JSONDecoder().decode(MatchOracle.self, from: Data(contentsOf: url))
    }
    private func localPhoto(_ name: String) throws -> PhotoPixels {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let url = root.appendingPathComponent(name)
        guard FileManager.default.fileExists(atPath: url.path) else { throw XCTSkip("Local photographer image required: \(name)") }
        return try PhotoPixels.load(url)
    }
    private func verify(_ name: String) throws {
        let photo = try localPhoto(name)
        let oracleURL = try XCTUnwrap(Bundle.module.url(forResource: "eyepiece-python-oracle", withExtension: "json"))
        let oracle = try XCTUnwrap(JSONDecoder().decode(Oracle.self, from: Data(contentsOf: oracleURL)).cases.first { $0.photo == name })
        var state = ProjectState(); state.utc = oracle.utc; state.captureMode = "afocal"
        let geometry = try NativeCompute.ephemeris(utc: state.utc)
        let result = try RecognitionEngine.identify(photo: photo, geometry: geometry, state: state, features: Catalog.load(), dem: nil, task: ComputeTask(), progress: { _ in })
        XCTAssertEqual(result.method.contains("rigid-aligned rematch"), oracle.method.contains("rigid-aligned rematch"))
        XCTAssertNotNil(result.calibration.distortion)
        XCTAssertGreaterThanOrEqual(result.matches, 100); XCTAssertLessThan(result.rms, 2)
        XCTAssertLessThan(result.details["limb_p95_px"]?.number ?? .infinity, oracle.limbP95 + 1)
        var errors: [Double] = []
        for probe in oracle.probes {
            let model = result.calibration.geometry.project(latitude: probe[0], longitude: probe[1])
            let point = result.calibration.photoPoint(model.point)
            errors.append(hypot(point.x - probe[2], point.y - probe[3]))
        }
        errors.sort(); XCTAssertFalse(errors.isEmpty)
        XCTAssertLessThan(errors[Int(Double(errors.count - 1) * 0.95)], 3, "Illuminated surface positions must agree with the Python fit")
    }
}
