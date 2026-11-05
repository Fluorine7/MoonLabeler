// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CoreGraphics
import ImageIO
import CMoonNative
import simd

public final class ComputeTask: @unchecked Sendable {
    public let pointer: OpaquePointer
    public init() { pointer = mn_task_create()! }
    deinit { mn_task_destroy(pointer) }
    public func cancel() { mn_task_cancel(pointer) }
    public var isCancelled: Bool { mn_task_cancelled(pointer) != 0 }
    public func check() throws { if isCancelled { throw CancellationError() } }
}

public struct PhotoPixels: Sendable {
    public let width: Int
    public let height: Int
    public var rgba: [UInt8]
    public init(width: Int, height: Int, rgba: [UInt8]) {
        self.width = width; self.height = height; self.rgba = rgba
    }
    public init(_ image: CGImage, flatten: Bool = true, colorSpace: CGColorSpace? = nil, intent: CGColorRenderingIntent = .defaultIntent) throws {
        width = image.width; height = image.height
        rgba = [UInt8](repeating: 0, count: width * height * 4)
        try rgba.withUnsafeMutableBytes { bytes in
            guard let context = CGContext(data: bytes.baseAddress, width: width, height: height, bitsPerComponent: 8,
                                          bytesPerRow: width * 4, space: colorSpace ?? CGColorSpace(name: CGColorSpace.sRGB)!,
                                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { throw MoonError.invalid("图像内存分配失败。") }
            if flatten { context.setFillColor(CGColor(gray: 0, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: width, height: height)) }
            context.setRenderingIntent(intent)
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        }
    }
    public var cgImage: CGImage {
        let provider = CGDataProvider(data: Data(rgba) as CFData)!
        return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: width * 4,
                       space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                       provider: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent)!
    }
    public var gray: [UInt8] {
        var values = [UInt8](repeating: 0, count: width * height)
        for index in values.indices {
            values[index] = UInt8(min(255, (Int(rgba[index * 4]) * 299 + Int(rgba[index * 4 + 1]) * 587 + Int(rgba[index * 4 + 2]) * 114 + 500) / 1000))
        }
        return values
    }
    func desaturated() -> PhotoPixels {
        let firstColor = rgba.withUnsafeBufferPointer { bytes -> Int? in
            for i in stride(from: 0, to: bytes.count, by: 4) {
                if bytes[i] != bytes[i + 1] || bytes[i] != bytes[i + 2] { return i }
            }
            return nil
        }
        guard let firstColor else { return self }
        var pixels = rgba
        pixels.withUnsafeMutableBufferPointer { bytes in
            for i in stride(from: firstColor, to: bytes.count, by: 4) {
                let gray = UInt8((Int(bytes[i]) * 299 + Int(bytes[i + 1]) * 587 + Int(bytes[i + 2]) * 114 + 500) / 1000)
                bytes[i] = gray; bytes[i + 1] = gray; bytes[i + 2] = gray
            }
        }
        return PhotoPixels(width: width, height: height, rgba: pixels)
    }
    public func resized(maximum: Int) throws -> PhotoPixels {
        let ratio = min(1, Double(maximum) / Double(max(width, height)))
        if ratio == 1 { return self }
        let w = max(1, Int((Double(width) * ratio).rounded())), h = max(1, Int((Double(height) * ratio).rounded()))
        var error = nativeError()
        guard let pointer = mn_resize_rgba(rgba, Int32(width), Int32(height), Int32(w), Int32(h), &error) else { throw failure(error) }
        defer { mn_free(pointer) }
        return PhotoPixels(width: w, height: h, rgba: Array(UnsafeBufferPointer(start: pointer, count: w * h * 4)))
    }
    public func cropped(_ rect: CGRect) throws -> PhotoPixels {
        guard let image = cgImage.cropping(to: rect.integral.intersection(CGRect(x: 0, y: 0, width: width, height: height))) else {
            throw MoonError.invalid("照片裁切范围无效。")
        }
        return try PhotoPixels(image)
    }
    public static func load(_ url: URL) throws -> PhotoPixels {
        if ["fit", "fits", "fts"].contains(url.pathExtension.lowercased()) {
            var w: Int32 = 0, h: Int32 = 0, c: Int32 = 0, error = nativeError()
            guard let pointer = mn_read_fits(url.path, &w, &h, &c, &error) else { throw failure(error) }
            defer { mn_free(pointer) }
            let width = Int(w), height = Int(h), channels = Int(c), size = width * height
            let values = UnsafeBufferPointer(start: pointer, count: size * channels)
            let stretched = try stretch(values)
            var rgba = [UInt8](repeating: 255, count: size * 4)
            for y in 0..<height { for x in 0..<width { for channel in 0..<3 {
                rgba[(y * width + x) * 4 + channel] = stretched[(channels == 1 ? 0 : channel) * size + (height - 1 - y) * width + x]
            } } }
            return PhotoPixels(width: width, height: height, rgba: rgba)
        }
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int, width > 0, height > 0,
              Double(width) * Double(height) <= 160_000_000 else { throw MoonError.invalid("照片无法读取或尺寸超出范围。") }
        let depth = properties[kCGImagePropertyDepth] as? Int ?? 8
        let orientation = PhotoOrientation.value(properties, url: url, source: source)
        if ["jpg", "jpeg"].contains(url.pathExtension.lowercased()), depth <= 8 {
            var w: Int32 = 0, h: Int32 = 0, error = nativeError()
            if let bytes = mn_read_jpeg(url.path, &w, &h, &error) {
                defer { mn_free(bytes) }
                let raw = PhotoPixels(width: Int(w), height: Int(h), rgba: Array(UnsafeBufferPointer(start: bytes, count: Int(w) * Int(h) * 4)))
                return try raw.oriented(orientation)
            }
        }
        if depth <= 8 {
            guard let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { throw MoonError.invalid("照片解码失败。") }
            return try rawDecoded(image).oriented(orientation)
        }
        guard let image = CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldAllowFloat: true] as CFDictionary) else {
            throw MoonError.invalid("无法解码高位深图像。")
        }
        let encoding = image.colorSpace ?? CGColorSpace(name: CGColorSpace.sRGB)!
        let monochrome = encoding.model == .monochrome, channels = monochrome ? 1 : 4
        var floats = [Float](repeating: 0, count: width * height * channels)
        try floats.withUnsafeMutableBytes { bytes in
            let flags = CGBitmapInfo.floatComponents.rawValue | CGBitmapInfo.byteOrder32Little.rawValue | (monochrome ? CGImageAlphaInfo.none.rawValue : CGImageAlphaInfo.premultipliedLast.rawValue)
            guard let context = CGContext(data: bytes.baseAddress, width: width, height: height, bitsPerComponent: 32,
                                          bytesPerRow: width * channels * 4, space: encoding.model == .rgb || monochrome ? encoding : CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: flags) else {
                throw MoonError.invalid("无法读取高位深图像像素。")
            }
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        }
        let sampleChannels = monochrome ? 1 : 3
        let samples = (0..<(width * height * sampleChannels)).lazy.map { index in
            Double(floats[monochrome ? index : (index / 3) * 4 + index % 3])
        }
        let stretched = try stretch(samples)
        var output = [UInt8](repeating: 255, count: width * height * 4)
        for index in 0..<(width * height) { for channel in 0..<3 { output[index * 4 + channel] = stretched[index * sampleChannels + (monochrome ? 0 : channel)] } }
        let raw = PhotoPixels(width: width, height: height, rgba: output)
        return try raw.oriented(orientation)
    }
    func oriented(_ orientation: Int32) throws -> PhotoPixels {
        guard (2...8).contains(orientation) else { return self }
        let swapped = orientation >= 5, w = swapped ? height : width, h = swapped ? width : height
        var output = [UInt8](repeating: 0, count: rgba.count)
        for y in 0..<h { for x in 0..<w {
            let sx: Int, sy: Int
            switch orientation {
            case 2: (sx, sy) = (width - 1 - x, y)
            case 3: (sx, sy) = (width - 1 - x, height - 1 - y)
            case 4: (sx, sy) = (x, height - 1 - y)
            case 5: (sx, sy) = (y, x)
            case 6: (sx, sy) = (y, height - 1 - x)
            case 7: (sx, sy) = (width - 1 - y, height - 1 - x)
            default: (sx, sy) = (width - 1 - y, x)
            }
            for c in 0..<4 { output[(y * w + x) * 4 + c] = rgba[(sy * width + sx) * 4 + c] }
        } }
        return PhotoPixels(width: w, height: h, rgba: output)
    }
    private static func stretch<Values: Collection>(_ values: Values) throws -> [UInt8] where Values.Element == Double {
        var finite = values.filter(\.isFinite)
        finite.sort()
        guard !finite.isEmpty else { throw MoonError.invalid("图像没有有效的数值像素。") }
        func percentile(_ fraction: Double) -> Double {
            let index = Double(finite.count - 1) * fraction, lower = Int(index), f = index - Double(lower)
            return finite[lower] * (1 - f) + finite[min(lower + 1, finite.count - 1)] * f
        }
        let low = percentile(0.002), high = percentile(0.998), span = max(high - low, 1e-9)
        return values.map {
            let sample = $0 == .infinity ? high : $0.isFinite ? $0 : low
            return UInt8(min(255, max(0, (sample - low) / span * 255)))
        }
    }
}

