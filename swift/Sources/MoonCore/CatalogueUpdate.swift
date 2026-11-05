// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CMoonNative

public enum CatalogueUpdate {
    public static func refresh(task: ComputeTask, directory: URL? = nil) async throws -> [Feature] {
        let directory = directory ?? DataStore.cache
        let archive = try await DataStore.download(URL(string: "https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/MOON_nomenclature_center_pts.zip")!, to: directory.appendingPathComponent("moon-nomenclature.zip"), task: task, force: true)
        return try importArchive(archive, directory: directory, task: task)
    }
    public static func importArchive(_ archive: URL, directory: URL, task: ComputeTask) throws -> [Feature] {
        var count = 0, error = nativeError()
        guard let pointer = mn_zip_member(archive.path, ".dbf", &count, &error) else { throw failure(error) }
        defer { mn_free(pointer) }
        let features = try parseDBF(Array(UnsafeBufferPointer(start: pointer, count: count)), previous: Catalog.bundled(), task: task)
        guard !features.isEmpty else { throw MoonError.invalid("USGS 地名数据库为空，保留现有目录。") }
        try JSONEncoder().encode(features).write(to: directory.appendingPathComponent("catalog-native.json"), options: .atomic)
        return features
    }
    public static func parseDBF(_ bytes: [UInt8], previous: [Feature], task: ComputeTask) throws -> [Feature] {
        guard bytes.count >= 33 else { throw MoonError.invalid("USGS 地名数据库不完整。") }
        func integer(_ offset: Int, _ length: Int) -> Int { (0..<length).reduce(0) { $0 | Int(bytes[offset + $1]) << ($1 * 8) } }
        let count = integer(4, 4), header = integer(8, 2), record = integer(10, 2)
        guard count < 50_000, header >= 33, record > 1, header + count * record <= bytes.count else { throw MoonError.invalid("USGS 地名数据库尺寸无效。") }
        var fields: [(String, Int, Int)] = [], start = 1
        for offset in stride(from: 32, to: header - 1, by: 32) {
            guard offset + 32 <= bytes.count, bytes[offset] != 0x0d else { break }
            let name = String(decoding: bytes[offset..<(offset + 11)].prefix { $0 != 0 }, as: UTF8.self), length = Int(bytes[offset + 16])
            guard start + length <= record else { throw MoonError.invalid("USGS 地名字段无效。") }
            fields.append((name, start, length)); start += length
        }
        let existing = Dictionary(previous.map { ($0.name, $0) }, uniquingKeysWith: { first, _ in first })
        var output: [Feature] = [], ids = Set<String>()
        for row in 0..<count {
            if row % 256 == 0 { try task.check() }; let base = header + row * record
            if bytes[base] == 0x2a { continue }
            let values = Dictionary(uniqueKeysWithValues: fields.map { name, start, length in (name, String(decoding: bytes[(base + start)..<(base + start + length)], as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines.union(.controlCharacters))) })
            guard values["approval"] == "Adopted by IAU", let name = values["name"], let lat = values["center_lat"].flatMap(Double.init), let lon = values["center_lon"].flatMap(Double.init), let link = values["link"], let id = URL(string: link)?.lastPathComponent, !id.isEmpty else { continue }
            guard lat.isFinite, lon.isFinite, (-90...90).contains(lat), ids.insert(id).inserted else { continue }
            let old = existing[name]
            output.append(Feature(id: id, name: name, chinese: old?.chinese ?? "", latitude: lat, longitude: (lon + 540).truncatingRemainder(dividingBy: 360) - 180,
                                  diameter: values["diameter"].flatMap(Double.init) ?? 0, kind: values["type"] ?? "", aliases: old?.aliases))
        }
        return output
    }
}
