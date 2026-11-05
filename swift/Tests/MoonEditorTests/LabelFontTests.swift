// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import XCTest
@testable import MoonCore
@testable import MoonEditor

final class LabelFontTests: XCTestCase {
    private func monospace() throws -> String {
        try XCTUnwrap(["Menlo", "Monaco", "Courier New"].compactMap(LabelFonts.installedFamily).first)
    }

    private func directory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func captionDocument() -> MoonDocument {
        var document = MoonDocument(imagePath: "/tmp/synthetic-label-font.png")
        document.imageWidth = 640; document.imageHeight = 220; document.settings.fontSize = 32
        document.changeStyle { $0.set("font_weight", "normal") }
        document.annotations = [Annotation(text: "月溪 · Moon III", anchor: PixelPoint(30, 70), position: PixelPoint(64, 55))]
        return document
    }

    func testCustomFontChangesRasterAndKeepsEditableMixedScriptSVG() throws {
        let family = try monospace(), folder = try directory()
        defer { try? FileManager.default.removeItem(at: folder) }
        let original = captionDocument()
        let image = PhotoPixels(width: original.imageWidth, height: original.imageHeight,
                                rgba: [UInt8](repeating: 96, count: original.imageWidth * original.imageHeight * 4)).cgImage
        var custom = original
        custom.changeStyle { $0.set("font_family", family) }
        let defaultPNG = folder.appendingPathComponent("default.png"), customPNG = folder.appendingPathComponent("custom.png")
        // Keep annotation IDs and positions the same to exercise the caption cache.
        try PhotoIO.png(image: image, document: original, to: defaultPNG)
        try PhotoIO.png(image: image, document: custom, to: customPNG)
        XCTAssertNotEqual(try PhotoPixels.load(defaultPNG).rgba, try PhotoPixels.load(customPNG).rgba)

        let svg = folder.appendingPathComponent("custom.svg")
        try AnnotationRenderer.svg(image: image, document: custom, scene: nil, to: svg)
        let xml = try XMLDocument(contentsOf: svg, options: [.nodePreserveWhitespace])
        let captions = try xml.nodes(forXPath: "//*[local-name()='g'][@class='caption']//*[local-name()='text']")
        let text = try XCTUnwrap(captions.first as? XMLElement)
        XCTAssertEqual(text.stringValue, original.annotations[0].text)
        XCTAssertEqual(text.attribute(forName: "font-family")?.stringValue, family)
        let runs = try text.nodes(forXPath: "./*[local-name()='tspan']").compactMap { $0 as? XMLElement }
        let latin = try XCTUnwrap(runs.first { $0.stringValue?.contains("Moon III") == true })
        XCTAssertEqual(latin.attribute(forName: "font-family")?.stringValue, family)
        let chinese = try XCTUnwrap(runs.first { $0.stringValue?.contains("月") == true })
        XCTAssertNotEqual(chinese.attribute(forName: "font-family")?.stringValue, family)
        XCTAssertFalse(chinese.attribute(forName: "font-family")?.stringValue?.isEmpty ?? true)
    }

    func testLandformCaptionUsesActualSelectedFaceAdvances() throws {
        let family = try monospace(), feature = try XCTUnwrap(Catalog.load().first { $0.name == "Montes Haemus" })
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = 1600; document.imageHeight = 1450; document.settings.fontSize = 22
        document.settings.language = .bilingual
        document.changeStyle { $0.set("font_family", family); $0.set("font_weight", "normal"); $0.set("follow_feature_paths", true) }
        let anchor = try XCTUnwrap(document.calibration).project(feature).point
        let original = Annotation(featureID: feature.id, text: "海穆斯山脉 · Mill iii", anchor: anchor, position: anchor, automatic: true)
        let arranged = SceneRenderer.configureCaption(original, feature: feature, document: document)
        let glyphs = try XCTUnwrap(arranged.visual?.pathGlyphs)
        let m = try XCTUnwrap(glyphs.first { $0.text == "M" }), i = try XCTUnwrap(glyphs.first { $0.text == "i" })
        XCTAssertEqual(m.family, family); XCTAssertEqual(i.family, family)
        XCTAssertEqual(m.advance, i.advance, accuracy: 0.08)
        let chinese = try XCTUnwrap(glyphs.first { $0.text == "海" })
        XCTAssertNotEqual(chinese.family, family)
    }

