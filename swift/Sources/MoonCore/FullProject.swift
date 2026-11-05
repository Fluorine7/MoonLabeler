// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CoreGraphics

public enum JSONValue: Codable, Equatable, Sendable {
    case null, bool(Bool), number(Double), string(String), array([JSONValue]), object([String: JSONValue])
    public init(from decoder: Decoder) throws {
        let box = try decoder.singleValueContainer()
        if box.decodeNil() { self = .null }
        else if let value = try? box.decode(Bool.self) { self = .bool(value) }
        else if let value = try? box.decode(Double.self) { self = .number(value) }
        else if let value = try? box.decode(String.self) { self = .string(value) }
        else if let value = try? box.decode([JSONValue].self) { self = .array(value) }
        else { self = .object(try box.decode([String: JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var box = encoder.singleValueContainer()
        switch self {
        case .null: try box.encodeNil()
        case .bool(let value): try box.encode(value)
        case .number(let value): try box.encode(value)
        case .string(let value): try box.encode(value)
        case .array(let value): try box.encode(value)
        case .object(let value): try box.encode(value)
        }
    }
    public var object: [String: JSONValue] { if case .object(let value) = self { return value }; return [:] }
    public var array: [JSONValue] { if case .array(let value) = self { return value }; return [] }
    public var string: String? { if case .string(let value) = self { return value }; return nil }
    public var number: Double? { if case .number(let value) = self { return value }; return nil }
    public var bool: Bool? { if case .bool(let value) = self { return value }; return nil }
    public static func encode<T: Encodable>(_ value: T) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value))
    }
    public func decode<T: Decodable>(_ type: T.Type) throws -> T {
        try JSONDecoder().decode(type, from: JSONEncoder().encode(self))
    }
}

public struct ProjectStyle: Codable, Equatable, Sendable {
    public var values: [String: JSONValue]
    public init(_ values: [String: JSONValue] = [:]) { self.values = values }
    public func number(_ key: String, _ fallback: Double) -> Double { values[key]?.number ?? fallback }
    public func bool(_ key: String, _ fallback: Bool = false) -> Bool { values[key]?.bool ?? fallback }
    public func string(_ key: String, _ fallback: String = "") -> String { values[key]?.string ?? fallback }
    public mutating func set(_ key: String, _ value: Double) { values[key] = .number(value) }
    public mutating func set(_ key: String, _ value: Bool) { values[key] = .bool(value) }
    public mutating func set(_ key: String, _ value: String) { values[key] = .string(value) }
    public var art: String { string("art_style", "standard") }
    public var isArt: Bool { art != "standard" }
    public var fontFamily: String { string("font_family") }
    public var preferredLabelFamily: String { isArt ? "" : fontFamily }
    public var threshold: Int? { values["map_light_threshold"]?.number.map(Int.init) }
    public var contourInterval: Double? { values["contour_interval"]?.number }
    public var contourEnabled: Bool { bool("contour_enabled") }
    public var elevationEnabled: Bool { bool("elevation_enabled") }
    public var litMapOnly: Bool { bool("map_light_mask") }
    public var illuminatedOnly: Bool { bool("illuminated_only", true) }

    public mutating func applyArt(_ name: String) {
        set("art_style", name)
        if name == "standard" {
            for key in ["elevation_enabled", "contour_enabled", "terminator_enabled", "map_light_mask"] { set(key, false) }
            set("grid_spacing", 0.0)
            return
        }
        let palettes = ["manuscript": "antique", "topographic": "wilderness", "cyanotype": "cyanotype",
                        "copperplate": "copperplate", "inkwash": "inkwash", "redalert": "redalert"]
        set("elevation_palette", palettes[name] ?? "terrain")
        set("elevation_enabled", true); set("contour_enabled", true); set("map_light_mask", true)
        let opacity: [String: Double] = ["manuscript": 0.72, "topographic": 1, "cyanotype": 0.9,
                                       "copperplate": 0.9, "inkwash": 0.78, "redalert": 1]
        set("elevation_opacity", opacity[name] ?? 0.35)
        let contourOpacity: [String: Double] = ["manuscript": 0.48, "topographic": 0.75, "cyanotype": 0.55,
                                              "copperplate": 0.50, "inkwash": 0.62, "redalert": 0.32]
        set("contour_opacity", contourOpacity[name] ?? 0.55)
    }
}

public struct ControlPoint: Codable, Identifiable, Equatable, Sendable {
    public var id: String
    public var pixel: [Double]
    public var enabled: Bool?
    public var source: String?
    public init(id: String, point: PixelPoint, enabled: Bool = true, source: String = "manual") {
        self.id = id; pixel = [point.x, point.y]; self.enabled = enabled; self.source = source
    }
    public var point: PixelPoint { PixelPoint(pixel[0], pixel[1]) }
}

public struct MaskStroke: Codable, Equatable, Sendable {
    public var kind: String
    public var points: [[Double]]
    public var radius: Double?
    public init(kind: String, points: [PixelPoint], radius: Double = 25) {
        self.kind = kind; self.points = points.map { [$0.x, $0.y] }; self.radius = radius
    }
}
public struct RecognitionMask: Codable, Equatable, Sendable {
    public var enabled = true
    public var operations: [MaskStroke] = []
    public init() {}

