// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI
import MoonCore

struct CanvasHost: NSViewRepresentable {
    @ObservedObject var model: EditorModel
    func makeNSView(context: Context) -> MoonCanvas {
        let view = MoonCanvas(); view.model = model; return view
    }
    func updateNSView(_ view: MoonCanvas, context: Context) {
        view.model = model
        if view.canvasInteractionRevision != model.canvasInteractionRevision {
            view.canvasInteractionRevision = model.canvasInteractionRevision; view.cancelInteraction()
        }
        if view.fitRequest != model.fitRequest {
            view.fitRequest = model.fitRequest; view.fitImage()
        }
        if view.actualSizeRequest != model.actualSizeRequest {
            view.actualSizeRequest = model.actualSizeRequest
            view.zoom(to: 1, at: CGPoint(x: view.bounds.midX, y: view.bounds.midY))
        }
        if view.zoomStepRequest != model.zoomStepRequest {
            view.zoomStepRequest = model.zoomStepRequest
            view.zoom(to: view.scale * pow(1.2, Double(model.zoomStep)), at: CGPoint(x: view.bounds.midX, y: view.bounds.midY))
        }
        view.needsDisplay = true
        view.window?.invalidateCursorRects(for: view)
    }
}

@MainActor
final class MoonCanvas: PhotoViewport {
    override var photo: CGImage? { model?.image }
    weak var model: EditorModel?
    var fitRequest = -1
    var actualSizeRequest = -1
    var zoomStepRequest = 0
    var canvasInteractionRevision = -1
    private var dragStart = CGPoint.zero
    private var originStart = CGPoint.zero
    private var positionStart: PixelPoint?
    private var documentStart: MoonDocument?
    private var anchorDrag = false
    private var moved = false
    private var draftPoints: [PixelPoint] = []
    private var spaceHeld = false
    private var overlayDrag: String?
    private var maskPreview: CGImage?
    private var maskSnapshot: RecognitionMask?
    private var maskDimensions = CGSize.zero
    private let renderCache = CanvasRenderCache()
    private var pendingZoomLabel: String?
    private var zoomPublicationQueued = false
    private var zoomRefinement: Task<Void, Never>?
    private var tileRefinementQueued = false
    private(set) var isZooming = false
    var displayNeedsRefinement: Bool { renderCache.needsRefinement }
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        registerForDraggedTypes([.fileURL])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func zoom(to requested: CGFloat, at cursor: CGPoint) {
        guard photo != nil else { return }
        isZooming = true; zoomRefinement?.cancel()
        super.zoom(to: requested, at: cursor)
        zoomRefinement = Task { [weak self] in
            do { try await Task.sleep(for: .milliseconds(120)); self?.finishZoomInteraction() }
            catch { }
        }
    }
    override func fitImage() { finishZoomInteraction(); super.fitImage() }
    func finishZoomInteraction() {
        zoomRefinement?.cancel(); zoomRefinement = nil
        if isZooming { isZooming = false; needsDisplay = true }
    }