    func testUnavailableFamilySurvivesBothFormatsAndArtPresets() throws {
        let missing = "MoonLabeler Test Font Not Installed 0124", folder = try directory()
        defer { try? FileManager.default.removeItem(at: folder) }
        XCTAssertNil(LabelFonts.installedFamily(missing))
        let original = captionDocument()
        var custom = original
        custom.changeStyle { $0.set("font_family", missing) }
        for suffix in ["moonswift", "moonlabel"] {
            let url = folder.appendingPathComponent("font.\(suffix)")
            if suffix == "moonswift" { try ProjectIO.write(custom, to: url) }
            else { try ProjectCompatibility.writeLegacy(custom, to: url) }
            let reopened = try ProjectIO.read(url).document
            XCTAssertEqual(reopened.style.fontFamily, missing)
            XCTAssertEqual(SceneRenderer.captionPath(original.annotations[0], document: reopened).boundingBoxOfPath,
                           SceneRenderer.captionPath(original.annotations[0], document: original).boundingBoxOfPath)
        }
        let installed = try monospace()
        var art = original; art.changeStyle { $0.applyArt("manuscript") }
        custom.changeStyle { $0.set("font_family", installed); $0.applyArt("manuscript") }
        XCTAssertEqual(SceneRenderer.captionPath(art.annotations[0], document: art).boundingBoxOfPath,
                       SceneRenderer.captionPath(custom.annotations[0], document: custom).boundingBoxOfPath)
        custom.changeStyle { $0.applyArt("standard") }
        XCTAssertEqual(custom.style.preferredLabelFamily, installed)
    }

    func testImportedFontFamilyMustBeAString() throws {
        let folder = try directory(); defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("invalid.moonlabel")
        let project: [String: Any] = ["format": "MoonLabeler", "version": 2, "image_path": "image.png", "style": ["font_family": 42]]
        try JSONSerialization.data(withJSONObject: project).write(to: url)
        XCTAssertThrowsError(try ProjectIO.read(url)) { XCTAssertTrue($0.localizedDescription.contains("字体")) }
    }

    @MainActor func testFontChoiceAppliesOnRegenerationAndKeepsEditedCaption() async throws {
        _ = NSApplication.shared
        let family = try monospace(), model = EditorModel()
        var document = try ProjectIO.read(Catalog.demoURL).document
        let photo = try PhotoPixels.load(URL(fileURLWithPath: document.imagePath))
        document.imageWidth = photo.width; document.imageHeight = photo.height
        document.annotations = captionDocument().annotations
        let edited = document.annotations[0]
        model.image = photo.cgImage; model.document = document; model.appliedDocument = document
        model.styleString("font_family").wrappedValue = family
        XCTAssertTrue(model.hasPendingStyle)
        XCTAssertEqual(model.displayDocument?.style.fontFamily, "")
        model.applyNativeScene()
        let deadline = Date().addingTimeInterval(10)
        while model.busy && Date() < deadline { try await Task.sleep(for: .milliseconds(20)) }
        XCTAssertFalse(model.busy)
        XCTAssertFalse(model.hasPendingStyle)
        XCTAssertEqual(model.displayDocument?.style.fontFamily, family)
        let retained = try XCTUnwrap(model.displayDocument?.annotations.first { $0.id == edited.id })
        XCTAssertEqual(retained.text, edited.text); XCTAssertEqual(retained.position, edited.position)
    }
}
