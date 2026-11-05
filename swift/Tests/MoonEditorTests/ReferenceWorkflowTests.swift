// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
import SwiftUI
@testable import MoonCore
@testable import MoonEditor

final class ReferenceWorkflowTests: XCTestCase {
    func testLocalReferenceRegistersTheBundledPhotoThroughTheEditor() async throws {
        let observation = await MainActor.run { ReferenceModalObservation() }
        let (model, original, timer) = try await MainActor.run {
            var document = try ProjectIO.read(Catalog.demoURL).document
            let opened = try PhotoIO.open(URL(fileURLWithPath: document.imagePath))
            document.imageWidth = opened.raw.width; document.imageHeight = opened.raw.height
            let model = EditorModel(); model.document = document; model.appliedDocument = document
            model.image = opened.raw; model.displayImage = opened.display; model.panelTab = 2; model.markClean()
            let timer = dismissErrors(observation)
            model.loadLocalReference(Catalog.demoURL)
            return (model, document, timer)
        }
        let completed = await poll(attempts: 500) { !model.busy && (model.scene != nil || observation.count > 0) }
        await MainActor.run {
            timer.invalidate()
            XCTAssertTrue(completed, model.status); XCTAssertEqual(observation.count, 0, model.status)
            XCTAssertEqual(model.panelTab, 1); XCTAssertNotNil(model.scene)
            XCTAssertEqual(model.document?.state.utc, original.state.utc)
            if let actual = model.document?.calibration?.matrix, let expected = original.calibration?.matrix {
                for (row, originalRow) in zip(actual, expected) {
                    for (value, originalValue) in zip(row, originalRow) { XCTAssertEqual(value, originalValue, accuracy: 0.1) }
                }
            } else { XCTFail("Reference registration must retain a valid calibration") }
        }
    }
    func testCancelledLocalReferenceReadReleasesTheEditorAndDiscardsItsLateResult() async throws {
        let (model, original, previous) = try await MainActor.run { try makeModel() }
        let reader = HeldReferenceReader(result: (previous, original)); defer { reader.release() }
        await MainActor.run {
            model.referenceReader = { url, utc in try reader.read(url, utc) }
            model.loadLocalReference(URL(fileURLWithPath: "/private/tmp/pending-reference.moonlabel"))
            XCTAssertNotNil(model.operation)
        }
        await assertEventually({ reader.started })
        await MainActor.run { model.cancelOperation() }
        await assertEventually({ !model.busy }, message: "Cancellation must release the editor before a blocked file read returns")
        await MainActor.run { XCTAssertEqual(model.document, original); XCTAssertFalse(model.dirty) }
        reader.release(); await assertEventually({ reader.finished && !model.busy })
        await MainActor.run {
            XCTAssertNil(model.operation); XCTAssertEqual(model.document, original)
            XCTAssertEqual(model.reference?.matrix, previous.matrix); XCTAssertEqual(model.referenceProject, original)
        }
    }
    func testClosingTheWindowCancelsAPendingLocalReferenceRead() async throws {
        let (model, original, previous) = try await MainActor.run { try makeModel() }
        let reader = HeldReferenceReader(result: (previous, original)); defer { reader.release() }
        let (window, bridge) = await MainActor.run {
            let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 200, height: 160), styleMask: [.titled, .closable], backing: .buffered, defer: false)
            let bridge = WindowBridge(); bridge.model = model; window.delegate = bridge
            window.isReleasedWhenClosed = false; window.orderFront(nil)
            model.referenceReader = { url, utc in try reader.read(url, utc) }
            model.loadLocalReference(URL(fileURLWithPath: "/private/tmp/closing-reference.moonlabel"))
            return (window, bridge)
        }
        await assertEventually({ reader.started })
        await MainActor.run { window.performClose(nil) }
        await assertEventually({ !model.busy && !window.isVisible }, message: "A stalled reference read must not prevent closing a clean window")
        reader.release(); await assertEventually({ reader.finished && !model.busy })
        await MainActor.run { _ = bridge; window.close(); XCTAssertEqual(model.document, original) }
    }
    func testCancelledReferenceReadCannotClearTheRetryOperation() async throws {
        let (model, original, previous) = try await MainActor.run { try makeModel() }
        let first = HeldReferenceReader(result: (previous, original)), retry = HeldReferenceReader(result: (previous, original))
        defer { first.release(); retry.release() }
        await MainActor.run {
            model.referenceReader = { url, utc in try first.read(url, utc) }
            model.loadLocalReference(URL(fileURLWithPath: "/private/tmp/first-reference.moonlabel"))
        }
        await assertEventually({ first.started })
        await MainActor.run { model.cancelOperation() }; await assertEventually({ !model.busy })
        await MainActor.run {
            model.referenceReader = { url, utc in try retry.read(url, utc) }
            model.loadLocalReference(URL(fileURLWithPath: "/private/tmp/retry-reference.moonlabel"))
        }
        await assertEventually({ retry.started })
        first.release(); await assertEventually({ first.finished })
        await MainActor.run {
            XCTAssertTrue(model.busy); XCTAssertNotNil(model.operation)
            XCTAssertEqual(model.document, original); XCTAssertEqual(model.reference?.matrix, previous.matrix)
            model.cancelOperation()
        }
        await assertEventually({ !model.busy }); retry.release(); await assertEventually({ retry.finished })
        await MainActor.run { XCTAssertNil(model.operation); XCTAssertEqual(model.document, original) }
    }
    func testCancelledReferenceReadDiscardsALateDecoderError() async throws {
        let (model, original, _) = try await MainActor.run { try makeModel() }
        let reader = HeldReferenceReader(failure: CocoaError(.fileReadCorruptFile)); defer { reader.release() }
        let observation = await MainActor.run { ReferenceModalObservation() }
        let timer = await MainActor.run {
            let timer = dismissErrors(observation)
            model.referenceReader = { url, utc in try reader.read(url, utc) }
            model.loadLocalReference(URL(fileURLWithPath: "/private/tmp/bad-reference.moonlabel"))
            return timer
        }
        await assertEventually({ reader.started })
        await MainActor.run { model.cancelOperation() }; await assertEventually({ !model.busy })
        reader.release(); await assertEventually({ reader.finished })
        try await Task.sleep(for: .milliseconds(30))
        await MainActor.run {
            timer.invalidate(); XCTAssertEqual(observation.count, 0)
            XCTAssertEqual(model.document, original); XCTAssertFalse(model.busy)
        }
    }
    func testFailedNASALoadOpensManualCalibrationWithoutChangingThePhoto() async throws {
        let (model, original, previous) = try await MainActor.run { try makeModel() }
        let observation = await MainActor.run { ReferenceModalObservation() }
        let timer = await MainActor.run {
            let timer = dismissErrors(observation)
            model.nasaLoader = { _, _ in throw MoonError.invalid("NASA download unavailable") }
            model.loadNASA(); return timer
        }
        await assertEventually({ !model.busy })
        await MainActor.run {
            timer.invalidate()
            XCTAssertEqual(observation.count, 1)
            XCTAssertEqual(model.panelTab, 0); XCTAssertTrue(model.manualSectionExpanded)
            XCTAssertFalse(model.manualPickingExpanded)
            XCTAssertTrue(model.status.contains("可用手动校准"))
            XCTAssertEqual(model.document, original); XCTAssertFalse(model.dirty)
            XCTAssertEqual(model.reference?.matrix, previous.matrix); XCTAssertEqual(model.referenceProject, original)
        }
    }
    func testNASAFailureScrollsTheManualControlsIntoView() async throws {
        let (model, _, _) = try await MainActor.run { try makeModel() }
        let observation = await MainActor.run { ReferenceModalObservation() }
        let (host, window, timer) = await MainActor.run {
            let host = NSHostingView(rootView: NativeInspector(model: model))
            let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 420, height: 360), styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = host; window.orderFront(nil); host.layoutSubtreeIfNeeded()
            if let scroll = panelScroll(host) { scroll.contentView.scroll(to: .zero) }
            let timer = dismissErrors(observation)
            model.nasaLoader = { _, _ in throw MoonError.invalid("NASA download unavailable") }; model.loadNASA()
            return (host, window, timer)
        }
        let revealed = await poll {
            host.layoutSubtreeIfNeeded()
            return !model.busy && model.panelTab == 0 && (self.panelScroll(host)?.contentView.bounds.minY ?? 0) > 100
        }
        await MainActor.run {
            timer.invalidate()
            XCTAssertEqual(observation.count, 1)
            XCTAssertTrue(revealed, "Manual controls must be revealed below the capture controls; scroll offset=\(panelScroll(host)?.contentView.bounds.minY ?? -1)")
            window.close()
        }
    }
    func testFailedNASAMatchAlsoOpensManualCalibration() async throws {
        let (model, original, reference) = try await MainActor.run { try makeModel() }
        let geometry = try XCTUnwrap(original.calibration?.geometry)
        let observation = await MainActor.run { ReferenceModalObservation() }
        let timer = await MainActor.run {
            let timer = dismissErrors(observation)
            // Uniform reference/photo images force a real native SIFT failure.
            model.nasaLoader = { _, _ in (reference, geometry) }; model.loadNASA()
            return timer
        }
        await assertEventually({ observation.count == 1 && !model.busy })
        await MainActor.run {
            timer.invalidate(); XCTAssertEqual(observation.count, 1)
            XCTAssertEqual(model.panelTab, 0); XCTAssertTrue(model.manualSectionExpanded)
            XCTAssertTrue(model.status.contains("可用手动校准"))
            XCTAssertEqual(model.document, original); XCTAssertFalse(model.dirty)
        }
    }
    func testCancellingNASALoadKeepsTheCurrentPanelAndCalibration() async throws {
        let (model, original, reference) = try await MainActor.run { try makeModel() }
        let geometry = try XCTUnwrap(original.calibration?.geometry), started = expectation(description: "NASA loading started")
        let observation = await MainActor.run { ReferenceModalObservation() }
        let timer = await MainActor.run {
            let timer = dismissErrors(observation)
            model.nasaLoader = { _, _ in
                started.fulfill(); try await Task.sleep(for: .seconds(30))
                return (reference, geometry)
            }
            model.loadNASA(); return timer
        }
        await fulfillment(of: [started], timeout: 1)
        await MainActor.run { model.cancelOperation() }; await assertEventually({ !model.busy })
        await MainActor.run {
            timer.invalidate(); XCTAssertEqual(observation.count, 0)
            XCTAssertEqual(model.panelTab, 2); XCTAssertFalse(model.manualSectionExpanded)
            XCTAssertEqual(model.document, original); XCTAssertFalse(model.dirty)
            XCTAssertNil(model.operation)
        }
    }
    @MainActor private func makeModel() throws -> (EditorModel, MoonDocument, TerrainReference) {
        _ = NSApplication.shared
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.annotations = []; document.imageWidth = 32; document.imageHeight = 24; document.state.latitude = nil; document.state.longitude = nil
        let photo = PhotoPixels(width: 32, height: 24, rgba: [UInt8](repeating: 255, count: 32 * 24 * 4))
        let reference = TerrainReference(image: photo, matrix: [[10,0,16],[0,10,12]], validFraction: 1, resolutionKM: 0)
        let model = EditorModel(); model.document = document; model.appliedDocument = document; model.image = photo.cgImage
        model.reference = reference; model.referenceGeometry = document.calibration?.geometry; model.referenceProject = document
        model.panelTab = 2; model.markClean()
        return (model, document, reference)
    }
    private func poll(attempts: Int = 100, _ condition: @escaping @MainActor () -> Bool) async -> Bool {
        for _ in 0..<attempts {
            if await MainActor.run(body: condition) { return true }
            try? await Task.sleep(for: .milliseconds(10))
        }
        return false
    }
    private func assertEventually(_ condition: @escaping @MainActor () -> Bool, message: String = "The editor did not finish the expected transition", file: StaticString = #filePath, line: UInt = #line) async {
        let satisfied = await poll(condition)
        XCTAssertTrue(satisfied, message, file: file, line: line)
    }
    @MainActor private func dismissErrors(_ observation: ReferenceModalObservation) -> Timer {
        let timer = Timer(timeInterval: 0.01, repeats: true) { _ in
            MainActor.assumeIsolated {
                guard let window = NSApp.modalWindow else { return }
                observation.count += 1; NSApp.stopModal(withCode: .cancel); window.orderOut(nil)
            }
        }
        RunLoop.main.add(timer, forMode: .modalPanel); RunLoop.main.add(timer, forMode: .common)
        return timer
    }
    @MainActor private func panelScroll(_ root: NSView) -> NSScrollView? {
        var views = [root], result: NSScrollView?
        while let view = views.popLast() {
            if let scroll = view as? NSScrollView, scroll.frame.height > (result?.frame.height ?? 0) { result = scroll }
            views += view.subviews
        }
        return result
    }
}

private final class HeldReferenceReader: @unchecked Sendable {
    private let result: Result<(TerrainReference, MoonDocument), Error>
    private let lock = NSLock(), semaphore = DispatchSemaphore(value: 0)
    private var hasStarted = false, hasFinished = false
    var started: Bool { lock.lock(); defer { lock.unlock() }; return hasStarted }
    var finished: Bool { lock.lock(); defer { lock.unlock() }; return hasFinished }
    init(result: (TerrainReference, MoonDocument)) { self.result = .success(result) }
    init(failure: Error) { result = .failure(failure) }
    func release() { semaphore.signal() }
    func read(_ url: URL, _ utc: String) throws -> (TerrainReference, MoonDocument) {
        lock.lock(); hasStarted = true; lock.unlock()
        semaphore.wait()
        defer { lock.lock(); hasFinished = true; lock.unlock() }
        return try result.get()
    }
}
@MainActor private final class ReferenceModalObservation { var count = 0 }
