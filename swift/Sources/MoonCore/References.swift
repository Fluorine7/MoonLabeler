// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import ImageIO
import simd
import CMoonNative

public enum ReferenceIO {
    public static func nasa(utc: String, task: ComputeTask, directory: URL? = nil) async throws -> (TerrainReference, MoonGeometry) {
        guard let date = UTCClock.parse(utc) else { throw MoonError.invalid("UTC 时间格式无效。") }
        let beginning = UTCClock.parse("2026-01-01T00:00:00Z")!, index = Int(floor(date.timeIntervalSince(beginning) / 3600))
        guard (0..<8760).contains(index) else { throw MoonError.invalid("当前 NASA 自动参考支持 2026 年；其他年份可选择已校准的本地参考工程。") }
        let root = (directory ?? DataStore.cache).appendingPathComponent("nasa-2026", isDirectory: true)
        let base = URL(string: "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/")!
        let info = try await DataStore.download(base.appendingPathComponent("mooninfo_2026.json"), to: root.appendingPathComponent("mooninfo.json"), task: task)
        let records = try JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: info)).array
        guard records.indices.contains(index) else { throw MoonError.invalid("NASA 星历记录不完整。") }
        let geometry = try nasaGeometry(record: records[index].object, utc: UTCClock.string(beginning.addingTimeInterval(Double(index) * 3600)))
        let frames = base.appendingPathComponent("frames/3840x2160_16x9_30p/plain/")
        let listingURL = try await DataStore.download(frames, to: root.appendingPathComponent("frames.html"), task: task)
        let listing = try String(contentsOf: listingURL, encoding: .utf8)
        let regex = try NSRegularExpression(pattern: "href=[\"']([^\"']*moon\\.\\d+\\.(?:tif|png|jpg))[\"']", options: .caseInsensitive)
        guard let match = regex.firstMatch(in: listing, range: NSRange(listing.startIndex..., in: listing)), let range = Range(match.range(at: 1), in: listing) else {
            throw MoonError.invalid("NASA 参考影像目录格式已改变。请使用本地参考工程。")
        }
        let sample = String(listing[range]), frame = sample.replacingOccurrences(of: "moon\\.\\d+", with: String(format: "moon.%04d", index + 1), options: .regularExpression)
        guard let url = URL(string: frame, relativeTo: frames)?.absoluteURL else { throw MoonError.invalid("NASA 参考地址无效。") }
        let imageURL = try await DataStore.download(url, to: root.appendingPathComponent(url.lastPathComponent), task: task)
        try task.check()
        guard let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil), let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { throw MoonError.invalid("NASA 影像无法读取。") }
        let pixels = try PhotoPixels(image, flatten: false)
        var disk = [Double](repeating: 0, count: 3), error = nativeError()
        guard mn_reference_disk(pixels.rgba, Int32(pixels.width), Int32(pixels.height), &disk, &error) != 0 else { throw failure(error) }
        let scale = disk[2] * sqrt(1 - pow(moonRadius / geometry.distanceKM, 2))
        return (TerrainReference(image: try PhotoPixels(image), matrix: [[scale, 0, disk[0]], [0, scale, disk[1]]], validFraction: .pi * disk[2] * disk[2] / Double(pixels.width * pixels.height), resolutionKM: 0), geometry)
    }
    public static func nasaGeometry(record: [String: JSONValue], utc: String) throws -> MoonGeometry {
        let earth = record["subearth"]?.object ?? [:], solar = record["subsolar"]?.object ?? [:]
        guard let lat = earth["lat"]?.number, let lon = earth["lon"]?.number,
              let slat = solar["lat"]?.number, let slon = solar["lon"]?.number,
              let angle = record["posangle"]?.number, let distance = record["distance"]?.number else { throw MoonError.invalid("NASA 星历记录格式无效。") }
        let observer = surfaceVector(latitude: lat, longitude: lon), lunarNorth = simd_normalize(SIMD3<Double>(0, 0, 1) - observer.z * observer)
        let north = cos(angle * .pi / 180) * lunarNorth + sin(angle * .pi / 180) * simd_normalize(simd_cross(lunarNorth, observer))
        let right = simd_normalize(simd_cross(north, observer)), sun = surfaceVector(latitude: slat, longitude: slon)
        let geometry = MoonGeometry(native: [observer.x, observer.y, observer.z, right.x, right.y, right.z, north.x, north.y, north.z, sun.x, sun.y, sun.z, distance], utc: utc)
        try geometry.validate(); return geometry
    }
    public static func local(_ url: URL, utc: String) throws -> (TerrainReference, MoonDocument) {
        var document = try ProjectIO.read(url).document
        guard let camera = document.calibration else { throw MoonError.invalid("参考工程未配准。") }
        guard camera.distortion == nil else { throw MoonError.invalid("此参考工程含目镜畸变校正，请对当前照片使用自动识别。") }
        guard let requested = UTCClock.parse(utc), let referenceDate = UTCClock.parse(document.state.utc), abs(requested.timeIntervalSince(referenceDate)) <= 3600 else {
            throw MoonError.invalid("参考工程与当前拍摄时间相差超过一小时，请先设置为相同拍摄时刻。不同日期的天平动不能用同一平面变换处理。")
        }
        let photo = try PhotoPixels.load(URL(fileURLWithPath: document.imagePath))
        document.imageWidth = photo.width; document.imageHeight = photo.height
        return (TerrainReference(image: photo, matrix: camera.matrix, validFraction: 1, resolutionKM: 0), document)
    }
    public static func save(_ reference: TerrainReference, geometry: MoonGeometry, state: ProjectState, to url: URL) throws {
        guard let destination = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil) else { throw MoonError.invalid("无法写入参考图。") }
        CGImageDestinationAddImage(destination, reference.image.cgImage, nil)
        guard CGImageDestinationFinalize(destination) else { throw MoonError.invalid("参考图写入失败。") }
        var document = MoonDocument(imagePath: url.path)
        document.imageWidth = reference.image.width; document.imageHeight = reference.image.height
        document.state.utc = geometry.utc; document.state.geometry = geometry
        document.state.latitude = state.latitude; document.state.longitude = state.longitude
        document.state.terrainPath = state.terrainPath; document.state.terrainSettings = state.terrainSettings
        document.calibration = Calibration(geometry: geometry, matrix: reference.matrix)
        document.settings.minimumDiameter = 5
        try ProjectCompatibility.writeLegacy(document, to: url.deletingPathExtension().appendingPathExtension("moonlabel"))
    }
}
