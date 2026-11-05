// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

public struct PathCaptionRow: Codable, Sendable {
    public var advances: [Double], size: Double, offset: Double
    public init(advances: [Double], size: Double, offset: Double) { self.advances = advances; self.size = size; self.offset = offset }
}
public struct PathGlyphPlacement: Codable, Sendable {
    public var point: PixelPoint, angle: Double
}
public struct PathCaptionPlacement: Sendable {
    public var origin: PixelPoint, glyphs: [PathGlyphPlacement]
}
private final class ProjectedPaths: NSObject {
    let values: [[PixelPoint]]
    init(_ values: [[PixelPoint]]) { self.values = values }
}

public enum LandformPaths {
    public static let kinds = Set(["Rima", "Mons", "Dorsum", "Vallis", "Rupes", "Catena"])
    private static let records: [String: JSONValue] = {
        guard let url = Catalog.resource("feature_paths", "json"), let data = try? Data(contentsOf: url), let root = try? JSONDecoder().decode(JSONValue.self, from: data) else { return [:] }
        return root.object["features"]?.object ?? [:]
    }()
    private static let cache = NSCache<NSString, ProjectedPaths>()
    public static func projected(feature: Feature, document: MoonDocument) -> [[PixelPoint]] {
        guard document.style.bool("follow_feature_paths", true), kinds.contains(feature.kind.components(separatedBy: ",")[0]), let camera = document.calibration, let lines = records[feature.id]?.object["paths"]?.array else { return [] }
        let g = camera.geometry
        let key = "\(feature.id)|\(g.observer)|\(g.right)|\(g.north)|\(g.distanceKM)|\(camera.matrix)|\(String(describing: camera.distortion))|\(document.imageWidth),\(document.imageHeight)" as NSString
        if let cached = cache.object(forKey: key) { return cached.values }
        var result: [[PixelPoint]] = []
        for line in lines {
            var coordinates: [PixelPoint] = []
            for record in line.array {
                let values = record.array.compactMap(\.number); guard values.count == 2, values.allSatisfy(\.isFinite) else { continue }
                var longitude = values[0]
                if let previous = coordinates.last { while longitude - previous.x > 180 { longitude -= 360 }; while longitude - previous.x < -180 { longitude += 360 } }
                coordinates.append(PixelPoint(longitude, values[1]))
            }
            guard let dense = resample(coordinates, step: 0.1) else { continue }
            var current: [PixelPoint] = []
            func finish() {
                defer { current = [] }
                guard var segment = resample(current, step: 2) else { return }
                let first = segment.first!, last = segment.last!
                if last.x < first.x || (abs(last.x - first.x) < 1e-5 && last.y > first.y) { segment.reverse() }
                result.append(segment)
            }
            for point in dense {
                let projected = camera.geometry.project(latitude: point.y, longitude: point.x), pixel = camera.photoPoint(projected.point)
                let inside = document.imageWidth <= 0 || document.imageHeight <= 0 || (pixel.x >= 0 && pixel.x <= Double(document.imageWidth) && pixel.y >= 0 && pixel.y <= Double(document.imageHeight))
                if projected.visible && pixel.isFinite && inside { current.append(pixel) } else { finish() }
            }
            finish()
        }
        result = result.enumerated().sorted { a, b in let x = length(a.element), y = length(b.element); return x == y ? a.offset < b.offset : x > y }.map(\.element)
        cache.countLimit = 512; cache.setObject(ProjectedPaths(result), forKey: key); return result
    }
    public static func fittedSize(paths: [[PixelPoint]], size: Double, span: Double) -> Double {
        guard let path = paths.first, span > 0 else { return size }
        let fitted = min(size, floor(length(path) * 0.92 / span))
        return fitted >= max(8, ceil(size * 0.65)) ? fitted : size
    }
    public static func length(_ points: [PixelPoint]) -> Double {
        zip(points, points.dropFirst()).reduce(0) { $0 + hypot($1.1.x - $1.0.x, $1.1.y - $1.0.y) }
    }
    private static func stations(_ points: [PixelPoint]) -> [Double] {
        var result = [0.0]
        for (a, b) in zip(points, points.dropFirst()) { result.append(result.last! + hypot(b.x - a.x, b.y - a.y)) }; return result
    }
    private static func interpolate(_ distance: Double, along: [Double], values: [Double]) -> Double {
        guard let first = values.first, let last = values.last else { return 0 }
        if distance <= along[0] { return first }; if distance >= along.last! { return last }
        var low = 0, high = along.count - 1
        while high - low > 1 { let middle = (low + high) / 2; if along[middle] <= distance { low = middle } else { high = middle } }
        let fraction = (distance - along[low]) / max(1e-30, along[high] - along[low])
        return values[low] * (1 - fraction) + values[high] * fraction
    }
    private static func sample(_ distance: Double, along: [Double], points: [PixelPoint]) -> PixelPoint {
        // Binary search once; glyph stations need only two linear coordinates.
        if distance <= along[0] { return points[0] }; if distance >= along.last! { return points.last! }
        var low = 0, high = along.count - 1
        while high - low > 1 { let middle = (low + high) / 2; if along[middle] <= distance { low = middle } else { high = middle } }
        let t = (distance - along[low]) / max(1e-30, along[high] - along[low]), a = points[low], b = points[high]
        return PixelPoint(a.x * (1 - t) + b.x * t, a.y * (1 - t) + b.y * t)
    }
    private static func resample(_ input: [PixelPoint], step: Double) -> [PixelPoint]? {
        guard input.count >= 2, step > 0, input.allSatisfy(\.isFinite) else { return nil }
        let original = stations(input)
        var points = [input[0]], along = [0.0]
        for index in 1..<input.count where original[index] - original[index - 1] > 1e-8 { points.append(input[index]); along.append(original[index]) }
        guard points.count >= 2, let total = along.last, total >= 1e-5 else { return nil }
        let count = min(2048, max(2, Int(ceil(total / step)) + 1))
        return (0..<count).map { sample(total * Double($0) / Double(count - 1), along: along, points: points) }
    }
    public static func place(paths: [[PixelPoint]], rows: [PathCaptionRow]) -> PathCaptionPlacement? {
        guard !rows.isEmpty, rows.allSatisfy({ !$0.advances.isEmpty && $0.advances.allSatisfy { $0.isFinite && $0 >= 0 } && $0.size.isFinite && $0.size > 0 && $0.offset.isFinite }) else { return nil }
        let width = rows.map { $0.advances.reduce(0, +) }.max()!, size = rows.map(\.size).max()!
        guard width > 0 else { return nil }
        for line in paths {
            guard let source = resample(line, step: max(1, size * 0.12)) else { continue }
            let step = length(source) / Double(source.count - 1)
            for smoothness in [0.4, 0.65] {
                let sigma = max(1, size * smoothness / step), radius = max(2, Int(ceil(sigma * 3)))
                var kernel = (-radius...radius).map { exp(-0.5 * pow(Double($0) / sigma, 2)) }; let total = kernel.reduce(0, +); kernel = kernel.map { $0 / total }
                let points = source.indices.map { index -> PixelPoint in
                    var x = 0.0, y = 0.0
                    for offset in -radius...radius { let p = source[min(source.count - 1, max(0, index + offset))], weight = kernel[offset + radius]; x += p.x * weight; y += p.y * weight }
                    return PixelPoint(x, y)
                }
                let along = stations(points), length = along.last!
                if width > length * 0.95 { continue }
                let normals = points.indices.map { index -> PixelPoint in
                    let a = points[max(0, index - 1)], b = points[min(points.count - 1, index + 1)], divisor = index == 0 || index == points.count - 1 ? 1.0 : 2.0
                    let dx = (b.x - a.x) / divisor, dy = (b.y - a.y) / divisor, norm = max(1e-8, hypot(dx, dy))
                    return PixelPoint(-dy / norm, dx / norm)
                }
                var best: (Double, PathCaptionPlacement)?
                for fraction in [0.5, 0.4, 0.6, 0.3, 0.7] {
                    let center = min(length * 0.975 - width / 2, max(width / 2 + length * 0.025, length * fraction))
                    var deviation = 0.0
                    for i in points.indices where abs(along[i] - center) <= width / 2 { deviation = max(deviation, hypot(points[i].x - source[i].x, points[i].y - source[i].y)) }
                    if deviation > max(2, size * 0.85) { continue }
                    var placements: [PathGlyphPlacement] = [], corners: [PixelPoint] = [], allAngles: [Double] = [], costs: [Double] = []
                    var valid = true
                    for row in rows {
                        let rowPoints = zip(points, normals).map { PixelPoint($0.0.x + $0.1.x * row.offset, $0.0.y + $0.1.y * row.offset) }, rowAlong = stations(rowPoints)
                        let rowCenter = interpolate(center, along: along, values: rowAlong), rowWidth = row.advances.reduce(0, +)
                        var cursor = rowCenter - rowWidth / 2, distances: [Double] = []
                        for advance in row.advances { distances.append(cursor + advance / 2); cursor += advance }
                        if distances[0] - row.advances[0] / 2 < 0 || distances.last! + row.advances.last! / 2 > rowAlong.last! { valid = false; break }
                        var angles: [Double] = [], rowPlacements: [PathGlyphPlacement] = [], rowCorners: [PixelPoint] = []
                        for (index, distance) in distances.enumerated() {
                            let advance = row.advances[index], reach = max(row.size * 0.5, advance * 0.45)
                            let a = sample(distance - reach, along: rowAlong, points: rowPoints), b = sample(distance + reach, along: rowAlong, points: rowPoints), norm = hypot(b.x - a.x, b.y - a.y)
                            if norm < 1e-6 { valid = false; break }
                            let tx = (b.x - a.x) / norm, ty = (b.y - a.y) / norm, midpoint = sample(distance, along: rowAlong, points: rowPoints)
                            let baseline = PixelPoint(midpoint.x - advance / 2 * tx, midpoint.y - advance / 2 * ty), angle = atan2(ty, tx) * 180 / .pi
                            angles.append(angle); rowPlacements.append(PathGlyphPlacement(point: baseline, angle: angle))
                            for dx in [0.0, 1] { for dy in [-1.0, 0.25] { rowCorners.append(PixelPoint(baseline.x + dx * advance * tx - dy * row.size * ty, baseline.y + dx * advance * ty + dy * row.size * tx)) } }
                        }
                        if !valid { break }
                        if angles.contains(where: { abs($0) > 95 }) || angles.max()! - angles.min()! > 55 { valid = false; break }
                        var turn = 0.0
                        if angles.count > 1 { for index in 1..<angles.count {
                            let delta = abs(angles[index] - angles[index - 1]); turn += delta
                            if row.advances[index] <= row.size * 1.5 && row.advances[index - 1] <= row.size * 1.5 && delta > 14 { valid = false }
                        } }
                        if !valid { break }
                        costs.append(turn / Double(max(1, angles.count - 1))); allAngles += angles; placements += rowPlacements; corners += rowCorners
                    }
                    guard valid, !allAngles.isEmpty, allAngles.max()! - allAngles.min()! <= 55 else { continue }
                    let origin = PixelPoint(corners.map(\.x).min()!, corners.map(\.y).min()!)
                    let relative = placements.map { PathGlyphPlacement(point: PixelPoint($0.point.x - origin.x, $0.point.y - origin.y), angle: $0.angle) }
                    let score = abs(fraction - 0.5) * 2 + deviation / size * 0.1 + costs.reduce(0, +) / Double(max(1, rows.count)) * 0.01
                    if best == nil || score < best!.0 { best = (score, PathCaptionPlacement(origin: origin, glyphs: relative)) }
                }
                if let best { return best.1 }
            }
        }
        return nil
    }
}
