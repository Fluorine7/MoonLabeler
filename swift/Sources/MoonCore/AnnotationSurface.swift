// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import simd

/// The same elevated geographic / visual anchors serve manual fitting and display.
public final class AnnotationSurface {
    private let document: MoonDocument
    private let camera: Calibration
    private let points: [String: JSONValue]
    private let rims: [String: JSONValue]
    private var cachedRims: [String: ([PixelPoint], [Bool])] = [:]
    public init(document: MoonDocument) throws {
        guard let camera = document.calibration else { throw MoonError.invalid("请先校准照片。") }
        self.document = document; self.camera = camera
        let relief = document.state.legacy["annotation_relief"]?.object ?? [:]
        points = relief["points"]?.object ?? [:]
        rims = (relief["rims"]?.object ?? [:]).merging(document.state.legacy["terrain_rims"]?.object ?? [:]) { _, edited in edited }
    }
    public func height(_ feature: Feature) -> Double {
        guard document.state.projectionSurface == "terrain", let values = points[feature.id]?.array.compactMap(\.number), values.count == 3,
              abs(values[0] - feature.latitude) <= 1e-8, abs(values[1] - feature.longitude) <= 1e-8, values[2].isFinite, abs(values[2]) <= 15 else { return 0 }
        return values[2]
    }
    public func rim(_ feature: Feature, coordinates supplied: [JSONValue]? = nil) -> ([PixelPoint], [Bool]) {
        if supplied == nil, let cached = cachedRims[feature.id] { return cached }
        let coordinates = supplied ?? savedRim(feature)
        let valid = coordinates?.compactMap { item -> [Double]? in
            let values = item.array.compactMap(\.number); return values.count == 3 && values.allSatisfy(\.isFinite) ? values : nil
        } ?? []
        var pixels: [PixelPoint] = [], visible: [Bool] = []
        if valid.count >= 16, valid.count == coordinates?.count {
            for values in valid {
                let projected = camera.geometry.project(latitude: values[0], longitude: values[1], height: values[2])
                pixels.append(camera.photoPoint(projected.point)); visible.append(projected.visible)
            }
        } else {
            for coordinate in FeatureGeometry.ring(feature) {
                let projected = camera.geometry.project(latitude: coordinate.latitude, longitude: coordinate.longitude, height: height(feature))
                pixels.append(camera.photoPoint(projected.point)); visible.append(projected.visible)
            }
        }
        let result = (pixels, visible); if supplied == nil { cachedRims[feature.id] = result }; return result
    }
    public func position(_ feature: Feature) -> (point: PixelPoint, visible: Bool) {
        let projected = camera.geometry.project(latitude: feature.latitude, longitude: feature.longitude, height: height(feature))
        let point = camera.photoPoint(projected.point)
        guard projected.visible, document.state.projectionSurface == "terrain", ["Crater, craters", "Satellite Feature"].contains(feature.kind), feature.diameter >= 35, savedRim(feature) != nil else { return (point, projected.visible) }
        let outline = rim(feature)
        guard !outline.1.contains(false), let centroid = Self.contourCenter(outline.0) else { return (point, true) }
        let center = document.style.string("crater_outline_shape", "ellipse") == "terrain" ? centroid : NativeCompute.ellipse(outline.0)?.center ?? centroid
        let x = outline.0.map(\.x), y = outline.0.map(\.y), width = (x.max() ?? 0) - (x.min() ?? 0), height = (y.max() ?? 0) - (y.min() ?? 0)
        guard width > 0.1, height > 0.1, hypot(center.x - point.x, center.y - point.y) < max(8, width, height) else { return (point, true) }
        return (center, true)
    }
    private func savedRim(_ feature: Feature) -> [JSONValue]? {
        guard let record = rims[feature.id]?.object else { return nil }
        let shape = record["feature"]?.array.compactMap(\.number) ?? []
        guard document.state.legacy["terrain_rims"]?.object[feature.id] != nil || (shape.count == 3 && abs(shape[0] - feature.latitude) <= 1e-8 && abs(shape[1] - feature.longitude) <= 1e-8 && abs(shape[2] - feature.diameter) <= 1e-8) else { return nil }
        guard let coordinates = record["coordinates"]?.array, coordinates.count >= 16,
              coordinates.allSatisfy({ $0.array.count == 3 && $0.array.allSatisfy { $0.number?.isFinite == true } }) else { return nil }
        return coordinates
    }
    public static func contourCenter(_ ring: [PixelPoint]) -> PixelPoint? {
        guard ring.count >= 6, ring.allSatisfy(\.isFinite), let first = ring.first, let last = ring.last,
              abs(first.x - last.x) <= 1e-8 + 1e-5 * abs(first.x), abs(first.y - last.y) <= 1e-8 + 1e-5 * abs(first.y) else { return nil }
        let count = Double(ring.count - 1), origin = PixelPoint(ring.dropLast().reduce(0) { $0 + $1.x } / count, ring.dropLast().reduce(0) { $0 + $1.y } / count)
        var area = 0.0, x = 0.0, y = 0.0
        for (a, b) in zip(ring, ring.dropFirst()) {
            let ax = a.x - origin.x, ay = a.y - origin.y, bx = b.x - origin.x, by = b.y - origin.y, cross = ax * by - bx * ay
            area += cross; x += (ax + bx) * cross; y += (ay + by) * cross
        }
        guard abs(area) >= 1e-6 else { return nil }
        return PixelPoint(origin.x + x / (3 * area), origin.y + y / (3 * area))
    }
    public static func snapshot(features: [Feature], camera: Calibration, width: Int, height: Int, dem: ElevationMap, task: ComputeTask) throws -> JSONValue {
        let m = camera.matrix, square = m[0][0] * m[0][0] + m[0][1] * m[0][1] + m[1][0] * m[1][0] + m[1][1] * m[1][1]
        let determinant = m[0][0] * m[1][1] - m[0][1] * m[1][0], scale = sqrt((square + sqrt(max(0, square * square - 4 * determinant * determinant))) / 2)
        let margin = max(4, scale * 15 / moonRadius * 3), short = Double(min(width, height))
        var points: [String: JSONValue] = [:], rims: [String: JSONValue] = [:]
        for (index, feature) in features.enumerated() {
            if index % 128 == 0 { try task.check() }
            let projected = camera.geometry.project(latitude: feature.latitude, longitude: feature.longitude), pixel = camera.photoPoint(projected.point)
            guard projected.visible, pixel.isFinite, pixel.x >= -margin, pixel.y >= -margin, pixel.x < Double(width) + margin, pixel.y < Double(height) + margin else { continue }
            let height = dem.sample(feature.latitude, feature.longitude)
            guard height.isFinite, abs(height) <= 15 else { continue }
            points[feature.id] = .array([.number(feature.latitude), .number(feature.longitude), .number(height)])
            guard ["Crater, craters", "Satellite Feature"].contains(feature.kind), feature.diameter >= max(35, 6 * dem.resolutionKM), feature.diameter / moonRadius * scale >= short * 0.055 else { continue }
            var coordinates: [JSONValue] = []
            for point in FeatureGeometry.ring(feature) {
                let h = dem.sample(point.latitude, point.longitude)
                if !h.isFinite || abs(h) > 15 { coordinates = []; break }
                coordinates.append(.array([.number(point.latitude), .number(point.longitude), .number(h)]))
            }
            if !coordinates.isEmpty { rims[feature.id] = .object(["feature": .array([.number(feature.latitude), .number(feature.longitude), .number(feature.diameter)]), "coordinates": .array(coordinates)]) }
        }
        return .object(["source": .string(dem.name), "resolution_km": .number(dem.resolutionKM), "points": .object(points), "rims": .object(rims)])
    }
}

