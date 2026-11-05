// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
import ImageIO
@testable import MoonCore
@testable import MoonEditor

final class ExportWorkflowTests: XCTestCase {
    func testCancelledPNGExportKeepsTheTargetAndDiscardsLateCompletion() async throws { try await cancelledExport(.png) }
    func testCancelledSVGExportKeepsTheTargetAndDiscardsLateCompletion() async throws { try await cancelledExport(.svg) }
    func testSuccessfulPNGExportReplacesTheChosenTarget() async throws { try await successfulExport(.png) }
    func testSuccessfulSVGExportReplacesTheChosenTarget() async throws { try await successfulExport(.svg) }
    func testExportCannotReplaceTheSourceThroughADirectoryAlias() async throws {
        let directory = try makeDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let source = directory.appendingPathComponent("source.png"), alias = directory.appendingPathComponent("alias")
        let original = Data("original photo".utf8); try original.write(to: source)
        try FileManager.default.createSymbolicLink(at: alias, withDestinationURL: directory)
        await MainActor.run {
            let model = makeModel(in: directory)
            for format in [ImageExport.Format.png, .svg] {
                let timer = Timer(timeInterval: 0.01, repeats: true) { _ in
                    MainActor.assumeIsolated {
                        guard let window = NSApp.modalWindow else { return }
                        NSApp.stopModal(withCode: .cancel); window.orderOut(nil)
                    }
                }
                RunLoop.main.add(timer, forMode: .modalPanel); RunLoop.main.add(timer, forMode: .common)
                if format == .png { model.exportPNG(to: alias.appendingPathComponent("source.png")) }
                else { model.exportSVG(to: alias.appendingPathComponent("source.png")) }
                timer.invalidate()
                XCTAssertFalse(model.busy); XCTAssertNil(model.operation)
                XCTAssertTrue(model.status.contains("保留原始照片"))
            }
        }
        XCTAssertEqual(try Data(contentsOf: source), original)
    }
    func testFailedEncoderKeepsTheTargetAndRemovesItsPartialFile() async throws {
        let directory = try makeDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let target = directory.appendingPathComponent("export.png"), original = Data("previous export".utf8)
        try original.write(to: target)
        do {
            try await CancellableExport.run(to: target) { url in
                try Data("partial encoding".utf8).write(to: url)
                throw CocoaError(.fileWriteUnknown)
            }
            XCTFail("An encoder failure must reach the caller")
        } catch { XCTAssertEqual((error as NSError).code, CocoaError.fileWriteUnknown.rawValue) }
        try await waitForCleanup(in: directory, keeping: target.lastPathComponent)
        XCTAssertEqual(try Data(contentsOf: target), original)
    }
    func testFailedCommitKeepsTheExistingDirectory() async throws {
        let directory = try makeDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let target = directory.appendingPathComponent("export.svg")
        try FileManager.default.createDirectory(at: target, withIntermediateDirectories: false)
        let sentinel = target.appendingPathComponent("keep.txt"), original = Data("keep directory".utf8)
        try original.write(to: sentinel)
        do {
            try await CancellableExport.run(to: target) { try Data("encoded image".utf8).write(to: $0) }
            XCTFail("A directory cannot be replaced by an image")
        } catch { XCTAssertEqual((error as NSError).domain, NSPOSIXErrorDomain) }
        try await waitForCleanup(in: directory, keeping: target.lastPathComponent)
        XCTAssertEqual(try Data(contentsOf: sentinel), original)
    }
    func testClosingTheWindowCancelsAPendingPNGExport() async throws {
        let directory = try makeDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let target = directory.appendingPathComponent("export.png"), original = Data("keep export".utf8)
        try original.write(to: target)
        let gate = ExportGate(); defer { gate.release() }
        let (model, window, bridge) = await MainActor.run {
            let model = makeModel(in: directory), bridge = WindowBridge()
            let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 200, height: 160), styleMask: [.titled, .closable], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; bridge.model = model; window.delegate = bridge; window.orderFront(nil)
            model.exportWriter = { _, _, _, _, url in try gate.write(url) }
            model.exportPNG(to: target)
            return (model, window, bridge)
        }
        for _ in 0..<100 where !gate.started { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(gate.started)
        await MainActor.run { window.performClose(nil) }
        for _ in 0..<100 {
            if await MainActor.run(body: { !model.busy && !window.isVisible }) { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        await MainActor.run { XCTAssertFalse(model.busy); XCTAssertFalse(window.isVisible); _ = bridge; window.close() }
        gate.release()
        for _ in 0..<100 where !gate.finished { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(gate.finished)
        try await waitForCleanup(in: directory, keeping: target.lastPathComponent)
        XCTAssertEqual(try Data(contentsOf: target), original)
    }
    func testCancellationBeforeTheExportStartsDoesNotInvokeTheEncoder() async throws {
        let directory = try makeDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let target = directory.appendingPathComponent("export.png"), gate = ExportGate(); defer { gate.release() }
        let model = await MainActor.run {
            let model = makeModel(in: directory)
            model.exportWriter = { _, _, _, _, url in try gate.write(url) }
            model.exportPNG(to: target); model.cancelOperation()
            return model
        }
        try await waitForIdle(model)
        XCTAssertFalse(gate.started); XCTAssertFalse(FileManager.default.fileExists(atPath: target.path))
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: directory.path).isEmpty)
    }
    func testANewExportCanCompleteWhileACancelledEncoderIsStillWaiting() async throws {
        let directory = try makeDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let first = directory.appendingPathComponent("first.png"), second = directory.appendingPathComponent("second.svg")
        let original = Data("keep first".utf8); try original.write(to: first)
        let gate = ExportGate(); defer { gate.release() }
        let model = await MainActor.run {
            let model = makeModel(in: directory)
            model.exportWriter = { _, _, _, _, url in try gate.write(url) }
            model.exportPNG(to: first); return model
        }
        for _ in 0..<100 where !gate.started { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(gate.started)
        await MainActor.run { model.cancelOperation() }; try await waitForIdle(model)
        await MainActor.run {
            model.exportWriter = { try ImageExport.write($0, image: $1, document: $2, scene: $3, to: $4) }
            model.exportSVG(to: second)
        }
        try await waitForIdle(model)
        let completedStatus = await MainActor.run { model.status }
        XCTAssertTrue(completedStatus.contains(second.lastPathComponent)); XCTAssertTrue(FileManager.default.fileExists(atPath: second.path))
        gate.release()
        for _ in 0..<100 where !gate.finished { try await Task.sleep(for: .milliseconds(10)) }
        for _ in 0..<100 {
            if try FileManager.default.contentsOfDirectory(atPath: directory.path).count == 2 { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertTrue(gate.finished); XCTAssertEqual(try Data(contentsOf: first), original)
        XCTAssertEqual(Set(try FileManager.default.contentsOfDirectory(atPath: directory.path)), [first.lastPathComponent, second.lastPathComponent])
        await MainActor.run { XCTAssertEqual(model.status, completedStatus); XCTAssertFalse(model.busy); XCTAssertNil(model.operation) }
    }
    private func successfulExport(_ format: ImageExport.Format) async throws {
        let directory = try makeDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let target = directory.appendingPathComponent(format == .png ? "export.png" : "export.svg")
        try Data("previous export".utf8).write(to: target)
        let model = await MainActor.run {
            let model = makeModel(in: directory)
            if format == .png { model.exportPNG(to: target) } else { model.exportSVG(to: target) }
            return model
        }
        try await waitForIdle(model)
        if format == .png {
            let source = try XCTUnwrap(CGImageSourceCreateWithURL(target as CFURL, nil))
            let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
            XCTAssertEqual(image.width, 16); XCTAssertEqual(image.height, 12)
        } else {
            let svg = try String(contentsOf: target, encoding: .utf8)
            XCTAssertTrue(svg.contains("<svg")); XCTAssertTrue(svg.contains("viewBox=\"0 0 16 12\""))
        }
        try await waitForCleanup(in: directory, keeping: target.lastPathComponent)
        await MainActor.run { XCTAssertTrue(model.status.contains(target.lastPathComponent)); XCTAssertFalse(model.dirty) }
    }
    @MainActor private func makeModel(in directory: URL) -> EditorModel {
        _ = NSApplication.shared
        let model = EditorModel(), photo = PhotoPixels(width: 16, height: 12, rgba: [UInt8](repeating: 255, count: 16 * 12 * 4))
        var document = MoonDocument(imagePath: directory.appendingPathComponent("source.png").path)
        document.imageWidth = 16; document.imageHeight = 12
        model.document = document; model.appliedDocument = document; model.image = photo.cgImage; model.markClean()
        return model
    }
    private func makeDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
    private func waitForIdle(_ model: EditorModel) async throws {
        for _ in 0..<100 {
            if await MainActor.run(body: { !model.busy }) { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        await MainActor.run { XCTAssertFalse(model.busy); XCTAssertNil(model.operation) }
    }
    private func waitForCleanup(in directory: URL, keeping file: String) async throws {
        for _ in 0..<100 {
            if try FileManager.default.contentsOfDirectory(atPath: directory.path) == [file] { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.path), [file])
    }
    private func cancelledExport(_ format: ImageExport.Format) async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let target = directory.appendingPathComponent(format == .png ? "export.png" : "export.svg")
        let original = Data("keep-existing-export".utf8); try original.write(to: target)
        let gate = ExportGate(); defer { gate.release() }
        let model = await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(), photo = PhotoPixels(width: 16, height: 12, rgba: [UInt8](repeating: 255, count: 16 * 12 * 4))
            var document = MoonDocument(imagePath: directory.appendingPathComponent("source.png").path)
            document.imageWidth = 16; document.imageHeight = 12
            model.document = document; model.appliedDocument = document; model.image = photo.cgImage; model.markClean()
            model.exportWriter = { _, _, _, _, url in try gate.write(url) }
            if format == .png { model.exportPNG(to: target) } else { model.exportSVG(to: target) }
            XCTAssertTrue(model.busy); XCTAssertNotNil(model.operation, "Every export must participate in cancel and close handoff")
            return model
        }
        for _ in 0..<100 where !gate.started { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(gate.started)
        await MainActor.run { model.cancelOperation() }
        for _ in 0..<100 {
            if await MainActor.run(body: { !model.busy }) { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        await MainActor.run { XCTAssertFalse(model.busy, "Cancel must release the editor while the encoder is still waiting") }
        gate.release()
        for _ in 0..<100 where !gate.finished { try await Task.sleep(for: .milliseconds(10)) }
        for _ in 0..<100 {
            if await MainActor.run(body: { !model.busy }) { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertTrue(gate.finished)
        try await waitForCleanup(in: directory, keeping: target.lastPathComponent)
        XCTAssertEqual(try Data(contentsOf: target), original, "A late cancelled export must never overwrite the target")
        await MainActor.run { XCTAssertNil(model.operation); XCTAssertFalse(model.busy) }
    }
}

private final class ExportGate: @unchecked Sendable {
    private let lock = NSLock(), semaphore = DispatchSemaphore(value: 0)
    private var hasStarted = false, hasFinished = false
    var started: Bool { lock.lock(); defer { lock.unlock() }; return hasStarted }
    var finished: Bool { lock.lock(); defer { lock.unlock() }; return hasFinished }
    func release() { semaphore.signal() }
    func write(_ url: URL) throws {
        lock.lock(); hasStarted = true; lock.unlock()
        semaphore.wait()
        try Data("late-encoder-result".utf8).write(to: url)
        lock.lock(); hasFinished = true; lock.unlock()
    }
}
