// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CoreGraphics
import CMoonNative
import simd

public struct MapLine: Codable, Sendable {
    public var points: [PixelPoint]
    public var major: Bool
    public var value: Double
    public var text: String?
    public var captionPosition: PixelPoint?
    public init(_ points: [PixelPoint], major: Bool = false, value: Double = 0, text: String? = nil) {
        self.points = points; self.major = major; self.value = value; self.text = text
    }
}

public struct HeightRaster: Sendable {
    public var width: Int, height: Int
    public var photoWidth: Int, photoHeight: Int
    public var values: [Float]
    public var resolutionKM: Double
    public func contours(interval: Double) -> [MapLine] {
        let finite = values.filter(\.isFinite)
        guard let minimum = finite.min(), let maximum = finite.max(), minimum < maximum, interval > 0 else { return [] }
        var output: [MapLine] = []
        let start = Int(ceil(Double(minimum) / interval)), end = Int(floor(Double(maximum) / interval))
        guard start <= end, end - start < 1000 else { return [] }
        for index in start...end {
            let level = Double(index) * interval
            var neighbours: [Int: [Int]] = [:], positions: [Int: PixelPoint] = [:]
            for y in 0..<(height - 1) { for x in 0..<(width - 1) {
                let corners = [Double(values[y * width + x]), Double(values[y * width + x + 1]),
                               Double(values[(y + 1) * width + x + 1]), Double(values[(y + 1) * width + x])]
                guard corners.allSatisfy(\.isFinite) else { continue }
                let points = [PixelPoint(Double(x), Double(y)), PixelPoint(Double(x + 1), Double(y)),
                              PixelPoint(Double(x + 1), Double(y + 1)), PixelPoint(Double(x), Double(y + 1))]
                let keys = [(y * width + x) * 2, (y * width + x + 1) * 2 + 1,
                            ((y + 1) * width + x) * 2, (y * width + x) * 2 + 1]
                var edges: [Int] = []
                for edge in 0..<4 {
                    let next = (edge + 1) % 4, a = corners[edge], b = corners[next]
                    if (a <= level && b > level) || (b <= level && a > level) {
                        let f = (level - a) / (b - a), p = points[edge], q = points[next]
                        positions[keys[edge]] = PixelPoint((p.x + (q.x - p.x) * f + 0.5) * Double(photoWidth) / Double(width),
                                                           (p.y + (q.y - p.y) * f + 0.5) * Double(photoHeight) / Double(height))
                        edges.append(keys[edge])
                    }
                }
                if edges.count == 4 && corners.reduce(0, +) / 4 > level { edges.swapAt(1, 3) }
                for pair in stride(from: 0, to: edges.count - 1, by: 2) {
                    let a = edges[pair], b = edges[pair + 1]
                    neighbours[a, default: []].append(b); neighbours[b, default: []].append(a)
                }
            } }
            let starts = neighbours.keys.filter { neighbours[$0]?.count == 1 } + Array(neighbours.keys)
            for start in starts {
                guard !(neighbours[start] ?? []).isEmpty else { continue }
                var keys = [start], current = start
                while let following = neighbours[current]?.popLast() {
                    neighbours[following]?.removeAll { $0 == current }
                    keys.append(following); current = following
                }
                var points = keys.compactMap { positions[$0] }
                if points.count > 2 {
                    let original = points
                    points = [original[0]]
                    for i in 1..<(original.count - 1) {
                        let a = original[i - 1], b = original[i], c = original[i + 1]
                        if abs((b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x)) > 1e-8 { points.append(b) }
                    }
                    points.append(original.last!)
                }
                if points.count > 1 { output.append(MapLine(points, major: index % 5 == 0, value: level)) }
            }
        }
        return output
    }
    public var automaticInterval: Double {
        var gradients: [Double] = []
        for y in 0..<(height - 1) { for x in 0..<(width - 1) {
            let a = values[y * width + x], b = values[y * width + x + 1], c = values[(y + 1) * width + x + 1], d = values[(y + 1) * width + x]
            if [a, b, c, d].allSatisfy(\.isFinite) { gradients.append(Double(hypot((b - a + c - d) * 0.5, (d - a + c - b) * 0.5))) }
        } }
        gradients.sort()
        let target = gradients.isEmpty ? 0.5 : gradients[Int(Double(gradients.count - 1) * 0.8)] * Double(min(width, height)) / 1000 * 8
        return [0.25, 0.5, 1.0, 2.0].first { $0 >= target } ?? 2
    }
}

