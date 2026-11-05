// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI

struct NativeLanguageMenu: NSViewRepresentable {
    @ObservedObject var model: EditorModel
    func makeCoordinator() -> Coordinator { Coordinator(model: model) }
    func makeNSView(context: Context) -> NSButton {
        let button = NSButton(title: "", target: context.coordinator, action: #selector(Coordinator.open(_:)))
        button.isBordered = false; button.font = .systemFont(ofSize: 13)
        button.keyEquivalent = "L"; button.keyEquivalentModifierMask = [.command, .shift]
        button.toolTip = "⌘⇧L"
        return button
    }
    func updateNSView(_ button: NSButton, context: Context) {
        context.coordinator.model = model
        button.isEnabled = context.environment.isEnabled && !model.busy
        button.attributedTitle = NSAttributedString(string: model.tr("界面语言 / Language"), attributes: [
            .font: NSFont.systemFont(ofSize: 13),
            .foregroundColor: AnnotationRenderer.color(button.isEnabled ? "#dfe6ef" : "#9badc0").withAlphaComponent(button.isEnabled ? 1 : 0.5)
        ])
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSButton, context: Context) -> CGSize? {
        let width = (model.tr("界面语言 / Language") as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 13)]).width
        return CGSize(width: ceil(width) + 20, height: 34)
    }
    @MainActor final class Coordinator: NSObject {
        weak var model: EditorModel?
        init(model: EditorModel) { self.model = model }
        @objc func open(_ sender: NSButton) {
            guard let model, !model.busy else { return }
            let menu = NSMenu(); menu.autoenablesItems = false
            for name in InterfaceText.languages {
                let item = NSMenuItem(title: name, action: #selector(selectLanguage(_:)), keyEquivalent: "")
                item.target = self; item.representedObject = name
                item.state = name == model.uiLanguage ? .on : .off; menu.addItem(item)
            }
            menu.popUp(positioning: nil, at: CGPoint(x: 0, y: sender.bounds.maxY + 2), in: sender)
        }
        @objc func selectLanguage(_ sender: NSMenuItem) {
            guard let name = sender.representedObject as? String else { return }
            model?.setInterfaceLanguage(name)
        }
    }
}
