// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import ImageIO
import MoonCore

/// One vector card drives the canvas, PNG and editable SVG decorations.
enum OverviewCard {
    private static let bitmaps = NSCache<NSString, CGImage>()
    struct Ink {
        var border = "#3b4750", grid = "#bac6d3", text = "#d7dfdd", muted = "#80928f", accent = "#efb85f"
        var serif = false
        static func resolve(_ style: String) -> Ink {
            switch style {
            case "manuscript": return Ink(border: "#9e814c", grid: "#d4bd83", text: "#f4e0a8", muted: "#b7a57e", accent: "#f2bd61", serif: true)
            case "topographic": return Ink(border: "#85805a", grid: "#e1d29d", text: "#f3dfa0", muted: "#b4b38d", accent: "#8bd9d0")
            case "cyanotype": return Ink(border: "#4b8daf", grid: "#bee5ed", text: "#e3f2ee", muted: "#91bdcc", accent: "#eed29c")
            case "copperplate": return Ink(border: "#bc8969", grid: "#d9c7a3", text: "#f2dfbf", muted: "#bea98c", accent: "#f1ac78", serif: true)
            case "inkwash": return Ink(border: "#81918b", grid: "#c3d0c9", text: "#eee6d5", muted: "#a6b3aa", accent: "#e5866c", serif: true)
            case "redalert": return Ink(border: "#87935d", grid: "#d4d8a2", text: "#f4eccb", muted: "#abb58a", accent: "#f2bd68")
            default: return Ink()
            }
        }
    }
    private static let images: NSCache<NSString, NSImage> = {
        let cache = NSCache<NSString, NSImage>()
        // Original plus six art styles fit without retaining every retired
        // scene's SVG source (and any AppKit representations it owns).
        cache.countLimit = 8
        return cache
    }()
    static func clearCache() { images.removeAllObjects(); bitmaps.removeAllObjects() }
    static var language: String { UserDefaults.standard.string(forKey: "swift-ui-language") ?? "简体中文" }
    static func markup(_ model: PhotoOverview, style: String) throws -> String {
        let ink = Ink.resolve(style), panel = "#080808", original = style == "standard"
        let family = ink.serif ? "Baskerville,Songti SC,serif" : "sans-serif"
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil) else { throw MoonError.invalid("无法生成示意图。") }
        CGImageDestinationAddImage(destination, model.image.cgImage, nil)
        guard CGImageDestinationFinalize(destination) else { throw MoonError.invalid("无法生成示意图。") }
        func path(_ points: [PixelPoint]) -> String { points.enumerated().map { "\($0.offset == 0 ? "M" : "L") \($0.element.x),\($0.element.y)" }.joined(separator: " ") }
        let grid = model.grid.map { path($0.points) }.joined(separator: " ")
        let scale = 300.0 / Double(model.image.width), center = Double(model.image.width - 1) / 2, rim = Double(model.image.width) * 0.47
        var parts = ["<rect class=\"overview-card\" x=\"1\" y=\"1\" width=\"318\" height=\"364\" rx=\"12\" fill=\"\(panel)\" fill-opacity=\".88\" stroke=\"\(ink.border)\" stroke-width=\"1.2\"/>"]
        if ink.serif { parts.append("<rect x=\"6\" y=\"6\" width=\"308\" height=\"354\" rx=\"8\" fill=\"none\" stroke=\"\(ink.border)\" stroke-opacity=\".45\" stroke-width=\".65\"/>") }
        if style == "cyanotype" { parts.append("<path d=\"M 18,30 V 18 H 30 M 290,18 H 302 V 30\" fill=\"none\" stroke=\"\(ink.grid)\" stroke-width=\"1.2\"/>") }
        parts += ["<g transform=\"translate(10 10) scale(\(scale))\">",
                  "<image width=\"\(model.image.width)\" height=\"\(model.image.height)\" xlink:href=\"data:image/png;base64,\(data.base64EncodedString())\"/>",
                  "<path d=\"\(grid)\" fill=\"none\" stroke=\"\(panel)\" stroke-opacity=\".65\" stroke-width=\"4\"/>",
                  "<path d=\"\(grid)\" fill=\"none\" stroke=\"\(ink.grid)\" stroke-opacity=\".8\" stroke-width=\"2.1\"/>",
                  "<circle cx=\"\(center)\" cy=\"\(center)\" r=\"\(rim)\" fill=\"none\" stroke=\"\(original ? "#757e73" : ink.muted)\" stroke-width=\"1.1\"/>"]
        for polygon in model.footprint {
            let outline = path(polygon) + " Z"
            parts += ["<path class=\"photo-footprint\" d=\"\(outline)\" fill=\"\(original ? "none" : ink.accent)\" fill-opacity=\".1\" stroke=\"\(original ? "#493b26" : panel)\" stroke-width=\"4.5\" stroke-linejoin=\"round\"/>",
                      "<path d=\"\(outline)\" fill=\"none\" stroke=\"\(ink.accent)\" stroke-width=\"2.5\" stroke-linejoin=\"round\"/>"]
        }
        parts.append("</g>")
        for (name, letter, point, sign) in [("north", "N", model.north, 1.0), ("south", "S", model.south, -1.0)] {
            let dx = model.northBearing.x * sign, dy = model.northBearing.y * sign
            let x = point.map { 10 + $0.x * scale } ?? (160 + 138 * dx), y = point.map { 10 + $0.y * scale } ?? (160 + 138 * dy)
            let tx = min(296, max(24, x + 17)), ty = min(298, max(22, y))
            parts.append("<g id=\"overview-\(name)-pole\" data-placement=\"\(point == nil ? "direction" : "surface")\">")
            if point != nil { parts.append("<circle cx=\"\(x)\" cy=\"\(y)\" r=\"3\" fill=\"\(ink.text)\" stroke=\"\(panel)\" stroke-width=\"1.2\"/>") }
            else {
                let arrow = "M \(x - 3 * dx + 4 * dy),\(y - 3 * dy - 4 * dx) L \(x + 3 * dx),\(y + 3 * dy) L \(x - 3 * dx - 4 * dy),\(y - 3 * dy + 4 * dx)"
                for (color, width) in [(panel, 4.0), (ink.text, 1.7)] { parts.append("<path d=\"\(arrow)\" fill=\"none\" stroke=\"\(color)\" stroke-width=\"\(width)\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>") }
            }
            parts += ["<rect x=\"\(tx - 10)\" y=\"\(ty - 10)\" width=\"20\" height=\"20\" rx=\"4\" fill=\"\(panel)\" fill-opacity=\".94\" stroke=\"\(ink.border)\" stroke-width=\".65\"/>",
                      "<text x=\"\(tx)\" y=\"\(ty + 5)\" text-anchor=\"middle\" fill=\"\(ink.text)\" font-family=\"\(family)\" font-size=\"15\" font-weight=\"700\">\(letter)</text></g>"]
        }
        let lat = model.footprint.isEmpty ? "—" : String(format: "%.2f° %@", abs(model.latitude), model.latitude >= 0 ? "N" : "S")
        let lon = model.footprint.isEmpty ? "—" : String(format: "%.2f° %@", abs(model.longitude), model.longitude >= 0 ? "E" : "W")
        let label = InterfaceText.translate("取景范围", language: language)
        parts += ["<path d=\"M 14,312 H 306\" stroke=\"\(ink.border)\" stroke-width=\".7\"/>",
                  "<g fill=\"\(ink.text)\" font-family=\"\(family)\"><path d=\"M 20,326 H 34\" stroke=\"\(ink.accent)\" stroke-width=\"1.7\"/>",
                  "<text x=\"42\" y=\"330\" font-size=\"11\">\(label)</text>",
                  "<text x=\"20\" y=\"351\" font-size=\"8\" fill=\"\(ink.muted)\">LAT</text><text x=\"47\" y=\"352\" font-size=\"12\">\(lat)</text>",
                  "<text x=\"172\" y=\"351\" font-size=\"8\" fill=\"\(ink.muted)\">LON</text><text x=\"203\" y=\"352\" font-size=\"12\">\(lon)</text></g>"]
        return parts.joined()
    }
    static func image(_ model: PhotoOverview, style: String, sceneID: UUID) throws -> NSImage {
        let key = "\(sceneID)|\(style)|\(language)" as NSString
        if let image = images.object(forKey: key) { return image }
        let svg = "<svg xmlns=\"http://www.w3.org/2000/svg\" xmlns:xlink=\"http://www.w3.org/1999/xlink\" width=\"320\" height=\"366\" viewBox=\"0 0 320 366\">" + (try markup(model, style: style)) + "</svg>"
        guard let image = NSImage(data: Data(svg.utf8)) else { throw MoonError.invalid("无法读取示意图。") }
        images.setObject(image, forKey: key); return image
    }
    static func bitmap(_ model: PhotoOverview, style: String, sceneID: UUID, width: Int, height: Int) throws -> CGImage {
        let key = "\(sceneID)|\(style)|\(language)|\(width)x\(height)" as NSString
        if let result = bitmaps.object(forKey: key) { return result }
        guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { throw MoonError.invalid("无法绘制示意图。") }
        context.translateBy(x: 0, y: CGFloat(height)); context.scaleBy(x: CGFloat(width) / 320, y: -CGFloat(height) / 366)
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
        defer { NSGraphicsContext.restoreGraphicsState() }
        try image(model, style: style, sceneID: sceneID).draw(in: CGRect(x: 0, y: 0, width: 320, height: 366),
            from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
        guard let result = context.makeImage() else { throw MoonError.invalid("无法绘制示意图。") }
        bitmaps.totalCostLimit = 64 * 1024 * 1024
        bitmaps.setObject(result, forKey: key, cost: result.bytesPerRow * result.height)
        return result
    }
}
