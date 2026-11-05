#!/usr/bin/env swift
// Run from any directory after changing the shared catalogue or demo.
import Foundation

let package = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let repo = package.deletingLastPathComponent()
let destination = package.appendingPathComponent("Sources/MoonCore/Resources", isDirectory: true)
func object(_ path: String) throws -> [String: Any] {
    try JSONSerialization.jsonObject(with: Data(contentsOf: repo.appendingPathComponent(path))) as! [String: Any]
}
let catalog = try object("moonlabeler/data/catalog.json")["features"] as! [[String: Any]]
let primary = try object("moonlabeler/data/lunar_chinese_names.json")["names"] as! [String: [String: Any]]
let fallback = try object("moonlabeler/data/chinese_names.json")["names"] as! [String: [String: Any]]
let features = catalog.map { feature -> [String: Any] in
    let name = feature["name"] as! String
    let components = name.components(separatedBy: " "), suffix = components.last ?? ""
    let satellite = suffix.count == 1 && suffix.range(of: "^[A-Z]$", options: .regularExpression) != nil
    let parent = satellite ? components.dropLast().joined(separator: " ") : name
    func entry(_ table: [String: [String: Any]], _ key: String) -> String? {
        guard let zh = table[key]?["zh"] as? String, zh.range(of: "[\\u3400-\\u9fff]", options: .regularExpression) != nil else { return nil }; return zh
    }
    var chinese = entry(primary, name) ?? (satellite ? entry(primary, parent).map { $0 + " " + suffix } : nil) ?? entry(fallback, name) ?? (satellite ? entry(fallback, parent).map { $0 + " " + suffix } : nil) ?? ""
    if satellite {
        chinese = chinese.replacingOccurrences(of: "[", with: "").replacingOccurrences(of: "]", with: "")
        chinese = chinese.replacingOccurrences(of: "(?:坑)?\\s*" + suffix + "(?:坑)?$", with: " " + suffix, options: .regularExpression)
    }
    var aliases = Set((feature["name_zh_aliases"] as? [String] ?? []) + [feature["name_zh"] as? String, entry(fallback, name), primary[name]?["term_zh"] as? String, entry(primary, name)].compactMap { $0 })
    if satellite, let old = entry(fallback, parent) { aliases.insert(old + " " + suffix) }
    aliases.remove(chinese); aliases.remove("")
    return ["id": feature["id"]!, "name": name, "chinese": chinese == name ? "" : chinese,
            "latitude": feature["lat"]!, "longitude": feature["lon"]!,
            "diameter": feature["diameter"] ?? 0, "kind": feature["kind"]!, "aliases": aliases.sorted()]
}
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
func writeIfChanged(_ data: Data, _ name: String) throws {
    let url = destination.appendingPathComponent(name)
    if (try? Data(contentsOf: url)) != data { try data.write(to: url, options: .atomic) }
}
try writeIfChanged(JSONSerialization.data(withJSONObject: features, options: [.sortedKeys, .withoutEscapingSlashes]), "catalog.json")
for name in ["demo.moonlabel", "synthetic-moon.png"] {
    try writeIfChanged(Data(contentsOf: repo.appendingPathComponent("examples/" + name)), name)
}
for name in ["feature_paths.json", "landing_sites.json", "moon_albedo_2k.jpg", "ui_en.json", "ui_zh_TW.json",
             "lunar_chinese_names.provenance.json", "moon_albedo_2k.provenance.json"] {
    try writeIfChanged(Data(contentsOf: repo.appendingPathComponent("moonlabeler/data/" + name)), name)
}
let kernels = repo.appendingPathComponent(".cache/ephemeris")
for name in ["de421.bsp", "moon_080317.tf", "pck00008.tpc", "moon_pa_de421_1900-2050.bpc"] {
    if FileManager.default.fileExists(atPath: kernels.appendingPathComponent(name).path) {
        try writeIfChanged(Data(contentsOf: kernels.appendingPathComponent(name)), name)
    }
}
let leapseconds = package.appendingPathComponent(".build/native-deps/naif0012.tls")
if FileManager.default.fileExists(atPath: leapseconds.path) { try writeIfChanged(Data(contentsOf: leapseconds), "naif0012.tls") }
for name in ["ACKNOWLEDGEMENTS.md", "THIRD_PARTY_NOTICES.md"] {
    try writeIfChanged(Data(contentsOf: package.appendingPathComponent(name)), name)
}
print("Prepared \(features.count) lunar names and the demo.")
