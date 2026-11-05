// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
import SwiftUI
import Carbon
@testable import MoonCore
@testable import MoonEditor

final class ApplicationIntegrationTests: XCTestCase {
    func testFileOpenEventReachesTheExistingEditor() async throws { try await verifyFileEvent(beforeAttachment: false) }
    func testFileOpenEventWaitsForTheEditorToAttach() async throws { try await verifyFileEvent(beforeAttachment: true) }
    func testLegacyFileOpenEventReachesTheExistingEditor() async throws { try await verifyFileEvent(beforeAttachment: false, legacy: true) }
    func testAppleOpenDocumentsEventReachesTheExistingEditor() async throws { try await verifyFileEvent(beforeAttachment: false, appleEvent: true) }
    private func verifyFileEvent(beforeAttachment: Bool, legacy: Bool = false, appleEvent: Bool = false) async throws {
        let url = URL(fileURLWithPath: "/private/tmp/application-open-\(UUID().uuidString).png")
        let (model, delegate) = await MainActor.run {
            _ = NSApplication.shared
            let image = PhotoPixels(width: 24, height: 16, rgba: [UInt8](repeating: 255, count: 24 * 16 * 4)).cgImage
            let model = EditorModel(photoReader: { _ in (image, image) }), delegate = ApplicationDelegate()
            if !beforeAttachment { delegate.model = model }
            if appleEvent {
                let event = NSAppleEventDescriptor.appleEvent(withEventClass: AEEventClass(kCoreEventClass), eventID: AEEventID(kAEOpenDocuments),
                    targetDescriptor: nil, returnID: AEReturnID(kAutoGenerateReturnID), transactionID: AETransactionID(kAnyTransactionID))
                let files = NSAppleEventDescriptor.list(); files.insert(NSAppleEventDescriptor(fileURL: url), at: 1)
                event.setParam(files, forKeyword: AEKeyword(keyDirectObject))
                delegate.openDocumentEvent(event, reply: NSAppleEventDescriptor.null())
            } else if legacy { (delegate as NSApplicationDelegate).application?(NSApp, openFiles: [url.path]) }
            else { (delegate as NSApplicationDelegate).application?(NSApp, open: [url]) }
            if beforeAttachment { delegate.model = model }
            return (model, delegate)
        }
        for _ in 0..<100 {
            if await MainActor.run(body: { !model.busy && model.document?.imagePath == url.path }) { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        await MainActor.run {
            _ = delegate
            XCTAssertFalse(model.busy); XCTAssertEqual(model.document?.imagePath, url.path)
            XCTAssertEqual(model.image?.width, 24)
        }
    }
    func testLanguageShortcutOpensTheChoicesAndRespectsBusyState() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(), host = NSHostingView(rootView: EditorView(model: model))
            let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 1440, height: 860), styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = host; window.orderFront(nil); host.layoutSubtreeIfNeeded()
            defer { window.close() }
            let observation = LanguageMenuObservation()
            let token = NotificationCenter.default.addObserver(forName: NSMenu.didBeginTrackingNotification, object: nil, queue: nil) { notification in
                MainActor.assumeIsolated {
                    guard let menu = notification.object as? NSMenu else { return }
                    observation.titles.append(menu.items.map(\.title))
                    let timer = Timer(timeInterval: 0.02, repeats: false) { _ in MainActor.assumeIsolated { menu.cancelTracking() } }
                    RunLoop.main.add(timer, forMode: .common); RunLoop.main.add(timer, forMode: .eventTracking)
                }
            }
            defer { NotificationCenter.default.removeObserver(token) }
            let event = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.command, .shift], timestamp: 0,
                windowNumber: window.windowNumber, context: nil, characters: "L", charactersIgnoringModifiers: "L", isARepeat: false, keyCode: 37))
            XCTAssertTrue(window.performKeyEquivalent(with: event))
            XCTAssertTrue(observation.titles.contains(InterfaceText.languages), "The shortcut must open all language choices")
            model.busy = true; host.layoutSubtreeIfNeeded(); observation.titles = []
            XCTAssertFalse(window.performKeyEquivalent(with: event))
            XCTAssertTrue(observation.titles.isEmpty)
        }
    }
}
@MainActor private final class LanguageMenuObservation { var titles: [[String]] = [] }
