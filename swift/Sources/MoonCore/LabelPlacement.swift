// SPDX-License-Identifier: GPL-3.0-or-later
// Placement rules ported from MoonLabeler 0.12.1 layout.py.
import Foundation
import CoreGraphics

public struct PlacementRequest: Codable {
    public var key: String
    public var anchor: PixelPoint
    public var width: Double, height: Double, radius: Double
    public var fixed: PixelPoint?
    public var force: Bool, important: Bool, region: Bool
    public var preferred: PixelPoint?
    public var outline: [[PixelPoint]]
    public init(key: String, anchor: PixelPoint, width: Double, height: Double, radius: Double = 4, fixed: PixelPoint? = nil,
                force: Bool = false, important: Bool = false, region: Bool = false, preferred: PixelPoint? = nil, outline: [[PixelPoint]] = []) {
        self.key = key; self.anchor = anchor; self.width = width; self.height = height; self.radius = radius; self.fixed = fixed
        self.force = force; self.important = important; self.region = region; self.preferred = preferred; self.outline = outline
    }
}
public struct LeaderSegment: Equatable {
    public var start: PixelPoint, end: PixelPoint
    var bounds: CGRect { CGRect(x: min(start.x, end.x), y: min(start.y, end.y), width: abs(start.x - end.x), height: abs(start.y - end.y)) }
}
private final class PlacementIndex<T> {
    let size: Double
    var buckets: [String: Set<String>] = [:], cells: [String: [String]] = [:], values: [String: T] = [:]
    init(_ size: Double) { self.size = size }
    func cellKeys(_ rect: CGRect, _ padding: Double = 0) -> [String] {
        var keys: [String] = []
        for x in Int(floor((rect.minX - padding) / size))...Int(floor((rect.maxX + padding) / size)) {
            for y in Int(floor((rect.minY - padding) / size))...Int(floor((rect.maxY + padding) / size)) { keys.append("\(x),\(y)") }
        }
        return keys
    }
    func remove(_ key: String) {
        for cell in cells.removeValue(forKey: key) ?? [] { buckets[cell]?.remove(key); if buckets[cell]?.isEmpty == true { buckets.removeValue(forKey: cell) } }
        values.removeValue(forKey: key)
    }
    func put(_ key: String, rect: CGRect, value: T) {
        remove(key); let keys = cellKeys(rect); cells[key] = keys; values[key] = value
        for cell in keys { buckets[cell, default: []].insert(key) }
    }
    func near(_ rect: CGRect, padding: Double = 0, excluding: String? = nil) -> [(String, T)] {
        var keys = Set<String>(); for cell in cellKeys(rect, padding) { keys.formUnion(buckets[cell] ?? []) }
        if let excluding { keys.remove(excluding) }
        return keys.sorted().compactMap { key in values[key].map { (key, $0) } }
    }
}
public enum LabelPlacement {
    public static func intersects(_ a: CGRect, _ b: CGRect, padding: Double = 0) -> Bool {
        a.minX < b.maxX + padding && a.maxX + padding > b.minX && a.minY < b.maxY + padding && a.maxY + padding > b.minY
    }
    public static func leader(anchor: PixelPoint, rect: CGRect, hole: Double = 3, outline: [[PixelPoint]] = []) -> LeaderSegment {
        var end = PixelPoint(max(rect.minX, min(anchor.x, rect.maxX)), max(rect.minY, min(anchor.y, rect.maxY)))
        if anchor.x > rect.minX && anchor.x < rect.maxX && anchor.y > rect.minY && anchor.y < rect.maxY {
            end = [PixelPoint(rect.minX, anchor.y), PixelPoint(rect.maxX, anchor.y), PixelPoint(anchor.x, rect.minY), PixelPoint(anchor.x, rect.maxY)].min { hypot($0.x - anchor.x, $0.y - anchor.y) < hypot($1.x - anchor.x, $1.y - anchor.y) }!
        }
        let length = hypot(end.x - anchor.x, end.y - anchor.y)
        if length <= hole { return LeaderSegment(start: anchor, end: anchor) }
        if !outline.isEmpty {
            let dx = end.x - anchor.x, dy = end.y - anchor.y
            var intersections: [Double] = []
            for line in outline { for (p, q) in zip(line, line.dropFirst()) {
                let vx = q.x - p.x, vy = q.y - p.y, cross = dx * vy - dy * vx
                if abs(cross) < 1e-10 { continue }
                let t = ((p.x - anchor.x) * vy - (p.y - anchor.y) * vx) / cross
                let u = ((p.x - anchor.x) * dy - (p.y - anchor.y) * dx) / cross
                if (0...1).contains(t) && (0...1).contains(u) { intersections.append(t) }
            } }
            if let t = intersections.max() { return LeaderSegment(start: PixelPoint(anchor.x + t * dx, anchor.y + t * dy), end: end) }
            return LeaderSegment(start: end, end: end)
        }
        return LeaderSegment(start: PixelPoint(anchor.x + (end.x - anchor.x) * hole / length, anchor.y + (end.y - anchor.y) * hole / length), end: end)
    }
    public static func hits(_ line: LeaderSegment, rect: CGRect, padding: Double = 0) -> Bool {
        let rect = rect.insetBy(dx: -padding, dy: -padding), ax = line.start.x, ay = line.start.y, dx = line.end.x - ax, dy = line.end.y - ay
        var low = 0.0, high = 1.0
        for (p, q) in [(-dx, ax - rect.minX), (dx, rect.maxX - ax), (-dy, ay - rect.minY), (dy, rect.maxY - ay)] {
            if abs(p) < 1e-12 { if q < 0 { return false } }
            else if p < 0 { low = max(low, q / p) } else { high = min(high, q / p) }
            if low > high { return false }
        }
        return low < high && high > 1e-5 && low < 1 - 1e-5
    }
    private static func crosses(_ a: LeaderSegment, _ b: LeaderSegment) -> Bool {
        func side(_ p: PixelPoint, _ q: PixelPoint, _ r: PixelPoint) -> Double { (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x) }
        return side(a.start, a.end, b.start) * side(a.start, a.end, b.end) < -1e-8 && side(b.start, b.end, a.start) * side(b.start, b.end, a.end) < -1e-8
    }
    private static func distance(_ a: CGRect, _ b: CGRect) -> Double { hypot(max(b.minX - a.maxX, a.minX - b.maxX, 0), max(b.minY - a.maxY, a.minY - b.maxY, 0)) }
    private static func candidates(_ item: PlacementRequest, gap: Double, extended: Bool) -> [CGRect] {
        if let p = item.preferred { return [CGRect(x: p.x, y: p.y, width: item.width, height: item.height)] }
        var output: [CGRect] = []
        if item.region && !extended { output.append(CGRect(x: item.anchor.x - item.width / 2, y: item.anchor.y - item.height / 2, width: item.width, height: item.height)) }
        let angles = [45.0, -45, 135, -135, 0, 180, 90, -90, 22.5, -22.5, 157.5, -157.5, 67.5, -67.5, 112.5, -112.5]
        var rimDistances: [Double: Double] = [:]
        if !item.outline.isEmpty {
            let outer = (item.outline.flatMap { $0 }.map { hypot($0.x - item.anchor.x, $0.y - item.anchor.y) }.max() ?? 0) * 2
            for angle in angles {
                let dx = cos(angle * .pi / 180), dy = sin(angle * .pi / 180)
                let line = leader(anchor: item.anchor, rect: CGRect(x: item.anchor.x + outer * dx, y: item.anchor.y + outer * dy, width: 0, height: 0), outline: item.outline)
                if line.start != line.end { rimDistances[angle] = hypot(line.start.x - item.anchor.x, line.start.y - item.anchor.y) }
            }
        }
        for extra in extended ? [4 * gap, 7 * gap, 11 * gap] : [0, gap, 2.5 * gap] {
            for angle in angles {
                let d = (rimDistances[angle] ?? item.radius) + gap + extra, dx = cos(angle * .pi / 180), dy = sin(angle * .pi / 180)
                output.append(CGRect(x: item.anchor.x + d * dx - (dx < -0.1 ? item.width : abs(dx) <= 0.1 ? item.width / 2 : 0),
                                     y: item.anchor.y + d * dy - (dy < -0.1 ? item.height : abs(dy) <= 0.1 ? item.height / 2 : 0), width: item.width, height: item.height))
            }
        }
        return output
    }
    public static func arrange(next: () -> PlacementRequest?, width: Double, height: Double, gap: Double = 8, maximum: Int,
                               obstacles: [CGRect] = []) -> (placements: [String: CGRect], omitted: Set<String>) {
        var items: [PlacementRequest] = []
        while items.count < maximum, let item = next() { items.append(item) }
        var placements: [String: CGRect] = [:], markers: [String: CGRect] = [:]
        let text = PlacementIndex<CGRect>(max(96, gap * 12)), lines = PlacementIndex<LeaderSegment>(max(96, gap * 12)), centers = PlacementIndex<CGRect>(max(96, gap * 12))
        for (i, rect) in obstacles.enumerated() { text.put("__map_legend_\(i)", rect: rect, value: rect) }
        func place(_ item: PlacementRequest, _ rect: CGRect, _ line: LeaderSegment) { placements[item.key] = rect; text.put(item.key, rect: rect, value: rect); lines.put(item.key, rect: line.bounds, value: line) }
        for item in items {
            let radius = min(item.radius, max(4, item.height * 0.45)); markers[item.key] = CGRect(x: item.anchor.x - radius, y: item.anchor.y - radius, width: radius * 2, height: radius * 2)
        }
        let fixed = Set(items.filter { $0.fixed != nil }.map(\.key)), protected = Set(items.filter { $0.important || $0.force || $0.fixed != nil }.map(\.key))
        for key in protected { if let rect = markers[key] { centers.put(key, rect: rect, value: rect) } }
        for item in items { if let p = item.fixed { let rect = CGRect(x: p.x, y: p.y, width: item.width, height: item.height); place(item, rect, item.preferred == nil ? leader(anchor: item.anchor, rect: rect, outline: item.outline) : LeaderSegment(start: item.anchor, end: item.anchor)) } }
        func bestPosition(_ item: PlacementRequest, extended: Bool = false) -> (CGRect, LeaderSegment)? {
            var best: (Double, CGRect, LeaderSegment)?
            for rect in candidates(item, gap: gap, extended: extended) {
                if rect.minX < gap || rect.minY < gap || rect.maxX > width - gap || rect.maxY > height - gap { continue }
                let inside = item.anchor.x >= rect.minX && item.anchor.x <= rect.maxX && item.anchor.y >= rect.minY && item.anchor.y <= rect.maxY
                let line = item.preferred != nil || (item.region && inside) ? LeaderSegment(start: item.anchor, end: item.anchor) : leader(anchor: item.anchor, rect: rect, outline: item.outline)
                let neighborhood = rect.union(line.bounds), otherRects = text.near(neighborhood, padding: 3 * gap, excluding: item.key).map(\.1)
                if !item.force && otherRects.contains(where: { intersects(rect, $0, padding: gap * 0.65) }) { continue }
                let nearby = centers.near(neighborhood, padding: 3 * gap, excluding: item.region ? item.key : nil), nearbyMarkers = nearby.map(\.1), otherMarkers = nearby.filter { $0.0 != item.key }.map(\.1)
                let otherLines = lines.near(neighborhood, padding: 3 * gap, excluding: item.key).map(\.1)
                let conflicts = otherRects.filter { intersects(rect, $0, padding: gap * 0.65) }.count + nearbyMarkers.filter { intersects(rect, $0, padding: gap * 0.3) }.count + otherRects.filter { hits(line, rect: $0, padding: 1) }.count + otherLines.filter { hits($0, rect: rect, padding: 1) }.count + otherLines.filter { crosses(line, $0) }.count + otherMarkers.filter { hits(line, rect: $0) }.count
                if !item.force && conflicts > 0 { continue }
                let clearance = (otherRects + otherMarkers).map { distance(rect, $0) }.min() ?? 3 * gap
                let score = Double(conflicts) * 1e6 + 0.45 * hypot(line.end.x - line.start.x, line.end.y - line.start.y) - 0.8 * min(clearance, 3 * gap)
                if best == nil || score < best!.0 { best = (score, rect, line) }
            }
            if let best { return (best.1, best.2) }
            return item.important && !extended ? bestPosition(item, extended: true) : nil
        }
        func arrangeGroup(_ group: [PlacementRequest]) {
            for _ in 0..<3 {
                var moved = false
                for item in group { let previous = placements[item.key]; if let best = bestPosition(item) { place(item, best.0, best.1); moved = moved || previous != best.0 } }
                if !moved { break }
            }
        }
        let pending = items.filter { !fixed.contains($0.key) }
        arrangeGroup(pending.filter { protected.contains($0.key) })
        func centerConflicts(_ marker: CGRect) -> Bool { text.near(marker, padding: gap * 0.3).contains { intersects(marker, $0.1, padding: gap * 0.3) } || lines.near(marker).contains { hits($0.1, rect: marker) } }
        var ordinary: [PlacementRequest] = []
        for item in pending where !protected.contains(item.key) { if let rect = markers[item.key], !centerConflicts(rect) { centers.put(item.key, rect: rect, value: rect); ordinary.append(item) } }
        arrangeGroup(ordinary)
        for key in Array(markers.keys) where placements[key] == nil { centers.remove(key); markers.removeValue(forKey: key) }
        func refill(_ item: PlacementRequest) {
            guard placements.count < maximum else { return }
            let radius = min(item.radius, max(4, item.height * 0.45)), rect = CGRect(x: item.anchor.x - radius, y: item.anchor.y - radius, width: radius * 2, height: radius * 2)
            if !item.force && centerConflicts(rect) { return }
            markers[item.key] = rect; centers.put(item.key, rect: rect, value: rect)
            if let best = bestPosition(item) { place(item, best.0, best.1) } else { markers.removeValue(forKey: item.key); centers.remove(item.key) }
        }
        for item in pending where placements[item.key] == nil { refill(item) }
        while placements.count < maximum, let item = next() { items.append(item); refill(item) }
        return (placements, Set(items.filter { placements[$0.key] == nil }.map(\.key)))
    }
}
