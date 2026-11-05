// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
@testable import MoonCore
@testable import MoonEditor

final class ReviewWorkflowTests: XCTestCase {
    func testBusyUndoAndRedoDoNotConsumeHistory() async throws {
        await MainActor.run {
            for redo in [false, true] {
                let model = EditorModel(), original = MoonDocument(imagePath: "history.png")
                model.document = original
                model.edit { $0.annotations.append(Annotation(text: "我的标注", anchor: PixelPoint(10, 10), position: PixelPoint(20, 20))) }
                let changed = model.document
                if redo { model.undo() }
                let before = model.document
                model.busy = true
                if redo { model.redo() } else { model.undo() }
                XCTAssertEqual(model.document, before)
                model.busy = false
                XCTAssertTrue(redo ? model.canRedo : model.canUndo, "A rejected busy command must keep its history entry")
                if redo { model.redo(); XCTAssertEqual(model.document, changed) }
                else { model.undo(); XCTAssertEqual(model.document, original) }
            }
        }
    }
    private func waitUntil(_ condition: @escaping @MainActor () -> Bool) async throws {
        for _ in 0..<500 {
            if await MainActor.run(body: condition) { return }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("The editor did not finish the requested transition")
        throw CancellationError()
    }
    func testDetectingCandidatesFinishesMaskEditingAndOpensReview() async throws {
        let model = await MainActor.run {
            let model = EditorModel()
            var document = MoonDocument(imagePath: "detection.png"); document.imageWidth = 240; document.imageHeight = 160
            model.document = document
            model.image = PhotoPixels(width: 240, height: 160, rgba: [UInt8](repeating: 255, count: 240 * 160 * 4)).cgImage
            model.manualSectionExpanded = true; model.canvasTool = .paint
            model.detectCandidates(); XCTAssertEqual(model.canvasTool, .pan)
            return model
        }
        try await waitUntil { !model.busy }
        await MainActor.run { XCTAssertEqual(model.panelTab, 0); XCTAssertTrue(model.manualSectionExpanded); XCTAssertFalse(model.manualPickingExpanded) }
    }
    func testFeatureCheckboxesKeepEmptySelectionsAndStagedChanges() async throws {
        try await MainActor.run {
            let model = EditorModel(); model.document = try ProjectIO.read(Catalog.demoURL).document
            model.document?.settings.kinds = []; model.document?.settings.allKinds = true
            model.appliedDocument = model.document
            let original = model.document?.annotations
            model.allFeatureKinds.wrappedValue = false
            XCTAssertFalse(model.allFeatureKinds.wrappedValue)
            XCTAssertEqual(model.document?.settings.kinds, [])
            for kind in ["Mare, maria", "Crater, craters"] { model.featureKind(kind).wrappedValue = true }
            model.allFeatureKinds.wrappedValue = true; model.allFeatureKinds.wrappedValue = false
            XCTAssertEqual(model.document?.settings.kinds, ["Crater, craters", "Mare, maria"])
            XCTAssertEqual(model.document?.annotations, original)
            XCTAssertTrue(model.hasPendingStyle)
            XCTAssertTrue(model.displayDocument?.settings.matchesAllKinds == true)
            model.document?.settings.kinds.append("Future type")
            XCTAssertTrue(model.availableFeatureKinds.contains("Future type"))
            model.uiLanguage = "English"
            XCTAssertFalse(model.featureKindSummary.contains("已选"))
        }
    }
    func testCandidateCanBeSelectedOnThePhotoWithoutKeepingThePreviousName() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            var document = MoonDocument(imagePath: "candidates.png"); document.imageWidth = 240; document.imageHeight = 160
            model.document = document
            model.image = PhotoPixels(width: 240, height: 160, rgba: [UInt8](repeating: 255, count: 240 * 160 * 4)).cgImage
            model.manualSectionExpanded = true
            model.craterCandidates = [CraterCandidate(id: 1, center: PixelPoint(60, 70), major: 16, minor: 12, angle: 0, support: 1),
                                      CraterCandidate(id: 2, center: PixelPoint(170, 90), major: 20, minor: 17, angle: 0, support: 1)]
            model.selectedCandidate = 1; model.craterQuery = "Copernicus"
            let feature = try XCTUnwrap(model.craterSearchResults.first); XCTAssertEqual(feature.name, "Copernicus")
            model.craterSelection = feature.id; XCTAssertTrue(model.canConfirmCandidate)
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 240, height: 160)); canvas.model = model
            let window = NSWindow(contentRect: canvas.frame, styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = canvas; defer { window.close() }
            let point = canvas.convert(CGPoint(x: 170, y: 90), to: nil)
            let event = try XCTUnwrap(NSEvent.mouseEvent(with: .leftMouseDown, location: point, modifierFlags: [], timestamp: 0, windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1))
            canvas.mouseDown(with: event)
            XCTAssertEqual(model.selectedCandidate, 2); XCTAssertNil(model.craterSelection); XCTAssertFalse(model.canConfirmCandidate)
            XCTAssertFalse(try model.useSelectedCandidate())
            model.craterSelection = feature.id; XCTAssertTrue(try model.useSelectedCandidate())
            XCTAssertEqual(model.document?.state.anchors.first?.point, PixelPoint(170, 90))
            model.craterQuery = "Mare Imbrium"
            XCTAssertTrue(model.craterSearchResults.allSatisfy { ["Crater, craters", "Satellite Feature"].contains($0.kind) })
            XCTAssertFalse(model.craterSearchResults.contains { $0.name == "Mare Imbrium" }); XCTAssertNil(model.craterSelection)
            model.canvasTool = .candidateCenter(2); model.selectedCandidate = 1; XCTAssertEqual(model.canvasTool, .pan)
        }
    }
    func testCandidateNameMustBeOnTheVisibleSideOfTheMoon() async throws {
        try await MainActor.run {
            let model = EditorModel(); model.document = try ProjectIO.read(Catalog.demoURL).document
            model.document?.imageWidth = 1600; model.document?.imageHeight = 1450
            model.craterCandidates = [CraterCandidate(id: 1, center: PixelPoint(60, 70), major: 16, minor: 12, angle: 0, support: 1)]
            model.selectedCandidate = 1; model.craterQuery = "Korolev"
            let feature = try XCTUnwrap(model.craterSearchResults.first { $0.name == "Korolev" })
            model.craterSelection = feature.id
            let before = model.document
            XCTAssertThrowsError(try model.useSelectedCandidate())
            XCTAssertEqual(model.document, before)
        }
    }
    func testHiddenAnnotationLayerCannotBeSelectedOnThePhoto() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            var document = MoonDocument(imagePath: "selection.png"); document.imageWidth = 240; document.imageHeight = 160
            let label = Annotation(text: "Copernicus", anchor: PixelPoint(60, 70), position: PixelPoint(80, 80))
            document.annotations = [label]; model.document = document
            model.image = PhotoPixels(width: 240, height: 160, rgba: [UInt8](repeating: 255, count: 240 * 160 * 4)).cgImage
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 240, height: 160)); canvas.model = model
            let window = NSWindow(contentRect: canvas.frame, styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = canvas; defer { window.close() }
            let point = canvas.convert(CGPoint(x: 60, y: 70), to: nil)
            let event = try XCTUnwrap(NSEvent.mouseEvent(with: .leftMouseDown, location: point, modifierFlags: [], timestamp: 0, windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1))
            model.showAnnotations = false; canvas.mouseDown(with: event); canvas.mouseUp(with: event)
            XCTAssertNil(model.selectedID)
            model.showAnnotations = true; canvas.mouseDown(with: event); canvas.mouseUp(with: event)
            XCTAssertEqual(model.selectedID, label.id)
            XCTAssertEqual(model.document, document)
        }
    }
    func testCancelledPhotoReadKeepsTheCurrentDocumentAndDiscardsItsLateResult() async throws {
        let image = PhotoPixels(width: 24, height: 16, rgba: [UInt8](repeating: 255, count: 24 * 16 * 4)).cgImage
        let reader = DelayedPhotoReader(image: image); defer { reader.release() }
        let model = await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(photoReader: reader.load)
            var current = MoonDocument(imagePath: "current.png"); current.imageWidth = 24; current.imageHeight = 16
            model.document = current; model.image = image; model.markClean()
            model.requestOpen(URL(fileURLWithPath: "/private/tmp/late-photo.png")); return model
        }
        try await waitUntil { reader.started }
        await MainActor.run { XCTAssertNotNil(model.operation); model.cancelOperation() }
        try await waitUntil { !model.busy }
        await MainActor.run {
            XCTAssertEqual(model.document?.imagePath, "current.png"); XCTAssertFalse(model.dirty)
            XCTAssertTrue(model.status.contains("中止读取"))
            model.requestOpen(URL(fileURLWithPath: "/private/tmp/retry-photo.png"))
        }
        try await waitUntil { !model.busy && model.document?.imagePath == "/private/tmp/retry-photo.png" }
        reader.release(); try await waitUntil { reader.finished }
        await Task.yield()
        await MainActor.run { XCTAssertEqual(model.document?.imagePath, "/private/tmp/retry-photo.png"); XCTAssertFalse(model.dirty) }
    }
    func testClosingTheWindowCancelsAPendingPhotoRead() async throws {
        let image = PhotoPixels(width: 24, height: 16, rgba: [UInt8](repeating: 255, count: 24 * 16 * 4)).cgImage
        let reader = DelayedPhotoReader(image: image); defer { reader.release() }
        let (model, window, bridge) = await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(photoReader: reader.load), bridge = WindowBridge()
            let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 200, height: 160), styleMask: [.titled, .closable], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; bridge.model = model; window.delegate = bridge; window.orderFront(nil)
            model.requestOpen(URL(fileURLWithPath: "/private/tmp/closing-photo.png"))
            return (model, window, bridge)
        }
        try await waitUntil { reader.started }
        await MainActor.run { window.performClose(nil) }
        try await waitUntil { !model.busy && !window.isVisible }
        await MainActor.run { XCTAssertNil(model.document); _ = bridge; window.close() }
    }
    func testLabelVisibilityRelayoutKeepsPendingFiltersAndCachedMap() async throws {
        let model = await MainActor.run { _ = NSApplication.shared; let model = EditorModel(); model.openDemo(); return model }
        try await waitUntil { !model.busy && model.scene != nil }
        let (id, lightness) = try await MainActor.run {
            let selected = try XCTUnwrap(model.document?.annotations.first { !$0.hidden && $0.visual?.layoutHidden != true && $0.visual?.landing != true })
            model.scene?.layers.grid.append(MapLine([PixelPoint(7, 8), PixelPoint(9, 10)]))
            model.edit { $0.settings.kinds = []; $0.settings.allKinds = false }
            model.setAnnotationVisible(selected.id, false)
            return (selected.id, model.scene?.layers.lightness)
        }
        try await waitUntil { !model.busy }
        await MainActor.run {
            XCTAssertTrue(model.document?.annotations.first { $0.id == id }?.hidden == true)
            XCTAssertTrue(model.hasPendingStyle); XCTAssertFalse(model.document?.settings.matchesAllKinds ?? true)
            XCTAssertTrue(model.displayDocument?.settings.includes(kind: "Crater, craters") == true)
            XCTAssertTrue(model.scene?.layers.lightness === lightness)
            XCTAssertEqual(model.scene?.layers.grid.last?.points, [PixelPoint(7, 8), PixelPoint(9, 10)])
            model.setAnnotationVisible(id, true)
        }
        try await waitUntil { !model.busy }
        try await MainActor.run {
            let displayed = try XCTUnwrap(model.displayDocument), restored = try XCTUnwrap(displayed.annotations.first { $0.id == id })
            XCTAssertTrue(AnnotationSceneBuilder.visible(restored, document: displayed, scene: model.scene))
            XCTAssertTrue(model.document?.state.legacy["labels"]?.object[restored.featureID!]?.object["force"]?.bool == true)
            model.undo()
            XCTAssertTrue(model.document?.annotations.first { $0.id == id }?.hidden == true)
        }
    }
}

private final class DelayedPhotoReader: @unchecked Sendable {
    private let lock = NSLock(), gate = DispatchSemaphore(value: 0)
    private let image: CGImage
    private var calls = 0, firstStarted = false, firstFinished = false
    init(image: CGImage) { self.image = image }
    var started: Bool { lock.withLock { firstStarted } }
    var finished: Bool { lock.withLock { firstFinished } }
    func release() { gate.signal() }
    func load(_ url: URL) throws -> (raw: CGImage, display: CGImage) {
        let first = lock.withLock { calls += 1; if calls == 1 { firstStarted = true }; return calls == 1 }
        if first { gate.wait(); lock.withLock { firstFinished = true } }
        return (image, image)
    }
}