public struct RegistrationResult: Sendable {
    public var matrix: [[Double]]
    public var rms: Double
    public var coverage: Double
    public var matches: Int
    public var source: [PixelPoint]
    public var target: [PixelPoint]
    public var sourceMatches: [PixelPoint]
    public var targetMatches: [PixelPoint]
    public var mirrored: Bool
}
public struct CalibrationReport: Sendable {
    public var matrix: [[Double]]
    public var rms: Double
    public var residuals: [Double]
    public var checkErrors: [Double]
    public var suspect: Int?
}
public struct CraterCandidate: Identifiable, Sendable {
    public var id: Int
    public var center: PixelPoint
    public var major: Double
    public var minor: Double
    public var angle: Double
    public var support: Double
    public var method: String = "EDCircles"
}

func nativeError() -> [CChar] { [CChar](repeating: 0, count: 1024) }
func failure(_ error: [CChar]) -> MoonError { .invalid(String(cString: error)) }
func splitMatrix(_ values: [Double]) -> [[Double]] { [Array(values[0..<3]), Array(values[3..<6])] }
func pointArray(_ pointer: UnsafeMutablePointer<Double>?, _ count: Int) -> [PixelPoint] {
    guard let pointer else { return [] }
    return (0..<count).map { PixelPoint(pointer[$0 * 2], pointer[$0 * 2 + 1]) }
}

