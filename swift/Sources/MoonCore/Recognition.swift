// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CoreGraphics
import simd
import CMoonNative

public struct IdentifiedCrater: Sendable {
    public var feature: Feature
    public var center: PixelPoint
    public init(feature: Feature, center: PixelPoint) { self.feature = feature; self.center = center }
}
public struct IdentificationResult: Sendable {
    public var calibration: Calibration
    public var method: String
    public var rms: Double
    public var matches: Int
    public var coverage: Double
    public var details: [String: JSONValue]
    public var identifiedCraters: [IdentifiedCrater]
    public var candidates: [CraterCandidate]
    public init(calibration: Calibration, method: String, rms: Double, matches: Int, coverage: Double,
                details: [String: JSONValue] = [:], identifiedCraters: [IdentifiedCrater] = [], candidates: [CraterCandidate] = []) {
        self.calibration = calibration; self.method = method; self.rms = rms; self.matches = matches; self.coverage = coverage; self.details = details
        self.identifiedCraters = identifiedCraters; self.candidates = candidates
    }
}

public enum RecognitionEngine {
    private static func trace(_ message: String) {
        if ProcessInfo.processInfo.environment["MOON_SWIFT_TRACE"] == "1" { FileHandle.standardError.write((message + "\n").data(using: .utf8)!) }
    }
    public static func identify(photo: PhotoPixels, geometry: MoonGeometry, state: ProjectState, features: [Feature],
                                dem: ElevationMap?, task: ComputeTask, allowCompact: Bool = true,
                                progress: @Sendable (String) -> Void) throws -> IdentificationResult {
        let mask = state.recognitionMask.operations.isEmpty || !state.recognitionMask.enabled ? nil :
            state.recognitionMask.raster(width: photo.width, height: photo.height, originalWidth: photo.width, originalHeight: photo.height, padding: 3)
        var failures: [String] = []
        if allowCompact, state.anchors.allSatisfy({ $0.source == "automatic" || $0.enabled == false }), let rectangle = compactField(photo: photo, mask: mask) {
            do {
                let cropped = try photo.cropped(rectangle)
                var local = state
                for index in local.recognitionMask.operations.indices {
                    local.recognitionMask.operations[index].points = local.recognitionMask.operations[index].points.map { [$0[0] - rectangle.minX, $0[1] - rectangle.minY] }
                }
                var result = try identify(photo: cropped, geometry: geometry, state: local, features: features, dem: dem, task: task, allowCompact: false, progress: progress)
                result.calibration.matrix[0][2] += rectangle.minX; result.calibration.matrix[1][2] += rectangle.minY
                for i in result.identifiedCraters.indices { result.identifiedCraters[i].center.x += rectangle.minX; result.identifiedCraters[i].center.y += rectangle.minY }
                for i in result.candidates.indices { result.candidates[i].center.x += rectangle.minX; result.candidates[i].center.y += rectangle.minY }
                if result.calibration.distortion != nil {
                    result.calibration.distortion!.center[0] += rectangle.minX; result.calibration.distortion!.center[1] += rectangle.minY
                }
                result.method += " / compact lunar field"; return result
            } catch { try task.check() }
        }
        if !state.anchors.filter({ $0.enabled != false && $0.source != "automatic" }).isEmpty, let dem {
            progress("用已确认的参考点搜索局部地形…")
            do { return try guided(photo: photo, geometry: geometry, state: state, features: features, dem: dem, mask: mask, task: task) }
            catch { try task.check(); failures.append(error.localizedDescription) }
        }
        progress("正在投影月球反照率参考…")
        let atlas = try ReferenceRenderer.atlas(geometry: geometry, task: task)
        do {
            progress("正在匹配月面纹理与镜像方向…")
            let match = try NativeCompute.match(reference: atlas.image, photo: photo, mask: mask, task: task)
            let camera = compose(match.matrix, atlas.matrix)
            guard match.source.count >= 24, Double(match.source.count) / Double(match.matches) >= 0.45 else { throw MoonError.invalid("纹理对应点太少，未采用结果。") }
            let limb = try photographedLimb(photo: photo, geometry: geometry, matrix: camera, mask: mask, task: task)
            let coverage = match.coverage * (limb.map { Double(photo.width * photo.height) / min(Double(photo.width * photo.height), 4 * $0[2] * $0[2]) } ?? 1)
            guard coverage >= 0.04 else { throw MoonError.invalid("纹理对应点过于集中，未采用结果。") }
            var effective = geometry, matrix = camera
            var mapMatch = match
            let referenceCalibration = Calibration(geometry: geometry, matrix: atlas.matrix)
            let cameraCalibration = Calibration(geometry: geometry, matrix: camera)
            mapMatch.source = match.source.map { cameraCalibration.photoPoint(referenceCalibration.modelPoint($0)) }
            if let refined = try NativeCompute.refine(geometry: geometry, matrix: camera, match: mapMatch, width: photo.width, height: photo.height, bound: limb == nil ? 1.25 : 3) {
                effective = refined.0; matrix = refined.1
            }
            if let limb, limbError(matrix, effective, limb) > max(3, limb[2] * 0.008, limb[3] * 4) {
                if state.captureMode != "direct" { return try opticalOrRetry(photo: photo, geometry: geometry, reference: atlas, match: match, mask: mask, limb: limb, dem: dem, task: task, progress: progress) }
                throw MoonError.invalid("纹理配准与独立月缘不一致。")
            }
            guard foregroundInside(photo: photo, matrix: matrix, mask: mask, minimum: 0.95) else {
                if state.captureMode != "direct" { return try opticalOrRetry(photo: photo, geometry: geometry, reference: atlas, match: match, mask: mask, limb: limb, dem: dem, task: task, progress: progress) }
                throw MoonError.invalid("纹理配准与照片月盘范围不一致。")
            }
            return IdentificationResult(calibration: Calibration(geometry: effective, matrix: matrix), method: "LROC / symmetric SIFT / JPL DE421", rms: match.rms, matches: match.source.count, coverage: coverage)
        } catch { try task.check(); failures.append(error.localizedDescription) }
        do {
            progress("正在独立验证月缘、月相和月海方向…")
            let limb = try NativeCompute.limb(photo: photo, mask: mask, task: task)
            let reference = try ReferenceRenderer.atlas(geometry: geometry, size: 256, task: task)
            var error = nativeError(), matrix = [Double](repeating: 0, count: 6), evidence = [Double](repeating: 0, count: 2)
            let masks = mask ?? []
            let status = masks.withUnsafeBufferPointer { buffer in mn_limb_pose(reference.image.rgba, 256, photo.rgba, Int32(photo.width), Int32(photo.height), 4,
                mask == nil ? nil : buffer.baseAddress, geometry.native, limb, task.pointer, &matrix, &evidence, &error) }
            guard status != 0 else { throw failure(error) }
            return IdentificationResult(calibration: Calibration(geometry: geometry, matrix: splitMatrix(matrix)), method: "lunar limb / phase + high-pass LROC / JPL", rms: limb[3], matches: Int(limb[4]), coverage: 0,
                                        details: ["texture_correlation": .number(evidence[0]), "phase_correlation": .number(evidence[1])])
        } catch { try task.check(); failures.append(error.localizedDescription) }
        do {
            progress("正在检测并验证多坑图案…")
            let candidates = try NativeCompute.rims(photo: photo, mask: mask, task: task)
            var result = try triangles(photo: photo, geometry: geometry, features: features, candidates: candidates, mask: mask, task: task)
            if let dem, let refined = try refineTerrain(photo: photo, result: result, dem: dem, mask: mask, task: task, craterVerified: true) { result = refined }
            return result
        } catch { try task.check(); failures.append(error.localizedDescription) }
        if let dem {
            progress("正在搜索 LOLA 高程与阴影参考…")
            do { return try terrain(photo: photo, geometry: geometry, dem: dem, mask: mask, task: task, progress: progress) }
            catch { try task.check(); failures.append(error.localizedDescription) }
        }
        throw MoonError.invalid("自动配准尚未通过独立验证。\n" + failures.joined(separator: "\n") + "\n请核对 UTC 时间、拍摄方式，或添加分散的参考点。")
    }
    public static func triangles(photo: PhotoPixels, geometry: MoonGeometry, features: [Feature], candidates: [CraterCandidate],
                                  mask: [UInt8]?, task: ComputeTask) throws -> IdentificationResult {
        var selected: [Feature] = [], points: [Double] = [], radii: [Double] = [], named: [Int32] = []
        for feature in features where ["Crater, craters", "Satellite Feature"].contains(feature.kind) && (3...250).contains(feature.diameter) {
            let projected = geometry.project(latitude: feature.latitude, longitude: feature.longitude)
            guard projected.visible, hypot(projected.point.x, projected.point.y) < 0.98 else { continue }
            selected.append(feature); points.append(contentsOf: [projected.point.x, projected.point.y]); radii.append(feature.diameter / (2 * moonRadius))
            named.append(feature.kind == "Crater, craters" ? 1 : 0)
        }
        let nativeCandidates = candidates.map { candidate -> MNCandidate in
            var result = MNCandidate(); result.x = candidate.center.x; result.y = candidate.center.y; result.major = candidate.major; result.minor = candidate.minor
            result.angle = candidate.angle; result.support = candidate.support; return result
        }
        var result = MNMatch(), score = 0.0, error = nativeError(); let masks = mask ?? []
        let status = masks.withUnsafeBufferPointer { buffer in mn_triangles(points, radii, named, Int32(selected.count), nativeCandidates, Int32(candidates.count),
            Int32(photo.width), Int32(photo.height), photo.rgba, 4, mask == nil ? nil : buffer.baseAddress, task.pointer, &result, &score, &error) }
        guard status != 0 else { try task.check(); throw failure(error) }; defer { mn_match_destroy(&result) }
        let matrix = withUnsafeBytes(of: result.matrix) { splitMatrix(Array($0.bindMemory(to: Double.self))) }
        var pairs: [JSONValue] = [], identified: [IdentifiedCrater] = []
        for index in 0..<Int(result.count) {
            let feature = selected[Int(result.feature_indices[index])]
            identified.append(IdentifiedCrater(feature: feature, center: candidates[Int(result.candidate_indices[index])].center))
            pairs.append(.object(["feature_id": .string(feature.id), "candidate_index": .number(Double(result.candidate_indices[index]))]))
        }
        return IdentificationResult(calibration: Calibration(geometry: geometry, matrix: matrix), method: "EDCircles / multiscale named + satellite triangles / JPL projection",
                                    rms: result.rms, matches: Int(result.count), coverage: result.coverage, details: ["crater_matches": .array(pairs), "score": .number(score)], identifiedCraters: identified, candidates: candidates)
    }

