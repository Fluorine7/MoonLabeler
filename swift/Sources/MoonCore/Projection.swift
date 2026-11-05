// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

public struct MoonGeometry: Codable, Equatable, Sendable {
    public var observer: [Double]
    public var right: [Double]
    public var north: [Double]
    public var sun: [Double]
    public var distanceKM: Double
    public var utc: String
    public init(native: [Double], utc: String) {
        observer = Array(native[0..<3]); right = Array(native[3..<6]); north = Array(native[6..<9])
        sun = Array(native[9..<12]); distanceKM = native[12]; self.utc = utc
    }
    public var native: [Double] { observer + right + north + sun + [distanceKM] }
    enum CodingKeys: String, CodingKey {
        case observer, right, north, sun, utc
        case distanceKM = "distance_km"
    }

    public func validate() throws {
        let vectors = [observer, right, north, sun]
        guard distanceKM.isFinite, distanceKM > 1737.4,
              vectors.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }),
              vectors.allSatisfy({ abs(Self.dot($0, $0) - 1) < 0.01 }),
              abs(Self.dot(observer, north)) < 0.01,
              abs(Self.dot(observer, right)) < 0.01,
              abs(Self.dot(north, right)) < 0.01 else {
            throw MoonError.invalid("工程的月球投影参数无效。")
        }
    }

    // Same finite-distance spherical projection and top-left pixel convention as geometry.py.
    public func project(latitude: Double, longitude: Double) -> (point: PixelPoint, visible: Bool, lit: Bool) {
        let lat = latitude * .pi / 180, lon = longitude * .pi / 180
        let vector = [cos(lat) * cos(lon), cos(lat) * sin(lon), sin(lat)]
        let depth = Self.dot(vector, observer)
        let ratio = 1737.4 / distanceKM
        let perspective = 1 - ratio * depth
        return (PixelPoint(Self.dot(vector, right) / perspective, -Self.dot(vector, north) / perspective),
                depth > ratio, Self.dot(vector, sun) > 0)
    }
    private static func dot(_ a: [Double], _ b: [Double]) -> Double {
        zip(a, b).reduce(0) { $0 + $1.0 * $1.1 }
    }
}

public struct LensDistortion: Codable, Equatable, Sendable {
    public var center: [Double]
    public var scale: Double
    public var k: Double
    public var k2: Double? = nil

    public func distort(_ point: PixelPoint) -> PixelPoint {
        let x = (point.x - center[0]) / scale, y = (point.y - center[1]) / scale, squared = x * x + y * y
        let radial = (k * squared + (k2 ?? 0) * squared * squared) * scale
        return PixelPoint(point.x + x * radial, point.y + y * radial)
    }
    public func undistort(_ point: PixelPoint) -> PixelPoint {
        let second = k2 ?? 0
        guard k != 0 || second != 0 else { return point }
        let x = (point.x - center[0]) / scale, y = (point.y - center[1]) / scale, radius = hypot(x, y)
        guard radius.isFinite else { return PixelPoint(.nan, .nan) }
        var original: Double
        if second == 0 {
            original = min(radius, cbrt(radius / k))
            for _ in 0..<12 { original -= (original + k * original * original * original - radius) / (1 + 3 * k * original * original) }
        } else {
            var upper: Double
            if second < 0 {
                let turn = sqrt((3 * k + sqrt(9 * k * k - 20 * second)) / (-10 * second))
                upper = min(radius * 1.25, turn * (1 - 1e-10))
            } else {
                upper = min(radius, pow(radius / second, 0.2))
                if k != 0 { upper = min(upper, cbrt(radius / k)) }
            }
            let squared = upper * upper, maximum = upper * (1 + k * squared + second * squared * squared)
            guard radius <= maximum else { return PixelPoint(.nan, .nan) }
            var lower = 0.0; original = min(radius, upper * 0.9)
            for _ in 0..<24 {
                let squared = original * original, residual = original * (1 + k * squared + second * squared * squared) - radius
                if residual < 0 { lower = original }; if residual > 0 { upper = original }
                let trial = original - residual / (1 + 3 * k * squared + 5 * second * squared * squared)
                original = trial.isFinite && trial >= lower && trial <= upper ? trial : (lower + upper) / 2
            }
        }
        let ratio = original / max(radius, 1e-30)
        return PixelPoint(center[0] + x * ratio * scale, center[1] + y * ratio * scale)
    }
    public func areaScale(at point: PixelPoint) -> Double {
        let x = (point.x - center[0]) / scale, y = (point.y - center[1]) / scale, squared = x * x + y * y
        let second = (k2 ?? 0) * squared * squared
        return (1 + k * squared + second) * (1 + 3 * k * squared + 5 * second)
    }
}

public struct Calibration: Codable, Equatable, Sendable {
    public var geometry: MoonGeometry
    public var matrix: [[Double]]
    public var distortion: LensDistortion?

    public init(geometry: MoonGeometry, matrix: [[Double]], distortion: LensDistortion? = nil) {
        self.geometry = geometry; self.matrix = matrix; self.distortion = distortion
    }

    public func validate() throws {
        try geometry.validate()
        guard matrix.count == 2, matrix.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }),
              abs(matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]) > 1e-10 else {
            throw MoonError.invalid("工程的配准矩阵无效。")
        }
        if let d = distortion {
            guard d.center.count == 2, d.center.allSatisfy(\.isFinite),
                  d.scale.isFinite, d.scale >= 1, d.k.isFinite, (0...0.6).contains(d.k),
                  (d.k2 ?? 0).isFinite, (-0.3...0.3).contains(d.k2 ?? 0) else {
                throw MoonError.invalid("工程的镜头畸变参数无效。")
            }
        }
    }

    public func project(_ feature: Feature) -> (point: PixelPoint, visible: Bool, lit: Bool) {
        let result = geometry.project(latitude: feature.latitude, longitude: feature.longitude)
        return (photoPoint(result.point), result.visible, result.lit)
    }
}
