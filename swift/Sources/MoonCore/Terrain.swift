// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import simd
import CMoonNative

public let moonRadius = 1737.4
public func surfaceVector(latitude: Double, longitude: Double) -> SIMD3<Double> {
    let lat = latitude * .pi / 180, lon = longitude * .pi / 180
    return SIMD3(cos(lat) * cos(lon), cos(lat) * sin(lon), sin(lat))
}
public func coordinates(_ vector: SIMD3<Double>) -> (Double, Double) {
    let radius = simd_length(vector)
    return (asin(min(1, max(-1, vector.z / radius))) * 180 / .pi, atan2(vector.y, vector.x) * 180 / .pi)
}

public extension MoonGeometry {
    var observerVector: SIMD3<Double> { SIMD3(observer[0], observer[1], observer[2]) }
    var northVector: SIMD3<Double> { SIMD3(north[0], north[1], north[2]) }
    var rightVector: SIMD3<Double> { SIMD3(right[0], right[1], right[2]) }
    var sunVector: SIMD3<Double> { SIMD3(sun[0], sun[1], sun[2]) }
    func project(latitude: Double, longitude: Double, height: Double) -> (point: PixelPoint, visible: Bool, lit: Bool) {
        let vector = surfaceVector(latitude: latitude, longitude: longitude) * (1 + height / moonRadius)
        let depth = simd_dot(vector, observerVector), ratio = moonRadius / distanceKM
        let perspective = 1 - ratio * depth
        return (PixelPoint(simd_dot(vector, rightVector) / perspective, -simd_dot(vector, northVector) / perspective),
                depth > ratio * simd_dot(vector, vector), simd_dot(vector, sunVector) > 0)
    }
    func unproject(_ point: PixelPoint, terrain: ElevationMap? = nil) -> (latitude: Double, longitude: Double, visible: Bool) {
        guard point.isFinite else { return (.nan, .nan, false) }
        let d = distanceKM / moonRadius
        let ray = -observerVector + (point.x * rightVector - point.y * northVector) / d
        let a = simd_dot(ray, ray)
        if let terrain {
            let upper = 1 + 15 / moonRadius, lower = 1 - 15 / moonRadius
            let discriminant = d * d - a * (d * d - upper * upper)
            guard discriminant >= 0 else { return (.nan, .nan, false) }
            let first = (d * d - upper * upper) / (d + sqrt(discriminant))
            let lowDisc = d * d - a * (d * d - lower * lower)
            let last = lowDisc >= 0 ? (d * d - lower * lower) / (d + sqrt(lowDisc)) : d / a
            func sample(_ length: Double) -> (Double, Double, Double) {
                let vector = d * observerVector + length * ray, (lat, lon) = coordinates(vector)
                return (lat, lon, simd_length(vector) - 1 - terrain.sample(lat, lon) / moonRadius)
            }
            var near = first, far = last, previous = first, found = false
            for step in 1...32 {
                let length = first + (last - first) * Double(step) / 32
                if sample(length).2 <= 0 { near = previous; far = length; found = true; break }
                previous = length
            }
            guard found else { return (.nan, .nan, false) }
            for _ in 0..<10 { let middle = (near + far) / 2; if sample(middle).2 > 0 { near = middle } else { far = middle } }
            let (lat, lon, _) = sample((near + far) / 2)
            return (lat, lon, true)
        }
        let discriminant = d * d - a * (d * d - 1)
        guard discriminant >= 0 else { return (.nan, .nan, false) }
        let length = (d * d - 1) / (d + sqrt(discriminant))
        let (lat, lon) = coordinates(d * observerVector + length * ray)
        return (lat, lon, true)
    }
}

public extension Calibration {
    func photoPoint(_ point: PixelPoint) -> PixelPoint {
        let pixel = PixelPoint(matrix[0][0] * point.x + matrix[0][1] * point.y + matrix[0][2],
                               matrix[1][0] * point.x + matrix[1][1] * point.y + matrix[1][2])
        return distortion?.distort(pixel) ?? pixel
    }
    func modelPoint(_ pixel: PixelPoint) -> PixelPoint {
        let point = distortion?.undistort(pixel) ?? pixel
        let determinant = matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
        let x = point.x - matrix[0][2], y = point.y - matrix[1][2]
        return PixelPoint((matrix[1][1] * x - matrix[0][1] * y) / determinant,
                          (-matrix[1][0] * x + matrix[0][0] * y) / determinant)
    }
    var scale: Double { sqrt(abs(matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0])) }
}

