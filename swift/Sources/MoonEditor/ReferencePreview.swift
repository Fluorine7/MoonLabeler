// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI
import MoonCore

@MainActor
final class ReferencePreviewController: NSWindowController, NSWindowDelegate {
    private weak var model: EditorModel?
    private let hosting: NSHostingController<ReferencePreview>
    init(model: EditorModel, reference: TerrainReference, state: ProjectState) {
        self.model = model
        hosting = NSHostingController(rootView: ReferencePreview(model: model, image: reference.image.cgImage, state: state, resolution: reference.resolutionKM))
        hosting.sizingOptions = []
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 880), styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.contentViewController = hosting; window.identifier = NSUserInterfaceItemIdentifier("moon-reference")
        window.title = model.tr("DEM 模拟"); window.minSize = NSSize(width: 580, height: 520); window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .darkAqua)
        super.init(window: window); window.delegate = self
        let screen = NSScreen.main?.visibleFrame.size ?? NSSize(width: 1100, height: 1000)
        window.setContentSize(NSSize(width: min(900, max(580, screen.width - 80)), height: min(880, max(520, screen.height - 80))))
        window.center()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    func update(reference: TerrainReference, state: ProjectState) {
        guard let model else { return }
        hosting.rootView = ReferencePreview(model: model, image: reference.image.cgImage, state: state, resolution: reference.resolutionKM)
        window?.title = model.tr("DEM 模拟")
    }
    func windowWillClose(_ notification: Notification) { if model?.referenceWindow === self { model?.referenceWindow = nil } }
}

private struct ReferencePreview: View {
    @ObservedObject var model: EditorModel
    let image: CGImage
    let state: ProjectState
    let resolution: Double
    var body: some View {
        VStack(spacing: 12) {
            Text(state.utc + " · " + model.tr("视野") + String(format: " %.0f km · ", state.terrainSettings.number("width_km", 300)) + model.tr("采样") + String(format: " %.3f km", resolution))
                .frame(maxWidth: .infinity, alignment: .leading)
                .help(model.tr("球面光照模拟，未加入反照率纹理；细节和阴影可能与实拍不同。"))
            ReferenceViewportHost(image: image).frame(maxWidth: .infinity, maxHeight: .infinity)
            HStack(spacing: 12) {
                Button(model.tr("保存模拟图与参考工程")) { model.saveReference() }.disabled(model.busy)
                Button(model.tr("匹配当前照片")) { model.alignReference() }.disabled(model.image == nil || model.busy)
                Spacer()
                Button(model.tr("关闭预览")) { model.closeReferencePreview() }
            }
        }.padding(14).frame(minWidth: 550, minHeight: 480).background(EditorPalette.panel).foregroundStyle(EditorPalette.text)
            .font(.system(size: 13)).buttonStyle(EditorButtonStyle())
    }
}

private struct ReferenceViewportHost: NSViewRepresentable {
    let image: CGImage
    func makeNSView(context: Context) -> ReferenceViewport { let view = ReferenceViewport(); view.image = image; return view }
    func updateNSView(_ view: ReferenceViewport, context: Context) {
        if view.image !== image { view.image = image; view.fitImage() }
    }
}
private final class ReferenceViewport: PhotoViewport {
    var image: CGImage?
    override var photo: CGImage? { image }
}

@MainActor extension EditorModel {
    func showReferencePreview() {
        guard let reference else { return }
        if let referenceWindow { referenceWindow.update(reference: reference, state: workingState) }
        else { referenceWindow = ReferencePreviewController(model: self, reference: reference, state: workingState) }
        referenceWindow?.showWindow(nil); referenceWindow?.window?.makeKeyAndOrderFront(nil)
    }
    func closeReferencePreview() { referenceWindow?.close(); referenceWindow = nil }
}
