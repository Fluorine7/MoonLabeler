// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import simd
import CMoonNative

enum EyepieceEdgeRefinement {
    static func needed(_ result: IdentificationResult) -> Bool {
        guard let lens = result.calibration.distortion, lens.k >= 0.08 else { return false }
        let error = result.details["limb_p95_px"]?.number ?? 0
        return error.isFinite && error > max(3, lens.scale * 0.004)
    }
    static func refine(photo: PhotoPixels, geometry: MoonGeometry, atlas: TerrainReference, match: RegistrationResult,
                       accepted: IdentificationResult, dem: ElevationMap?, mask: [UInt8]?, task: ComputeTask,
                       progress: @Sendable (String) -> Void) throws -> IdentificationResult {
        guard needed(accepted), simd_dot(geometry.observerVector, geometry.sunVector) <= 0.98 else { return accepted }
        try task.check()
        var result = accepted
        guard let dem else {
            result.details["edge_refinement"] = .object(["status": .string("unavailable"), "reason": .string("高程数据不可用，未完成边缘精校。")])
            return result
        }
        do {
            progress("正在独立验证目镜边缘精校…")
            guard let lens = accepted.calibration.distortion else { throw MoonError.invalid("缺少目镜畸变校正。") }
            let factor = min(1, 1800 / Double(max(photo.width, photo.height)))
            let width = Int((Double(photo.width) * factor).rounded(.toNearestOrEven)), height = Int((Double(photo.height) * factor).rounded(.toNearestOrEven))
            let reference = try ReferenceRenderer.calibrated(dem: dem, calibration: accepted.calibration, width: width, height: height,
                                                            reliefAware: false, samplingScale: PixelPoint(Double(width) / Double(photo.width), Double(height) / Double(photo.height)), task: task)
            var pairs = MNMatch(), error = nativeError(); let masks = mask ?? []
            let gray = reference.image.gray
            let paired = masks.withUnsafeBufferPointer { buffer in
                mn_eyepiece_edge_matches(gray, Int32(width), Int32(height), photo.rgba, Int32(photo.width), Int32(photo.height),
                                         mask == nil ? nil : buffer.baseAddress, max(12, lens.scale * 0.03), task.pointer, &pairs, &error)
            }
            guard paired != 0 else { try task.check(); throw failure(error) }
            defer { mn_match_destroy(&pairs) }
            let source = pointArray(pairs.source, Int(pairs.count)), target = pointArray(pairs.target, Int(pairs.count))
            var combinedSource = match.sourceMatches, combinedTarget = match.targetMatches
            let map = Calibration(geometry: geometry, matrix: atlas.matrix)
            for (source, target) in zip(source, target) {
                let position = accepted.calibration.geometry.unproject(accepted.calibration.modelPoint(source))
                guard position.visible else { continue }
                let point = geometry.project(latitude: position.latitude, longitude: position.longitude).point
                combinedSource.append(map.photoPoint(point)); combinedTarget.append(target)
            }
            guard let offsets = accepted.details["view_offset_deg"]?.array.compactMap(\.number), offsets.count == 2 else {
                throw MoonError.invalid("目镜校正缺少初始视向参数。")
            }
            var updatedGeometry = [Double](repeating: 0, count: 13), matrix = [Double](repeating: 0, count: 6)
            var updatedLens = [Double](repeating: 0, count: 5), evidence = [Double](repeating: 0, count: 14), folds = [Double](repeating: 0, count: 36)
            let status = masks.withUnsafeBufferPointer { buffer in
                mn_refine_eyepiece_edges(geometry.native, atlas.matrix.flatMap { $0 }, accepted.calibration.matrix.flatMap { $0 },
                    lens.center + [lens.scale, lens.k], offsets, combinedSource.flatMap { [$0.x, $0.y] }, combinedTarget.flatMap { [$0.x, $0.y] },
                    Int32(match.sourceMatches.count), Int32(combinedSource.count), photo.rgba, Int32(photo.width), Int32(photo.height), mask == nil ? nil : buffer.baseAddress,
                    task.pointer, &updatedGeometry, &matrix, &updatedLens, &evidence, &folds, &error)
            }
            try task.check()
            if status == 2 { return accepted }
            guard status == 1 else { throw failure(error) }
            result.calibration = Calibration(geometry: MoonGeometry(native: updatedGeometry, utc: geometry.utc), matrix: splitMatrix(matrix),
                                             distortion: LensDistortion(center: Array(updatedLens.prefix(2)), scale: updatedLens[2], k: updatedLens[3], k2: updatedLens[4]))
            result.method += " / terrain-supported edge correction"; result.rms = evidence[0]; result.matches = Int(evidence[1]); result.coverage = evidence[2]
            result.details["limb_p95_px"] = .number(evidence[3]); result.details["limb_arc_deg"] = .number(evidence[4])
            result.details["view_offset_deg"] = .array([.number(evidence[5]), .number(evidence[6])])
            result.details["validation_folds"] = .array((0..<Int(evidence[13])).map { index in
                .object(["cell": .number(folds[4 * index]), "count": .number(folds[4 * index + 1]), "median_px": .number(folds[4 * index + 2]), "within_4px": .number(folds[4 * index + 3])])
            })
            result.details["edge_refinement"] = .object(["status": .string("accepted"), "terrain_matches": .number(evidence[7]),
                "median_before_px": .number(evidence[8]), "median_after_px": .number(evidence[9]), "limb_training_points": .number(evidence[10]),
                "limb_validation_points": .number(evidence[11]), "heldout_limb_p95_px": .number(evidence[12])])
            return result
        } catch {
            try task.check()
            result.details["edge_refinement"] = .object(["status": .string("not_adopted"), "reason": .string(error.localizedDescription)])
            return result
        }
    }
}