public final class ElevationMap: @unchecked Sendable {
    public let identity = UUID()
    public let rows: Int, columns: Int
    public let north: Double, west: Double, pixelsPerDegree: Double, scale: Double
    public let name: String
    public let maximumHeight: Double
    private let storage: NSData
    private let sampleBytes: Int
    private let bigEndian: Bool
    private let globalLongitude: Bool
    public var resolutionKM: Double { .pi * moonRadius / (180 * pixelsPerDegree) }
    public var gpuEligible: Bool { globalLongitude && storage.length <= 64 * 1024 * 1024 }
    public func rawFloats() -> [Float] {
        if sampleBytes == 4 { return Array(UnsafeBufferPointer(start: storage.bytes.assumingMemoryBound(to: Float.self), count: rows * columns)) }
        let bits = storage.bytes.assumingMemoryBound(to: UInt16.self)
        return (0..<(rows * columns)).map { index in Float(Int16(bitPattern: bigEndian ? UInt16(bigEndian: bits[index]) : UInt16(littleEndian: bits[index]))) }
    }

    public init(url: URL) throws {
        if url.pathExtension.lowercased() == "npz" {
            var r: Int32 = 0, c: Int32 = 0, metadata = [Double](repeating: 0, count: 3), error = nativeError()
            guard let pointer = mn_read_npz(url.path, &r, &c, &metadata, &error) else { throw failure(error) }
            defer { mn_free(pointer) }
            rows = Int(r); columns = Int(c); north = metadata[0]; west = metadata[1]; pixelsPerDegree = metadata[2]
            scale = 1; sampleBytes = 4; bigEndian = false; name = url.lastPathComponent
            storage = NSData(bytes: pointer, length: rows * columns * 4)
            let array = UnsafeBufferPointer(start: pointer, count: rows * columns)
            maximumHeight = array.filter(\.isFinite).max().map(Double.init) ?? .infinity
        } else {
            var label = url
            if url.pathExtension.lowercased() == "img" {
                let candidate = url.deletingPathExtension().appendingPathExtension("LBL")
                label = FileManager.default.fileExists(atPath: candidate.path) ? candidate : url.deletingPathExtension().appendingPathExtension("lbl")
            }
            guard label.pathExtension.lowercased() == "lbl" else { throw MoonError.invalid("请选择 LOLA 的 LBL / IMG 或 NPZ 高程数据。") }
            let text = try String(contentsOf: label, encoding: .ascii).replacingOccurrences(of: #"/\*.*?\*/"#, with: "", options: .regularExpression)
            let regex = try NSRegularExpression(pattern: #"(?m)^\s*([\w^]+)\s*=\s*([^\r\n]+)"#)
            var fields: [String: String] = [:]
            for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
                let key = String(text[Range(match.range(at: 1), in: text)!]), value = String(text[Range(match.range(at: 2), in: text)!])
                fields[key] = value.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "\""))
            }
            func value(_ key: String) throws -> String { guard let value = fields[key] else { throw MoonError.invalid("DEM 标签缺少 \(key)。") }; return value }
            func number(_ key: String) throws -> Double {
                guard let n = Double(try value(key).split(separator: " ").first ?? ""), n.isFinite else { throw MoonError.invalid("DEM 的 \(key) 无效。") }; return n
            }
            guard try value("INSTRUMENT_ID").contains("LOLA"), try value("TARGET_NAME") == "MOON",
                  try value("MAP_PROJECTION_TYPE").replacingOccurrences(of: "_", with: " ") == "SIMPLE CYLINDRICAL",
                  try value("POSITIVE_LONGITUDE_DIRECTION") == "EAST", try abs(number("MAP_PROJECTION_ROTATION")) < 1e-9,
                  try value("COORDINATE_SYSTEM_NAME").contains("MEAN EARTH/POLAR AXIS OF DE421"), try value("UNIT") == "METER",
                  try abs(number("OFFSET") - moonRadius * 1000) <= 1, try number("SAMPLE_BITS") == 16 else {
                throw MoonError.invalid("DEM 坐标系、投影、单位或位深与 LOLA DE421 不一致。")
            }
            let sample = try value("SAMPLE_TYPE")
            guard ["LSB_INTEGER", "MSB_INTEGER"].contains(sample) else { throw MoonError.invalid("DEM 必须为 16 位有符号整数。") }
            let imageName = try value("^IMAGE")
            guard !imageName.contains("/"), !imageName.contains("\\"), !imageName.contains("("), !imageName.contains(")") else { throw MoonError.invalid("DEM 必须使用同目录独立 IMG。") }
            let r = try number("LINES"), c = try number("LINE_SAMPLES")
            guard r >= 2, c >= 2, r.rounded() == r, c.rounded() == c, r * c < Double(Int.max / 2) else { throw MoonError.invalid("DEM 尺寸无效。") }
            rows = Int(r); columns = Int(c); north = try number("MAXIMUM_LATITUDE"); west = try number("WESTERNMOST_LONGITUDE")
            pixelsPerDegree = try number("MAP_RESOLUTION"); scale = try number("SCALING_FACTOR") / 1000
            let south = try number("MINIMUM_LATITUDE"), east = try number("EASTERNMOST_LONGITUDE")
            let span = east > west ? east - west : east - west + 360
            guard abs((north - south) * pixelsPerDegree - r) <= 1e-4, abs(span * pixelsPerDegree - c) <= 1e-4 else { throw MoonError.invalid("DEM 边界和分辨率不一致。") }
            var image = label.deletingLastPathComponent().appendingPathComponent(imageName)
            if !FileManager.default.fileExists(atPath: image.path) {
                image = try FileManager.default.contentsOfDirectory(at: label.deletingLastPathComponent(), includingPropertiesForKeys: nil)
                    .first(where: { $0.lastPathComponent.lowercased() == imageName.lowercased() }) ?? image
            }
            storage = try NSData(contentsOf: image, options: .mappedIfSafe)
            guard storage.length == rows * columns * 2 else { throw MoonError.invalid("IMG 长度与 DEM 标签不一致。") }
            bigEndian = sample == "MSB_INTEGER"; sampleBytes = 2; name = try value("PRODUCT_ID")
            if storage.length <= 64 * 1024 * 1024 {
                var maximum = -Double.infinity
                let bytes = storage.bytes.assumingMemoryBound(to: UInt16.self)
                for index in 0..<(rows * columns) { let raw = bigEndian ? UInt16(bigEndian: bytes[index]) : UInt16(littleEndian: bytes[index]); maximum = max(maximum, Double(Int16(bitPattern: raw)) * scale) }
                maximumHeight = maximum
            } else { maximumHeight = .infinity }
        }
        guard pixelsPerDegree.isFinite, pixelsPerDegree > 0, scale.isFinite, scale > 0, north > -90, north <= 90,
              Double(rows) / pixelsPerDegree <= north + 90 + 1e-6, Double(columns) / pixelsPerDegree <= 360 + 1e-6 else {
            throw MoonError.invalid("DEM 经纬度网格无效。")
        }
        globalLongitude = abs(Double(columns) / pixelsPerDegree - 360) < 1e-6
    }
    private func at(_ row: Int, _ column: Int) -> Double {
        let index = row * columns + column
        if sampleBytes == 4 { return Double(storage.bytes.assumingMemoryBound(to: Float.self)[index]) }
        let bits = storage.bytes.assumingMemoryBound(to: UInt16.self)[index]
        return Double(Int16(bitPattern: bigEndian ? UInt16(bigEndian: bits) : UInt16(littleEndian: bits))) * scale
    }
    public func sample(_ latitude: Double, _ longitude: Double) -> Double {
        guard latitude.isFinite, longitude.isFinite else { return .nan }
        var y = (north - latitude) * pixelsPerDegree - 0.5
        var x = ((longitude - west).truncatingRemainder(dividingBy: 360) + 360).truncatingRemainder(dividingBy: 360) * pixelsPerDegree - 0.5
        guard y >= -0.5, y <= Double(rows) - 0.5 else { return .nan }
        if !globalLongitude { guard x >= -0.5, x <= Double(columns) - 0.5 else { return .nan }; x = min(max(x, 0), Double(columns - 1)) }
        y = min(max(y, 0), Double(rows - 1))
        let xx = Int(floor(x)), yy = Int(floor(y)), fx = x - floor(x), fy = y - floor(y)
        let x0 = (xx % columns + columns) % columns, x1 = (x0 + 1) % columns, y1 = min(yy + 1, rows - 1)
        return (1 - fx) * (1 - fy) * at(yy, x0) + fx * (1 - fy) * at(yy, x1) + (1 - fx) * fy * at(y1, x0) + fx * fy * at(y1, x1)
    }
    public func normal(_ latitude: Double, _ longitude: Double) -> SIMD3<Double> {
        let lat = latitude * .pi / 180, lon = longitude * .pi / 180, step = 0.5 / pixelsPerDegree
        let east = SIMD3(-sin(lon), cos(lon), 0), north = SIMD3(-sin(lat) * cos(lon), -sin(lat) * sin(lon), cos(lat))
        let vertical = (sample(latitude + step, longitude) - sample(latitude - step, longitude)) / (2 * step * .pi / 180 * moonRadius)
        let horizontal = (sample(latitude, longitude + step) - sample(latitude, longitude - step)) / (2 * step * .pi / 180 * moonRadius * max(cos(lat), 1e-6))
        return simd_normalize(surfaceVector(latitude: latitude, longitude: longitude) - horizontal * east - vertical * north)
    }
    public func shadow(radial: SIMD3<Double>, height: Double, sun: SIMD3<Double>, steps: Int = 12) -> Bool {
        let start = radial * (moonRadius + height)
        for step in 0..<steps {
            let startDistance = max(0.01, resolutionKM * 0.75)
            let distance = startDistance * pow(80 / startDistance, Double(step) / Double(steps - 1))
            let ray = start + distance * sun, radius = simd_length(ray)
            if radius >= moonRadius + maximumHeight && simd_dot(start, sun) + distance * simd_dot(sun, sun) >= 0 { return false }
            let (lat, lon) = coordinates(ray)
            if radius < moonRadius + sample(lat, lon) - 1e-4 { return true }
        }
        return false
    }
}

