// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
@testable import MoonCore
@testable import MoonEditor

final class CatalogueRefreshTests: XCTestCase {
    private func waitForEditor(_ model: EditorModel) async throws {
        for _ in 0..<300 {
            if await MainActor.run(body: { !model.busy }) { return }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("Catalogue refresh did not finish"); throw CancellationError()
    }
    func testUpdatedCatalogueRefreshesCurrentLabelsWithoutApplyingPendingSettings() async throws {
        let before = Feature(id: "catalogue-auto", name: "Before", chinese: "旧名", latitude: 0, longitude: -12, diameter: 80, kind: "Crater, craters")
        let after = Feature(id: before.id, name: "After Mare", chinese: "更新后", latitude: 0, longitude: -12, diameter: 800, kind: "Mare, maria")
        let manual = Feature(id: "catalogue-manual", name: "Manual", chinese: "手工基准", latitude: 10, longitude: 18, diameter: 50, kind: "Crater, craters")
        let (model, original, oldScene) = try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(catalogueLoader: { _ in [after, manual] })
            var document = MoonDocument(imagePath: "catalogue.png")
            document.imageWidth = 512; document.imageHeight = 512
            document.calibration = Calibration(geometry: MoonGeometry(native: [1,0,0, 0,1,0, 0,0,1, 1,0,0, 384400], utc: "2026-07-08T15:00:00Z"), matrix: [[220,0,256],[0,-220,256]])
            document.settings.minimumDiameter = 0; document.settings.maximumLabels = 20; document.settings.fontSize = 18
            document.changeStyle { $0.set("art_style", "manuscript"); $0.set("illuminated_only", false) }
            let pixels = PhotoPixels(width: 512, height: 512, rgba: [UInt8](repeating: 255, count: 512 * 512 * 4))
            let built = try AnnotationSceneBuilder.build(document: document, photo: pixels, features: [before, manual], dem: nil, task: ComputeTask(),
                measure: AnnotationRenderer.measure, captionBounds: SceneRenderer.labelBounds,
                configureCaption: { SceneRenderer.configureCaption($0, feature: $1, document: $2) })
            document = built.0
            let index = try XCTUnwrap(document.annotations.firstIndex { $0.featureID == manual.id })
            document.annotations[index].text = "我的改名"; document.annotations[index].textEdited = true
            document.annotations[index].position = PixelPoint(80, 240); document.annotations[index].positionEdited = true
            document.state.legacy["annotation_relief"] = .object(["stale": .number(1)])
            model.document = document; model.appliedDocument = document; model.scene = built.1; model.image = pixels.cgImage
            model.document?.settings.maximumLabels = 1
            model.refreshCatalogue()
            return (model, document, built.1.id)
        }
        try await waitForEditor(model)
        try await MainActor.run {
            let actual = try XCTUnwrap(model.document), applied = try XCTUnwrap(model.appliedDocument)
            XCTAssertEqual(model.features.count, 2)
            XCTAssertTrue(model.searchFeatures("After Mare").contains { $0.id == after.id })
            XCTAssertNotEqual(model.scene?.id, oldScene, "The displayed labels must refresh after a catalogue update")
            let automatic = try XCTUnwrap(actual.annotations.first { $0.featureID == after.id })
            XCTAssertTrue(automatic.text.contains("AFTER MARE"), "Automatic names must use the new catalogue")
            let edited = try XCTUnwrap(actual.annotations.first { $0.featureID == manual.id })
            XCTAssertEqual(edited.text, "我的改名"); XCTAssertEqual(edited.position, PixelPoint(80, 240))
            XCTAssertEqual(actual.settings.maximumLabels, 1); XCTAssertEqual(applied.settings.maximumLabels, 20)
            XCTAssertEqual(actual.calibration, original.calibration)
            XCTAssertNil(actual.state.legacy["annotation_relief"])
            let knownMare = try XCTUnwrap(Catalog.bundled().first { $0.kind.hasPrefix("Mare") && !$0.chinese.isEmpty })
            var reference = automatic; reference.featureID = knownMare.id
            reference.visual = AnnotationVisual(); reference.visual?.fontScale = automatic.visual?.fontScale ?? 1
            let actualPath = SceneRenderer.captionPath(automatic, document: applied)
            let referencePath = SceneRenderer.captionPath(reference, document: applied)
            XCTAssertEqual(actualPath.boundingBoxOfPath, referencePath.boundingBoxOfPath, "New IAU IDs need the same artistic typography as known features of that type")
        }
    }
    func testCancelledCatalogueRefreshKeepsThePreviousCatalogueAndProject() async throws {
        let (model, previous, count) = try await MainActor.run {
            let model = EditorModel(catalogueLoader: { task in task.cancel(); return [] })
            let document = try ProjectIO.read(Catalog.demoURL).document
            model.document = document; model.appliedDocument = document
            let count = model.features.count; model.refreshCatalogue(); return (model, document, count)
        }
        try await waitForEditor(model)
        await MainActor.run { XCTAssertEqual(model.document, previous); XCTAssertEqual(model.features.count, count) }
    }
}