public final class PhotoLightness: @unchecked Sendable {
    public let width: Int, height: Int
    public let photoWidth: Int, photoHeight: Int
    public let values: [UInt8]
    public let automaticThreshold: Int
    public init(photo: PhotoPixels, calibration: Calibration?) throws {
        let small = try photo.resized(maximum: 512)
        width = small.width; height = small.height; photoWidth = photo.width; photoHeight = photo.height
        var automatic: Int32 = 1, error = nativeError()
        guard let pointer = mn_lightness(small.rgba, Int32(width), Int32(height), 4, &automatic, &error) else { throw failure(error) }
        defer { mn_free(pointer) }
        values = Array(UnsafeBufferPointer(start: pointer, count: width * height))
        var samples: [UInt8] = []
        for y in 0..<height { for x in 0..<width {
            if let calibration {
                let point = PixelPoint((Double(x) + 0.5) * Double(photo.width) / Double(width), (Double(y) + 0.5) * Double(photo.height) / Double(height))
                if !calibration.geometry.unproject(calibration.modelPoint(point)).visible { continue }
            }
            samples.append(values[y * width + x])
        } }
        if samples.isEmpty { automaticThreshold = 1 }
        else {
            let high = samples.sorted()[Int(Double(samples.count - 1) * 0.95)]
            var histogram = [Double](repeating: 0, count: 256)
            for value in samples { histogram[Int(value)] += 1 }
            let total = Double(samples.count), sum = histogram.enumerated().reduce(0) { $0 + Double($1.offset) * $1.element }
            var weight = 0.0, mean = 0.0, variance = -1.0, otsu = 0
            for level in 0..<256 {
                weight += histogram[level]; mean += Double(level) * histogram[level]
                guard weight > 0, weight < total else { continue }
                let a = mean / weight, b = (sum - mean) / (total - weight), score = weight * (total - weight) * (a - b) * (a - b)
                if score > variance { variance = score; otsu = level }
            }
            var threshold = max(1, Int(min(Double(otsu) * 0.35, Double(high) * 0.15).rounded()))
            if calibration?.distortion != nil { threshold = max(threshold, 30, Int((Double(high) * 0.25).rounded())) }
            automaticThreshold = threshold
        }
    }
    public func coverage(threshold: Int?) throws -> PhotoPixels {
        var error = nativeError()
        guard let pointer = mn_coverage(values, Int32(width), Int32(height), Int32(threshold ?? automaticThreshold), &error) else { throw failure(error) }
        defer { mn_free(pointer) }
        var rgba = [UInt8](repeating: 255, count: width * height * 4)
        for index in 0..<(width * height) { for channel in 0..<4 { rgba[index * 4 + channel] = pointer[index] } }
        return PhotoPixels(width: width, height: height, rgba: rgba)
    }
    public func score(feature: Feature, anchor: PixelPoint, calibration: Calibration) -> Int {
        let radius = max(4, min(Double(min(photoWidth, photoHeight)) * 0.08, feature.diameter * calibration.scale / (2 * moonRadius) * 1.12))
        var samples: [UInt8] = []
        for iy in -6...6 { for ix in -6...6 where ix * ix + iy * iy <= 36 {
            let x = min(width - 1, max(0, Int((anchor.x + Double(ix) / 6 * radius) / Double(photoWidth) * Double(width))))
            let y = min(height - 1, max(0, Int((anchor.y + Double(iy) / 6 * radius) / Double(photoHeight) * Double(height))))
            samples.append(values[y * width + x])
        } }
        if feature.kind == "Crater, craters" || feature.kind == "Satellite Feature" {
            for ring in [0.85, 1.0, 1.15] { for point in FeatureGeometry.ring(feature, factor: ring) {
                let projected = calibration.geometry.project(latitude: point.latitude, longitude: point.longitude)
                guard projected.visible else { continue }
                let pixel = calibration.photoPoint(projected.point)
                let x = Int(pixel.x / Double(photoWidth) * Double(width)), y = Int(pixel.y / Double(photoHeight) * Double(height))
                if x >= 0, y >= 0, x < width, y < height { samples.append(values[y * width + x]) }
            } }
        }
        samples.sort(); return samples.isEmpty ? 0 : Int(samples[Int(Double(samples.count - 1) * 0.8)])
    }
}