public enum ManualCalibration {
    public static func solve(document: MoonDocument, features: [Feature], dem: ElevationMap?, mirror: Int = -1, task: ComputeTask) throws -> (MoonDocument, CalibrationReport) {
        try task.check()
        let geometry = try document.state.geometry ?? document.calibration?.geometry ?? NativeCompute.ephemeris(utc: document.state.utc, latitude: document.state.latitude, longitude: document.state.longitude)
        var result = try RecognitionEngine.manual(geometry: geometry, anchors: document.state.anchors, features: features, mirror: mirror)
        var updated = document; updated.calibration = result.0; updated.state.geometry = geometry
        for key in ["automatic_recognition", "annotation_relief", "terrain_rims", "labels"] { updated.state.legacy.removeValue(forKey: key) }
        updated.annotations = document.annotations.filter { $0.featureID == nil }; updated.state.projectionSurface = "sphere"
        if let dem {
            let all = features + (try AnnotationSceneBuilder.landings())
            let relief = try AnnotationSurface.snapshot(features: all, camera: result.0, width: document.imageWidth, height: document.imageHeight, dem: dem, task: task)
            updated.state.legacy["annotation_relief"] = relief; updated.state.projectionSurface = "terrain"
            let surface = try AnnotationSurface(document: updated), byID = Dictionary(uniqueKeysWithValues: features.map { ($0.id, $0) })
            let anchors = document.state.anchors.filter { $0.enabled != false }
            let source = try anchors.map { anchor -> PixelPoint in
                guard let feature = byID[anchor.id] else { throw MoonError.invalid("参考点的地名已不在地名库中。") }
                return result.0.modelPoint(surface.position(feature).point)
            }
            let report = try NativeCompute.fit(source: source, target: anchors.map(\.point), mirror: mirror)
            result = (Calibration(geometry: geometry, matrix: report.matrix), report); updated.calibration = result.0
        }
        try task.check(); return (updated, result.1)
    }
}
