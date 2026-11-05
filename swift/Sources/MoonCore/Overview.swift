// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import simd
import CMoonNative

public struct PhotoOverview: Sendable {
    public var image: PhotoPixels
    public var footprint: [[PixelPoint]]
    public var grid: [MapLine]
    public var latitude: Double, longitude: Double
    public var north: PixelPoint?, south: PixelPoint?, earth: PixelPoint?
    public var northBearing = PixelPoint(0, -1)
}

public enum OverviewBuilder {
    public static func build(document: MoonDocument, size: Int = 320, task: ComputeTask) throws -> PhotoOverview? {
        guard let camera = document.calibration else { return nil }
        var total = SIMD3<Double>.zero
        for y in 0..<32 { for x in 0..<32 {
            let pixel = PixelPoint(0.5 + Double(x) / 31 * Double(document.imageWidth - 1), 0.5 + Double(y) / 31 * Double(document.imageHeight - 1))
            let p = camera.geometry.unproject(camera.modelPoint(pixel))
            if p.visible { total += surfaceVector(latitude: p.latitude, longitude: p.longitude) }
        } }
        let observer = simd_length(total) > 1e-8 ? simd_normalize(total) : camera.geometry.observerVector
        let view = camera.geometry
        let reference = try ReferenceRenderer.overview(geometry: view, size: size, task: task), globe = Calibration(geometry: view, matrix: reference.matrix)
        var mask = [UInt8](repeating: 0, count: size * size)
        for y in 0..<size {
            if y % 32 == 0 { try task.check() }
            for x in 0..<size {
                let p = view.unproject(globe.modelPoint(PixelPoint(Double(x), Double(y))))
                guard p.visible else { continue }
                let projected = camera.geometry.project(latitude: p.latitude, longitude: p.longitude), pixel = camera.photoPoint(projected.point)
                if projected.visible && pixel.x >= 0 && pixel.y >= 0 && pixel.x <= Double(document.imageWidth) && pixel.y <= Double(document.imageHeight) { mask[y * size + x] = 1 }
            }
        }
        var error = nativeError()
        guard let pointer = mn_binary_contours(mask, Int32(size), Int32(size), &error) else { throw failure(error) }
        defer { mn_free(pointer) }
        let arrays = try JSONDecoder().decode([[[Double]]].self, from: Data(String(cString: pointer).utf8))
        let footprint = arrays.map { $0.map { PixelPoint($0[0], $0[1]) } }
        var grid: [MapLine] = []
        for lon in stride(from: -180.0, to: 180, by: 30) { grid += MapBuilder.projectedLine(stride(from: -90.0, through: 90, by: 0.5).map { ($0, lon) }, calibration: globe) }
        for lat in stride(from: -60.0, through: 60, by: 30) { grid += MapBuilder.projectedLine(stride(from: -180.0, through: 180, by: 0.5).map { (lat, $0) }, calibration: globe) }
        func marker(_ vector: SIMD3<Double>) -> PixelPoint? { let p = coordinates(vector), q = view.project(latitude: p.0, longitude: p.1); return q.visible ? globe.photoPoint(q.point) : nil }
        let center = coordinates(observer)
        let bearing = SIMD2(camera.geometry.rightVector.z, -camera.geometry.northVector.z)
        let direction = simd_length(bearing) > 1e-12 ? simd_normalize(bearing) : SIMD2<Double>(0, -1)
        return PhotoOverview(image: tinted(reference.image, style: document.style.art), footprint: footprint, grid: grid, latitude: center.0, longitude: center.1,
                             north: marker(SIMD3(0, 0, 1)), south: marker(SIMD3(0, 0, -1)), earth: nil, northBearing: PixelPoint(direction.x, direction.y))
    }
    private static func tinted(_ image: PhotoPixels, style: String) -> PhotoPixels {
        let themes: [String: [UInt32]] = ["manuscript": [0x0c1722, 0x607580, 0xebd3a1], "topographic": [0x101710, 0x7a8053, 0xddc38e],
            "cyanotype": [0x071629, 0x346b95, 0xd7eeea], "copperplate": [0x101f20, 0x53817c, 0xe8c59c], "inkwash": [0x142225, 0x7e9292, 0xeee5ce], "redalert": [0x0c1a12, 0x65804c, 0xdbc18c]]
        guard let stops = themes[style] else { return image }; var result = image
        for i in 0..<(image.width * image.height) where image.rgba[i * 4 + 3] > 0 {
            let value = Double(image.rgba[i * 4]), index = value < 110 ? 0 : 1, fraction = value < 110 ? value / 110 : (value - 110) / 145
            for channel in 0..<3 { let shift = UInt32((2 - channel) * 8), a = Double((stops[index] >> shift) & 255), b = Double((stops[index + 1] >> shift) & 255); result.rgba[i * 4 + channel] = UInt8((a * (1 - fraction) + b * fraction).rounded()) }
        }
        return result
    }
}