public enum NativeCompute {
    public static func gaussian(_ values: [Double], width: Int, height: Int, sigma: Double) -> [Double] {
        guard values.count == width * height, let pointer = mn_gaussian_f64(values, Int32(width), Int32(height), sigma) else { return values }
        defer { mn_free(pointer) }; return Array(UnsafeBufferPointer(start: pointer, count: values.count))
    }
    public static func ellipse(_ points: [PixelPoint]) -> (points: [PixelPoint], center: PixelPoint)? {
        var output = [Double](repeating: 0, count: points.count * 2), center = [Double](repeating: 0, count: 2)
        guard points.count >= 6, points.allSatisfy(\.isFinite), mn_ellipse_outline(points.flatMap { [$0.x, $0.y] }, Int32(points.count), &output, &center) != 0 else { return nil }
        return ((0..<points.count).map { PixelPoint(output[$0 * 2], output[$0 * 2 + 1]) }, PixelPoint(center[0], center[1]))
    }
    public static func ephemeris(utc: String, latitude: Double? = nil, longitude: Double? = nil, kernelDirectory: URL? = nil) throws -> MoonGeometry {
        var error = nativeError(), values = [Double](repeating: 0, count: 13)
        let folder = kernelDirectory ?? Catalog.resourceDirectory
        let delta = TimeScale.deltaT(utc)
        let normalized = UTCClock.parse(utc).map { UTCClock.string($0) } ?? utc
        guard mn_ephemeris(folder.path, normalized, latitude ?? 0, longitude ?? 0, latitude != nil && longitude != nil ? 1 : 0, delta, &values, &error) != 0 else { throw failure(error) }
        return MoonGeometry(native: values, utc: utc)
    }
    public static func fit(source: [PixelPoint], target: [PixelPoint], mirror: Int = -1) throws -> CalibrationReport {
        guard source.count == target.count else { throw MoonError.invalid("参考点数量不一致。") }
        var matrix = [Double](repeating: 0, count: 6), rms = 0.0, residuals = [Double](repeating: 0, count: source.count)
        var checks = residuals, suspect: Int32 = -1, error = nativeError()
        let s = source.flatMap { [$0.x, $0.y] }, t = target.flatMap { [$0.x, $0.y] }
        guard mn_fit_similarity(s, t, Int32(source.count), Int32(mirror), &matrix, &rms, &residuals, &checks, &suspect, &error) != 0 else { throw failure(error) }
        return CalibrationReport(matrix: splitMatrix(matrix), rms: rms, residuals: residuals, checkErrors: checks, suspect: suspect >= 0 ? Int(suspect) : nil)
    }
    public static func quickFit(source: [PixelPoint], target: [PixelPoint], mirror: Int = 0) throws -> ([[Double]], Double) {
        var matrix = [Double](repeating: 0, count: 6), rms = 0.0, suspect: Int32 = -1, error = nativeError()
        guard source.count == target.count,
              mn_fit_similarity(source.flatMap { [$0.x, $0.y] }, target.flatMap { [$0.x, $0.y] }, Int32(source.count), Int32(mirror), &matrix, &rms, nil, nil, &suspect, &error) != 0 else { throw failure(error) }
        return (splitMatrix(matrix), rms)
    }
    public static func match(reference: PhotoPixels, photo: PhotoPixels, mask: [UInt8]? = nil, task: ComputeTask,
                             ratio: Double = 0.75, contrast: Double = 0.02, inlierFraction: Double = 0.35) throws -> RegistrationResult {
        var result = MNMatch(), error = nativeError()
        let masks = mask ?? []
        let status = masks.withUnsafeBufferPointer { buffer in
            mn_match(reference.rgba, Int32(reference.width), Int32(reference.height), 4, photo.rgba, Int32(photo.width), Int32(photo.height), 4,
                     mask == nil ? nil : buffer.baseAddress, ratio, contrast, inlierFraction, task.pointer, &result, &error)
        }
        guard status != 0 else { try task.check(); throw failure(error) }
        defer { mn_match_destroy(&result) }
        let values = withUnsafeBytes(of: result.matrix) { Array($0.bindMemory(to: Double.self)) }
        return RegistrationResult(matrix: splitMatrix(values), rms: result.rms, coverage: result.coverage, matches: Int(result.matches),
                                  source: pointArray(result.source, Int(result.count)), target: pointArray(result.target, Int(result.count)),
                                  sourceMatches: pointArray(result.source_matches, Int(result.matches)), targetMatches: pointArray(result.target_matches, Int(result.matches)), mirrored: result.mirrored != 0)
    }
    public static func detect(photo: PhotoPixels, mask: [UInt8]? = nil, task: ComputeTask, minimum: Double = 8,
                              maximum: Double = 180, count: Int = 80, sensitivity: Double = 50) throws -> [CraterCandidate] {
        var error = nativeError(), found: Int32 = 0
        let masks = mask ?? []
        let result = masks.withUnsafeBufferPointer { buffer in
            mn_detect(photo.rgba, Int32(photo.width), Int32(photo.height), 4, mask == nil ? nil : buffer.baseAddress,
                      minimum, maximum, Int32(count), sensitivity, task.pointer, &found, &error)
        }
        guard let result else { try task.check(); if error[0] != 0 { throw failure(error) }; return [] }
        defer { mn_free(result) }
        return (0..<Int(found)).map { index in
            let c = result[index]
            return CraterCandidate(id: index, center: PixelPoint(c.x, c.y), major: c.major, minor: c.minor, angle: c.angle, support: c.support)
        }
    }
    public static func limb(photo: PhotoPixels, mask: [UInt8]? = nil, task: ComputeTask) throws -> [Double] {
        var error = nativeError(), result = [Double](repeating: 0, count: 5)
        let masks = mask ?? []
        let status = masks.withUnsafeBufferPointer { buffer in
            mn_limb(photo.rgba, Int32(photo.width), Int32(photo.height), 4, mask == nil ? nil : buffer.baseAddress, task.pointer, &result, &error)
        }
        guard status != 0 else { try task.check(); throw failure(error) }; return result
    }
    public static func rims(photo: PhotoPixels, mask: [UInt8]? = nil, task: ComputeTask) throws -> [CraterCandidate] {
        var error = nativeError(), count: Int32 = 0; let masks = mask ?? []
        let result = masks.withUnsafeBufferPointer { buffer in mn_detect_rims(photo.rgba, Int32(photo.width), Int32(photo.height), 4, mask == nil ? nil : buffer.baseAddress, task.pointer, &count, &error) }
        guard let result else { try task.check(); if error[0] != 0 { throw failure(error) }; return [] }; defer { mn_free(result) }
        return (0..<Int(count)).map { i in let c = result[i]; return CraterCandidate(id: i, center: PixelPoint(c.x, c.y), major: c.major, minor: c.minor, angle: c.angle, support: c.support) }
    }
    public static func refine(geometry: MoonGeometry, matrix: [[Double]], match: RegistrationResult,
                              width: Int, height: Int, bound: Double = 1.25, surface: [SIMD3<Double>]? = nil, cameraOnly: Bool = false) throws -> (MoonGeometry, [[Double]], [Double])? {
        var outputGeometry = [Double](repeating: 0, count: 13), outputMatrix = [Double](repeating: 0, count: 6)
        var evidence = [Double](repeating: 0, count: 6), error = nativeError()
        let vertices = surface?.flatMap { [$0.x, $0.y, $0.z] } ?? []
        let status = vertices.withUnsafeBufferPointer { buffer in
            mn_refine_view(geometry.native, matrix.flatMap { $0 }, match.source.flatMap { [$0.x, $0.y] }, match.target.flatMap { [$0.x, $0.y] },
                           surface == nil ? nil : buffer.baseAddress, Int32(match.source.count), Int32(width), Int32(height), bound, cameraOnly ? 1 : 0,
                           &outputGeometry, &outputMatrix, &evidence, &error)
        }
        return status != 0 ? (MoonGeometry(native: outputGeometry, utc: geometry.utc), splitMatrix(outputMatrix), evidence) : nil
    }
    public static func realignedMatch(reference: PhotoPixels, photo: PhotoPixels, coarse: RegistrationResult, mask: [UInt8]?, task: ComputeTask) throws -> RegistrationResult {
        var result = MNMatch(), error = nativeError(); let masks = mask ?? []
        let status = masks.withUnsafeBufferPointer { buffer in
            mn_realign_match(reference.rgba, Int32(reference.width), Int32(reference.height), 4,
                photo.rgba, Int32(photo.width), Int32(photo.height), 4, mask == nil ? nil : buffer.baseAddress,
                coarse.matrix.flatMap { $0 }, task.pointer, &result, &error)
        }
        guard status != 0 else { try task.check(); throw failure(error) }
        defer { mn_match_destroy(&result) }
        let values = withUnsafeBytes(of: result.matrix) { Array($0.bindMemory(to: Double.self)) }
        return RegistrationResult(matrix: splitMatrix(values), rms: result.rms, coverage: result.coverage, matches: Int(result.matches),
            source: pointArray(result.source, Int(result.count)), target: pointArray(result.target, Int(result.count)),
            sourceMatches: pointArray(result.source_matches, Int(result.matches)), targetMatches: pointArray(result.target_matches, Int(result.matches)), mirrored: result.mirrored != 0)
    }
    public static func localMatches(reference: PhotoPixels, photo: PhotoPixels, mask: [UInt8]?, task: ComputeTask) throws -> RegistrationResult? {
        var result = MNMatch(), error = nativeError(); let masks = mask ?? []
        let status = masks.withUnsafeBufferPointer { buffer in mn_local_matches(reference.rgba, photo.rgba, Int32(photo.width), Int32(photo.height), mask == nil ? nil : buffer.baseAddress, task.pointer, &result, &error) }
        guard status != 0 else { try task.check(); return nil }; defer { mn_match_destroy(&result) }
        return RegistrationResult(matrix: [[1, 0, 0], [0, 1, 0]], rms: 0, coverage: result.coverage, matches: Int(result.matches), source: pointArray(result.source, Int(result.count)),
                                  target: pointArray(result.target, Int(result.count)), sourceMatches: [], targetMatches: [], mirrored: false)
    }
}