    override func publishZoom() {
        let text = String(format: "%.0f%%", scale * 100)
        // Fit can be requested during a SwiftUI view update.
        let topLeft = pixel(.zero), bottomRight = pixel(CGPoint(x: bounds.maxX, y: bounds.maxY))
        let viewport = CGRect(x: topLeft.x, y: topLeft.y, width: bottomRight.x - topLeft.x, height: bottomRight.y - topLeft.y)
        model?.viewport = viewport
        pendingZoomLabel = text
        guard model?.zoomLabel != text || zoomPublicationQueued else { pendingZoomLabel = nil; return }
        guard !zoomPublicationQueued else { return }
        zoomPublicationQueued = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.zoomPublicationQueued = false
            if let value = self.pendingZoomLabel, self.model?.zoomLabel != value { self.model?.zoomLabel = value }
            self.pendingZoomLabel = nil
        }
    }
    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.saveGState(); defer { context.restoreGState() }
        // A fractional dirty edge would blend the background into retained
        // pixels on every drag. AppKit and bitmap contexts both need whole
        // backing pixels, including the actual Retina transform.
        let damage = context.convertToUserSpace(context.convertToDeviceSpace(bounds.intersection(dirtyRect)).integral)
        context.clip(to: bounds); context.clip(to: damage)
        AnnotationRenderer.color("#10151d").setFill(); bounds.fill()
        guard let image = model?.displayImage ?? model?.image, var document = model?.displayDocument else { return }
        if model?.showAnnotations == false { document.annotations = [] }
        context.translateBy(x: origin.x, y: origin.y); context.scaleBy(x: scale, y: scale)
        let dragging = documentStart != nil && positionStart != nil && overlayDrag == nil ? model?.selectedID : nil
        renderCache.draw(image: image, document: document, scene: model?.scene, context: context,
                         editing: dragging != nil, editingAnnotationID: dragging, interactiveZoom: isZooming,
                         viewport: CGRect(x: -origin.x / scale, y: -origin.y / scale, width: bounds.width / scale, height: bounds.height / scale))
        if renderCache.needsRefinement && !tileRefinementQueued {
            tileRefinementQueued = true
            DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(16)) { [weak self] in
                self?.tileRefinementQueued = false; self?.needsDisplay = true
            }
        }
        drawEditingOverlays(document: document, context: context)
        // Renderer clips to the photograph; selection belongs to the editor only.
        if model?.showAnnotations == true, let selected = model?.selectedAnnotation,
           AnnotationSceneBuilder.visible(selected, document: document, scene: model?.scene) {
            let rect = SceneRenderer.labelBounds(selected, document: document).insetBy(dx: -4 / scale, dy: -4 / scale)
            context.setStrokeColor(NSColor.systemOrange.cgColor)
            context.setLineWidth(1.5 / scale); context.setLineDash(phase: 0, lengths: [4 / scale, 3 / scale])
            context.stroke(rect)
            context.setLineDash(phase: 0, lengths: [])
            context.strokeEllipse(in: CGRect(x: selected.anchor.x - 6 / scale, y: selected.anchor.y - 6 / scale,
                                             width: 12 / scale, height: 12 / scale))
        }
    }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: model?.placementText == nil && model?.canvasTool == .pan ? .openHand : .crosshair)
    }

    override func mouseDown(with event: NSEvent) {
        guard let model, !model.busy, let document = model.displayDocument else { return }
        window?.makeFirstResponder(self)
        let local = convert(event.locationInWindow, from: nil), point = pixel(local)
        if !spaceHeld {
            switch model.canvasTool {
            case .anchor(let id): model.addAnchor(id: id, point: PixelPoint(point.x, point.y)); return
            case .candidateCenter(let id):
                if let index = model.craterCandidates.firstIndex(where: { $0.id == id }) { model.craterCandidates[index].center = PixelPoint(point.x, point.y); model.craterCandidates[index].support = .nan; model.craterCandidates[index].method = "manual" }
                model.canvasTool = .pan; return
            case .paint, .erase: draftPoints = [PixelPoint(point.x, point.y)]; needsDisplay = true; return
            case .polygon:
                draftPoints.append(PixelPoint(point.x, point.y))
                if event.clickCount == 2, draftPoints.count >= 3 { model.commitMask(MaskStroke(kind: "polygon", points: draftPoints)); draftPoints = [] }
                needsDisplay = true; return
            case .pan: break
            }
        }
        if model.placementText != nil {
            if CGRect(x: 0, y: 0, width: document.imageWidth, height: document.imageHeight).contains(point) {
                model.finishPlacement(at: PixelPoint(point.x, point.y))
            }
            return
        }
        if !spaceHeld, model.candidateOverlaysVisible,
           let candidate = model.craterCandidates.reversed().first(where: { hypot($0.center.x - point.x, $0.center.y - point.y) <= 12 / scale }) {
            model.selectedCandidate = candidate.id; model.selectedID = nil; needsDisplay = true; return
        }
        documentStart = model.document; dragStart = local; originStart = origin; positionStart = nil; moved = false; overlayDrag = nil
        if event.modifierFlags.contains(.command), let scene = model.scene {
            if document.style.bool("overview_enabled"), scene.overview != nil, SceneRenderer.overviewRect(document).contains(point) { overlayDrag = "overview_position"; positionStart = PixelPoint(SceneRenderer.overviewRect(document).minX, SceneRenderer.overviewRect(document).minY); return }
            if let legend = SceneRenderer.visibleLegendRect(document, scene: scene), legend.contains(point) { overlayDrag = "legend_position"; positionStart = PixelPoint(legend.minX, legend.minY); return }
        }
        let radius = 9 / scale
        let hit = model.showAnnotations ? document.annotations.reversed().first { annotation in
            AnnotationSceneBuilder.visible(annotation, document: document, scene: model.scene) && (SceneRenderer.labelBounds(annotation, document: document)
                .insetBy(dx: -3 / scale, dy: -3 / scale).contains(point) ||
                hypot(annotation.anchor.x - point.x, annotation.anchor.y - point.y) < radius)
        } : nil
        model.selectedID = hit?.id
        if let hit {
            anchorDrag = event.modifierFlags.contains(.option)
            if event.modifierFlags.contains(.command) { positionStart = anchorDrag ? hit.anchor : hit.position }
            if event.clickCount == 2 { documentStart = nil; positionStart = nil; editText(hit); return }
        }
        if positionStart == nil { NSCursor.closedHand.push() }
        needsDisplay = true
    }
    override func mouseDragged(with event: NSEvent) {
        guard let model, !model.busy else { return }
        let local = convert(event.locationInWindow, from: nil)
        if !spaceHeld, model.canvasTool == .paint || model.canvasTool == .erase {
            let point = pixel(local)
            if let previous = draftPoints.last, hypot(previous.x - point.x, previous.y - point.y) >= max(1, 2 / scale) { draftPoints.append(PixelPoint(point.x, point.y)) }
            needsDisplay = true; return
        }
        guard documentStart != nil else { return }
        let dx = local.x - dragStart.x, dy = local.y - dragStart.y
        moved = moved || hypot(dx, dy) > 2
        guard moved else { return }
        if let positionStart {
            let point = PixelPoint(positionStart.x + dx / scale, positionStart.y + dy / scale)
            if let overlayDrag {
                let previous = model.displayDocument
                model.overlayPreview = EditorModel.OverlayPreview(key: overlayDrag, position: point)
                if let previous, let current = model.displayDocument {
                    let damage: CGRect
                    if overlayDrag == "overview_position" {
                        damage = (SceneRenderer.overviewExclusion(previous, scene: model.scene) ?? .null)
                            .union(SceneRenderer.overviewExclusion(current, scene: model.scene) ?? .null)
                    } else { damage = SceneRenderer.legendRect(previous).union(SceneRenderer.legendRect(current)) }
                    let canvasRect = CGRect(x: origin.x + damage.minX * scale, y: origin.y + damage.minY * scale,
                                            width: damage.width * scale, height: damage.height * scale).insetBy(dx: -max(4, scale * 2), dy: -max(4, scale * 2))
                    setNeedsDisplay(canvasRect)
                    return
                }
            }
            else { model.moveSelected(to: point, anchor: anchorDrag) }
        } else {
            origin = CGPoint(x: originStart.x + dx, y: originStart.y + dy); fitsWindow = false; publishZoom()
        }
        needsDisplay = true
    }
    override func mouseUp(with event: NSEvent) {
        if let model, !draftPoints.isEmpty, model.canvasTool == .paint || model.canvasTool == .erase {
            model.commitMask(MaskStroke(kind: model.canvasTool == .paint ? "paint" : "erase", points: draftPoints, radius: model.brushDiameter / 2))
            draftPoints = []; needsDisplay = true
        }
        if let previous = documentStart, positionStart != nil, moved {
            if let preview = model?.overlayPreview {
                model?.document?.changeStyle { $0.values[preview.key] = .array([.number(preview.position.x), .number(preview.position.y)]) }
            }
            model?.overlayPreview = nil; model?.endDrag(previous: previous)
        }
        model?.overlayPreview = nil
        if documentStart != nil && positionStart == nil { NSCursor.pop() }
        documentStart = nil; positionStart = nil
        needsDisplay = true
    }
    func cancelInteraction() {
        if let previous = documentStart {
            if positionStart != nil { if overlayDrag == nil { model?.document = previous } }
            else { NSCursor.pop() }
        }
        model?.overlayPreview = nil
        documentStart = nil; positionStart = nil; overlayDrag = nil; draftPoints = []; spaceHeld = false; needsDisplay = true
    }
    private func editText(_ annotation: Annotation) {
        model?.selectedID = annotation.id; model?.editSelectedLabel()
    }
    override func keyDown(with event: NSEvent) {
        guard let model, !model.busy else { return }
        switch event.keyCode {
        case 49: spaceHeld = true
        case 36, 76:
            if model.canvasTool == .polygon, draftPoints.count >= 3 { model.commitMask(MaskStroke(kind: "polygon", points: draftPoints)); draftPoints = []; needsDisplay = true }
        case 53:
            model.placementText = nil; model.placementFeatureID = nil; model.selectedID = nil
            model.cancelCanvasInteraction(); cancelInteraction()
            model.status = "已取消放置。"
        case 51, 117: model.deleteSelected()
        case 123...126:
            let distance = event.modifierFlags.contains(.shift) ? 10.0 : 1.0
            model.changeSelected { annotation in
                if event.keyCode == 123 { annotation.position.x -= distance }
                if event.keyCode == 124 { annotation.position.x += distance }
                if event.keyCode == 125 { annotation.position.y += distance }
                if event.keyCode == 126 { annotation.position.y -= distance }
            }
        default: super.keyDown(with: event)
        }
    }
    override func keyUp(with event: NSEvent) { if event.keyCode == 49 { spaceHeld = false } else { super.keyUp(with: event) } }
    private func drawEditingOverlays(document: MoonDocument, context: CGContext) {
        guard let model else { return }
        if model.showMask {
            var mask = document.state.recognitionMask
            if !draftPoints.isEmpty { mask.operations.append(MaskStroke(kind: model.canvasTool == .erase ? "erase" : model.canvasTool == .polygon ? "polygon" : "paint", points: draftPoints, radius: model.brushDiameter / 2)) }
            let dimensions = CGSize(width: document.imageWidth, height: document.imageHeight)
            if mask != maskSnapshot || maskDimensions != dimensions {
                let ratio = min(1, 768.0 / Double(max(document.imageWidth, document.imageHeight)))
                let width = max(1, Int(Double(document.imageWidth) * ratio)), height = max(1, Int(Double(document.imageHeight) * ratio))
                let values = mask.raster(width: width, height: height, originalWidth: document.imageWidth, originalHeight: document.imageHeight)
                var rgba = [UInt8](repeating: 0, count: width * height * 4)
                for i in values.indices { let alpha = UInt8(Double(255 - values[i]) * 0.4); rgba[i * 4] = alpha; rgba[i * 4 + 1] = alpha / 8; rgba[i * 4 + 2] = alpha / 6; rgba[i * 4 + 3] = alpha }
                maskPreview = PhotoPixels(width: width, height: height, rgba: rgba).cgImage; maskSnapshot = mask; maskDimensions = dimensions
            }
            if let maskPreview {
                context.saveGState(); context.translateBy(x: 0, y: Double(document.imageHeight)); context.scaleBy(x: 1, y: -1)
                context.draw(maskPreview, in: CGRect(x: 0, y: 0, width: document.imageWidth, height: document.imageHeight)); context.restoreGState()
            }
        }
        if model.referenceMarkersVisible {
            let surface = try? AnnotationSurface(document: document)
            for (index, anchor) in document.state.anchors.enumerated() {
                context.saveGState()
                let radius = 8 / scale, color = AnnotationRenderer.color(anchor.enabled == false ? "#718399" : "#75d6d6")
                context.setStrokeColor(color.cgColor); context.setLineWidth(1.5 / scale)
                context.move(to: CGPoint(x: anchor.point.x - radius, y: anchor.point.y)); context.addLine(to: CGPoint(x: anchor.point.x + radius, y: anchor.point.y))
                context.move(to: CGPoint(x: anchor.point.x, y: anchor.point.y - radius)); context.addLine(to: CGPoint(x: anchor.point.x, y: anchor.point.y + radius)); context.strokePath()
                let number = " \(index + 1) " as NSString
                let attributes: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 11 / scale), .foregroundColor: color, .backgroundColor: AnnotationRenderer.color("#111821")]
                number.draw(at: CGPoint(x: anchor.point.x + 3 / scale, y: anchor.point.y + 3 / scale), withAttributes: attributes)
                if anchor.enabled != false, let surface, let feature = model.features.first(where: { $0.id == anchor.id }) {
                    let predicted = surface.position(feature).point
                    if predicted.isFinite, hypot(predicted.x - anchor.point.x, predicted.y - anchor.point.y) > 1 {
                        context.setStrokeColor(AnnotationRenderer.color("#ffb36b").cgColor); context.setLineDash(phase: 0, lengths: [4 / scale, 3 / scale])
                        context.move(to: CGPoint(x: anchor.point.x, y: anchor.point.y)); context.addLine(to: CGPoint(x: predicted.x, y: predicted.y)); context.strokePath()
                    }
                }
                context.restoreGState()
            }
        }
        if model.candidateOverlaysVisible {
            for (index, candidate) in model.craterCandidates.enumerated() {
                let selected = candidate.id == model.selectedCandidate
                let color = selected ? NSColor.systemOrange : NSColor.systemCyan.withAlphaComponent(0.6)
                context.saveGState(); context.setStrokeColor(color.cgColor); context.setLineWidth((selected ? 2 : 1) / scale)
                let radius = (selected ? 5.0 : 3.0) / scale
                context.move(to: CGPoint(x: candidate.center.x - radius, y: candidate.center.y)); context.addLine(to: CGPoint(x: candidate.center.x + radius, y: candidate.center.y))
                context.move(to: CGPoint(x: candidate.center.x, y: candidate.center.y - radius)); context.addLine(to: CGPoint(x: candidate.center.x, y: candidate.center.y + radius)); context.strokePath()
                ("\(index + 1)" as NSString).draw(at: CGPoint(x: candidate.center.x + radius, y: candidate.center.y + radius), withAttributes: [.font: NSFont.systemFont(ofSize: 11 / scale), .foregroundColor: color])
                if selected || model.showAllCandidateContours {
                    context.translateBy(x: candidate.center.x, y: candidate.center.y); context.rotate(by: candidate.angle * .pi / 180)
                    context.strokeEllipse(in: CGRect(x: -candidate.major, y: -candidate.minor, width: candidate.major * 2, height: candidate.minor * 2))
                }
                context.restoreGState()
            }
        }
    }
    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation { model?.busy == true ? [] : .copy }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        guard let url = (sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: nil) as? [URL])?.first else { return false }
        model?.requestOpen(url); return true
    }
}
