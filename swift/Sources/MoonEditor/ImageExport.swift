// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import MoonCore

enum ImageExport {
    enum Format: Sendable { case png, svg }
    typealias Writer = @Sendable (Format, CGImage, MoonDocument, AnnotationScene?, URL) throws -> Void
    static func write(_ format: Format, image: CGImage, document: MoonDocument, scene: AnnotationScene?, to url: URL) throws {
        switch format {
        case .png: try PhotoIO.png(image: image, document: document, scene: scene, to: url)
        case .svg: try SceneRenderer.svg(image: image, document: document, scene: scene, to: url)
        }
    }
}

@MainActor extension EditorModel {
    func beginExport(_ format: ImageExport.Format, image: CGImage, document: MoonDocument, scene: AnnotationScene?, to url: URL) {
        guard !busy else { return }
        if url.resolvingSymlinksInPath().standardizedFileURL == URL(fileURLWithPath: document.imagePath).resolvingSymlinksInPath().standardizedFileURL {
            show(MoonError.invalid("请换一个导出文件名，保留原始照片。")); return
        }
        let writer = exportWriter
        busy = true; taskStatus = format == .png ? "导出 PNG" : "导出 SVG"
        operation = Task {
            defer { busy = false; operation = nil; taskStatus = "" }
            do {
                try await CancellableExport.run(to: url) { temporary in try writer(format, image, document, scene, temporary) }
                status = format == .png ? "已导出 \(image.width) × \(image.height) PNG · \(url.lastPathComponent)" : "SVG · \(url.lastPathComponent)"
            } catch is CancellationError { status = "已中止导出，保留原有文件。" }
            catch { show(error) }
        }
    }
}