    public func raster(width: Int, height: Int, originalWidth: Int, originalHeight: Int, padding: Double = 0) -> [UInt8] {
        var data = [UInt8](repeating: 255, count: width * height)
        guard enabled, !operations.isEmpty else { return data }
        data.withUnsafeMutableBytes { bytes in
            guard let context = CGContext(data: bytes.baseAddress, width: width, height: height, bitsPerComponent: 8,
                                          bytesPerRow: width, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: 0) else { return }
            context.translateBy(x: 0, y: Double(height)); context.scaleBy(x: 1, y: -1)
            context.scaleBy(x: Double(width) / Double(originalWidth), y: Double(height) / Double(originalHeight))
            for stroke in operations {
                let points = stroke.points.filter { $0.count == 2 && $0.allSatisfy(\.isFinite) }
                guard let first = points.first else { continue }
                context.setFillColor(gray: stroke.kind == "erase" ? 1 : 0, alpha: 1)
                context.setStrokeColor(gray: stroke.kind == "erase" ? 1 : 0, alpha: 1)
                context.beginPath(); context.move(to: CGPoint(x: first[0], y: first[1]))
                for point in points.dropFirst() { context.addLine(to: CGPoint(x: point[0], y: point[1])) }
                if stroke.kind == "polygon" { context.closePath(); context.fillPath() }
                else {
                    let radius = max(0.5, (stroke.radius ?? 25) + (stroke.kind == "erase" ? -padding : padding))
                    context.setLineCap(.round); context.setLineJoin(.round); context.setLineWidth(radius * 2); context.strokePath()
                    context.fillEllipse(in: CGRect(x: first[0] - radius, y: first[1] - radius, width: radius * 2, height: radius * 2))
                }
            }
        }
        return data
    }
}

public struct ProjectState: Codable, Equatable, Sendable {
    public var utc = ""
    public var geometry: MoonGeometry?
    public var latitude: Double?
    public var longitude: Double?
    public var captureMode = "auto"
    public var projectionSurface = "sphere"
    public var anchors: [ControlPoint] = []
    public var recognitionMask = RecognitionMask()
    public var terrainPath = ""
    public var terrainSettings = ProjectStyle()
    public var style = ProjectStyle()
    public var legacy: [String: JSONValue] = [:]
    public var craterDetection: ProjectStyle {
        get { ProjectStyle(legacy["crater_detection"]?.object ?? [:]) }
        set { legacy["crater_detection"] = .object(newValue.values) }
    }
    public init() {}
    public func validate() throws {
        try geometry?.validate()
        if let value = legacy["crater_detection"], case .object = value {
            let limits: [String: ClosedRange<Double>] = ["min_radius": 3...4000, "max_radius": 3...4000, "sensitivity": 0...100, "max_candidates": 1...500]
            for (key, range) in limits {
                guard let stored = value.object[key] else { continue }
                guard let number = stored.number, number.isFinite, range.contains(number) else { throw MoonError.invalid("候选检测设置无效。") }
            }
        }
        guard latitude.map({ $0.isFinite && (-90...90).contains($0) }) ?? true,
              longitude.map({ $0.isFinite && (-180...180).contains($0) }) ?? true,
              anchors.count <= 10_000, anchors.allSatisfy({ $0.pixel.count == 2 && $0.pixel.allSatisfy(\.isFinite) }),
              recognitionMask.operations.count <= 10_000,
              recognitionMask.operations.allSatisfy({ stroke in
                  stroke.points.count <= 100_000 && stroke.points.allSatisfy { $0.count == 2 && $0.allSatisfy(\.isFinite) } &&
                  (stroke.radius.map { $0.isFinite && (0...100_000).contains($0) } ?? true)
              }) else { throw MoonError.invalid("工程中的拍摄地点、参考点或排除区域无效。") }
        let ranges: [String: ClosedRange<Double>] = ["font_percent": 0.000001...100, "font_step_percent": 0...100,
            "label_opacity": 0...1, "grid_opacity": 0...1, "elevation_opacity": 0...1, "contour_opacity": 0...1,
            "terminator_opacity": 0...1, "grid_spacing": 0...90, "map_light_threshold": 0...255, "contour_interval": 0.25...2]
        for (key, range) in ranges {
            guard let value = style.values[key], value != .null, value != .string("auto") else { continue }
            guard let number = value.number, number.isFinite, range.contains(number) else { throw MoonError.invalid("工程样式 \(key) 无效。") }
        }
        if let family = style.values["font_family"], family.string == nil {
            throw MoonError.invalid("工程的标注字体名称无效。")
        }
        for key in ["legend_position", "overview_position"] {
            if let value = style.values[key], value != .null {
                let numbers = value.array.compactMap(\.number)
                guard numbers.count == 2, numbers.allSatisfy(\.isFinite) else { throw MoonError.invalid("图例或示意图的位置无效。") }
            }
        }
        for key in ["color", "landing_color"] {
            if let value = style.values[key] { guard let text = value.string, text.range(of: "^#[0-9A-Fa-f]{6}$", options: .regularExpression) != nil else { throw MoonError.invalid("工程颜色无效。") } }
        }
    }
}

public extension MoonDocument {
    var state: ProjectState {
        get { projectState ?? ProjectState() }
        set { projectState = newValue }
    }
    var style: ProjectStyle {
        get { state.style }
        set { var next = state; next.style = newValue; state = next }
    }
    mutating func changeStyle(_ change: (inout ProjectStyle) -> Void) {
        var next = style; change(&next); style = next
    }
    var effectiveGeometry: MoonGeometry? { calibration?.geometry ?? state.geometry }
    mutating func applyIdentification(_ result: IdentificationResult) throws {
        calibration = result.calibration
        var next = state
        next.geometry = result.calibration.geometry
        next.utc = result.calibration.geometry.utc
        next.projectionSurface = result.details["relief_aware"]?.bool == true ? "terrain" : "sphere"
        // These samples belong to the previous pose; the scene builder will
        // regenerate them for the newly accepted calibration.
        for key in ["annotation_relief", "terrain_rims"] { next.legacy.removeValue(forKey: key) }
        var recognition: [String: JSONValue] = ["method": .string(result.method), "rms_px": .number(result.rms),
            "image_inliers": .number(Double(result.matches)), "coverage": .number(result.coverage), "refinement": .object(result.details)]
        recognition["candidate_count"] = result.candidates.isEmpty ? .null : .number(Double(result.candidates.count))
        recognition["matched_names"] = .array(result.identifiedCraters.map { .string($0.feature.name) })
        let previousAuto = Dictionary(next.anchors.filter { $0.source == "automatic" }.map { ($0.id, $0.enabled != false) }, uniquingKeysWith: { _, last in last })
        next.anchors.removeAll { $0.source == "automatic" }
        var existing = Set(next.anchors.map(\.id)), labels = next.legacy["labels"]?.object ?? [:]
        for match in result.identifiedCraters {
            if existing.insert(match.feature.id).inserted {
                next.anchors.append(ControlPoint(id: match.feature.id, point: match.center, enabled: previousAuto[match.feature.id] ?? true, source: "automatic"))
            }
            if match.feature.kind == "Crater, craters" {
                var edit = labels[match.feature.id]?.object ?? [:]; edit["force"] = .bool(true); labels[match.feature.id] = .object(edit)
            }
        }
        next.legacy["labels"] = .object(labels)
        recognition["lens_distortion"] = try result.calibration.distortion.map { try JSONValue.encode($0) }
        next.legacy["automatic_recognition"] = .object(recognition)
        state = next
        // Match Python accept_identification: reveal smaller formations after
        // a validated image fit using the same scale-dependent cutoff.
        let scale = hypot(result.calibration.matrix[0][0], result.calibration.matrix[1][0])
        settings.minimumDiameter = result.matches > 0 && scale > 0
            ? max(5, min(settings.minimumDiameter, 15 * moonRadius / scale))
            : min(settings.minimumDiameter, 5)
    }
    func referenceReport(features: [Feature]) -> CalibrationReport? {
        guard let calibration else { return nil }
        let byID = Dictionary(features.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let residuals = state.anchors.filter { $0.enabled != false }.map { anchor -> Double in
            guard let feature = byID[anchor.id] else { return .nan }
            let p = calibration.project(feature).point; return hypot(p.x - anchor.point.x, p.y - anchor.point.y)
        }
        guard !residuals.isEmpty else { return nil }
        let finite = residuals.filter(\.isFinite)
        return CalibrationReport(matrix: calibration.matrix, rms: finite.isEmpty ? 0 : sqrt(finite.map { $0 * $0 }.reduce(0, +) / Double(finite.count)), residuals: residuals, checkErrors: [], suspect: nil)
    }
    mutating func invalidateRegistration(clearGeometry: Bool = true) {
        var next = state
        if clearGeometry { next.geometry = nil; next.legacy.removeValue(forKey: "geometry") }
        for key in ["matrix", "automatic_recognition", "annotation_relief", "terrain_rims", "labels"] { next.legacy.removeValue(forKey: key) }
        next.projectionSurface = "sphere"; state = next; calibration = nil
        annotations.removeAll { $0.featureID != nil }
    }
}

public enum ProjectCompatibility {
    public static func captureEdits(_ document: inout MoonDocument) {
        var labels = document.state.legacy["labels"]?.object ?? [:]
        for annotation in document.annotations {
            guard let id = annotation.featureID else { continue }
            var edit = labels[id]?.object ?? [:]
            if annotation.hasTextEdit { edit["text"] = .string(annotation.text) }
            if annotation.hasPositionEdit { edit["position"] = .array([.number(annotation.position.x), .number(annotation.position.y)]) }
            edit["hidden"] = .bool(annotation.hidden)
            if !annotation.automatic { edit["force"] = .bool(true) }
            labels[id] = .object(edit)
        }
        document.state.legacy["labels"] = .object(labels)
    }
    public static func labelOverrides(_ document: MoonDocument) -> [String: LegacyOverride] {
        (document.state.legacy["labels"]?.object ?? [:]).mapValues { value in
            let edit = value.object, point = edit["position"]?.array.compactMap(\.number) ?? []
            return LegacyOverride(text: edit["text"]?.string, position: point.count == 2 ? PixelPoint(point[0], point[1]) : nil,
                                  hidden: edit["hidden"]?.bool ?? false, force: edit["force"]?.bool ?? false)
        }
    }
    public static func resetAnnotations(_ document: inout MoonDocument, layoutOnly: Bool) {
        var labels = document.state.legacy["labels"]?.object ?? [:]
        if layoutOnly {
            for id in labels.keys { var value = labels[id]!.object; value.removeValue(forKey: "position"); labels[id] = .object(value) }
            for i in document.annotations.indices where document.annotations[i].featureID != nil {
                let edited = document.annotations[i].hasTextEdit
                document.annotations[i].positionEdited = false; document.annotations[i].textEdited = edited
                document.annotations[i].automatic = !edited && !document.annotations[i].hidden && !document.annotations[i].hasAnchorEdit
            }
        } else { labels = [:]; document.annotations = [] }
        document.state.legacy["labels"] = .object(labels)
    }
    public static func importState(root: [String: JSONValue], relativeTo url: URL) throws -> ProjectState {
        var state = ProjectState(); state.legacy = root
        state.utc = root["utc"]?.string ?? ""
        state.captureMode = root["capture_mode"]?.string ?? "auto"
        let refined = root["automatic_recognition"]?.object["refinement"]?.object["relief_aware"]?.bool == true
        state.projectionSurface = root["projection_surface"]?.string ?? (refined ? "terrain" : "sphere")
        if let geometry = root["geometry"], geometry != .null { state.geometry = try geometry.decode(MoonGeometry.self); try state.geometry?.validate() }
        if let anchors = root["anchors"] { state.anchors = try anchors.decode([ControlPoint].self) }
        if let mask = root["recognition_mask"] { state.recognitionMask = try mask.decode(RecognitionMask.self) }
        let observer = root["observer"]?.object ?? [:]
        state.latitude = observer["latitude"]?.number; state.longitude = observer["longitude"]?.number
        let terrain = root["terrain"]?.object ?? [:]
        if let path = terrain["dem_path"]?.string, !path.isEmpty { state.terrainPath = ProjectIO.resolve(path, relativeTo: url).path }
        state.terrainSettings = ProjectStyle(terrain["settings"]?.object ?? [:])
        if state.terrainSettings.values["center_lat"] == nil, let id = state.terrainSettings.values["center_id"]?.string,
           let feature = try Catalog.load().first(where: { $0.id == id }) {
            state.terrainSettings.set("center_lat", feature.latitude); state.terrainSettings.set("center_lon", feature.longitude)
        }
        state.style = ProjectStyle(root["style"]?.object ?? [:])
        // 0.12.1 enables paths for new photos but keeps older projects' layout.
        if state.style.values["follow_feature_paths"] == nil { state.style.set("follow_feature_paths", false) }
        for anchor in state.anchors {
            guard anchor.pixel.count == 2, anchor.pixel.allSatisfy(\.isFinite) else { throw MoonError.invalid("工程中的参考点无效。") }
        }
        try state.validate(); return state
    }

