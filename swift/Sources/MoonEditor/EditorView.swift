// SPDX-License-Identifier: GPL-3.0-or-later
import SwiftUI
import AppKit
import MoonCore

enum EditorPalette {
    static let background = Color(nsColor: AnnotationRenderer.color("#131821"))
    static let panel = Color(nsColor: AnnotationRenderer.color("#171d28"))
    static let surface = Color(nsColor: AnnotationRenderer.color("#0f141d"))
    static let line = Color(nsColor: AnnotationRenderer.color("#242e3c"))
    static let text = Color(nsColor: AnnotationRenderer.color("#dfe6ef"))
    static let secondary = Color(nsColor: AnnotationRenderer.color("#9badc0"))
    static let accent = Color(nsColor: AnnotationRenderer.color("#d9a96c"))
}
struct EditorButtonStyle: ButtonStyle {
    var primary = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 13, weight: primary ? .semibold : .regular))
            .padding(.horizontal, 11).padding(.vertical, 7)
            .foregroundStyle(enabled ? (primary ? Color(nsColor: AnnotationRenderer.color("#1f1506")) : EditorPalette.text) : EditorPalette.secondary.opacity(0.5))
            .background(primary ? EditorPalette.accent.opacity(enabled ? 1 : 0.3) : Color(nsColor: AnnotationRenderer.color(configuration.isPressed ? "#26303f" : "#222c3a")), in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(primary ? EditorPalette.accent.opacity(0.6) : EditorPalette.line, lineWidth: 1))
    }
}
private struct EditorToolbarStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 13)).padding(.horizontal, 10).frame(height: 34)
            .foregroundStyle(enabled ? EditorPalette.text : EditorPalette.secondary.opacity(0.5))
            .background(configuration.isPressed ? Color(nsColor: AnnotationRenderer.color("#26303f")) : .clear, in: RoundedRectangle(cornerRadius: 6))
    }
}

