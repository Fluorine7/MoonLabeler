// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI
import Carbon

@MainActor
public struct MoonLabelerApplication: App {
    @StateObject private var model = EditorModel()
    @NSApplicationDelegateAdaptor(ApplicationDelegate.self) private var delegate
    public init() {}
    public var body: some Scene {
        Window("MoonLabeler Swift", id: "editor") {
            EditorView(model: model)
                .preferredColorScheme(.dark)
                .onAppear {
                    delegate.model = model
                    let path = CommandLine.arguments.dropFirst().first(where: {
                        !$0.hasPrefix("-") && FileManager.default.fileExists(atPath: $0)
                    })
                    delegate.openStartupURL(path.map { URL(fileURLWithPath: $0) })
                }
        }
        .defaultSize(width: 1440, height: 930)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button(model.tr("打开照片")) { model.requestOpen() }.keyboardShortcut("o").disabled(model.busy)
                Button(model.tr("打开工程")) { model.requestOpen() }.keyboardShortcut("o", modifiers: [.command, .shift]).disabled(model.busy)
            }
            CommandGroup(replacing: .saveItem) {
                Button(model.tr("保存工程")) { model.save() }.keyboardShortcut("s").disabled(model.document == nil || model.busy)
                Button(model.tr("另存为…")) { model.save(asNew: true) }.keyboardShortcut("s", modifiers: [.command, .shift])
                    .disabled(model.document == nil || model.busy)
                Divider()
                Button(model.tr("导出 PNG…")) { model.exportPNG() }.keyboardShortcut("e").disabled(model.document == nil || model.busy)
                Button(model.tr("导出 SVG…")) { model.exportSVG() }.keyboardShortcut("e", modifiers: [.command, .shift]).disabled(model.document == nil || model.busy)
                Button(model.tr("保存兼容 .moonlabel 工程…")) { model.saveLegacy() }.disabled(model.document == nil || model.busy)
            }
            CommandGroup(replacing: .undoRedo) {
                Button(model.tr("撤销标注修改")) { model.undo() }.keyboardShortcut("z").disabled(!model.canUndo)
                Button(model.tr("重做标注修改")) { model.redo() }.keyboardShortcut("z", modifiers: [.command, .shift]).disabled(!model.canRedo)
            }
            CommandMenu(model.tr("画布")) {
                Button(model.tr("适合窗口")) { model.fitRequest += 1 }.keyboardShortcut("0").disabled(model.image == nil || model.busy)
                Button(model.tr("原图比例 1:1")) { model.actualSizeRequest += 1 }.keyboardShortcut("1").disabled(model.image == nil || model.busy)
                Button(model.tr("放大")) { model.zoomStep = 1; model.zoomStepRequest += 1 }.keyboardShortcut("=").disabled(model.image == nil || model.busy)
                Button(model.tr("缩小")) { model.zoomStep = -1; model.zoomStepRequest += 1 }.keyboardShortcut("-").disabled(model.image == nil || model.busy)
            }
            CommandGroup(replacing: .help) {
                Button(model.tr("帮助")) { model.showHelp() }.disabled(model.busy)
                Button(model.tr("致谢")) { model.showCredits() }.disabled(model.busy)
            }
        }
    }
}

@MainActor
final class ApplicationDelegate: NSObject, NSApplicationDelegate {
    weak var model: EditorModel? {
        didSet {
            guard let model, let url = deferredFileURL else { return }
            deferredFileURL = nil; model.requestOpen(url)
        }
    }
    private var wheelMonitor: Any?
    private var deferredFileURL: URL?
    private var receivedFileEvent = false
    private var checkedStartupURL = false
    func application(_ application: NSApplication, open urls: [URL]) {
        guard let url = urls.first(where: \.isFileURL) else { return }
        receivedFileEvent = true
        if let model { model.requestOpen(url) } else { deferredFileURL = url }
    }
    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        let urls = filenames.filter { !$0.isEmpty }.map { URL(fileURLWithPath: $0) }
        application(sender, open: urls)
        if NSAppleEventManager.shared().currentAppleEvent != nil {
            sender.reply(toOpenOrPrint: urls.isEmpty ? .failure : .success)
        }
    }
    func application(_ sender: NSApplication, openFile filename: String) -> Bool {
        guard !filename.isEmpty else { return false }
        application(sender, open: [URL(fileURLWithPath: filename)]); return true
    }
    func openStartupURL(_ url: URL?) {
        guard !checkedStartupURL else { return }
        checkedStartupURL = true
        // Launch Services can deliver the initial file before the SwiftUI view
        // attaches. The command-line fallback must not open that file twice.
        guard !receivedFileEvent, let url else { return }
        model?.requestOpen(url)
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSAppleEventManager.shared().setEventHandler(self, andSelector: #selector(openDocumentEvent(_:reply:)),
            forEventClass: AEEventClass(kCoreEventClass), andEventID: AEEventID(kAEOpenDocuments))
        wheelMonitor = WheelProtection.install()
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    @objc func openDocumentEvent(_ event: NSAppleEventDescriptor, reply: NSAppleEventDescriptor) {
        guard let files = event.paramDescriptor(forKeyword: AEKeyword(keyDirectObject)) else { return }
        let urls: [URL]
        if files.numberOfItems > 0 { urls = (1...files.numberOfItems).compactMap { files.atIndex($0)?.fileURLValue } }
        else { urls = files.fileURLValue.map { [$0] } ?? [] }
        application(NSApp, open: urls)
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if let model, model.busy {
            let operation = model.operation; model.cancelOperation()
            Task { await operation?.value; sender.reply(toApplicationShouldTerminate: model.acceptWindowClose()) }
            return .terminateLater
        }
        return model?.acceptWindowClose() == false ? .terminateCancel : .terminateNow
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