    public static func writeLegacy(_ document: MoonDocument, to url: URL) throws {
        try document.validate()
        var root = document.state.legacy
        root["format"] = .string("MoonLabeler"); root["version"] = .number(2)
        root["image_path"] = .string(document.imagePath)
        root["image_size"] = .array([.number(Double(document.imageWidth)), .number(Double(document.imageHeight))])
        root["utc"] = .string(document.state.utc)
        root["capture_mode"] = .string(document.state.captureMode)
        root["projection_surface"] = .string(document.state.projectionSurface)
        root["geometry"] = try document.effectiveGeometry.map { try JSONValue.encode($0) } ?? .null
        root["matrix"] = try document.calibration.map { try JSONValue.encode($0.matrix) } ?? .null
        root["anchors"] = try JSONValue.encode(document.state.anchors)
        root["recognition_mask"] = try JSONValue.encode(document.state.recognitionMask)
        root["observer"] = .object(["latitude": document.state.latitude.map(JSONValue.number) ?? .null,
                                     "longitude": document.state.longitude.map(JSONValue.number) ?? .null])
        root["terrain"] = .object(["dem_path": .string(document.state.terrainPath), "settings": .object(document.state.terrainSettings.values)])
        var style = document.style.values
        style["font_size"] = .number(document.settings.fontSize); style["color"] = .string(document.settings.color)
        style["language"] = .string(document.settings.language.rawValue); style["min_diameter"] = .number(document.settings.minimumDiameter)
        style["max_labels"] = .number(Double(document.settings.maximumLabels))
        style["kind"] = document.settings.matchesAllKinds ? .string("全部") : .array(document.settings.kinds.map(JSONValue.string))
        root["style"] = .object(style)
        var labels = root["labels"]?.object ?? [:]
        for annotation in document.annotations {
            guard let id = annotation.featureID else { continue }
            var edit = labels[id]?.object ?? [:]
            edit["hidden"] = .bool(annotation.hidden)
            if annotation.hasTextEdit { edit["text"] = .string(annotation.text) } else { edit.removeValue(forKey: "text") }
            if annotation.hasPositionEdit { edit["position"] = .array([.number(annotation.position.x), .number(annotation.position.y)]) } else { edit.removeValue(forKey: "position") }
            if !annotation.automatic { edit["force"] = .bool(true) }
            labels[id] = .object(edit)
        }
        root["labels"] = .object(labels)
        if let distortion = document.calibration?.distortion {
            var recognition = root["automatic_recognition"]?.object ?? [:]
            recognition["lens_distortion"] = try JSONValue.encode(distortion)
            root["automatic_recognition"] = .object(recognition)
        } else if root["automatic_recognition"] != nil {
            var recognition = root["automatic_recognition"]!.object; recognition.removeValue(forKey: "lens_distortion")
            root["automatic_recognition"] = .object(recognition)
        }
        root["crater_detection"] = root["crater_detection"] ?? .object([:])
        root["automatic_recognition"] = root["automatic_recognition"] ?? .object([:])
        root["swift_annotations"] = try JSONValue.encode(document.annotations.filter { $0.featureID == nil })
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(JSONValue.object(root)).write(to: url, options: .atomic)
    }
}
