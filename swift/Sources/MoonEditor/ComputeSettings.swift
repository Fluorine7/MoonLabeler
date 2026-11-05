// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI
import MoonCore

@MainActor private final class ComputeSelection: ObservableObject {
    @Published var mode: String
    init(_ mode: String) { self.mode = mode }
}
private struct ComputeSettingsView: View {
    @ObservedObject var model: EditorModel
    @ObservedObject var selection: ComputeSelection
    let overrideVariable: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            EditorChoicePicker(model.tr("计算方式"), selection: $selection.mode,
                options: [("auto", model.tr("自动选择（推荐）")), ("cpu", model.tr("仅 CPU · 关闭 GPU"))], labelWidth: 78)
                .disabled(overrideVariable != nil)
            Text(status).fixedSize(horizontal: false, vertical: true)
            Text(model.tr("设置保存在本机，下次计算生效。GPU 不可用时自动改用 CPU。"))
                .foregroundStyle(EditorPalette.secondary).fixedSize(horizontal: false, vertical: true)
            if let overrideVariable {
                Text(model.tr("当前由环境变量指定，界面设置暂不生效。") + " " + overrideVariable)
                    .foregroundStyle(EditorPalette.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }.font(.system(size: 13)).foregroundStyle(EditorPalette.text).padding(14).frame(width: 450)
            .background(EditorPalette.panel)
    }
    private var status: String {
        if selection.mode == "cpu" { return model.tr("CPU · GPU 加速已关闭") }
        if MetalTerrainRenderer.available && MetalTerrainRenderer.diagnostic.isEmpty {
            return model.tr("可用设备：") + MetalTerrainRenderer.deviceName + " · Metal\n" + model.tr("加速高程与阴影参考；其余步骤使用 CPU。")
        }
        let reason = MetalTerrainRenderer.diagnostic
        return model.tr("使用 CPU。未找到可用的 Metal 设备。") + (reason.isEmpty ? "" : "\n" + reason)
    }
}

@MainActor extension EditorModel {
    func showComputeSettings() {
        guard !busy else { return }
        let policy = ComputePolicy(preference: computeMode), selection = ComputeSelection(policy.mode)
        let alert = NSAlert(); alert.messageText = tr("计算设置"); alert.window.identifier = NSUserInterfaceItemIdentifier("moon-compute")
        let hosting = NSHostingView(rootView: ComputeSettingsView(model: self, selection: selection, overrideVariable: policy.overrideVariable))
        hosting.frame.size = hosting.fittingSize; alert.accessoryView = hosting
        alert.addButton(withTitle: tr(policy.overrideVariable == nil ? "保存" : "关闭"))
        if policy.overrideVariable == nil { alert.addButton(withTitle: tr("取消")) }
        if NativeDialogs.run(alert) == .alertFirstButtonReturn && policy.overrideVariable == nil {
            computeMode = selection.mode; UserDefaults.standard.set(selection.mode, forKey: "moon-swift-compute")
        }
    }
}