    public static func manual(geometry: MoonGeometry, anchors: [ControlPoint], features: [Feature], mirror: Int = -1) throws -> (Calibration, CalibrationReport) {
        let enabled = anchors.filter { $0.enabled != false }, byID = Dictionary(uniqueKeysWithValues: features.map { ($0.id, $0) })
        var source: [PixelPoint] = [], target: [PixelPoint] = []
        for anchor in enabled {
            guard let feature = byID[anchor.id] else { throw MoonError.invalid("参考点的地名已不在地名库中。") }
            let projected = geometry.project(latitude: feature.latitude, longitude: feature.longitude)
            guard projected.visible else { throw MoonError.invalid("参考点位于月球背面，请核对日期和地名。") }
            source.append(projected.point); target.append(anchor.point)
        }
        let report = try NativeCompute.fit(source: source, target: target, mirror: mirror)
        return (Calibration(geometry: geometry, matrix: report.matrix), report)
    }

    public static func matchReference(reference: TerrainReference, geometry: MoonGeometry, photo: PhotoPixels,
                                      mask: [UInt8]?, task: ComputeTask) throws -> IdentificationResult {
        if let width = reference.widthKM, reference.resolutionKM > 0, width / reference.resolutionKM < 64 {
            throw MoonError.invalid("这个视野内不足 64 个地形采样点，细节不足以自动匹配。请导入更高分辨率 DEM，或用地形点校准。")
        }
        let match = try NativeCompute.match(reference: reference.image, photo: photo, mask: mask, task: task)
        return IdentificationResult(calibration: Calibration(geometry: geometry, matrix: compose(match.matrix, reference.matrix)),
                                    method: "reference / symmetric SIFT", rms: match.rms, matches: match.source.count, coverage: match.coverage)
    }