public enum TimeScale {
    private static let deltaTable: [[Double]] = {
        guard let url = Catalog.resource("delta-t", "json"), let data = try? Data(contentsOf: url),
              let table = try? JSONDecoder().decode([[Double]].self, from: data) else { return [] }
        return table
    }()
    public static func deltaT(_ utc: String) -> Double {
        let parser = ISO8601DateFormatter()
        guard let date = parser.date(from: utc), !deltaTable.isEmpty else { return 69 }
        let jd = date.timeIntervalSince1970 / 86400 + 2440587.5
        var lo = 0, hi = deltaTable.count - 1
        while hi - lo > 1 { let middle = (lo + hi) / 2; if deltaTable[middle][0] <= jd { lo = middle } else { hi = middle } }
        let fraction = min(1, max(0, (jd - deltaTable[lo][0]) / (deltaTable[hi][0] - deltaTable[lo][0])))
        return deltaTable[lo][1] * (1 - fraction) + deltaTable[hi][1] * fraction
    }
}

public enum UTCClock {
    public static func string(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }
    public static func parse(_ string: String) -> Date? {
        let parser = ISO8601DateFormatter()
        if let date = parser.date(from: string) { return date }
        parser.formatOptions.insert(.withFractionalSeconds)
        return parser.date(from: string)
    }
    public static func filenameDate(_ name: String) -> Date? {
        let pattern = #"(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(?:_(\d))?-Moon"#
        guard let regex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive),
              let match = regex.firstMatch(in: name, range: NSRange(name.startIndex..., in: name)) else { return nil }
        let groups = (1...6).map { index -> String in
            guard let range = Range(match.range(at: index), in: name) else { return "0" }
            return String(name[range])
        }
        let second = (Int(groups[5]) ?? 0) * 6
        return parse("\(groups[0])-\(groups[1])-\(groups[2])T\(groups[3]):\(groups[4]):\(String(format: "%02d", second))Z")
    }
}