public struct EditorView: View {
    @ObservedObject var model: EditorModel
    @State private var windowBridge = WindowBridge()
    public init(model: EditorModel) { self.model = model }
    public var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 6) { fileTools; Spacer(minLength: 10); settingsTools }
                HStack(spacing: 6) { compactFileTools; Spacer(minLength: 10); settingsTools }
            }.disabled(model.busy).buttonStyle(EditorToolbarStyle()).padding(.horizontal, 14).padding(.vertical, 7).background(EditorPalette.panel)
            Rectangle().fill(EditorPalette.line).frame(height: 1)
            HSplitView {
                VStack(spacing: 0) {
                    HStack {
                        Text(model.document.map { URL(fileURLWithPath: $0.imagePath).lastPathComponent } ?? model.tr("月面照片")).fontWeight(.semibold)
                        Spacer()
                        Text(model.tr("滚轮缩放 · 按住 Cmd 拖动标签 · 双击编辑文字")).font(.system(size: 12)).foregroundStyle(EditorPalette.secondary)
                    }.padding(.horizontal, 16).padding(.vertical, 9).background(EditorPalette.background)
                    Rectangle().fill(EditorPalette.line).frame(height: 1)
                    ZStack {
                        CanvasHost(model: model)
                        if model.image == nil { Text(model.tr("打开或拖入照片")).font(.system(size: 26)).foregroundStyle(EditorPalette.secondary) }
                        if model.busy { ProgressView(model.tr(model.taskStatus)).padding(20).background(EditorPalette.panel, in: RoundedRectangle(cornerRadius: 6)) }
                    }
                }.frame(minWidth: 540, maxWidth: .infinity, maxHeight: .infinity)
                NativeInspector(model: model).frame(minWidth: 340, idealWidth: 390, maxWidth: 432)
            }
            Rectangle().fill(EditorPalette.line).frame(height: 1)
            HStack(spacing: 12) {
                Text(model.tr(model.busy ? model.taskStatus : model.status)).lineLimit(1)
                if model.busy { Button(model.tr("中止")) { model.cancelOperation() } }
                Spacer()
                if let doc = model.document { Text("\(doc.imageWidth) × \(doc.imageHeight)").monospacedDigit() }
                Text(model.tr(model.zoomLabel)).monospacedDigit()
            }.font(.system(size: 12)).foregroundStyle(EditorPalette.secondary).padding(.horizontal, 14).frame(height: 28).background(EditorPalette.panel)
        }.foregroundStyle(EditorPalette.text).font(.system(size: 13)).tint(EditorPalette.accent)
            .buttonStyle(EditorButtonStyle()).background(EditorPalette.background).frame(minWidth: 1040, minHeight: 680)
            .background(WindowAccessor(model: model, bridge: windowBridge))
    }
    @ViewBuilder private var compactFileTools: some View {
        Button(model.tr("打开照片")) { model.requestOpen() }.buttonStyle(EditorButtonStyle(primary: true))
        Button(model.tr("打开工程")) { model.requestOpen() }
        Button(model.tr("保存工程")) { model.save() }.disabled(model.document == nil || model.busy)
        Divider().frame(height: 24)
        Button(model.tr("导出 PNG")) { model.exportPNG() }.disabled(model.image == nil || model.busy)
        Button(model.tr("导出 SVG")) { model.exportSVG() }.disabled(model.image == nil || model.busy)
        Toggle(model.tr("显示标注"), isOn: $model.showAnnotations).toggleStyle(.checkbox)
        Menu("»") {
            Button(model.tr("原始大小")) { model.actualSizeRequest += 1 }.disabled(model.image == nil)
            Button(model.tr("适合窗口")) { model.fitRequest += 1 }.disabled(model.image == nil)
            Button("+") { model.zoomStep = 1; model.zoomStepRequest += 1 }.disabled(model.image == nil)
            Button("−") { model.zoomStep = -1; model.zoomStepRequest += 1 }.disabled(model.image == nil)
            Toggle(model.tr("显示蒙版"), isOn: $model.showMask)
        }.menuStyle(.borderlessButton).fixedSize()
    }
    @ViewBuilder private var fileTools: some View {
        Button(model.tr("打开照片")) { model.requestOpen() }.buttonStyle(EditorButtonStyle(primary: true))
        Button(model.tr("打开工程")) { model.requestOpen() }
        Button(model.tr("保存工程")) { model.save() }.disabled(model.document == nil || model.busy)
        Divider().frame(height: 24)
        Button(model.tr("导出 PNG")) { model.exportPNG() }.disabled(model.image == nil || model.busy)
        Button(model.tr("导出 SVG")) { model.exportSVG() }.disabled(model.image == nil || model.busy)
        Divider().frame(height: 24)
        Button(model.tr("原始大小")) { model.actualSizeRequest += 1 }.disabled(model.image == nil)
        Button(model.tr("适合窗口")) { model.fitRequest += 1 }.disabled(model.image == nil)
        Button("+") { model.zoomStep = 1; model.zoomStepRequest += 1 }.disabled(model.image == nil)
        Button("−") { model.zoomStep = -1; model.zoomStepRequest += 1 }.disabled(model.image == nil)
        Toggle(model.tr("显示标注"), isOn: $model.showAnnotations).toggleStyle(.checkbox)
        Toggle(model.tr("显示蒙版"), isOn: $model.showMask).toggleStyle(.checkbox)
    }
    @ViewBuilder private var settingsTools: some View {
        Button(model.tr("打开示例")) { model.openDemo() }.disabled(model.busy)
        Button(model.tr("计算设置")) { model.showComputeSettings() }.disabled(model.busy)
        NativeLanguageMenu(model: model).fixedSize().disabled(model.busy)
        Button(model.tr("帮助")) { model.showHelp() }
        Button(model.tr("致谢")) { model.showCredits() }
    }
}

@MainActor
final class WindowBridge: NSObject, NSWindowDelegate {
    weak var model: EditorModel?
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if let model, model.busy {
            let operation = model.operation; model.cancelOperation()
            Task { await operation?.value; sender.performClose(nil) }; return false
        }
        let accepted = model?.acceptWindowClose() ?? true
        if accepted { model?.closeReferencePreview() }
        return accepted
    }
}
private struct WindowAccessor: NSViewRepresentable {
    @ObservedObject var model: EditorModel
    let bridge: WindowBridge
    func makeNSView(context: Context) -> NSView { NSView() }
    func updateNSView(_ view: NSView, context: Context) {
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            bridge.model = model; window.identifier = NSUserInterfaceItemIdentifier("moon-editor"); window.delegate = bridge
            window.title = model.title + " — MoonLabeler"; window.isDocumentEdited = model.dirty
        }
    }
}