    public static func terrain(photo: PhotoPixels, geometry: MoonGeometry, dem: ElevationMap, mask: [UInt8]?,
                                task: ComputeTask, progress: @Sendable (String) -> Void) throws -> IdentificationResult {
        let reference = try ReferenceRenderer.terrain(dem: dem, geometry: geometry, size: 4000, task: task)
        let working = try photo.resized(maximum: 880)
        let sx = Double(working.width) / Double(photo.width), sy = Double(working.height) / Double(photo.height)
        var smallMask: [UInt8]?
        if let mask {
            var resized = [UInt8](repeating: 0, count: working.width * working.height)
            for y in 0..<working.height { for x in 0..<working.width { resized[y * working.width + x] = mask[min(photo.height - 1, Int(Double(y) / sy)) * photo.width + min(photo.width - 1, Int(Double(x) / sx))] } }
            smallMask = resized
        }
        var solutions: [IdentificationResult] = [], pending: [IdentificationResult] = []
        let tile = 1536, offsets = [0, 1232, 2464]
        for (row, y) in offsets.enumerated() { for (column, x) in offsets.enumerated() {
            try task.check(); progress("正在验证高程区域 \(row + 1) · \(column + 1)…")
            do {
                let crop = try reference.image.cropped(CGRect(x: x, y: y, width: tile, height: tile))
                let match = try NativeCompute.match(reference: crop, photo: working, mask: smallMask, task: task, ratio: 0.8, contrast: 0.01, inlierFraction: 0.25)
                trace("tile \(x),\(y): \(match.source.count) inliers, coverage \(match.coverage)")
                guard match.source.count >= 12, match.coverage >= 0.06 else { continue }
                let referenceToPhoto = compose(match.matrix, [[1, 0, -Double(x)], [0, 1, -Double(y)]])
                var camera = compose(referenceToPhoto, reference.matrix)
                for c in 0..<3 { camera[0][c] /= sx; camera[1][c] /= sy }
                guard foregroundInside(photo: photo, matrix: camera, mask: mask, minimum: 0.95) else { trace("foreground rejected"); continue }
                let dense = try agreement(reference: reference.image, photo: working, matrix: referenceToPhoto, mask: smallMask)
                trace("dense: \(dense.0), \(dense.1)")
                let sparse = match.source.count < 18
                if sparse && !(match.coverage >= 0.15 && dense.0 >= 0.6 && dense.1 >= 0.35) { continue }
                let result = IdentificationResult(calibration: Calibration(geometry: geometry, matrix: camera), method: "LOLA terrain / symmetric SIFT / dense validation",
                                                    rms: match.rms / min(sx, sy), matches: match.source.count, coverage: match.coverage,
                                                    details: ["light_correlation": .number(dense.0), "detail_correlation": .number(dense.1), "score": .number(Double(match.source.count) * (dense.0 + dense.1))])
                if !sparse && consensus(light: dense.0, detail: dense.1, count: match.source.count, coverage: match.coverage) { solutions.append(result) }
                else if match.coverage >= 0.08 && dense.0 >= 0.25 && dense.1 >= 0.04 { pending.append(result) }
            } catch { trace("tile \(x),\(y): \(error.localizedDescription)"); try task.check() }
        } }
        let currentBest = solutions.max { quality($0) < quality($1) }
        var distinct: [IdentificationResult] = []
        for candidate in pending.sorted(by: { quality($0) > quality($1) }) {
            if let best = currentBest, quality(candidate) <= quality(best) * 0.8 || poseDifference(best.calibration, candidate.calibration, photo: photo) <= Double(max(photo.width, photo.height)) * 0.08 { continue }
            if distinct.allSatisfy({ poseDifference($0.calibration, candidate.calibration, photo: photo) > Double(max(photo.width, photo.height)) * 0.08 }) { distinct.append(candidate) }
        }
        for candidate in distinct.prefix(2) {
            try task.check(); progress("正在验证独立地形区域与局部精修…")
            if let refined = try refineTerrain(photo: photo, result: candidate, dem: dem, mask: mask, task: task),
               foregroundInside(photo: photo, matrix: refined.calibration.matrix, mask: mask, minimum: 0.95) { solutions.append(refined) }
        }
        var best = try bestDistinct(solutions, photo: photo)
        if best.details["validation_after_px"] == nil,
           let refined = try refineTerrain(photo: photo, result: best, dem: dem, mask: mask, task: task, reliefAware: false) { best = refined }
        return best
    }