public struct MapLayers: Sendable {
    public var grid: [MapLine] = []
    public var contours: [MapLine] = []
    public var terminator: [MapLine] = []
    public var raster: HeightRaster?
    public var elevation: PhotoPixels?
    public var contourInterval: Double?
    public var terminatorUnreliable = false
    public var lightness: PhotoLightness?
    public init() {}
}

public enum MapBuilder {
    public static let palettes: [String: [String]] = [
        "terrain": ["#20385b", "#337d9e", "#7aafad", "#cbc89a", "#d9a365", "#b86548", "#f3dfce"],
        "antique": ["#142635", "#29475f", "#4e7892", "#c5b78a", "#d9b56e", "#e4c184", "#eddaad"],
        "wilderness": ["#302c19", "#494222", "#72642e", "#a28f46", "#c3ab68", "#d5c28b", "#e6d5a7"],
        "cyanotype": ["#071b37", "#0b3669", "#1f5f98", "#ece2bd", "#f1d6a0", "#f3dda9", "#fff3d3"],
        "copperplate": ["#062f39", "#0e4d55", "#236776", "#e8a064", "#cf7845", "#edac69", "#f7e4b9"],
        "inkwash": ["#18252a", "#2f494d", "#48676b", "#d5d2b8", "#c8a393", "#eee0c6", "#f5f0dc"],
        "redalert": ["#183c47", "#294e35", "#568432", "#c7ae62", "#a48b5c", "#bdb197", "#e6dcc5"],
    ]
    public static func build(document: MoonDocument, photo: PhotoPixels, dem: ElevationMap?, task: ComputeTask,
                             reusing: MapLayers? = nil) throws -> MapLayers {
        var layers = MapLayers()
        let style = document.style
        guard let calibration = document.calibration else { return layers }
        layers.lightness = try reusing?.lightness ?? PhotoLightness(photo: photo, calibration: calibration)
        let spacing = Int(style.number("grid_spacing", 0))
        if spacing > 0 {
            let step = max(0.05, min(0.5, 180 / .pi / max(calibration.scale, 1)))
            for longitude in stride(from: -180, to: 180, by: spacing) {
                let coordinates = stride(from: -90.0, through: 90.0, by: step).map { ($0, Double(longitude)) }
                layers.grid += projectedLine(coordinates, calibration: calibration, major: longitude == 0, value: Double(longitude), text: longitude == 0 ? "0° lon" : "\(abs(longitude))°\(longitude < 0 ? "W" : "E")")
            }
            for latitude in stride(from: -90 + spacing, to: 90, by: spacing) {
                let coordinates = stride(from: -180.0, through: 180.0, by: step).map { (Double(latitude), $0) }
                layers.grid += projectedLine(coordinates, calibration: calibration, major: latitude == 0, value: Double(latitude), text: latitude == 0 ? "0° lat" : "\(abs(latitude))°\(latitude < 0 ? "S" : "N")")
            }
            var placed = Set<String>(), occupied: [CGRect] = []
            let inset = Double(min(document.imageWidth, document.imageHeight)) * 0.012, size = max(6, Double(min(document.imageWidth, document.imageHeight)) * 0.009)
            for index in layers.grid.indices {
                guard let text = layers.grid[index].text, !placed.contains(text) else { continue }
                let visible = layers.grid[index].points.filter { $0.x >= inset && $0.y >= inset && $0.x < Double(document.imageWidth) - inset && $0.y < Double(document.imageHeight) - inset }
                guard visible.count > 8 else { continue }
                for f in [0.5, 0.4, 0.6, 0.3, 0.7] {
                    let p = visible[Int(Double(visible.count - 1) * f)], rect = CGRect(x: p.x, y: p.y - size, width: size * Double(text.count) * 0.7, height: size * 1.4)
                    if !occupied.contains(where: { $0.intersects(rect) }) { layers.grid[index].captionPosition = p; placed.insert(text); occupied.append(rect); break }
                }
            }
        }
        if style.elevationEnabled || style.contourEnabled {
            guard let dem else { throw MoonError.invalid("高程着色和等高线需要 LOLA DEM。请先下载或导入高程数据。") }
            let ratio = min(1, 768.0 / Double(max(document.imageWidth, document.imageHeight)))
            let width = max(2, Int((Double(document.imageWidth) * ratio).rounded())), height = max(2, Int((Double(document.imageHeight) * ratio).rounded()))
            var heights = [Float](repeating: .nan, count: width * height)
            for y in 0..<height {
                if y % 16 == 0 { try task.check() }
                for x in 0..<width {
                    let pixel = PixelPoint((Double(x) + 0.5) / Double(width) * Double(document.imageWidth), (Double(y) + 0.5) / Double(height) * Double(document.imageHeight))
                    let position = calibration.geometry.unproject(calibration.modelPoint(pixel), terrain: document.state.projectionSurface == "terrain" ? dem : nil)
                    if position.visible { heights[y * width + x] = Float(dem.sample(position.latitude, position.longitude)) }
                }
            }
            let raster = HeightRaster(width: width, height: height, photoWidth: document.imageWidth, photoHeight: document.imageHeight, values: heights, resolutionKM: dem.resolutionKM)
            layers.raster = raster
            if style.elevationEnabled { layers.elevation = colorize(raster, palette: style.string("elevation_palette", "terrain"), photo: photo, style: style) }
            if style.contourEnabled { let interval = style.contourInterval ?? raster.automaticInterval; layers.contourInterval = interval; layers.contours = raster.contours(interval: interval) }
        }
        if style.bool("terminator_enabled") {
            if style.string("terminator_source", "photo") == "photo", let light = layers.lightness {
                let sample = try photo.resized(maximum: 480), gray = sample.gray
                var valid = [UInt8](repeating: 0, count: sample.width * sample.height), vectors = [Double](repeating: 0, count: sample.width * sample.height * 3)
                for y in 0..<sample.height { for x in 0..<sample.width {
                    let p = PixelPoint((Double(x) + 0.5) * Double(document.imageWidth) / Double(sample.width), (Double(y) + 0.5) * Double(document.imageHeight) / Double(sample.height))
                    let position = calibration.geometry.unproject(calibration.modelPoint(p)), index = y * sample.width + x
                    guard position.visible else { continue }
                    let vector = surfaceVector(latitude: position.latitude, longitude: position.longitude)
                    if simd_dot(vector, calibration.geometry.observerVector) > 0.12 { valid[index] = 255; vectors[index * 3] = vector.x; vectors[index * 3 + 1] = vector.y; vectors[index * 3 + 2] = vector.z }
                } }
                var normal = [Double](repeating: 0, count: 3)
                if mn_photo_sun(gray, valid, vectors, Int32(sample.width), Int32(sample.height), &normal) != 0 {
                    layers.terminator = terminator(sun: SIMD3(normal[0], normal[1], normal[2]), calibration: calibration)
                    let samples = layers.terminator.flatMap(\.points).compactMap { p -> Int? in
                        let x = Int(p.x / Double(document.imageWidth) * Double(sample.width)), y = Int(p.y / Double(document.imageHeight) * Double(sample.height))
                        return x >= 0 && y >= 0 && x < sample.width && y < sample.height ? Int(gray[y * sample.width + x]) : nil
                    }.sorted()
                    let domain = gray.enumerated().filter { valid[$0.offset] != 0 }.map(\.element).sorted()
                    if samples.isEmpty || domain.isEmpty || samples[samples.count / 2] > Int(domain[domain.count / 50]) + Int(Double(Int(domain[Int(Double(domain.count - 1) * 0.9)]) - Int(domain[domain.count / 50])) * 0.25) { layers.terminator = [] }
                }
                layers.terminatorUnreliable = layers.terminator.isEmpty
                _ = light
            } else {
                layers.terminator = terminator(sun: calibration.geometry.sunVector, calibration: calibration)
            }
        }
        return layers
    }
    private static func terminator(sun: SIMD3<Double>, calibration: Calibration) -> [MapLine] {
        let axis = simd_normalize(simd_cross(sun, abs(sun.z) > 0.9 ? SIMD3(1, 0, 0) : SIMD3(0, 0, 1))), other = simd_cross(sun, axis)
        let step = max(0.05, min(0.5, 180 / .pi / max(calibration.scale, 1))), count = Int(ceil(360 / step))
        let points = (0...count).map { i -> (Double, Double) in let t = Double(i) / Double(count) * 2 * .pi; return coordinates(cos(t) * axis + sin(t) * other) }
        return projectedLine(points, calibration: calibration)
    }
    public static func projectedLine(_ coordinates: [(Double, Double)], calibration: Calibration, major: Bool = false, value: Double = 0, text: String? = nil) -> [MapLine] {
        var result: [MapLine] = [], current: [PixelPoint] = []
        for (lat, lon) in coordinates {
            let projected = calibration.geometry.project(latitude: lat, longitude: lon)
            if projected.visible { current.append(calibration.photoPoint(projected.point)) }
            else if !current.isEmpty { if current.count > 1 { result.append(MapLine(current, major: major, value: value, text: text)) }; current = [] }
        }
        if current.count > 1 { result.append(MapLine(current, major: major, value: value, text: text)) }
        return result
    }
    public static func colorize(_ raster: HeightRaster, palette: String, photo: PhotoPixels? = nil, style: ProjectStyle = ProjectStyle()) -> PhotoPixels {
        let colors = (palettes[palette] ?? palettes["terrain"]!).map { hex -> [Double] in
            let value = UInt32(hex.dropFirst(), radix: 16)!
            return [Double((value >> 16) & 255), Double((value >> 8) & 255), Double(value & 255)]
        }
        let stops = [-9.0, -4, -1.5, 0, 2, 5, 9]
        let cartographic = (style.art == "topographic" && palette == "wilderness") || (style.art == "redalert" && palette == "redalert")
        var values = raster.values.map(Double.init), shades = [Double](repeating: 1, count: values.count), cliffs = [Double](repeating: 0, count: values.count)
        if cartographic {
            let valid = values.map { $0.isFinite ? 1.0 : 0 }, weights = gaussian(valid, width: raster.width, height: raster.height, sigma: 1.1)
            let blurred = gaussian(values.map { $0.isFinite ? $0 : 0 }, width: raster.width, height: raster.height, sigma: 1.1)
            let smooth = zip(blurred, weights).map { $0 / max(1e-6, $1) }, interval = style.contourInterval ?? raster.automaticInterval
            var dx = shades, dy = shades, slopes: [Double] = []
            for y in 0..<raster.height { for x in 0..<raster.width {
                let i = y * raster.width + x, left = max(0, x - 1), right = min(raster.width - 1, x + 1), top = max(0, y - 1), bottom = min(raster.height - 1, y + 1)
                dx[i] = (smooth[y * raster.width + right] - smooth[y * raster.width + left]) / Double(max(1, right - left))
                dy[i] = (smooth[bottom * raster.width + x] - smooth[top * raster.width + x]) / Double(max(1, bottom - top))
                if valid[i] > 0 { slopes.append(hypot(dx[i], dy[i])) }
                values[i] = (floor(smooth[i] / interval) + 0.5) * interval
            } }
            slopes.sort(); let scale = max(0.01, slopes.isEmpty ? 0 : slopes[Int(Double(slopes.count - 1) * 0.9)])
            for i in shades.indices {
                if style.art == "redalert" { cliffs[i] = min(0.88, max(0, (hypot(dx[i], dy[i]) / scale - 0.55) / 0.65)); shades[i] = min(1.12, max(0.68, 0.97 + (-dx[i] - dy[i]) * 0.14 / scale)) }
                else { shades[i] = min(1.04, max(0.87, 0.97 + (-dx[i] - dy[i]) * 0.045 / scale)) }
            }
        } else if let photo, let sample = try? photo.resized(maximum: max(raster.width, raster.height)) {
            var luminance: [Double] = [], selected: [Double] = []
            for y in 0..<raster.height { for x in 0..<raster.width {
                let i = y * raster.width + x, p = (min(sample.height - 1, y * sample.height / raster.height) * sample.width + min(sample.width - 1, x * sample.width / raster.width)) * 4
                let light = Double(sample.rgba[p]) * 0.2126 + Double(sample.rgba[p + 1]) * 0.7152 + Double(sample.rgba[p + 2]) * 0.0722
                luminance.append(light); if values[i].isFinite { selected.append(light) }
            } }
            selected.sort(); let reference = max(25.5, selected.isEmpty ? 255 : selected[Int(Double(selected.count - 1) * 0.9)]), floor = palette == "wilderness" ? 0.55 : 0.18
            shades = luminance.map { floor + (1 - floor) * min(1, max(0, $0 / reference)) }
        }
        var rgba = [UInt8](repeating: 0, count: raster.values.count * 4)
        for (index, height) in values.enumerated() where raster.values[index].isFinite {
            let h = min(9, max(-9, height)), upper = (1..<stops.count).first { h <= stops[$0] } ?? 6, lower = upper - 1
            let fraction = (h - stops[lower]) / (stops[upper] - stops[lower])
            for channel in 0..<3 {
                var color = colors[lower][channel] * (1 - fraction) + colors[upper][channel] * fraction
                if cliffs[index] > 0 { color = color * (1 - cliffs[index]) + [132.0, 115, 87][channel] * cliffs[index] }
                rgba[index * 4 + channel] = UInt8(min(255, max(0, (color * shades[index]).rounded())))
            }
            rgba[index * 4 + 3] = 255
        }
        return PhotoPixels(width: raster.width, height: raster.height, rgba: rgba)
    }
    private static func gaussian(_ values: [Double], width: Int, height: Int, sigma: Double) -> [Double] {
        let radius = Int(ceil(sigma * 4)), weights = (-Int(ceil(sigma * 4))...Int(ceil(sigma * 4))).map { exp(-Double($0 * $0) / (2 * sigma * sigma)) }
        let norm = weights.reduce(0, +)
        func reflect(_ value: Int, _ size: Int) -> Int { if size <= 1 { return 0 }; let period = 2 * (size - 1), x = (value % period + period) % period; return x < size ? x : period - x }
        var buffer = values, output = values
        for y in 0..<height { for x in 0..<width { buffer[y * width + x] = (-radius...radius).reduce(0) { $0 + values[y * width + reflect(x + $1, width)] * weights[$1 + radius] } / norm } }
        for y in 0..<height { for x in 0..<width { output[y * width + x] = (-radius...radius).reduce(0) { $0 + buffer[reflect(y + $1, height) * width + x] * weights[$1 + radius] } / norm } }
        return output
    }
}

public enum FeatureGeometry {
    public static func ring(_ feature: Feature, factor: Double = 1, heights: [Double]? = nil) -> [(latitude: Double, longitude: Double)] {
        let center = surfaceVector(latitude: feature.latitude, longitude: feature.longitude), lon = feature.longitude * .pi / 180
        let east = SIMD3(-sin(lon), cos(lon), 0), north = simd_cross(center, east)
        let angle = feature.diameter / (2 * moonRadius) * factor
        return (0...96).map { step in let theta = Double(step) / 96 * 2 * .pi; return coordinates(cos(angle) * center + sin(angle) * (cos(theta) * north + sin(theta) * east)) }
    }
}
