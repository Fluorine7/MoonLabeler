// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CoreFoundation

public struct LegacyOverride: Sendable {
    public var text: String?
    public var position: PixelPoint?
    public var hidden: Bool
    public var force: Bool
}

public struct OpenedProject: Sendable {
    public var document: MoonDocument
    public var legacyOverrides: [String: LegacyOverride]?
    public var expectedSize: [Int]?
}

public enum ProjectIO {
    public static func read(_ url: URL) throws -> OpenedProject {
        let data = try Data(contentsOf: url)
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw MoonError.invalid("工程文件需要包含 JSON 对象。")
        }
        if root["format"] as? String == "MoonLabelerSwift" {
            var document = try JSONDecoder().decode(MoonDocument.self, from: data)
            try document.validate()
            document.imagePath = resolve(document.imagePath, relativeTo: url).path
            return OpenedProject(document: document, legacyOverrides: nil,
                                 expectedSize: [document.imageWidth, document.imageHeight])
        }
        guard root["format"] as? String == "MoonLabeler", root["version"] as? Int == 2,
              let imagePath = root["image_path"] as? String, !imagePath.isEmpty else {
            throw MoonError.invalid("请选择 .moonswift 工程或版本 2 的 .moonlabel 工程。")
        }
        var document = MoonDocument(imagePath: resolve(imagePath, relativeTo: url).path)
        document.projectState = try ProjectCompatibility.importState(root: JSONDecoder().decode(JSONValue.self, from: data).object, relativeTo: url)
        if let values = root["swift_annotations"] {
            document.annotations = try JSONDecoder().decode([Annotation].self, from: JSONSerialization.data(withJSONObject: values)).filter { $0.featureID == nil }
        }
        if let g = root["geometry"] as? [String: Any], let m = root["matrix"] as? [[Double]] {
            let geometry = try JSONDecoder().decode(MoonGeometry.self, from: JSONSerialization.data(withJSONObject: g))
            var distortion: LensDistortion?
            if let recognition = root["automatic_recognition"] as? [String: Any],
               let lens = recognition["lens_distortion"] as? [String: Any] {
                distortion = try JSONDecoder().decode(LensDistortion.self, from: JSONSerialization.data(withJSONObject: lens))
            }
            document.calibration = Calibration(geometry: geometry, matrix: m, distortion: distortion)
            try document.calibration?.validate()
        }
        if let style = root["style"] as? [String: Any] {
            document.settings.fontSize = try number(style, "font_size", fallback: 24, range: 1...100_000)
            document.settings.minimumDiameter = try number(style, "min_diameter", fallback: 40, range: 0...4000)
            document.settings.maximumLabels = Int(try number(style, "max_labels", fallback: 40, range: 1...1000))
            if let color = style["color"] as? String,
               color.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil {
                document.settings.color = color
            }
            if let language = style["language"] as? String {
                document.settings.language = NameLanguage(rawValue: language) ?? (language.contains("双语") ? .bilingual : .chinese)
            }
            if let kinds = style["kind"] as? [String] { document.settings.kinds = kinds; document.settings.allKinds = false }
            else if let kind = style["kind"] as? String {
                document.settings.allKinds = kind == "全部"
                document.settings.kinds = kind == "全部" ? [] : [kind]
            }
        }
        var overrides: [String: LegacyOverride] = [:]
        if let labels = root["labels"] as? [String: [String: Any]] {
            for (id, label) in labels {
                var position: PixelPoint?
                if let value = label["position"] {
                    guard let p = value as? [Double], p.count == 2, p.allSatisfy(\.isFinite) else {
                        throw MoonError.invalid("工程中存在无效的标注位置。")
                    }
                    position = PixelPoint(p[0], p[1])
                }
                overrides[id] = LegacyOverride(text: label["text"] as? String, position: position,
                                                hidden: label["hidden"] as? Bool ?? false,
                                                force: label["force"] as? Bool ?? false)
            }
        }
        document.sourceNote = ""
        return OpenedProject(document: document, legacyOverrides: overrides, expectedSize: root["image_size"] as? [Int])
    }

    public static func write(_ document: MoonDocument, to url: URL) throws {
        guard url.pathExtension.lowercased() == "moonswift" else {
            throw MoonError.invalid("Swift 工程请使用 .moonswift 扩展名保存。")
        }
        try document.validate()
        var snapshot = document
        snapshot.imagePath = relativePath(URL(fileURLWithPath: document.imagePath), from: url.deletingLastPathComponent())
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(snapshot).write(to: url, options: .atomic)
    }

    public static func resolve(_ path: String, relativeTo project: URL) -> URL {
        if path.hasPrefix("/") { return URL(fileURLWithPath: path).standardizedFileURL }
        return project.deletingLastPathComponent().appendingPathComponent(path).standardizedFileURL
    }

    private static func relativePath(_ image: URL, from directory: URL) -> String {
        let target = image.standardizedFileURL.pathComponents
        let base = directory.standardizedFileURL.pathComponents
        let shared = zip(target, base).prefix(while: { $0 == $1 }).count
        return (Array(repeating: "..", count: base.count - shared) + target.dropFirst(shared)).joined(separator: "/")
    }

    private static func number(_ values: [String: Any], _ key: String, fallback: Double,
                               range: ClosedRange<Double>) throws -> Double {
        guard let value = values[key] else { return fallback }
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, range.contains(number.doubleValue) else {
            throw MoonError.invalid("工程中的 \(key) 无效。")
        }
        return number.doubleValue
    }
}
