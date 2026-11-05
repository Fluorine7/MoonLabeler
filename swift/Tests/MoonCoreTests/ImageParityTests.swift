// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import ImageIO
@testable import MoonCore

final class ImageParityTests: XCTestCase {
    private struct Oracle: Decodable {
        struct Entry: Decodable {
            let name: String, file: String
            let width: Int?, height: Int?, rgb: [UInt8]?, error: String?
        }
        let cases: [Entry]
    }
    func testFITSLayoutsAndStretchMatchPython() throws {
        try checkOracle("image-fits-oracle")
    }
    func testTIFFLayoutsAndStretchMatchPython() throws {
        try checkOracle("image-tiff-oracle")
    }
    func testTIFFOrientationFallbackBoundsDirectoryReads() throws {
        let valid = try XCTUnwrap(Bundle.module.url(forResource: "image-tiff-big-1-orientation-6", withExtension: "tif"))
        let source = try XCTUnwrap(CGImageSourceCreateWithURL(valid as CFURL, nil))
        let properties: [CFString: Any] = [kCGImagePropertyOrientation: 6]
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".tif")
        defer { try? FileManager.default.removeItem(at: url) }
        let prefix: [UInt8] = [0x49, 0x49, 43, 0, 8, 0, 0, 0]
        let atSixteen: [UInt8] = [16, 0, 0, 0, 0, 0, 0, 0]
        let cases = [
            Data(prefix + [UInt8](repeating: 0xff, count: 8)),
            Data(prefix + atSixteen + [UInt8](repeating: 0xff, count: 8)),
            Data(prefix + atSixteen + [1, 0, 0, 0, 0, 0, 0, 0] + [UInt8](repeating: 0, count: 10)),
            Data([0x49, 0x49, 43])
        ]
        for bytes in cases {
            try bytes.write(to: url)
            XCTAssertEqual(PhotoOrientation.value(properties, url: url, source: source), 6, "Incomplete or out-of-bounds metadata must preserve the already decoded orientation")
        }
    }
    private func checkOracle(_ name: String) throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: name, withExtension: "json"))
        let oracle = try JSONDecoder().decode(Oracle.self, from: Data(contentsOf: url))
        for entry in oracle.cases {
            let filename = entry.file as NSString
            let input = try XCTUnwrap(Bundle.module.url(forResource: filename.deletingPathExtension, withExtension: filename.pathExtension))
            if entry.error != nil { XCTAssertThrowsError(try PhotoPixels.load(input), entry.name); continue }
            do {
                let result = try PhotoPixels.load(input)
                XCTAssertEqual(result.width, entry.width, entry.name); XCTAssertEqual(result.height, entry.height, entry.name)
                let rgb = result.rgba.enumerated().filter { $0.offset % 4 != 3 }.map(\.element)
                let expected = try XCTUnwrap(entry.rgb)
                XCTAssertEqual(rgb.count, expected.count, entry.name)
                let error = zip(rgb, expected).map { abs(Int($0) - Int($1)) }.max() ?? 0
                XCTAssertLessThanOrEqual(error, 1, entry.name)
            } catch { XCTFail("\(entry.name): \(error)") }
        }
    }
    func testLargeGrayTIFFLoad() throws {
        guard let path = ProcessInfo.processInfo.environment["MOON_SWIFT_TIFF_BENCHMARK"] else { throw XCTSkip("Set MOON_SWIFT_TIFF_BENCHMARK to measure a large TIFF file") }
        let start = ProcessInfo.processInfo.systemUptime
        let image = try PhotoPixels.load(URL(fileURLWithPath: path))
        XCTAssertEqual(image.width, 3072); XCTAssertEqual(image.height, 2048)
        XCTAssertEqual(image.rgba.count, 3072 * 2048 * 4)
        print(String(format: "TIFF_BENCHMARK load_ms=%.2f output_bytes=%d", (ProcessInfo.processInfo.systemUptime - start) * 1000, image.rgba.count))
    }
    func testLargeRGBFITSLoad() throws {
        guard let path = ProcessInfo.processInfo.environment["MOON_SWIFT_FITS_BENCHMARK"] else { throw XCTSkip("Set MOON_SWIFT_FITS_BENCHMARK to measure a large FITS file") }
        let start = ProcessInfo.processInfo.systemUptime
        let image = try PhotoPixels.load(URL(fileURLWithPath: path))
        XCTAssertEqual(image.width, 3072); XCTAssertEqual(image.height, 2048)
        XCTAssertEqual(image.rgba.count, 3072 * 2048 * 4)
        print(String(format: "FITS_BENCHMARK load_ms=%.2f output_bytes=%d", (ProcessInfo.processInfo.systemUptime - start) * 1000, image.rgba.count))
    }
}