    public static func guided(photo: PhotoPixels, geometry: MoonGeometry, state: ProjectState, features: [Feature],
                               dem: ElevationMap, mask: [UInt8]?, task: ComputeTask) throws -> IdentificationResult {
        let anchors = state.anchors.filter { $0.enabled != false && $0.source != "automatic" }
        let byID = Dictionary(uniqueKeysWithValues: features.map { ($0.id, $0) })
        let selected = try anchors.map { anchor -> Feature in
            guard let feature = byID[anchor.id], geometry.project(latitude: feature.latitude, longitude: feature.longitude).visible else { throw MoonError.invalid("参考点不可投影，请核对日期、地名及位置。") }
            return feature
        }
        guard !selected.isEmpty else { throw MoonError.invalid("请先确认至少一处已知地形。") }
        var widths = [160.0, 320, 80, 640], scales: [Double] = []
        if anchors.count >= 2 {
            for i in 0..<(anchors.count - 1) { for j in (i + 1)..<anchors.count {
                let a = geometry.project(latitude: selected[i].latitude, longitude: selected[i].longitude).point, b = geometry.project(latitude: selected[j].latitude, longitude: selected[j].longitude).point
                let distance = hypot(a.x - b.x, a.y - b.y), pixels = hypot(anchors[i].point.x - anchors[j].point.x, anchors[i].point.y - anchors[j].point.y)
                if distance > 1e-6, pixels >= 12 { scales.append(pixels / distance) }
            } }
        }
        if scales.isEmpty, let candidates = try? NativeCompute.rims(photo: photo, mask: mask, task: task) {
            for (feature, anchor) in zip(selected, anchors) where feature.diameter > 0 {
                if let candidate = candidates.filter({ hypot($0.center.x - anchor.point.x, $0.center.y - anchor.point.y) <= max(12, $0.major * 0.6) }).min(by: { hypot($0.center.x - anchor.point.x, $0.center.y - anchor.point.y) < hypot($1.center.x - anchor.point.x, $1.center.y - anchor.point.y) }) { scales.append(candidate.major * 2 * moonRadius / feature.diameter) }
            }
        }
        if !scales.isEmpty {
            scales.sort(); let scale = scales[scales.count / 2], extent = Double(max(photo.width, photo.height)) * moonRadius / scale
            widths = [0.85, 1.1, 1.5].map { extent * $0 }
            let center = PixelPoint(anchors.map { $0.point.x }.reduce(0, +) / Double(anchors.count), anchors.map { $0.point.y }.reduce(0, +) / Double(anchors.count))
            let radius = [PixelPoint(0, 0), PixelPoint(Double(photo.width), 0), PixelPoint(0, Double(photo.height)), PixelPoint(Double(photo.width), Double(photo.height))].map { hypot($0.x - center.x, $0.y - center.y) }.max()!
            let footprint = 2 * radius * moonRadius / scale
            if footprint > widths.last! { widths.append(footprint * 1.05) }
        }
        widths = widths.map { min(4200, max(40, ($0 / 10).rounded() * 10)) }
        let points = selected.map { geometry.project(latitude: $0.latitude, longitude: $0.longitude).point }
        let center = PixelPoint(points.map(\.x).reduce(0, +) / Double(points.count), points.map(\.y).reduce(0, +) / Double(points.count))
        let working = try photo.resized(maximum: 880), sx = Double(working.width) / Double(photo.width), sy = Double(working.height) / Double(photo.height)
        let smallMask = mask.map { values in (0..<working.height).flatMap { y in (0..<working.width).map { x in values[min(photo.height - 1, Int(Double(y) / sy)) * photo.width + min(photo.width - 1, Int(Double(x) / sx))] } } }
        var solutions: [IdentificationResult] = [], pending: [IdentificationResult] = []
        func errors(_ camera: Calibration) -> [Double] { zip(selected, anchors).map { feature, anchor in let p = camera.project(feature).point; return hypot(p.x - anchor.point.x, p.y - anchor.point.y) } }
        for width in widths {
            try task.check()
            do {
                let size = 600, scale = Double(size) * moonRadius / width, projection = [[scale, 0, Double(size) / 2 - center.x * scale], [0, scale, Double(size) / 2 - center.y * scale]]
                let reference = try ReferenceRenderer.calibrated(dem: dem, calibration: Calibration(geometry: geometry, matrix: projection), width: size, height: size, reliefAware: false, task: task)
                let match = try NativeCompute.match(reference: reference.image, photo: working, mask: smallMask, task: task, ratio: 0.8, contrast: 0.01, inlierFraction: 0.25)
                guard match.source.count >= 24, match.coverage >= 0.1 else { continue }
                var matrix = compose(match.matrix, projection)
                for column in 0..<3 { matrix[0][column] /= sx; matrix[1][column] /= sy }
                let camera = Calibration(geometry: geometry, matrix: matrix), rms = match.rms / min(sx, sy), pointErrors = errors(camera)
                guard pointErrors.allSatisfy({ $0 <= max(15, Double(min(photo.width, photo.height)) * 0.012, rms * 3) }) else { continue }
                let inverse = Calibration(geometry: geometry, matrix: match.matrix)
                var available = 0, total = 0
                for y in stride(from: Int(Double(working.height) * 0.08), to: Int(Double(working.height) * 0.93), by: 3) { for x in stride(from: Int(Double(working.width) * 0.05), to: Int(Double(working.width) * 0.95), by: 3) {
                    if smallMask?[y * working.width + x] == 0 { continue }; total += 1
                    let p = inverse.modelPoint(PixelPoint(Double(x), Double(y))); if p.x >= 1 && p.y >= 1 && p.x < Double(size - 1) && p.y < Double(size - 1) { available += 1 }
                } }
                guard total > 0, Double(available) / Double(total) >= 0.85 else { continue }
                let dense = try agreement(reference: reference.image, photo: working, matrix: match.matrix, mask: smallMask)
                let result = IdentificationResult(calibration: camera, method: "confirmed reference points / LOLA terrain", rms: rms,
                    matches: match.source.count, coverage: match.coverage, details: ["reference_errors_px": .array(pointErrors.map(JSONValue.number)), "light_correlation": .number(dense.0), "detail_correlation": .number(dense.1), "score": .number(Double(match.source.count) * (dense.0 + dense.1))])
                if consensus(light: dense.0, detail: dense.1, count: match.source.count, coverage: match.coverage) { solutions.append(result) }
                else if match.source.count >= 40 && match.coverage >= 0.18 && dense.0 >= 0.4 && dense.1 >= 0.25 { pending.append(result) }
            } catch { try task.check() }
        }
        var distinct: [IdentificationResult] = []
        for candidate in pending.sorted(by: { quality($0) > quality($1) }) {
            if distinct.allSatisfy({ poseDifference($0.calibration, candidate.calibration, photo: photo) > Double(max(photo.width, photo.height)) * 0.08 }) { distinct.append(candidate) }
        }
        for candidate in distinct.prefix(2) {
            if let refined = try refineTerrain(photo: photo, result: candidate, dem: dem, mask: mask, task: task), errors(refined.calibration).allSatisfy({ $0 <= max(15, Double(min(photo.width, photo.height)) * 0.012, refined.rms * 3) }) { solutions.append(refined) }
        }
        var best = try bestDistinct(solutions, photo: photo)
        if best.matches >= 40, best.details["validation_after_px"] == nil,
           let refined = try refineTerrain(photo: photo, result: best, dem: dem, mask: mask, task: task, reliefAware: false), errors(refined.calibration).allSatisfy({ $0 <= max(15, Double(min(photo.width, photo.height)) * 0.012, refined.rms * 3) }) { best = refined }
        return best
    }

