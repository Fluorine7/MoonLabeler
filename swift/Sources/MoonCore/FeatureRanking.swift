// SPDX-License-Identifier: GPL-3.0-or-later
// Photographic prominence and regional balancing from MoonLabeler 0.12.1.
import Foundation
import simd

public struct RankedFeature {
    public var feature: Feature
    public var anchor: PixelPoint
    public var edit: LegacyOverride?
}
public enum FeatureRanking {
    static func percentile(_ values: [Double], _ fraction: Double) -> Double {
        guard !values.isEmpty else { return 0 }; let sorted = values.sorted(), index = Double(sorted.count - 1) * fraction, lower = Int(index), f = index - Double(lower)
        return sorted[lower] * (1 - f) + sorted[min(lower + 1, sorted.count - 1)] * f
    }
    public static func rank(features: [Feature], document: MoonDocument, photo: PhotoPixels,
                            overrides: [String: LegacyOverride], anchor: (Feature) -> PixelPoint?, task: ComputeTask) throws -> [RankedFeature] {
        guard let camera = document.calibration else { return [] }
        let stride = max(1, Int(ceil(Double(max(photo.width, photo.height)) / 1600))), columns = (photo.width + stride - 1) / stride, rows = (photo.height + stride - 1) / stride
        var gray: [Double] = []; gray.reserveCapacity(columns * rows)
        for y in Swift.stride(from: 0, to: photo.height, by: stride) { for x in Swift.stride(from: 0, to: photo.width, by: stride) {
            let i = (y * photo.width + x) * 4; gray.append((Double(photo.rgba[i]) + Double(photo.rgba[i + 1]) + Double(photo.rgba[i + 2])) / 3)
        } }
        let blur = NativeCompute.gaussian(gray, width: columns, height: rows, sigma: 1.2), noise = zip(gray, blur).map { abs($0 - $1) }
        var background: [Double] = []
        for y in Swift.stride(from: 0, to: rows, by: 8) { for x in Swift.stride(from: 0, to: columns, by: 8) { background.append(gray[y * columns + x]) } }
        let bright = max(16, percentile(background, 0.95)), scale = sqrt(abs(camera.matrix[0][0] * camera.matrix[1][1] - camera.matrix[0][1] * camera.matrix[1][0]))
        let short = Double(min(photo.width, photo.height)), referenceFont = LabelSizing.tierSizes(document)[1]
        func index(_ p: PixelPoint) -> Int {
            let x = min(columns - 1, max(0, Int((p.x / Double(stride)).rounded(.toNearestOrEven)))), y = min(rows - 1, max(0, Int((p.y / Double(stride)).rounded(.toNearestOrEven))))
            return y * columns + x
        }
        struct Candidate { var tier: Int; var score: Double; var cell: Int; var item: RankedFeature }
        var candidates: [Candidate] = []
        for (number, feature) in features.enumerated() {
            if number % 128 == 0 { try task.check() }
            let projected = camera.project(feature)
            guard projected.visible, let point = anchor(feature), point.isFinite, point.x >= 0, point.y >= 0, point.x < Double(photo.width), point.y < Double(photo.height) else { continue }
            let landing = feature.kind == "Landing Site"
            if !landing && (feature.diameter < document.settings.minimumDiameter || !document.settings.includes(kind: feature.kind)) { continue }
            let radius = max(4, min(short * 0.08, feature.diameter * scale / (2 * moonRadius) * 1.12))
            var samples: [Int] = []
            for y in -6...6 { for x in -6...6 where x * x + y * y <= 36 { samples.append(index(PixelPoint(point.x + radius * Double(x) / 6, point.y + radius * Double(y) / 6))) } }
            let local = samples.map { gray[$0] }
            var contrast = min(1, (percentile(local, 0.9) - percentile(local, 0.1)) / bright), roughness = 0.0
            if ["Crater, craters", "Satellite Feature"].contains(feature.kind) {
                var inner: [Double] = [], outer: [Double] = []
                for (ringIndex, factor) in [0.4, 0.7, 1, 1.3, 1.6, 2].enumerated() {
                    for p in FeatureGeometry.ring(feature, factor: factor) {
                        let model = camera.geometry.project(latitude: p.latitude, longitude: p.longitude), p = camera.photoPoint(model.point)
                        guard model.visible, p.x >= 0, p.y >= 0, p.x < Double(photo.width), p.y < Double(photo.height) else { continue }
                        let i = index(p); if ringIndex < 3 { inner.append(gray[i]) } else { outer.append(noise[i]) }
                    }
                }
                if inner.count >= 12 { contrast = min(1, (percentile(inner, 0.9) - percentile(inner, 0.1)) / bright) }
                if outer.count >= 12 { roughness = percentile(outer, 0.8) / bright }
            } else { roughness = percentile(samples.map { noise[$0] }, 0.8) / bright }
            let edit = overrides[feature.id], satellite = feature.kind == "Satellite Feature" || feature.name.range(of: "\\s[A-Z]$", options: .regularExpression) != nil
            let tier = landing || edit?.force == true || edit?.position != nil ? 0 : Catalog.commonNames.contains(feature.name) ? 1 : satellite ? 3 : 2
            let depth = simd_dot(surfaceVector(latitude: feature.latitude, longitude: feature.longitude), camera.geometry.observerVector)
            let apparent = feature.diameter * scale / moonRadius * sqrt(max(0, depth))
            var score = 2.5 * contrast / (1 + 12 * roughness) + min(1, sqrt(apparent / max(6, referenceFont))) + 0.4 * sqrt(max(0, depth))
            if feature.kind == "Crater, craters" { score += 0.4 }
            let cell = min(3, Int(point.x * 4 / Double(photo.width))) * 4 + min(3, Int(point.y * 4 / Double(photo.height)))
            candidates.append(Candidate(tier: tier, score: score, cell: cell, item: RankedFeature(feature: feature, anchor: point, edit: edit)))
        }
        var ranked: [RankedFeature] = [], used: [Int: Int] = [:]
        for tier in 0..<4 {
            var cells: [Int: [Candidate]] = [:]
            for candidate in candidates where candidate.tier == tier { cells[candidate.cell, default: []].append(candidate) }
            for cell in cells.keys { cells[cell]!.sort { $0.score == $1.score ? $0.item.feature.id < $1.item.feature.id : $0.score > $1.score } }
            var offsets = Dictionary(uniqueKeysWithValues: cells.keys.map { ($0, 0) })
            while !offsets.isEmpty {
                let cell = offsets.keys.min { a, b in
                    let left = cells[a]![offsets[a]!].score - 0.08 * Double(used[a] ?? 0), right = cells[b]![offsets[b]!].score - 0.08 * Double(used[b] ?? 0)
                    return left == right ? a < b : left > right
                }!
                let i = offsets[cell]!, candidate = cells[cell]![i]; ranked.append(candidate.item)
                if candidate.item.edit?.hidden != true { used[cell, default: 0] += 1 }
                if i + 1 < cells[cell]!.count { offsets[cell] = i + 1 } else { offsets.removeValue(forKey: cell) }
            }
        }
        return ranked
    }
}
public enum LabelSizing {
    public static func tierSizes(_ document: MoonDocument) -> [Double] {
        guard let percent = document.style.values["font_percent"]?.number else { return Array(repeating: document.settings.fontSize, count: 3) }
        let short = Double(min(document.imageWidth, document.imageHeight)), step = document.style.number("font_step_percent", 0)
        return (0..<3).map { max(6, (short * max(0.05, percent - Double($0) * step) / 100).rounded(.toNearestOrEven)) }
    }
    public static func size(_ feature: Feature, document: MoonDocument) -> Double {
        let base = document.settings.fontSize, tiers = tierSizes(document)
        let satellite = feature.kind == "Satellite Feature" || feature.name.range(of: "\\s[A-Z]$", options: .regularExpression) != nil
        if document.style.art == "topographic" { return max(10, (base * (satellite ? 0.68 : feature.kind == "Landing Site" ? 0.8 : feature.diameter >= 80 ? 1.25 : 1)).rounded(.toNearestOrEven)) }
        if document.style.isArt {
            let typography = CaptionTypography.resolve(feature: feature, art: document.style.art)
            var extent = Double(min(document.imageWidth, document.imageHeight)) * 0.68
            if typography.region, let camera = document.calibration {
                let depth = simd_dot(surfaceVector(latitude: feature.latitude, longitude: feature.longitude), camera.geometry.observerVector)
                let apparent = feature.diameter * camera.scale / moonRadius * sqrt(max(0.05, depth))
                extent = min(extent, max(base * 5, apparent * 0.95))
            }
            let edited = document.state.legacy["labels"]?.object[feature.id]?.object["text"]?.string
            let caption = edited ?? (typography.uppercase ? feature.caption(document.settings.language).uppercased() : feature.caption(document.settings.language))
            return max(8, min(base * typography.scale, extent / max(1, typography.span(caption))).rounded(.toNearestOrEven))
        }
        if feature.kind == "Landing Site" { return tiers[2] }
        guard document.style.number("font_step_percent", 0) != 0, let camera = document.calibration else { return base }
        let depth = simd_dot(surfaceVector(latitude: feature.latitude, longitude: feature.longitude), camera.geometry.observerVector), q = moonRadius / camera.geometry.distanceKM
        var determinant = abs(camera.matrix[0][0] * camera.matrix[1][1] - camera.matrix[0][1] * camera.matrix[1][0]) * abs(depth - q) / pow(1 - q * depth, 3)
        if let lens = camera.distortion {
            let point = camera.geometry.project(latitude: feature.latitude, longitude: feature.longitude).point
            let pixel = PixelPoint(camera.matrix[0][0] * point.x + camera.matrix[0][1] * point.y + camera.matrix[0][2],
                                   camera.matrix[1][0] * point.x + camera.matrix[1][1] * point.y + camera.matrix[1][2])
            determinant *= abs(lens.areaScale(at: pixel))
        }
        let apparent = feature.diameter / moonRadius * sqrt(determinant) / Double(min(document.imageWidth, document.imageHeight))
        return tiers[apparent >= 0.02 ? 0 : apparent >= 0.008 ? 1 : 2]
    }
}
