// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
@testable import MoonCore

final class PhotoColorTests: XCTestCase {
    func testArtisticGrayPhotosShareUnchangedPixels() throws {
        let large = ProcessInfo.processInfo.environment["MOON_SWIFT_GRAYSCALE_BENCHMARK"] == "1"
        let width = large ? 3072 : 16, height = large ? 2048 : 16
        var bytes = [UInt8](repeating: 0, count: width * height * 4)
        for pixel in 0..<(width * height) {
            let value = UInt8(pixel % 256), i = pixel * 4
            bytes[i] = value; bytes[i + 1] = value; bytes[i + 2] = value; bytes[i + 3] = 255
        }
        let photo = PhotoPixels(width: width, height: height, rgba: bytes)
        let start = ProcessInfo.processInfo.systemUptime
        let display = try XCTUnwrap(artisticScene(photo).grayscale)
        let elapsed = (ProcessInfo.processInfo.systemUptime - start) * 1000
        let shares = photo.rgba.withUnsafeBufferPointer { source in
            display.rgba.withUnsafeBufferPointer { result in source.baseAddress == result.baseAddress }
        }
        XCTAssertEqual(display.width, width); XCTAssertEqual(display.height, height)
        XCTAssertEqual(display.rgba, bytes)
        XCTAssertTrue(shares, "Art desaturation must not duplicate an already gray photograph")
        if large { print(String(format: "ART_GRAY_BENCHMARK build_ms=%.2f shared=%@ image_bytes=%d", elapsed, String(shares), bytes.count)) }
    }
    func testArtDesaturationPreservesAlphaAndInputPixels() throws {
        let original: [UInt8] = [10,10,10,255, 50,80,30,128, 0,255,0,255, 0,0,255,255, 255,0,0,255, 5,5,5,8]
        let photo = PhotoPixels(width: 3, height: 2, rgba: original)
        let display = try XCTUnwrap(artisticScene(photo).grayscale)
        XCTAssertEqual(display.rgba, [10,10,10,255, 65,65,65,128, 150,150,150,255, 29,29,29,255, 76,76,76,255, 5,5,5,8])
        XCTAssertEqual(photo.rgba, original)
    }
    private func artisticScene(_ photo: PhotoPixels) throws -> AnnotationScene {
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = photo.width; document.imageHeight = photo.height; document.annotations = []
        document.style = ProjectStyle(["art_style": .string("manuscript")])
        return try AnnotationSceneBuilder.build(document: document, photo: photo, features: [], dem: nil, task: ComputeTask(), displayPhoto: photo).1
    }
    struct Oracle: Decodable { var file: String, raw: [UInt8], display: [UInt8], width: Int, height: Int, rawTolerance: Int?, rawPixels: [UInt8]?, displayPixels: [UInt8]? }
    func testICCDisplayCopiesMatchPythonWithoutChangingRecognitionSamples() throws {
        let data = try Data(contentsOf: XCTUnwrap(Bundle.module.url(forResource: "color-oracle", withExtension: "json")))
        for oracle in try JSONDecoder().decode([Oracle].self, from: data) {
            let url = try XCTUnwrap(Bundle.module.url(forResource: oracle.file, withExtension: nil))
            let raw = try PhotoPixels.load(url), saved = raw.rgba
            for c in 0..<3 { XCTAssertEqual(Int(raw.rgba[c]), Int(oracle.raw[c]), accuracy: oracle.rawTolerance ?? 0, "\(oracle.file): preserve original samples") }
            let display = try PhotoPixels.display(url, raw: raw)
            XCTAssertEqual(display.width, oracle.width); XCTAssertEqual(display.height, oracle.height)
            for c in 0..<3 { XCTAssertEqual(Int(display.rgba[c]), Int(oracle.display[c]), accuracy: 3, "\(oracle.file): display sRGB channel \(c)") }
            if let expectedRaw = oracle.rawPixels, let expectedDisplay = oracle.displayPixels {
                for i in expectedRaw.indices {
                    let offset = (i / 3) * 4 + i % 3
                    XCTAssertEqual(Int(raw.rgba[offset]), Int(expectedRaw[i]), accuracy: oracle.rawTolerance ?? 0, "\(oracle.file): input pixel channel \(i)")
                    XCTAssertEqual(Int(display.rgba[offset]), Int(expectedDisplay[i]), accuracy: 3, "\(oracle.file): display pixel channel \(i)")
                }
            }
            XCTAssertEqual(raw.rgba, saved)
        }
    }
    func testUntaggedPhotographsKeepTheirAssumedSRGBSamples() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "decoder-oracle", withExtension: "jpg"))
        let raw = try PhotoPixels.load(url)
        XCTAssertEqual(try PhotoPixels.display(url, raw: raw).rgba, raw.rgba)
    }
    func testArtDesaturationUsesTheDisplayCopyWithoutChangingRegistration() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "color-adobe-jpeg", withExtension: "jpg"))
        let raw = try PhotoPixels.load(url), display = try PhotoPixels.display(url, raw: raw)
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = raw.width; document.imageHeight = raw.height; document.annotations = []
        document.style = ProjectStyle(["art_style": .string("manuscript")])
        let camera = document.calibration, saved = raw.rgba
        let artistic = try AnnotationSceneBuilder.build(document: document, photo: raw, features: [], dem: nil, task: ComputeTask(), displayPhoto: display)
        XCTAssertEqual(Int(try XCTUnwrap(artistic.1.grayscale).rgba[0]), 111, accuracy: 1)
        XCTAssertEqual(artistic.0.calibration, camera); XCTAssertEqual(raw.rgba, saved)
        document.changeStyle { $0.set("art_style", "standard") }
        let original = try AnnotationSceneBuilder.build(document: document, photo: raw, features: [], dem: nil, task: ComputeTask(), displayPhoto: display)
        XCTAssertNil(original.1.grayscale); XCTAssertEqual(original.0.calibration, camera)
    }
}