public struct TerrainReference: Sendable {
    public var image: PhotoPixels
    public var matrix: [[Double]]
    public var validFraction: Double
    public var resolutionKM: Double
    public var widthKM: Double? = nil
}

public enum ReferenceRenderer {
    public static func calibrated(dem: ElevationMap, calibration: Calibration, width: Int, height: Int, reliefAware: Bool = true,
                                  samplingScale: PixelPoint = PixelPoint(1, 1), task: ComputeTask) throws -> TerrainReference {
        var pixels = [UInt8](repeating: 255, count: width * height * 4), valid = 0
        let geometry = calibration.geometry
        for y in 0..<height {
            if y % 8 == 0 { try task.check() }
            for x in 0..<width {
                let index = (y * width + x) * 4
                pixels[index] = 0; pixels[index + 1] = 0; pixels[index + 2] = 0
                let position = geometry.unproject(calibration.modelPoint(PixelPoint(Double(x) / samplingScale.x, Double(y) / samplingScale.y)), terrain: reliefAware ? dem : nil)
                guard position.visible else { continue }
                let h = dem.sample(position.latitude, position.longitude), radial = surfaceVector(latitude: position.latitude, longitude: position.longitude)
                let normal = dem.normal(position.latitude, position.longitude)
                guard h.isFinite, normal.x.isFinite, normal.y.isFinite, normal.z.isFinite else { continue }
                valid += 1
                let incidence = max(0, simd_dot(normal, geometry.sunVector)), emission = max(0, simd_dot(normal, geometry.observerVector))
                guard incidence > 0, emission > 0, !dem.shadow(radial: radial, height: h, sun: geometry.sunVector, steps: 12) else { continue }
                let brightness = UInt8(min(255, max(0, Float(sqrt(min(1, max(0, 2 * incidence / (incidence + emission + 1e-8)))) * 220))))
                for channel in 0..<3 { pixels[index + channel] = brightness }
            }
        }
        return TerrainReference(image: PhotoPixels(width: width, height: height, rgba: pixels), matrix: calibration.matrix,
                                validFraction: Double(valid) / Double(width * height), resolutionKM: dem.resolutionKM)
    }
    public static func atlas(geometry: MoonGeometry, size: Int = 1600, task: ComputeTask) throws -> TerrainReference {
        guard (1...8192).contains(size) else { throw MoonError.invalid("反照率参考图尺寸无效。") }
        guard let url = Catalog.resource("moon_albedo_2k", "jpg") else { throw MoonError.invalid("缺少月球反照率底图。") }
        let texture = try PhotoPixels.load(url)
        var error = nativeError(), fraction = 0.0
        guard let pixels = mn_albedo_atlas(texture.rgba, Int32(texture.width), Int32(texture.height), geometry.native, Int32(size), task.pointer, &fraction, &error) else {
            try task.check(); throw failure(error)
        }
        defer { mn_free(pixels) }
        return TerrainReference(image: PhotoPixels(width: size, height: size, rgba: Array(UnsafeBufferPointer(start: pixels, count: size * size * 4))),
                                matrix: [[Double(size) * 0.47, 0, Double(size - 1) / 2], [0, Double(size) * 0.47, Double(size - 1) / 2]],
                                validFraction: fraction, resolutionKM: 0)
    }
    public static func overview(geometry: MoonGeometry, size: Int = 320, task: ComputeTask) throws -> TerrainReference {
        guard let url = Catalog.resource("moon_albedo_2k", "jpg") else { throw MoonError.invalid("缺少月球反照率底图。") }
        var texture = try PhotoPixels.load(url); let gray = texture.gray
        for i in gray.indices { for c in 0..<3 { texture.rgba[i * 4 + c] = gray[i] } }
        return try render(geometry: geometry, size: size, matrix: [[Double(size) * 0.47, 0, Double(size - 1) / 2], [0, Double(size) * 0.47, Double(size - 1) / 2]], dem: nil, texture: texture, ambient: 0.045, transparent: true, task: task)
    }
    public static func terrain(dem: ElevationMap, geometry: MoonGeometry, size: Int = 4000, task: ComputeTask) throws -> TerrainReference {
        if let accelerated = try MetalTerrainRenderer.render(dem: dem, geometry: geometry, size: size, task: task) { return accelerated }
        return try render(geometry: geometry, size: size, matrix: [[Double(size) * 0.47, 0, Double(size - 1) / 2], [0, Double(size) * 0.47, Double(size - 1) / 2]], dem: dem, texture: nil, task: task)
    }
    public static func shade(dem: ElevationMap, geometry: MoonGeometry, latitude: Double, longitude: Double) -> UInt8 {
        let radial = surfaceVector(latitude: latitude, longitude: longitude), height = dem.sample(latitude, longitude), normal = dem.normal(latitude, longitude)
        let incidence = max(0, simd_dot(normal, geometry.sunVector)), emission = max(0, simd_dot(normal, geometry.observerVector))
        guard height.isFinite, normal.x.isFinite, normal.y.isFinite, normal.z.isFinite, incidence > 0, emission > 0,
              !dem.shadow(radial: radial, height: height, sun: geometry.sunVector) else { return 0 }
        return UInt8(min(255, max(0, Float(sqrt(min(1, max(0, 2 * incidence / (incidence + emission + 1e-8)))) * 220))))
    }
    public static func region(dem: ElevationMap, geometry: MoonGeometry, latitude: Double, longitude: Double,
                              widthKM: Double = 300, size: Int = 768, gamma: Double = 1.6, lambert: Bool = false,
                              shadows: Bool = true, task: ComputeTask) throws -> TerrainReference {
        let projected = geometry.project(latitude: latitude, longitude: longitude)
        guard projected.visible, simd_dot(surfaceVector(latitude: latitude, longitude: longitude), geometry.observerVector) > 0.2,
              dem.sample(latitude, longitude).isFinite, (10...4200).contains(widthKM), (128...4096).contains(size), (0.3...4).contains(gamma) else {
            throw MoonError.invalid("区域不可见、DEM 不覆盖或模拟参数超出范围。")
        }
        let scale = Double(size) * moonRadius / widthKM
        let matrix = [[scale, 0, Double(size) / 2 - scale * projected.point.x], [0, scale, Double(size) / 2 - scale * projected.point.y]]
        var result = try render(geometry: geometry, size: size, matrix: matrix, dem: dem, texture: nil, gamma: gamma, lambert: lambert, shadows: shadows, regional: true, task: task)
        result.widthKM = widthKM
        guard result.validFraction >= 0.5 else { throw MoonError.invalid("DEM 有效覆盖不足一半，请缩小视野或更换数据。") }
        return result
    }
    private static func render(geometry: MoonGeometry, size: Int, matrix: [[Double]], dem: ElevationMap?, texture: PhotoPixels?,
                                gamma: Double = 2, lambert: Bool = false, shadows: Bool = true, regional: Bool = false, ambient: Double = 0, transparent: Bool = false,
                                task: ComputeTask) throws -> TerrainReference {
        var pixels = [UInt8](repeating: transparent ? 0 : 255, count: size * size * 4), valid = 0
        let scale = matrix[0][0]
        for row in 0..<size {
            if row % 16 == 0 { try task.check() }
            for column in 0..<size {
                let point = PixelPoint((Double(column) + (regional ? 0.5 : 0) - matrix[0][2]) / scale,
                                       (Double(row) + (regional ? 0.5 : 0) - matrix[1][2]) / scale)
                let (lat, lon, visible) = geometry.unproject(point)
                let index = (row * size + column) * 4
                pixels[index] = 0; pixels[index + 1] = 0; pixels[index + 2] = 0
                guard visible else { continue }
                pixels[index + 3] = 255
                let radial = surfaceVector(latitude: lat, longitude: lon), h = dem?.sample(lat, lon) ?? 0
                let normal = dem?.normal(lat, lon) ?? radial
                guard h.isFinite, normal.x.isFinite, normal.y.isFinite, normal.z.isFinite else { continue }
                valid += 1
                let view = regional ? simd_normalize(geometry.observerVector * geometry.distanceKM - radial * (moonRadius + h)) : geometry.observerVector
                let incidence = max(0, simd_dot(normal, geometry.sunVector)), emission = max(0, simd_dot(normal, view))
                guard ambient > 0 || (incidence > 0 && emission > 0) else { continue }
                if shadows, let dem, dem.shadow(radial: radial, height: h, sun: geometry.sunVector, steps: regional ? 32 : 12) { continue }
                let light = lambert ? incidence : incidence / max(incidence + emission, 1e-8)
                let luminance = ambient + (1 - ambient) * pow(min(1, max(0, light * (regional ? (lambert ? 1 : 1.8) : 2))), 1 / gamma)
                if let texture {
                    let xx = (lon + 180) / 360 * Double(texture.width) - 0.5, yy = (90 - lat) / 180 * Double(texture.height) - 0.5
                    let x0 = Int(floor(xx)), y0 = Int(floor(yy)), fx = xx - floor(xx), fy = yy - floor(yy)
                    for channel in 0..<3 {
                        func at(_ x: Int, _ y: Int) -> Double {
                            let x = (x % texture.width + texture.width) % texture.width, y = (y % texture.height + texture.height) % texture.height
                            return Double(texture.rgba[(y * texture.width + x) * 4 + channel])
                        }
                        let color = (1 - fx) * (1 - fy) * at(x0, y0) + fx * (1 - fy) * at(x0 + 1, y0) + (1 - fx) * fy * at(x0, y0 + 1) + fx * fy * at(x0 + 1, y0 + 1)
                        pixels[index + channel] = UInt8(min(255, max(0, color * luminance)))
                    }
                } else { let gray = UInt8(min(255, max(0, luminance * (regional ? 255 : 220)))); for channel in 0..<3 { pixels[index + channel] = gray } }
            }
        }
        return TerrainReference(image: PhotoPixels(width: size, height: size, rgba: pixels), matrix: matrix,
                                validFraction: Double(valid) / Double(size * size), resolutionKM: dem?.resolutionKM ?? 0)
    }
}
