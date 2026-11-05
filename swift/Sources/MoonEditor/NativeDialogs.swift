// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit

@MainActor
enum NativeDialogs {
    private static var owner: NSWindow? { NSApp.windows.first { $0.identifier?.rawValue == "moon-editor" && $0.isVisible } }
    static func run(_ panel: NSSavePanel) -> NSApplication.ModalResponse {
        guard let owner else { return panel.runModal() }
        NSApp.activate(ignoringOtherApps: true); owner.makeKeyAndOrderFront(nil)
        var response = NSApplication.ModalResponse.cancel
        panel.beginSheetModal(for: owner) { result in response = result; NSApp.stopModal(withCode: result) }
        NSApp.runModal(for: panel)
        return response
    }
    static func run(_ alert: NSAlert) -> NSApplication.ModalResponse {
        guard let owner else { return alert.runModal() }
        NSApp.activate(ignoringOtherApps: true); owner.makeKeyAndOrderFront(nil)
        var response = NSApplication.ModalResponse.cancel
        alert.beginSheetModal(for: owner) { result in response = result; NSApp.stopModal(withCode: result) }
        NSApp.runModal(for: alert.window)
        return response
    }
}
