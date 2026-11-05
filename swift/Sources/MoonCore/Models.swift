// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

public struct PixelPoint: Codable, Equatable, Sendable {
    public var x: Double
    public var y: Double
    public init(_ x: Double, _ y: Double) { self.x = x; self.y = y }
    public var isFinite: Bool { x.isFinite && y.isFinite }
}

public struct Feature: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let chinese: String
    public let latitude: Double
    public let longitude: Double
    public let diameter: Double
    public let kind: String
    public var aliases: [String]?
    public var searchText: String { ([name, chinese, id] + (aliases ?? [])).map { $0 + " " + ChineseConversion.traditional($0) }.joined(separator: " ") }

    public func caption(_ language: NameLanguage) -> String {
        switch language {
        case .english: return name
        case .chinese: return chinese.isEmpty ? name : chinese
        case .traditional: return chinese.isEmpty ? name : ChineseConversion.traditional(chinese)
        case .bilingual, .bilingualTraditional:
            let zh = language == .bilingualTraditional ? ChineseConversion.traditional(chinese) : chinese
            return zh.isEmpty || zh == name ? name : "\(zh) · \(name)"
        }
    }
}

public enum NameLanguage: String, Codable, CaseIterable, Sendable {
    case bilingual = "双语", chinese = "中文", english = "英文"
    case bilingualTraditional = "双语（繁体）", traditional = "繁体中文"
}

public struct EditorSettings: Codable, Equatable, Sendable {
    public var fontSize: Double = 24
    public var color: String = "#F2E9D8"
    public var language: NameLanguage = .bilingual
    public var minimumDiameter: Double = 40
    public var maximumLabels: Int = 40
    public var showLeaders = true
    // Keep the precise legacy kind filter when importing a project.
    public var kinds: [String] = []
    // Older native projects used [] for all types. An explicit false preserves
    // Python's distinct empty selection without changing those old projects.
    public var allKinds: Bool?
    public var matchesAllKinds: Bool { allKinds ?? kinds.isEmpty }
    public func includes(kind: String) -> Bool { matchesAllKinds || kinds.contains(kind) }
    public init() {}
}

public struct Annotation: Codable, Identifiable, Equatable, Sendable {
    public var id: UUID
    public var featureID: String?
    public var text: String
    public var anchor: PixelPoint
    public var position: PixelPoint
    public var hidden: Bool
    public var automatic: Bool
    public var textEdited: Bool?
    public var positionEdited: Bool?
    public var anchorEdited: Bool?
    public var visual: AnnotationVisual?
    public var hasTextEdit: Bool { textEdited ?? !automatic }
    public var hasPositionEdit: Bool { positionEdited ?? !automatic }
    public var hasAnchorEdit: Bool { anchorEdited ?? false }

    public init(featureID: String? = nil, text: String, anchor: PixelPoint,
                position: PixelPoint, automatic: Bool = false) {
        id = UUID(); self.featureID = featureID; self.text = text
        self.anchor = anchor; self.position = position
        hidden = false; self.automatic = automatic
        textEdited = !automatic; positionEdited = !automatic; anchorEdited = false
    }
}

public struct MoonDocument: Codable, Equatable, Sendable {
    public var format = "MoonLabelerSwift"
    public var version = 1
    public var imagePath: String
    public var imageWidth = 0
    public var imageHeight = 0
    public var annotations: [Annotation] = []
    public var settings = EditorSettings()
    public var calibration: Calibration?
    public var sourceNote = ""
    public var projectState: ProjectState?
    public init(imagePath: String) { self.imagePath = imagePath }

    public func validate() throws {
        guard format == "MoonLabelerSwift", version == 1 else {
            throw MoonError.invalid("不支持这个 Swift 工程版本。")
        }
        guard !imagePath.isEmpty, imageWidth > 0, imageHeight > 0,
              imageWidth <= 100_000, imageHeight <= 100_000,
              settings.fontSize.isFinite, (1...100_000).contains(settings.fontSize),
              settings.minimumDiameter.isFinite, (0...4000).contains(settings.minimumDiameter),
              (1...1000).contains(settings.maximumLabels),
              settings.color.range(of: "^#[0-9A-Fa-f]{6}$", options: .regularExpression) != nil,
              annotations.count <= 10_000,
              Set(annotations.map(\.id)).count == annotations.count,
              annotations.allSatisfy({ $0.anchor.isFinite && $0.position.isFinite && $0.text.count <= 10_000 }) else {
            throw MoonError.invalid("工程中的尺寸、样式或标注数据无效。")
        }
        try calibration?.validate()
        try projectState?.validate()
    }
}

public enum MoonError: LocalizedError {
    case invalid(String)
    public var errorDescription: String? {
        switch self { case .invalid(let message): return message }
    }
}

public enum Catalog {
    public static var resourceDirectory: URL { Bundle.module.resourceURL! }
    public static func resource(_ name: String, _ extensionName: String) -> URL? {
        Bundle.module.url(forResource: name, withExtension: extensionName)
    }
    public static let commonNames: Set<String> = [
        "Tycho", "Copernicus", "Plato", "Clavius", "Aristarchus", "Kepler", "Gassendi",
        "Mare Imbrium", "Mare Serenitatis", "Mare Tranquillitatis", "Sinus Iridum",
        "Montes Apenninus", "Vallis Alpes", "Ptolemaeus", "Eratosthenes", "Archimedes", "Alphonsus", "Arzachel", "Theophilus", "Cyrillus", "Catharina", "Posidonius", "Langrenus", "Petavius", "Schickard", "Mare Crisium", "Mare Fecunditatis", "Mare Nectaris", "Mare Nubium", "Mare Humorum", "Oceanus Procellarum", "Autolycus", "Timocharis", "Pytheas", "Manilius",
    ]
    public static func load() throws -> [Feature] {
        if let data = try? Data(contentsOf: DataStore.cache.appendingPathComponent("catalog-native.json")), let values = try? JSONDecoder().decode([Feature].self, from: data), !values.isEmpty { return values }
        return try bundled()
    }
    public static func bundled() throws -> [Feature] {
        guard let url = Bundle.module.url(forResource: "catalog", withExtension: "json") else {
            throw MoonError.invalid("应用内的月面地名库缺失，请重新构建应用。")
        }
        return try JSONDecoder().decode([Feature].self, from: Data(contentsOf: url))
    }
    public static var demoURL: URL {
        Bundle.module.url(forResource: "demo", withExtension: "moonlabel")!
    }
}