    public static func agreement(reference: PhotoPixels, photo: PhotoPixels, matrix: [[Double]], mask: [UInt8]?) throws -> (Double, Double) {
        var error = nativeError(), result = [Double](repeating: 0, count: 2)
        let gray = reference.gray, masks = mask ?? []
        let status = masks.withUnsafeBufferPointer { buffer in mn_dense_agreement(gray, Int32(reference.width), Int32(reference.height), photo.rgba,
            Int32(photo.width), Int32(photo.height), 4, matrix.flatMap { $0 }, mask == nil ? nil : buffer.baseAddress, &result, &error) }
        guard status != 0 else { throw failure(error) }; return (result[0], result[1])
    }
    private static func opticalOrRetry(photo: PhotoPixels, geometry: MoonGeometry, reference: TerrainReference, match: RegistrationResult,
                                       mask: [UInt8]?, limb: [Double]?, dem: ElevationMap?, task: ComputeTask, progress: @Sendable (String) -> Void) throws -> IdentificationResult {
        func finish(_ result: IdentificationResult, _ observations: RegistrationResult) throws -> IdentificationResult {
            try EyepieceEdgeRefinement.refine(photo: photo, geometry: geometry, atlas: reference, match: observations, accepted: result, dem: dem, mask: mask, task: task, progress: progress)
        }
        do { return try finish(optical(photo: photo, geometry: geometry, reference: reference, match: match, mask: mask, limb: limb, task: task), match) }
        catch {
            try task.check(); let original = error
            guard limb != nil, match.source.count >= 64 else { throw original }
            do {
                let fresh = try NativeCompute.realignedMatch(reference: reference.image, photo: photo, coarse: match, mask: mask, task: task)
                guard fresh.mirrored == match.mirrored else { throw original }
                guard let observed = try photographedLimb(photo: photo, geometry: geometry, matrix: compose(fresh.matrix, reference.matrix), mask: mask, task: task) else { throw original }
                var result = try optical(photo: photo, geometry: geometry, reference: reference, match: fresh, mask: mask, limb: observed, task: task)
                result.method += " / rigid-aligned rematch"; return try finish(result, fresh)
            } catch { try task.check(); throw original }
        }
    }
    static func photographedLimb(photo: PhotoPixels, geometry: MoonGeometry, matrix: [[Double]], mask: [UInt8]?, task: ComputeTask) throws -> [Double]? {
        let scale = hypot(matrix[0][0], matrix[1][0]), center = PixelPoint(matrix[0][2], matrix[1][2])
        guard scale >= 50 else { return nil }
        if center.x - scale < 0 || center.y - scale < 0 || center.x + scale >= Double(photo.width) || center.y + scale >= Double(photo.height) {
            let margin = simd_dot(geometry.observerVector, geometry.sunVector) > 0.98 ? 0.02 : 0.15
            var illuminated = 0, inside = 0
            for i in 0..<720 {
                let angle = 2 * Double.pi * Double(i) / 720, circle = PixelPoint(cos(angle), sin(angle))
                let position = geometry.unproject(PixelPoint(circle.x * 0.999, circle.y * 0.999))
                guard position.visible, simd_dot(surfaceVector(latitude: position.latitude, longitude: position.longitude), geometry.sunVector) > margin else { continue }
                illuminated += 1
                let x = matrix[0][0] * circle.x + matrix[0][1] * circle.y + center.x
                let y = matrix[1][0] * circle.x + matrix[1][1] * circle.y + center.y
                if x > 3, y > 3, x < Double(photo.width - 4), y < Double(photo.height - 4) { inside += 1 }
            }
            guard illuminated >= 240, Double(inside) / Double(illuminated) >= 0.95 else { return nil }
        }
        let left = max(0, Int(floor(center.x - 1.1 * scale))), top = max(0, Int(floor(center.y - 1.1 * scale)))
        let right = min(photo.width, Int(ceil(center.x + 1.1 * scale))), bottom = min(photo.height, Int(ceil(center.y + 1.1 * scale)))
        guard right > left, bottom > top else { return nil }
        var pixels: [UInt8] = [], croppedMask: [UInt8]? = mask == nil ? nil : []
        pixels.reserveCapacity((right - left) * (bottom - top) * 4)
        for row in top..<bottom {
            pixels.append(contentsOf: photo.rgba[(row * photo.width + left) * 4..<(row * photo.width + right) * 4])
            if let mask { croppedMask!.append(contentsOf: mask[row * photo.width + left..<row * photo.width + right]) }
        }
        do {
            var limb = try NativeCompute.limb(photo: PhotoPixels(width: right - left, height: bottom - top, rgba: pixels), mask: croppedMask, task: task)
            limb[0] += Double(left); limb[1] += Double(top); return limb
        } catch { try task.check(); return nil }
    }
    public static func optical(photo: PhotoPixels, geometry: MoonGeometry, reference: TerrainReference, match: RegistrationResult,
                                mask: [UInt8]?, limb: [Double]?, task: ComputeTask) throws -> IdentificationResult {
        var error = nativeError(), outputGeometry = [Double](repeating: 0, count: 13), matrix = [Double](repeating: 0, count: 6)
        var distortion = [Double](repeating: 0, count: 4), evidence = [Double](repeating: 0, count: 7)
        let masks = mask ?? [], measured = limb ?? []
        let status = masks.withUnsafeBufferPointer { maskBuffer in measured.withUnsafeBufferPointer { limbBuffer in
            mn_eyepiece(geometry.native, reference.matrix.flatMap { $0 }, compose(match.matrix, reference.matrix).flatMap { $0 },
                         match.sourceMatches.flatMap { [$0.x, $0.y] }, match.targetMatches.flatMap { [$0.x, $0.y] },
                         Int32(match.sourceMatches.count), Int32(match.source.count), match.coverage, photo.rgba, Int32(photo.width), Int32(photo.height), 4,
                         mask == nil ? nil : maskBuffer.baseAddress, limb == nil ? nil : limbBuffer.baseAddress, task.pointer,
                         &outputGeometry, &matrix, &distortion, &evidence, &error)
        } }
        guard status != 0 else { try task.check(); throw failure(error) }
        let calibration = Calibration(geometry: MoonGeometry(native: outputGeometry, utc: geometry.utc), matrix: splitMatrix(matrix),
                                      distortion: LensDistortion(center: Array(distortion.prefix(2)), scale: distortion[2], k: distortion[3]))
        return IdentificationResult(calibration: calibration, method: "LROC / spatially validated eyepiece distortion", rms: evidence[0],
                                    matches: Int(evidence[1]), coverage: evidence[2], details: ["limb_p95_px": .number(evidence[3]), "limb_arc_deg": .number(evidence[4]),
                                        "view_offset_deg": .array([.number(evidence[5]), .number(evidence[6])])])
    }
    public static func refineTerrain(photo: PhotoPixels, result: IdentificationResult, dem: ElevationMap, mask: [UInt8]?, task: ComputeTask,
                                      craterVerified: Bool = false, reliefAware: Bool = true) throws -> IdentificationResult? {
        guard result.calibration.distortion == nil else { return nil }
        let working = try photo.resized(maximum: 1200)
        let sx = Double(working.width) / Double(photo.width), sy = Double(working.height) / Double(photo.height)
        var camera = result.calibration
        for column in 0..<3 { camera.matrix[0][column] *= sx; camera.matrix[1][column] *= sy }
        let reference = try ReferenceRenderer.calibrated(dem: dem, calibration: camera, width: working.width, height: working.height, reliefAware: reliefAware || craterVerified, task: task)
        var smallMask: [UInt8]?
        if let mask {
            var resized = [UInt8](repeating: 0, count: working.width * working.height)
            for y in 0..<working.height { for x in 0..<working.width { resized[y * working.width + x] = mask[min(photo.height - 1, Int(Double(y) / sy)) * photo.width + min(photo.width - 1, Int(Double(x) / sx))] } }
            smallMask = resized
        }
        guard var match = try NativeCompute.localMatches(reference: reference.image, photo: working, mask: smallMask, task: task) else { return nil }
        var source: [PixelPoint] = [], target: [PixelPoint] = [], surface: [SIMD3<Double>] = [], seen = Set<[Int]>()
        for (a, b) in zip(match.source, match.target) {
            guard hypot(a.x - b.x, a.y - b.y) < 25 else { continue }
            let key = [Int((a.x * 8).rounded()), Int((a.y * 8).rounded()), Int((b.x * 8).rounded()), Int((b.y * 8).rounded())]
            guard seen.insert(key).inserted else { continue }
            let position = camera.geometry.unproject(camera.modelPoint(a), terrain: reliefAware || craterVerified ? dem : nil)
            guard position.visible else { continue }
            let h = dem.sample(position.latitude, position.longitude)
            guard h.isFinite else { continue }
            source.append(a); target.append(b); surface.append(surfaceVector(latitude: position.latitude, longitude: position.longitude) * (1 + (reliefAware || craterVerified ? h : 0) / moonRadius))
        }
        if source.count > 1000 {
            let indices = (0..<1000).map { $0 * (source.count - 1) / 999 }
            source = indices.map { source[$0] }; target = indices.map { target[$0] }; surface = indices.map { surface[$0] }
        }
        guard source.count >= 40 else { return nil }
        match.source = source; match.target = target
        var refined: (MoonGeometry, [[Double]], [Double])?
        if craterVerified, let aligned = try NativeCompute.refine(geometry: camera.geometry, matrix: camera.matrix, match: match, width: working.width, height: working.height, surface: surface, cameraOnly: true) {
            camera = Calibration(geometry: aligned.0, matrix: aligned.1)
            let alignedReference = try ReferenceRenderer.calibrated(dem: dem, calibration: camera, width: working.width, height: working.height, task: task)
            if let rematch = try NativeCompute.localMatches(reference: alignedReference.image, photo: working, mask: smallMask, task: task) {
                var fresh = rematch; var points: [SIMD3<Double>] = [], a: [PixelPoint] = [], b: [PixelPoint] = []
                for (s, t) in zip(rematch.source, rematch.target) {
                    let position = camera.geometry.unproject(camera.modelPoint(s), terrain: dem)
                    guard position.visible else { continue }; let h = dem.sample(position.latitude, position.longitude)
                    if h.isFinite { points.append(surfaceVector(latitude: position.latitude, longitude: position.longitude) * (1 + h / moonRadius)); a.append(s); b.append(t) }
                }
                fresh.source = a; fresh.target = b
                refined = try NativeCompute.refine(geometry: camera.geometry, matrix: camera.matrix, match: fresh, width: working.width, height: working.height, surface: points)
                if refined != nil { match = fresh; source = a }
            }
            if refined == nil { refined = aligned }
        } else {
            refined = try NativeCompute.refine(geometry: camera.geometry, matrix: camera.matrix, match: match, width: working.width, height: working.height, surface: surface)
        }
        guard let refined else { return nil }
        let candidate = Calibration(geometry: refined.0, matrix: refined.1)
        let fresh = try ReferenceRenderer.calibrated(dem: dem, calibration: candidate, width: working.width, height: working.height, reliefAware: reliefAware || craterVerified, task: task)
        let dense: (Double, Double), beforeDense: (Double, Double)
        do {
            let before = try agreement(reference: reference.image, photo: working, matrix: [[1, 0, 0], [0, 1, 0]], mask: smallMask)
            beforeDense = before
            dense = try agreement(reference: fresh.image, photo: working, matrix: [[1, 0, 0], [0, 1, 0]], mask: smallMask)
            if dense.0 < before.0 || dense.1 < before.1 + 0.02 { return nil }
        }
        catch { return nil }
        let strong = consensus(light: dense.0, detail: dense.1, count: source.count, coverage: match.coverage)
        let tonal = dense.0 >= 0.5 && dense.1 >= 0.5 && source.count >= 80 && match.coverage >= 0.25 && refined.2[3] <= 1.5 && refined.2[3] <= refined.2[2] * 0.75 && refined.2[2] - refined.2[3] >= 0.5
        guard strong || tonal else { return nil }
        var matrix = candidate.matrix
        for column in 0..<3 { matrix[0][column] /= sx; matrix[1][column] /= sy }
        var details = result.details
        details["relief_aware"] = .bool(reliefAware || craterVerified); details["view_offset_deg"] = .array([.number(refined.2[4]), .number(refined.2[5])])
        details["validation_before_px"] = .number(refined.2[2]); details["validation_after_px"] = .number(refined.2[3])
        details["light_correlation"] = .number(dense.0); details["detail_correlation"] = .number(dense.1)
        details["light_before_after"] = .array([.number(beforeDense.0), .number(dense.0)]); details["detail_before_after"] = .array([.number(beforeDense.1), .number(dense.1)])
        details["score"] = .number(Double(source.count) * (dense.0 + dense.1)); details["points"] = .number(Double(source.count)); details["coverage"] = .number(match.coverage)
        details["working_shape"] = .array([.number(Double(working.height)), .number(Double(working.width))])
        details["base_geometry"] = try JSONValue.encode(result.calibration.geometry)
        return IdentificationResult(calibration: Calibration(geometry: candidate.geometry, matrix: matrix), method: result.method + " / spatially validated relief refinement",
                                    rms: refined.2[0] / sx, matches: source.count, coverage: match.coverage, details: details, identifiedCraters: result.identifiedCraters, candidates: result.candidates)
    }
    private static func cameraRefinement(source: [PixelPoint], target: [PixelPoint], width: Int, height: Int) throws -> ([[Double]], Double, Double, Double)? {
        let cells = source.map { min(2, max(0, Int($0.x / Double(width) * 3))) + 3 * min(2, max(0, Int($0.y / Double(height) * 3))) }
        let full = try NativeCompute.quickFit(source: source, target: target)
        let scale = hypot(full.0[0][0], full.0[1][0]), angle = atan2(full.0[1][0], full.0[0][0])
        guard (0.9...1.1).contains(scale), abs(angle) <= 0.1 else { return nil }
        func predicted(_ point: PixelPoint, _ matrix: [[Double]]) -> PixelPoint { PixelPoint(matrix[0][0] * point.x + matrix[0][1] * point.y + matrix[0][2], matrix[1][0] * point.x + matrix[1][1] * point.y + matrix[1][2]) }
        var folds = 0, improved = 0, total = 0, beforeSum = 0.0, afterSum = 0.0
        for cell in 0..<9 {
            let hold = cells.indices.filter { cells[$0] == cell }, train = cells.indices.filter { cells[$0] != cell }
            guard hold.count >= 3, train.count >= 20 else { continue }
            let fit = try NativeCompute.quickFit(source: train.map { source[$0] }, target: train.map { target[$0] }).0
            var before = 0.0, after = 0.0
            for i in hold { let p = predicted(source[i], fit); before += pow(source[i].x - target[i].x, 2) + pow(source[i].y - target[i].y, 2); after += pow(p.x - target[i].x, 2) + pow(p.y - target[i].y, 2) }
            guard sqrt(after / Double(hold.count)) <= sqrt(before / Double(hold.count)) * 1.1 + 0.25 else { return nil }
            folds += 1; if after < before { improved += 1 }; total += hold.count; beforeSum += before; afterSum += after
        }
        guard folds >= 4, Double(improved) >= Double(folds) * 0.75 else { return nil }
        let before = sqrt(beforeSum / Double(total)), after = sqrt(afterSum / Double(total))
        guard after <= before * 0.85, before - after >= 0.25 else { return nil }
        return (full.0, full.1, before, after)
    }
    public static func compose(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
        (0..<2).map { row in [a[row][0] * b[0][0] + a[row][1] * b[1][0], a[row][0] * b[0][1] + a[row][1] * b[1][1],
                              a[row][0] * b[0][2] + a[row][1] * b[1][2] + a[row][2]] }
    }
    public static func validateAnchors(_ camera: Calibration, state: ProjectState, features: [Feature], previous: Calibration? = nil) throws {
        let byID = Dictionary(uniqueKeysWithValues: features.map { ($0.id, $0) })
        let anchors = state.anchors.filter { $0.enabled != false && $0.source != "automatic" && byID[$0.id] != nil }
        guard anchors.count >= 3 else { return }
        func medianError(_ calibration: Calibration) -> Double {
            let errors = anchors.map { anchor -> Double in let p = calibration.project(byID[anchor.id]!).point; return hypot(p.x - anchor.point.x, p.y - anchor.point.y) }.sorted()
            return errors[errors.count / 2]
        }
        guard medianError(camera) <= max(6, 2 * (previous.map(medianError) ?? 0)) else { throw MoonError.invalid("DEM 匹配与已有地形点不一致，未采用该结果。请核对区域、时间或数据分辨率。") }
    }
    private static func compactField(photo: PhotoPixels, mask: [UInt8]?) -> CGRect? {
        var rectangle = [Int32](repeating: 0, count: 4); let masks = mask ?? []
        let status = masks.withUnsafeBufferPointer { buffer in mn_compact_field(photo.rgba, Int32(photo.width), Int32(photo.height), 4, mask == nil ? nil : buffer.baseAddress, &rectangle) }
        return status != 0 ? CGRect(x: Int(rectangle[0]), y: Int(rectangle[1]), width: Int(rectangle[2]), height: Int(rectangle[3])) : nil
    }
    private static func consensus(light: Double, detail: Double, count: Int, coverage: Double) -> Bool {
        (light >= 0.6 && detail >= 0.25 && count >= 24 && coverage >= 0.06) ||
        (light >= 0.59 && detail >= 0.30 && count >= 32 && coverage >= 0.15)
    }
    private static func limbError(_ matrix: [[Double]], _ geometry: MoonGeometry, _ limb: [Double]) -> Double {
        let scale = hypot(matrix[0][0], matrix[1][0]), predicted = scale / sqrt(1 - pow(moonRadius / geometry.distanceKM, 2))
        return hypot(hypot(matrix[0][2] - limb[0], matrix[1][2] - limb[1]) / sqrt(2), predicted - limb[2])
    }
    private static func foregroundInside(photo: PhotoPixels, matrix: [[Double]], mask: [UInt8]?, minimum: Double) -> Bool {
        let calibration = Calibration(geometry: MoonGeometry(native: [1,0,0,0,1,0,0,0,1,1,0,0,384400], utc: ""), matrix: matrix)
        var inside = 0, total = 0
        for y in stride(from: 0, to: Int(Double(photo.height) * 0.93), by: max(1, photo.height / 54)) {
            for x in stride(from: 0, to: photo.width, by: max(1, photo.width / 60)) {
                let index = y * photo.width + x
                guard (mask == nil || mask![index] > 0), max(photo.rgba[index * 4], photo.rgba[index * 4 + 1], photo.rgba[index * 4 + 2]) > 30 else { continue }
                let point = calibration.modelPoint(PixelPoint(Double(x), Double(y)))
                total += 1; if hypot(point.x, point.y) < 1.015 { inside += 1 }
            }
        }
        return total == 0 || Double(inside) / Double(total) >= minimum
    }
    private static func bestDistinct(_ results: [IdentificationResult], photo: PhotoPixels) throws -> IdentificationResult {
        let sorted = results.sorted { quality($0) > quality($1) }
        guard let best = sorted.first else { throw MoonError.invalid("未找到通过对应点与地形明暗共同验证的配准。") }
        for other in sorted.dropFirst() where quality(other) > quality(best) * 0.8 {
            let difference = poseDifference(best.calibration, other.calibration, photo: photo)
            if difference > Double(max(photo.width, photo.height)) * 0.08 { throw MoonError.invalid("存在多个接近的配准位置，请再确认一处地形参考点。") }
        }
        return best
    }
    private static func quality(_ result: IdentificationResult) -> Double {
        result.details["score"]?.number ?? Double(result.matches) * (result.details["light_correlation"]?.number ?? result.coverage)
    }
    private static func poseDifference(_ a: Calibration, _ b: Calibration, photo: PhotoPixels) -> Double {
        let probes = [PixelPoint(Double(photo.width) / 2, Double(photo.height) / 2), PixelPoint(Double(photo.width) * 0.75, Double(photo.height) / 2), PixelPoint(Double(photo.width) / 2, Double(photo.height) * 0.75)]
        return probes.map { point -> Double in let p = b.photoPoint(a.modelPoint(point)); return hypot(p.x - point.x, p.y - point.y) }.reduce(0, +) / 3
    }
}
