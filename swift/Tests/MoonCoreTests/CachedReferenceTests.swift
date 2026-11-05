// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import ImageIO
@testable import MoonCore

final class CachedReferenceTests: XCTestCase {
    func testNASACachedMetadataFrameSelectionAndAlphaDisk() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let root = directory.appendingPathComponent("nasa-2026")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let record: JSONValue = .object(["subearth": .object(["lat": .number(2), "lon": .number(-1)]),
            "subsolar": .object(["lat": .number(0.5), "lon": .number(40)]), "posangle": .number(20), "distance": .number(390_000)])
        try JSONEncoder().encode(JSONValue.array([record])).write(to: root.appendingPathComponent("mooninfo.json"))
        try "<a href=\"moon.0002.png\">example frame</a>".write(to: root.appendingPathComponent("frames.html"), atomically: true, encoding: .utf8)
        let width = 384, height = 256
        var rgba = [UInt8](repeating: 0, count: width * height * 4)
        for y in 0..<height { for x in 0..<width where hypot(Double(x - 192), Double(y - 128)) <= 100 {
            let index = (y * width + x) * 4
            rgba[index] = 160; rgba[index + 1] = 160; rgba[index + 2] = 160; rgba[index + 3] = 255
        } }
        let frame = root.appendingPathComponent("moon.0001.png")
        func write(_ pixels: PhotoPixels) throws {
            let output = try XCTUnwrap(CGImageDestinationCreateWithURL(frame as CFURL, "public.png" as CFString, 1, nil))
            CGImageDestinationAddImage(output, pixels.cgImage, nil); XCTAssertTrue(CGImageDestinationFinalize(output))
        }
        try write(PhotoPixels(width: width, height: height, rgba: rgba))
        let result = try await ReferenceIO.nasa(utc: "2026-01-01T00:42:00Z", task: ComputeTask(), directory: directory)
        XCTAssertEqual(result.1.utc, "2026-01-01T00:00:00Z"); XCTAssertEqual(result.1.distanceKM, 390_000)
        XCTAssertEqual(result.0.image.width, width); XCTAssertEqual(result.0.image.height, height)
        XCTAssertEqual(result.0.matrix[0][2], 192, accuracy: 0.2); XCTAssertEqual(result.0.matrix[1][2], 128, accuracy: 0.2)
        XCTAssertEqual(result.0.matrix[0][0], 100, accuracy: 1)
        for index in stride(from: 3, to: rgba.count, by: 4) { rgba[index] = 255 }
        try write(PhotoPixels(width: width, height: height, rgba: rgba))
        do {
            _ = try await ReferenceIO.nasa(utc: "2026-01-01T00:42:00Z", task: ComputeTask(), directory: directory)
            XCTFail("An opaque frame must not supply an inferred lunar scale")
        } catch { XCTAssertTrue(error.localizedDescription.contains("透明")) }
    }
}
