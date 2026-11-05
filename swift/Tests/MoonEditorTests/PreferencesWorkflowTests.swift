// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
@testable import MoonCore
@testable import MoonEditor

final class PreferencesWorkflowTests: XCTestCase {
    func testUnsavedChangesDialogUsesTheSelectedLanguageAndKeepsTheFilename() async throws {
        await MainActor.run {
            _ = NSApplication.shared
            for (language, expectedMessage, expectedButtons) in [
                ("English", "Save changes to 原图.png?", ["Save", "Cancel", "Don’t Save"]),
                ("繁體中文", "保存對 原图.png 的修改？", ["保存", "取消", "不保存"])
            ] {
                let model = EditorModel(); model.uiLanguage = language
                var document = MoonDocument(imagePath: "/private/tmp/原图.png"); document.imageWidth = 80; document.imageHeight = 60
                model.document = document; model.markClean(); model.edit { $0.changeStyle { $0.set("font_percent", 2.0) } }
                let observation = ErrorObservation()
                let timer = Timer(timeInterval: 0.01, repeats: true) { _ in
                    MainActor.assumeIsolated {
                        guard let window = NSApp.modalWindow, let root = window.contentView else { return }
                        var pending = [root]
                        while let view = pending.popLast() {
                            if let field = view as? NSTextField { observation.messages.append(field.stringValue) }
                            if let button = view as? NSButton { observation.messages.append(button.title) }
                            pending += view.subviews
                        }
                        NSApp.stopModal(withCode: .alertSecondButtonReturn); window.orderOut(nil)
                    }
                }
                RunLoop.main.add(timer, forMode: .modalPanel); RunLoop.main.add(timer, forMode: .common)
                XCTAssertFalse(model.confirmClose()); timer.invalidate()
                XCTAssertTrue(model.dirty)
                XCTAssertTrue(observation.messages.contains(expectedMessage), observation.messages.joined(separator: " | "))
                for button in expectedButtons { XCTAssertTrue(observation.messages.contains(button), button) }
                if language == "English" { XCTAssertTrue(observation.messages.contains("You can continue editing labels after saving.")) }
            }
        }
    }
    func testErrorDialogUsesTheSelectedInterfaceLanguage() async throws {
        await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            for (language, message, expected) in [
                ("English", "无法打开 FITS 文件。", "Cannot open the FITS file."),
                ("繁體中文", "FITS 像素读取失败。", "FITS 像素讀取失敗。")
            ] {
                model.uiLanguage = language
                let observation = ErrorObservation()
                let timer = Timer(timeInterval: 0.05, repeats: true) { _ in
                    MainActor.assumeIsolated {
                        guard let window = NSApp.modalWindow, let root = window.contentView else { return }
                        var pending = [root]
                        while let view = pending.popLast() {
                            if let field = view as? NSTextField { observation.messages.append(field.stringValue) }
                            pending += view.subviews
                        }
                        NSApp.stopModal(withCode: .cancel); window.orderOut(nil)
                    }
                }
                RunLoop.main.add(timer, forMode: .modalPanel); RunLoop.main.add(timer, forMode: .common)
                model.show(MoonError.invalid(message)); timer.invalidate()
                XCTAssertEqual(model.status, expected)
                XCTAssertTrue(observation.messages.joined(separator: "\n").contains(expected), language)
            }
        }
    }
    func testLanguageSelectionPreservesPreferencesDuringBusyTasks() async throws {
        await MainActor.run {
            let defaults = UserDefaults.standard, key = "swift-ui-language"
            let saved = defaults.object(forKey: key)
            defer { if let saved { defaults.set(saved, forKey: key) } else { defaults.removeObject(forKey: key) } }
            let model = EditorModel()
            model.setInterfaceLanguage("English")
            XCTAssertEqual(model.uiLanguage, "English"); XCTAssertEqual(defaults.string(forKey: key), "English")
            model.busy = true; model.setInterfaceLanguage("繁體中文")
            XCTAssertEqual(model.uiLanguage, "English"); XCTAssertEqual(defaults.string(forKey: key), "English")
            model.busy = false; model.setInterfaceLanguage("unsupported")
            XCTAssertEqual(model.uiLanguage, "English")
            model.setInterfaceLanguage("繁體中文")
            XCTAssertEqual(model.uiLanguage, "繁體中文"); XCTAssertEqual(defaults.string(forKey: key), "繁體中文")
        }
    }
    func testBusySettingsAndHelpRequestsDoNotOpenModalWindows() async throws {
        await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(); model.busy = true
            let actions: [(String, (EditorModel) -> Void)] = [
                ("compute", { $0.showComputeSettings() }), ("help", { $0.showHelp() }), ("credits", { $0.showCredits() })
            ]
            for (name, action) in actions {
                let observation = ModalObservation()
                let timer = Timer(timeInterval: 0.05, repeats: true) { _ in
                    MainActor.assumeIsolated {
                        if let window = NSApp.modalWindow {
                            observation.presented = true
                            NSApp.stopModal(withCode: .cancel); window.orderOut(nil)
                        }
                    }
                }
                RunLoop.main.add(timer, forMode: .modalPanel)
                RunLoop.main.add(timer, forMode: .common)
                action(model); timer.invalidate()
                XCTAssertTrue(model.busy)
                XCTAssertFalse(observation.presented, "\(name) must not interrupt an active calculation")
            }
        }
    }
}

@MainActor private final class ModalObservation {
    var presented = false
}

@MainActor private final class ErrorObservation {
    var messages: [String] = []
}
