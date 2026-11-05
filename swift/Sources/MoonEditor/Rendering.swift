// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import ImageIO
import UniformTypeIdentifiers
import MoonCore

public enum PhotoIO {
    public static func open(_ url: URL) throws -> (raw: CGImage, display: CGImage) {
        let raw = try PhotoPixels.load(url)
        let display = try PhotoPixels.display(url, raw: raw), image = raw.cgImage
        // Untagged/sRGB photos often need no display conversion. Keep one
        // immutable buffer in that case; ICC-converted samples stay separate.
        return (image, display.rgba == raw.rgba ? image : display.cgImage)
    }
    public static func load(_ url: URL) throws -> CGImage {
        try PhotoPixels.load(url).cgImage
    }

    public static func png(image: CGImage, document: MoonDocument, scene: AnnotationScene? = nil, to url: URL) throws {
        guard let space = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: image.width, height: image.height,
                                      bitsPerComponent: 8, bytesPerRow: 0, space: space,
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            throw MoonError.invalid("没有足够的内存来导出原尺寸照片。")
        }
        context.translateBy(x: 0, y: CGFloat(image.height))
        context.scaleBy(x: 1, y: -1)
        let graphics = NSGraphicsContext(cgContext: context, flipped: true)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = graphics
        AnnotationRenderer.draw(image: image, document: document, context: context, scene: scene)
        NSGraphicsContext.restoreGraphicsState()
        guard let output = context.makeImage() else { throw MoonError.invalid("导出图像失败。") }
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else {
            throw MoonError.invalid("无法创建 PNG 文件。")
        }
        CGImageDestinationAddImage(destination, output, nil)
        guard CGImageDestinationFinalize(destination) else { throw MoonError.invalid("PNG 编码失败。") }
        try (data as Data).write(to: url, options: .atomic)
    }
}

public enum AnnotationRenderer {
    public static func configureCaption(_ annotation: Annotation, _ feature: Feature, _ document: MoonDocument) -> Annotation { SceneRenderer.configureCaption(annotation, feature: feature, document: document) }
    public static func placementBounds(_ annotation: Annotation, _ document: MoonDocument) -> CGRect { SceneRenderer.labelBounds(annotation, document: document) }
    public static func svg(image: CGImage, document: MoonDocument, scene: AnnotationScene?, to url: URL) throws { try SceneRenderer.svg(image: image, document: document, scene: scene, to: url) }
    public static func color(_ hex: String) -> NSColor {
        let value = UInt32(hex.dropFirst(), radix: 16) ?? 0xF2E9D8
        return NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255,
                       green: CGFloat((value >> 8) & 255) / 255,
                       blue: CGFloat(value & 255) / 255, alpha: 1)
    }
    public static func attributes(size: Double, color: String) -> [NSAttributedString.Key: Any] {
        [.font: NSFont.systemFont(ofSize: size, weight: .semibold),
         .foregroundColor: self.color(color), .strokeColor: NSColor.black.withAlphaComponent(0.9),
         .strokeWidth: -3.5]
    }
    public static func measure(_ text: String, _ size: Double) -> (Double, Double) {
        let rect = (text as NSString).boundingRect(with: NSSize(width: 100_000, height: 100_000),
                                                 options: [.usesLineFragmentOrigin, .usesFontLeading],
                                                 attributes: attributes(size: size, color: "#FFFFFF"))
        return (ceil(rect.width) + 3, ceil(rect.height) + 2)
    }
    public static func bounds(_ annotation: Annotation, settings: EditorSettings) -> CGRect {
        let (width, height) = measure(annotation.text, settings.fontSize)
        return CGRect(x: annotation.position.x, y: annotation.position.y, width: width, height: height)
    }
    public static func draw(image: CGImage, document: MoonDocument, context: CGContext, scene: AnnotationScene? = nil) {
        SceneRenderer.draw(image: image, document: document, scene: scene, context: context)
    }
}
