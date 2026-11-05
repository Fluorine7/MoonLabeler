// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit

/// Pan and zoom in photograph coordinates, shared by the editor and DEM preview.
@MainActor
class PhotoViewport: NSView {
    var photo: CGImage? { nil }
    private(set) var scale: CGFloat = 1
    var origin = CGPoint.zero
    var fitsWindow = true
    private var panStart: CGPoint?
    private var panOrigin = CGPoint.zero
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    override var wantsDefaultClipping: Bool { true }
    override func layout() { super.layout(); if fitsWindow { fitImage() } }
    func fitImage() {
        guard let image = photo, bounds.width > 0, bounds.height > 0 else { return }
        scale = max(0.01, min((bounds.width - 64) / CGFloat(image.width), (bounds.height - 64) / CGFloat(image.height)))
        origin = CGPoint(x: (bounds.width - CGFloat(image.width) * scale) / 2, y: (bounds.height - CGFloat(image.height) * scale) / 2)
        fitsWindow = true; publishZoom(); needsDisplay = true
    }
    func zoom(to requested: CGFloat, at cursor: CGPoint) {
        guard photo != nil else { return }
        let next = min(max(requested, 0.01), 16), imagePoint = pixel(cursor)
        origin = CGPoint(x: cursor.x - imagePoint.x * next, y: cursor.y - imagePoint.y * next)
        scale = next; fitsWindow = false; publishZoom(); needsDisplay = true
    }
    func pixel(_ point: CGPoint) -> CGPoint { CGPoint(x: (point.x - origin.x) / scale, y: (point.y - origin.y) / scale) }
    func publishZoom() {}
    override func scrollWheel(with event: NSEvent) {
        zoom(to: scale * exp(event.scrollingDeltaY * (event.hasPreciseScrollingDeltas ? 0.012 : 0.08)), at: convert(event.locationInWindow, from: nil))
    }
    override func magnify(with event: NSEvent) { zoom(to: scale * max(0.1, 1 + event.magnification), at: convert(event.locationInWindow, from: nil)) }
    override func resetCursorRects() { addCursorRect(bounds, cursor: .openHand) }
    override func draw(_ dirtyRect: NSRect) {
        AnnotationRenderer.color("#10151d").setFill(); bounds.fill()
        guard let image = photo, let context = NSGraphicsContext.current?.cgContext else { return }
        context.saveGState(); context.clip(to: bounds)
        context.translateBy(x: origin.x, y: origin.y + CGFloat(image.height) * scale); context.scaleBy(x: scale, y: -scale)
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height)); context.restoreGState()
    }
    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self); panStart = convert(event.locationInWindow, from: nil); panOrigin = origin; NSCursor.closedHand.push()
    }
    override func mouseDragged(with event: NSEvent) {
        guard let start = panStart else { return }
        let point = convert(event.locationInWindow, from: nil)
        origin = CGPoint(x: panOrigin.x + point.x - start.x, y: panOrigin.y + point.y - start.y)
        fitsWindow = false; publishZoom(); needsDisplay = true
    }
    override func mouseUp(with event: NSEvent) { if panStart != nil { NSCursor.pop() }; panStart = nil }
}
