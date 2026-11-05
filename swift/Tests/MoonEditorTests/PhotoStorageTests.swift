// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import CoreGraphics
import ImageIO
@testable import MoonCore
@testable import MoonEditor

final class PhotoStorageTests: XCTestCase {
    func testUnchangedSRGBDisplaySharesThePhotographBuffer() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".png")
        defer { try? FileManager.default.removeItem(at: url) }
        let pixels = PhotoPixels(width: 48, height: 32,
            rgba: Array(repeating: [UInt8(210), 70, 90, 255], count: 48 * 32).flatMap { $0 })
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil))
        CGImageDestinationAddImage(destination, pixels.cgImage, nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let opened = try PhotoIO.open(url)
        XCTAssertEqual(try PhotoPixels(opened.raw).rgba, try PhotoPixels(opened.display).rgba)
        XCTAssertTrue(opened.raw === opened.display, "Unchanged display samples must share one retained image buffer")
    }

    func testMeasureRetainedRealPhotoBuffers() throws {
        let environment = ProcessInfo.processInfo.environment
        guard let path = environment["MOON_SWIFT_BENCHMARK_PROJECT"] else { throw XCTSkip("Set the real-photo benchmark project") }
        let document = try ProjectIO.read(URL(fileURLWithPath: path)).document
        let start = ProcessInfo.processInfo.systemUptime
        let opened = try PhotoIO.open(URL(fileURLWithPath: document.imagePath))
        let elapsed = (ProcessInfo.processInfo.systemUptime - start) * 1000
        let raw = opened.raw.bytesPerRow * opened.raw.height, display = opened.display.bytesPerRow * opened.display.height
        let shared = opened.raw === opened.display, retained = raw + (shared ? 0 : display)
        print(String(format: "PHOTO_STORAGE retained=%.2f MiB shared=%@ open=%.2f ms", Double(retained) / 1_048_576, String(shared), elapsed))
        if let output = environment["MOON_SWIFT_PHOTO_STORAGE_RESULT"] {
            let result: [String: Any] = ["raw_bytes": raw, "display_bytes": display, "shared_storage": shared,
                                       "retained_image_bytes": retained, "open_ms": elapsed]
            try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: output), options: .atomic)
        }
    }
}
