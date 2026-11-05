// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class EyepieceEdgeTests: XCTestCase {
    private struct Oracle: Decodable {
        struct Probe: Decodable { var id: String, name: String, lat: Double, lon: Double, photo: [Double] }
        var geometry: MoonGeometry, matrix: [[Double]], distortion: LensDistortion, features: [Probe]
    }
    private func oracle() throws -> Oracle {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "eyepiece-edge-python", withExtension: "json"))
        return try JSONDecoder().decode(Oracle.self, from: Data(contentsOf: url))
    }
    private func lens(_ k2: Double) throws -> LensDistortion {
        let data = try JSONSerialization.data(withJSONObject: ["center": [500,400], "scale": 500, "k": 0.2, "k2": k2])
        return try JSONDecoder().decode(LensDistortion.self, from: data)
    }
    func testSecondRadialTermUsesPythonPixelsAndInverse() throws {
        let geometry = try oracle().geometry
        let camera = Calibration(geometry: geometry, matrix: [[500,0,500],[0,500,400]], distortion: try lens(-0.06))
        let actual = camera.photoPoint(PixelPoint(0.8,0))
        XCTAssertEqual(actual.x, 941.3696, accuracy: 1e-8)
        let model = camera.modelPoint(PixelPoint(941.3696,400))
        XCTAssertEqual(model.x, 0.8, accuracy: 1e-8); XCTAssertEqual(model.y,0,accuracy:1e-8)
    }
    func testSecondTermOutsideTheOpticalBranchIsUnavailable() throws {
        let camera = Calibration(geometry: try oracle().geometry, matrix: [[1,0,0],[0,1,0]],
                                 distortion: try JSONDecoder().decode(LensDistortion.self, from: Data(#"{"center":[0,0],"scale":1,"k":0.2,"k2":-0.06}"#.utf8)))
        XCTAssertFalse(camera.modelPoint(PixelPoint(3,0)).isFinite)
    }
    func testSecondTermInverseHandlesMirrorsAndTinyCoefficients() throws {
        for sign in [-1.0,1.0] { for second in [-0.06,0.06,-1e-250,1e-250] {
            let camera = Calibration(geometry: try oracle().geometry, matrix: [[400 * sign,-100,500],[100 * sign,400,400]], distortion: try lens(second))
            for point in [PixelPoint(0.8,0),PixelPoint(0.1,-0.9),PixelPoint(-0.7,0.4),PixelPoint(0,0)] {
                let original = camera.modelPoint(camera.photoPoint(point))
                XCTAssertEqual(original.x,point.x,accuracy:1e-8); XCTAssertEqual(original.y,point.y,accuracy:1e-8)
            }
        } }
        let scale = try lens(-0.06).areaScale(at: PixelPoint(900,400))
        XCTAssertEqual(scale, 1.26112 * 1.103424, accuracy: 1e-10)
    }
    func testInvalidSecondTermCannotEnterAnAcceptedCalibration() throws {
        for second in [-0.301,0.301,Double.infinity,Double.nan] {
            let camera = Calibration(geometry: try oracle().geometry, matrix: [[1,0,0],[0,1,0]],
                                     distortion: LensDistortion(center: [0,0], scale: 1, k: 0.2, k2: second))
            XCTAssertThrowsError(try camera.validate())
        }
    }
    private func accepted() throws -> IdentificationResult {
        let expected = try oracle()
        return IdentificationResult(calibration: Calibration(geometry: expected.geometry, matrix: expected.matrix, distortion: expected.distortion),
                                    method: "accepted", rms: 1, matches: 333, coverage: 0.18, details: ["limb_p95_px":.number(6)])
    }
    private func refine(_ result: IdentificationResult, dem: ElevationMap? = nil, task: ComputeTask = ComputeTask()) throws -> IdentificationResult {
        let photo = PhotoPixels(width: 8,height: 8,rgba: [UInt8](repeating:0,count:8 * 8 * 4))
        let reference = TerrainReference(image: photo,matrix: [[1,0,0],[0,1,0]],validFraction:0,resolutionKM:0)
        let match = RegistrationResult(matrix: [[1,0,0],[0,1,0]],rms:1,coverage:1,matches:0,source:[],target:[],sourceMatches:[],targetMatches:[],mirrored:false)
        return try EyepieceEdgeRefinement.refine(photo:photo,geometry:result.calibration.geometry,atlas:reference,match:match,accepted:result,dem:dem,mask:nil,task:task,progress:{ _ in })
    }
    func testFastPathAndCancellationDoNotStartEdgeWork() throws {
        var result = try accepted(); result.details["limb_p95_px"] = .number(1)
        XCTAssertFalse(EyepieceEdgeRefinement.needed(result))
        XCTAssertNil(try refine(result).details["edge_refinement"])
        let task = ComputeTask(); task.cancel()
        XCTAssertThrowsError(try refine(accepted(),task:task)) { XCTAssertTrue($0 is CancellationError) }
        let unavailable = try refine(accepted())
        XCTAssertEqual(unavailable.calibration,try accepted().calibration)
        XCTAssertEqual(unavailable.details["edge_refinement"]?.object["status"]?.string,"unavailable")
    }
    func testRejectedEdgeEvidencePreservesTheAcceptedCalibration() throws {
        let original = try accepted(), dem = try ElevationMap(url:XCTUnwrap(Catalog.resource("LDEM_16","LBL")))
        let result = try refine(original,dem:dem)
        XCTAssertEqual(result.calibration,original.calibration)
        XCTAssertEqual(result.rms,original.rms); XCTAssertEqual(result.method,original.method)
        XCTAssertEqual(result.details["edge_refinement"]?.object["status"]?.string,"not_adopted")
        XCTAssertNil(original.details["edge_refinement"])
    }
    func testSecondTermSurvivesSwiftAndPythonProjectRoundTrips() throws {
        let expected = try oracle()
        var document = MoonDocument(imagePath: "/tmp/edge.jpg")
        document.imageWidth = 1706; document.imageHeight = 1279
        document.calibration = Calibration(geometry: expected.geometry, matrix: expected.matrix, distortion: expected.distortion)
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        for suffix in ["moonswift", "moonlabel"] {
            let url = folder.appendingPathComponent("edge.\(suffix)")
            if suffix == "moonlabel" { try ProjectCompatibility.writeLegacy(document, to: url) }
            else { try ProjectIO.write(document, to: url) }
            let actual = try XCTUnwrap(ProjectIO.read(url).document.calibration)
            let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(actual.distortion)) as? [String: Any]
            XCTAssertEqual((encoded?["k2"] as? Double) ?? .infinity, -0.06394593339064888, accuracy: 1e-10)
            for probe in expected.features {
                let point = actual.photoPoint(actual.geometry.project(latitude: probe.lat, longitude: probe.lon).point)
                XCTAssertEqual(point.x, probe.photo[0], accuracy: 1e-6, probe.name)
                XCTAssertEqual(point.y, probe.photo[1], accuracy: 1e-6, probe.name)
            }
        }
    }
    func testAfocalButtonWorkflowCorrectsStreetAndMoretus() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let url = root.appendingPathComponent("2507041216.jpg")
        guard FileManager.default.fileExists(atPath: url.path) else { throw XCTSkip("Local photographer image required") }
        var state = ProjectState(); state.utc = "2025-07-04T12:16:00+00:00"; state.captureMode = "afocal"
        let photo = try PhotoPixels.load(url), geometry = try NativeCompute.ephemeris(utc: state.utc)
        let dem = try ElevationMap(url: XCTUnwrap(Catalog.resource("LDEM_16", "LBL")))
        let actual = try RecognitionEngine.identify(photo: photo, geometry: geometry, state: state, features: Catalog.load(), dem: dem, task: ComputeTask(), progress: { _ in })
        for probe in try oracle().features {
            let point = actual.calibration.photoPoint(actual.calibration.geometry.project(latitude: probe.lat, longitude: probe.lon).point)
            XCTAssertLessThan(hypot(point.x-probe.photo[0], point.y-probe.photo[1]), 2.5, probe.name)
        }
        XCTAssertEqual(actual.details["edge_refinement"]?.object["status"]?.string, "accepted")
    }
}
