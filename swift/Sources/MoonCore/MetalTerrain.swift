// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import Metal

public enum MetalTerrainRenderer {
    private static let lock = NSLock()
    private static let device = MTLCreateSystemDefaultDevice()
    private static var pipeline: MTLComputePipelineState?
    private static var failureMessage = ""
    public static var diagnostic: String { lock.lock(); defer { lock.unlock() }; return failureMessage }
    public static var available: Bool { device != nil }
    public static var deviceName: String { device?.name ?? "CPU" }
    public static func render(dem: ElevationMap, geometry: MoonGeometry, size: Int, task: ComputeTask) throws -> TerrainReference? {
        if ComputePolicy.current.mode == "cpu" { return nil }
        guard size >= 512, dem.gpuEligible, let device else { return nil }
        lock.lock(); defer { lock.unlock() }
        do {
            if pipeline == nil {
                guard let url = Catalog.resource("terrain-kernel", "txt") else { return nil }
                let library = try device.makeLibrary(source: String(contentsOf: url, encoding: .utf8), options: nil)
                guard let function = library.makeFunction(name: "moon_terrain") else { return nil }
                pipeline = try device.makeComputePipelineState(function: function)
            }
            guard let pipeline, let queue = device.makeCommandQueue() else { return nil }
            let values = dem.rawFloats()
            guard let demBuffer = device.makeBuffer(bytes: values, length: values.count * 4, options: .storageModeShared) else { return nil }
            var params: [Float] = [Float(dem.rows), Float(dem.columns), Float(dem.north), Float(dem.west), Float(dem.pixelsPerDegree), Float(dem.scale),
                                   Float(moonRadius), Float(moonRadius + dem.maximumHeight)]
            params += geometry.sun.map(Float.init) + geometry.observer.map(Float.init)
            let startDistance = max(0.01, dem.resolutionKM * 0.75)
            let distances = (0..<12).map { Float(startDistance * pow(80 / startDistance, Double($0) / 11)) }
            guard let paramsBuffer = device.makeBuffer(bytes: params, length: params.count * 4, options: .storageModeShared),
                  let distanceBuffer = device.makeBuffer(bytes: distances, length: distances.count * 4, options: .storageModeShared) else { return nil }
            var rgba = [UInt8](repeating: 255, count: size * size * 4), valid = 0
            for index in 0..<(size * size) { rgba[index * 4] = 0; rgba[index * 4 + 1] = 0; rgba[index * 4 + 2] = 0 }
            let scale = Double(size) * 0.47, center = Double(size - 1) / 2
            for first in stride(from: 0, to: size, by: 64) {
                try task.check()
                var indices: [Int] = [], coordinates: [Float] = [], exact: [(Double, Double)] = []
                indices.reserveCapacity(size * 64); coordinates.reserveCapacity(size * 64 * 6)
                for y in first..<min(size, first + 64) { for x in 0..<size {
                    let position = geometry.unproject(PixelPoint((Double(x) - center) / scale, (Double(y) - center) / scale))
                    guard position.visible else { continue }
                    let lat = position.latitude, lon = position.longitude
                    let rawX = ((lon - dem.west).truncatingRemainder(dividingBy: 360) + 360).truncatingRemainder(dividingBy: 360) * dem.pixelsPerDegree - 0.5
                    let rawY = (dem.north - lat) * dem.pixelsPerDegree - 0.5
                    indices.append(y * size + x); exact.append((lat, lon))
                    coordinates.append(contentsOf: [Float(lat), Float(lon), Float(floor(rawX)), Float(floor(rawY)), Float(rawX - floor(rawX)), Float(rawY - floor(rawY))])
                } }
                if indices.isEmpty { continue }
                let shape: [UInt32] = [UInt32(indices.count)]
                guard let coordsBuffer = device.makeBuffer(bytes: coordinates, length: coordinates.count * 4, options: .storageModeShared),
                      let shapeBuffer = device.makeBuffer(bytes: shape, length: 4, options: .storageModeShared),
                      let output = device.makeBuffer(length: indices.count, options: .storageModeShared),
                      let repair = device.makeBuffer(length: indices.count, options: .storageModeShared),
                      let command = queue.makeCommandBuffer(), let encoder = command.makeComputeCommandEncoder() else { return nil }
                encoder.setComputePipelineState(pipeline)
                for (index, buffer) in [demBuffer, coordsBuffer, paramsBuffer, distanceBuffer, shapeBuffer, output, repair].enumerated() { encoder.setBuffer(buffer, offset: 0, index: index) }
                let group = min(256, pipeline.maxTotalThreadsPerThreadgroup)
                encoder.dispatchThreads(MTLSize(width: indices.count, height: 1, depth: 1), threadsPerThreadgroup: MTLSize(width: group, height: 1, depth: 1))
                encoder.endEncoding(); command.commit(); command.waitUntilCompleted()
                if let error = command.error { throw error }; try task.check()
                let pixels = output.contents().assumingMemoryBound(to: UInt8.self), repairs = repair.contents().assumingMemoryBound(to: UInt8.self)
                for i in indices.indices {
                    let brightness = repairs[i] != 0 ? ReferenceRenderer.shade(dem: dem, geometry: geometry, latitude: exact[i].0, longitude: exact[i].1) : pixels[i]
                    for channel in 0..<3 { rgba[indices[i] * 4 + channel] = brightness }
                }
                valid += indices.count
            }
            return TerrainReference(image: PhotoPixels(width: size, height: size, rgba: rgba), matrix: [[scale, 0, center], [0, scale, center]],
                                    validFraction: Double(valid) / Double(size * size), resolutionKM: dem.resolutionKM)
        } catch is CancellationError { throw CancellationError() }
        catch { failureMessage = error.localizedDescription; return nil }
    }
}
