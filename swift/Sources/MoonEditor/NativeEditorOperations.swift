// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI
import MoonCore

enum CanvasTool: Equatable { case pan, paint, erase, polygon, anchor(String), candidateCenter(Int) }

@MainActor
extension EditorModel {
    var workingState: ProjectState { document?.state ?? referenceState }
    var terrainSourceDescription: String {
        if !workingState.terrainPath.isEmpty { return URL(fileURLWithPath: workingState.terrainPath).lastPathComponent }
        return DataStore.bundledDEM == nil ? "未导入高程数据" : "内置基础高程 · LOLA 1.9 km"
    }
    func selectTerrainCenter(_ id: String) {
        guard let feature = features.first(where: { $0.id == id }) else { return }
        editState { $0.terrainSettings.set("center_lat", feature.latitude); $0.terrainSettings.set("center_lon", feature.longitude); $0.terrainSettings.set("center_id", id) }
    }
    func searchTerrainCenter(_ query: String) {
        if let feature = searchTerrainFeatures(query).first { selectTerrainCenter(feature.id) }
    }
    private var enabledAnchorIndices: [Int] { (document?.state.anchors ?? []).indices.filter { document?.state.anchors[$0].enabled != false } }
    func referenceResidual(at index: Int) -> Double? {
        guard let ordinal = enabledAnchorIndices.firstIndex(of: index), let report, report.residuals.indices.contains(ordinal) else { return nil }
        let value = report.residuals[ordinal]
        return value.isFinite ? value : nil
    }
    var suspectAnchorIndex: Int? {
        guard let suspect = report?.suspect, enabledAnchorIndices.indices.contains(suspect) else { return nil }
        return enabledAnchorIndices[suspect]
    }
    func editState(_ change: (inout ProjectState) -> Void) {
        guard !busy else { return }
        let previous = workingState; var next = previous; change(&next)
        let geometryChanged = next.utc != previous.utc || next.latitude != previous.latitude || next.longitude != previous.longitude
        let anchorsChanged = next.anchors != previous.anchors
        let terrainChanged = next.terrainSettings != previous.terrainSettings || next.terrainPath != previous.terrainPath
        if document != nil {
            edit { document in document.state = next; if geometryChanged || anchorsChanged { document.invalidateRegistration(clearGeometry: geometryChanged) } }
            if geometryChanged || anchorsChanged {
                appliedDocument = document; scene = nil; report = nil; selectedID = nil; canvasTool = .pan
                status = geometryChanged ? "拍摄条件已改，需重新校准" : "参考点已改，需重新校准"
            } else if next.captureMode != previous.captureMode { status = "拍摄方式已改，下次识别生效" }
        } else {
            referenceState = next
        }
        if geometryChanged || terrainChanged { closeReferencePreview(); reference = nil; referenceGeometry = nil; referenceProject = nil }
    }
    var hasPendingStyle: Bool {
        guard let document, let appliedDocument else { return false }
        let live = Set(["label_opacity", "map_light_mask", "map_light_threshold", "illuminated_only", "grid_opacity", "elevation_opacity", "contour_opacity", "terminator_opacity", "overview_enabled", "overview_position", "legend_position"])
        return document.settings != appliedDocument.settings || document.style.values.filter { !live.contains($0.key) } != appliedDocument.style.values.filter { !live.contains($0.key) }
    }
    var displayDocument: MoonDocument? {
        guard let document else { return nil }
        guard var applied = appliedDocument else { return previewingOverlay(document) }
        applied.annotations = document.annotations
        applied.state.anchors = document.state.anchors
        applied.state.recognitionMask = document.state.recognitionMask
        applied.state.legacy["labels"] = document.state.legacy["labels"]
        applied.changeStyle { $0.values["label_opacity"] = document.style.values["label_opacity"] }
        applied.changeStyle { $0.values["overview_enabled"] = document.style.values["overview_enabled"] }
        // Live display changes stay live even when an unrelated setting still
        // needs a new layout (for example, enabling landing-site labels).
        let keys = ["map_light_mask", "map_light_threshold", "illuminated_only", "grid_opacity", "elevation_opacity", "contour_opacity", "terminator_opacity", "overview_position", "legend_position"]
        applied.changeStyle { style in for key in keys { style.values[key] = document.style.values[key] } }
        return previewingOverlay(applied)
    }
    private func previewingOverlay(_ document: MoonDocument) -> MoonDocument {
        guard let preview = overlayPreview else { return document }
        var displayed = document
        displayed.changeStyle { $0.values[preview.key] = .array([.number(preview.position.x), .number(preview.position.y)]) }
        return displayed
    }
    func toggleOverview(_ enabled: Bool) {
        edit { $0.changeStyle { $0.set("overview_enabled", enabled) } }
        guard enabled, scene?.overview == nil, let snapshot = document else { return }
        Task {
            do {
                let overview = try await Task.detached { try OverviewBuilder.build(document: snapshot, task: ComputeTask()) }.value
                guard document?.calibration == snapshot.calibration, document?.style.bool("overview_enabled") == true else { return }
                var next = scene ?? AnnotationScene(); next.overview = overview; next.id = UUID(); scene = next
            } catch { show(error) }
        }
    }
    var chosenFeature: Feature? { features.first { $0.id == catalogSelection } }
    func styleNumber(_ key: String, fallback: Double, range: ClosedRange<Double>? = nil) -> Binding<Double> {
        Binding(get: { self.document?.style.number(key, fallback) ?? fallback }, set: { value in
            let value = range.map { min($0.upperBound, max($0.lowerBound, value)) } ?? value
            self.edit { $0.changeStyle { $0.set(key, value) } }
        })
    }
    func styleBool(_ key: String, fallback: Bool = false) -> Binding<Bool> {
        Binding(get: { self.document?.style.bool(key, fallback) ?? fallback }, set: { value in self.edit { $0.changeStyle { $0.set(key, value) } } })
    }
    func styleString(_ key: String, fallback: String = "") -> Binding<String> {
        Binding(get: { self.document?.style.string(key, fallback) ?? fallback }, set: { value in self.edit { $0.changeStyle { $0.set(key, value) } } })
    }
    func stateString(_ path: WritableKeyPath<ProjectState, String>) -> Binding<String> {
        Binding(get: { self.workingState[keyPath: path] }, set: { value in self.editState { $0[keyPath: path] = value } })
    }
    func cancelOperation() {
        nativeTask?.cancel(); operation?.cancel(); taskStatus = "正在中止…"
    }
    func startAutomatic() {
        guard !busy else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard captureDateValid && captureTimeValid else { status = "请输入完整、有效的拍摄日期和时间。"; return }
        guard let snapshot = document, let image else { return }
        busy = true; taskStatus = "计算 JPL DE421 月球位置…"
        let token = ComputeTask(); nativeTask = token
        operation = Task {
            defer { busy = false; nativeTask = nil; operation = nil; taskStatus = "" }
            do {
                var snapshot = snapshot
                let photo = try await Task.detached { try PhotoPixels(image) }.value
                let geometry = try await Task.detached { try NativeCompute.ephemeris(utc: snapshot.state.utc, latitude: snapshot.state.latitude, longitude: snapshot.state.longitude) }.value
                let features = self.features
                let currentDEM = snapshot.state.terrainPath
                let cachedDEM = Catalog.resource("LDEM_16", "LBL")?.path ?? DataStore.cache.appendingPathComponent("terrain/LDEM_16.LBL").path
                let existingDEM = FileManager.default.fileExists(atPath: currentDEM) ? currentDEM : FileManager.default.fileExists(atPath: cachedDEM) ? cachedDEM : nil
                if let existingDEM { snapshot.state.terrainPath = existingDEM }
                let progress: @Sendable (String) -> Void = { [weak self] message in Task { @MainActor in self?.taskStatus = message } }
                var result: IdentificationResult
                do {
                    result = try await Task.detached(priority: .userInitiated) {
                        let dem = try existingDEM.map { try ElevationMap(url: URL(fileURLWithPath: $0)) }
                        return try RecognitionEngine.identify(photo: photo, geometry: geometry, state: snapshot.state, features: features, dem: dem, task: token, progress: progress)
                    }.value
                } catch {
                    try token.check(); try Task.checkCancellation()
                    if existingDEM != nil { throw error }
                    taskStatus = "正在准备 LOLA 高程参考…"
                    let url = try await demURL(snapshot, token: token)
                    snapshot.state.terrainPath = url.path
                    let state = snapshot.state
                    result = try await Task.detached(priority: .userInitiated) {
                        let dem = try ElevationMap(url: url)
                        return try RecognitionEngine.identify(photo: photo, geometry: geometry, state: state, features: features, dem: dem, task: token, progress: progress)
                    }.value
                }
                try token.check(); try Task.checkCancellation()
                try snapshot.applyIdentification(result)
                report = snapshot.referenceReport(features: features)
                if !result.candidates.isEmpty { craterCandidates = result.candidates; selectedCandidate = craterCandidates.first?.id; craterSelection = nil }
                if let old = document { remember(old) }
                document = snapshot; appliedDocument = snapshot
                status = "配准通过 · \(result.matches) 个对应点 · RMS \(String(format: "%.2f", result.rms)) px"
                panelTab = 1
                DispatchQueue.main.async { [weak self] in self?.applyNativeScene() }
            } catch is CancellationError { status = "操作已中止，保留原有照片和配准。" }
            catch { if token.isCancelled { status = "操作已中止。" } else { show(error) } }
        }
    }
    func applyNativeScene(resetLayout: Bool = false, resetEdits: Bool = false, initialLoad: Bool = false) {
        guard var snapshot = document, let image, !busy else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        let keepClean = initialLoad && !dirty
        if resetEdits || resetLayout { ProjectCompatibility.resetAnnotations(&snapshot, layoutOnly: !resetEdits) }
        if let percent = snapshot.style.values["font_percent"]?.number {
            snapshot.settings.fontSize = max(6, (Double(min(snapshot.imageWidth, snapshot.imageHeight)) * percent / 100).rounded())
        }
        busy = true; taskStatus = "正在排布标签与地图图层…"
        let token = ComputeTask(); nativeTask = token
        operation = Task {
            defer { busy = false; nativeTask = nil; operation = nil; taskStatus = "" }
            do {
                var url: URL?
                if snapshot.state.projectionSurface == "terrain" || snapshot.style.elevationEnabled || snapshot.style.contourEnabled || snapshot.style.string("crater_outline_shape", "ellipse") == "terrain" {
                    taskStatus = "正在准备 LOLA DEM…"; url = try await demURL(snapshot, token: token); snapshot.state.terrainPath = url!.path
                } else if !snapshot.state.terrainPath.isEmpty, FileManager.default.fileExists(atPath: snapshot.state.terrainPath) { url = URL(fileURLWithPath: snapshot.state.terrainPath) }
                let immutable = snapshot, demPath = url, features = self.features, display = displayImage
                let result = try await Task.detached(priority: .userInitiated) {
                    let photo = try PhotoPixels(image), dem = try demPath.map { try ElevationMap(url: $0) }
                    return try AnnotationSceneBuilder.build(document: immutable, photo: photo, features: features, dem: dem, task: token, measure: AnnotationRenderer.measure, captionBounds: SceneRenderer.labelBounds, configureCaption: { SceneRenderer.configureCaption($0, feature: $1, document: $2) }, displayPhoto: display.map { try PhotoPixels($0) })
                }.value
                try token.check(); try Task.checkCancellation()
                if !initialLoad, let current = document { remember(current) }
                document = result.0; appliedDocument = result.0; scene = result.1; revision += 1
                if keepClean { markClean() }
                status = "已应用 · \(result.0.annotations.filter { AnnotationSceneBuilder.visible($0, document: result.0, scene: result.1) }.count) 个可见地名"
            } catch is CancellationError { status = "已中止图层生成，保留当前显示。" }
            catch { if !token.isCancelled { show(error) } }
        }
    }
    private func demURL(_ document: MoonDocument, token: ComputeTask) async throws -> URL {
        if !document.state.terrainPath.isEmpty, FileManager.default.fileExists(atPath: document.state.terrainPath) { return URL(fileURLWithPath: document.state.terrainPath) }
        return try await DataStore.basicDEM(task: token)
    }
    func manualCalibration() {
        guard !busy else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard captureDateValid && captureTimeValid, let snapshot = document else { return }
        busy = true; taskStatus = "按参考点校准…"
        let token = ComputeTask(); nativeTask = token
        operation = Task {
            defer { busy = false; operation = nil; nativeTask = nil; taskStatus = "" }
            do {
                let features = self.features, mirror = manualMirror
                let urls = [URL(fileURLWithPath: snapshot.state.terrainPath), DataStore.cache.appendingPathComponent("terrain/LDEM_16.LBL"), Catalog.resource("LDEM_16", "LBL")].compactMap { $0 }
                let result = try await Task.detached(priority: .userInitiated) { () throws -> (MoonDocument, CalibrationReport) in
                    var input = snapshot, map: ElevationMap?
                    for url in urls where FileManager.default.fileExists(atPath: url.path) {
                        try token.check()
                        if let dem = try? ElevationMap(url: url) { map = dem; input.state.terrainPath = url.path; break }
                    }
                    return try ManualCalibration.solve(document: input, features: features, dem: map, mirror: mirror, task: token)
                }.value
                try token.check(); try Task.checkCancellation()
                if let current = document { remember(current) }; document = result.0; report = result.1
                status = "手动校准 RMS \(String(format: "%.2f", result.1.rms)) px"; appliedDocument = result.0
                panelTab = 1; DispatchQueue.main.async { [weak self] in self?.applyNativeScene() }
            } catch is CancellationError { status = "已取消，保留原有配准。" }
            catch { if !token.isCancelled { show(error) } }
        }
    }
    func calculateGeometry() {
        guard var snapshot = document, !busy else { return }
        busy = true; taskStatus = "计算月面几何…"
        operation = Task {
            defer { busy = false; operation = nil; taskStatus = "" }
            do {
                let state = snapshot.state
                let geometry = try await Task.detached { try NativeCompute.ephemeris(utc: state.utc, latitude: state.latitude, longitude: state.longitude) }.value
                try Task.checkCancellation()
                ProjectCompatibility.captureEdits(&snapshot)
                snapshot.state.geometry = geometry; snapshot.calibration = nil; snapshot.state.projectionSurface = "sphere"; snapshot.annotations = []
                for key in ["automatic_recognition", "annotation_relief", "terrain_rims"] { snapshot.state.legacy.removeValue(forKey: key) }
                if let previous = document { remember(previous) }
                document = snapshot; appliedDocument = snapshot; scene = nil; report = nil; status = "月面几何已计算"
            } catch is CancellationError { status = "已取消。" }
            catch { show(error) }
        }
    }
    func pickAnchor() {
        guard let feature = chosenFeature, document != nil else { return }
        canvasTool = .anchor(feature.id)
        status = "在照片上点击 \(feature.chinese.isEmpty ? feature.name : feature.chinese) 的完整坑缘中心。Esc 取消。"
    }
    func addAnchor(id: String, point: PixelPoint) {
        editState { state in state.anchors.removeAll { $0.id == id }; state.anchors.append(ControlPoint(id: id, point: point)) }
        canvasTool = .pan; status = "已加入参考点，可继续补点或开始配准。"
    }
    func commitMask(_ stroke: MaskStroke) {
        edit { document in var state = document.state; state.recognitionMask.operations.append(stroke); document.state = state }
    }
    func craterNumber(_ key: String, fallback: Double) -> Binding<Double> {
        Binding(get: { self.workingState.craterDetection.number(key, fallback) }, set: { value in
            self.editState { $0.craterDetection.set(key, value) }
            if !self.craterCandidates.isEmpty { self.status = "参数已改，需重新检测" }
        })
    }
    var craterViewport: Binding<Bool> {
        Binding(get: { self.workingState.craterDetection.bool("viewport") }, set: { value in
            self.editState { $0.craterDetection.set("viewport", value) }
            if !self.craterCandidates.isEmpty { self.status = "参数已改，需重新检测" }
        })
    }
    func detectCandidates() {
        guard let document, let image, !busy else { return }
        let settings = document.state.craterDetection
        let minimum = settings.number("min_radius", 8), maximum = settings.number("max_radius", 180), sensitivity = settings.number("sensitivity", 50)
        let limit = Int(settings.number("max_candidates", 80)), onlyViewport = settings.bool("viewport")
        guard maximum > minimum else { show(MoonError.invalid("最大半径必须大于最小半径。")); return }
        cancelCanvasInteraction()
        busy = true; taskStatus = "正在检测候选坑缘…"
        let token = ComputeTask(); nativeTask = token
        let rect = viewport
        operation = Task {
            defer { busy = false; nativeTask = nil; operation = nil; taskStatus = "" }
            do {
                let candidates = try await Task.detached(priority: .userInitiated) { () throws -> [CraterCandidate] in
                    let full = try PhotoPixels(image)
                    let bounds = onlyViewport && rect.width > 0 ? rect.intersection(CGRect(x: 0, y: 0, width: full.width, height: full.height)).integral : CGRect(x: 0, y: 0, width: full.width, height: full.height)
                    let photo = try full.cropped(bounds)
                    let fullMask = document.state.recognitionMask.raster(width: full.width, height: full.height, originalWidth: full.width, originalHeight: full.height, padding: 3)
                    var mask = [UInt8](repeating: 255, count: photo.width * photo.height)
                    for y in 0..<photo.height { for x in 0..<photo.width { mask[y * photo.width + x] = fullMask[(y + Int(bounds.minY)) * full.width + x + Int(bounds.minX)] } }
                    var result = try NativeCompute.detect(photo: photo, mask: mask, task: token, minimum: minimum, maximum: maximum, count: min(500, max(1, limit)), sensitivity: sensitivity)
                    for i in result.indices { result[i].center.x += bounds.minX; result[i].center.y += bounds.minY }
                    return result
                }.value
                try token.check(); craterCandidates = candidates; selectedCandidate = candidates.first?.id
                craterSelection = nil; manualSectionExpanded = true; manualPickingExpanded = false; panelTab = 0
                status = "找到 \(candidates.count) 个候选坑缘，请核对后确认地名。"
            } catch is CancellationError { status = "已中止检测。" }
            catch { if !token.isCancelled { show(error) } }
        }
    }
    func confirmCandidate() {
        do { try useSelectedCandidate() } catch { show(error) }
    }
    func exportCraterCandidates() {
        guard let document, !craterCandidates.isEmpty else { return }
        let panel = NSSavePanel(); panel.title = tr("导出疑似坑候选")
        panel.allowedContentTypes = [.commaSeparatedText]; panel.canCreateDirectories = true
        let imageURL = URL(fileURLWithPath: document.imagePath)
        panel.nameFieldStringValue = imageURL.deletingPathExtension().lastPathComponent + "-crater-candidates.csv"
        guard NativeDialogs.run(panel) == .OK, let url = panel.url else { return }
        do { try CraterCSV.data(candidates: craterCandidates, imageName: imageURL.lastPathComponent).write(to: url, options: .atomic); status = "CSV 已保存" }
        catch { show(error) }
    }
    func downloadDEM() {
        guard !busy else { return }
        busy = true; taskStatus = "下载 LOLA 高程数据…"
        let token = ComputeTask(); nativeTask = token
        operation = Task {
            defer { busy = false; nativeTask = nil; operation = nil; taskStatus = "" }
            do {
                let url = try await DataStore.basicDEM(task: token)
                if var document { document.state.terrainPath = url.path; self.document = document } else { referenceState.terrainPath = url.path }
                status = "LOLA DEM 已缓存，可离线使用。"
            } catch is CancellationError { status = "已取消下载。" }
            catch { if !token.isCancelled { show(error) } }
        }
    }
    func importDEM() {
        let panel = NSOpenPanel(); panel.title = "导入 LOLA DEM（LBL、IMG 或 NPZ）"; panel.allowsOtherFileTypes = true
        guard NativeDialogs.run(panel) == .OK, let url = panel.url else { return }
        do { _ = try ElevationMap(url: url); editState { $0.terrainPath = url.path }; status = "已导入 \(url.lastPathComponent)" }
        catch { show(error) }
    }
    func renderRegion() {
        guard !busy else { return }
        var snapshot = document ?? MoonDocument(imagePath: "reference")
        if document == nil { snapshot.state = referenceState }
        if snapshot.state.terrainSettings.values["center_lat"] == nil,
           let center = features.first(where: { $0.id == snapshot.state.terrainSettings.string("center_id") }) ?? searchFeatures("").first {
            snapshot.state.terrainSettings.set("center_lat", center.latitude); snapshot.state.terrainSettings.set("center_lon", center.longitude); snapshot.state.terrainSettings.set("center_id", center.id)
        }
        busy = true; taskStatus = "生成局部地形参考…"
        let token = ComputeTask(); nativeTask = token
        operation = Task {
            defer { busy = false; nativeTask = nil; operation = nil; taskStatus = "" }
            do {
                let url = try await demURL(snapshot, token: token), settings = snapshot.state.terrainSettings
                let output = try await Task.detached(priority: .userInitiated) { () throws -> (TerrainReference, MoonGeometry) in
                    let dem = try ElevationMap(url: url)
                    let geometry = try NativeCompute.ephemeris(utc: snapshot.state.utc, latitude: snapshot.state.latitude, longitude: snapshot.state.longitude)
                    let reference = try ReferenceRenderer.region(dem: dem, geometry: geometry, latitude: settings.number("center_lat", 0), longitude: settings.number("center_lon", 0),
                        widthKM: settings.number("width_km", 300), size: Int(settings.number("size", 768)), gamma: settings.number("gamma", 1.6),
                        lambert: settings.string("model", "Lommel-Seeliger") == "Lambert", shadows: settings.bool("shadows", true), task: token)
                    return (reference, geometry)
                }.value
                try token.check(); reference = output.0; referenceGeometry = output.1; referenceProject = nil
                if document != nil { document?.state.terrainPath = url.path } else { referenceState.terrainPath = url.path }
                status = "局部参考已生成 · 有效覆盖 \(Int(output.0.validFraction * 100))%"
                showReferencePreview()
            } catch is CancellationError { status = "已中止。" }
            catch { if !token.isCancelled { show(error) } }
        }
    }
    func alignReference(usingNASA: Bool = false) {
        guard let reference, let geometry = referenceGeometry, let image, let snapshot = document, !busy else { return }
        busy = true; taskStatus = "匹配参考图与照片…"
        let token = ComputeTask(); nativeTask = token
        operation = Task {
            defer { busy = false; nativeTask = nil; operation = nil; taskStatus = "" }
            do {
                let features = self.features
                let result = try await Task.detached { () throws -> IdentificationResult in
                    let photo = try PhotoPixels(image)
                    let mask = snapshot.state.recognitionMask.raster(width: photo.width, height: photo.height, originalWidth: photo.width, originalHeight: photo.height)
                    let result = try RecognitionEngine.matchReference(reference: reference, geometry: geometry, photo: photo, mask: mask, task: token)
                    try RecognitionEngine.validateAnchors(result.calibration, state: snapshot.state, features: features, previous: snapshot.calibration)
                    return result
                }.value
                try token.check(); try Task.checkCancellation()
                var next = snapshot; next.calibration = result.calibration; next.state.geometry = geometry
                if let source = referenceProject {
                    next.state.projectionSurface = source.state.projectionSurface
                    next.state.latitude = source.state.latitude; next.state.longitude = source.state.longitude
                    for key in ["terrain_rims", "annotation_relief"] { next.state.legacy[key] = source.state.legacy[key] }
                } else { next.state.projectionSurface = "sphere" }
                remember(snapshot); document = next; appliedDocument = next; panelTab = 1
                DispatchQueue.main.async { [weak self] in self?.applyNativeScene() }
            } catch {
                if !token.isCancelled {
                    if usingNASA { nasaFailed(error) } else { show(error) }
                }
            }
        }
    }
    private func nasaFailed(_ error: Error) {
        panelTab = 0; manualSectionExpanded = true; manualPickingExpanded = false
        manualReviewRequest += 1
        show(error); status = "NASA 配准失败，可用手动校准"
    }
    func loadNASA() {
        guard let snapshot = document, !busy else { return }
        guard snapshot.state.latitude == nil else { show(MoonError.invalid("NASA 参考使用地心视角。请取消“使用拍摄地点”，或用地形参考点做站心配准。")); return }
        busy = true; taskStatus = "下载 NASA 同时刻影像…"
        let token = ComputeTask(); nativeTask = token
        let loader = nasaLoader
        operation = Task {
            defer { busy = false; nativeTask = nil; operation = nil; taskStatus = "" }
            do {
                let result = try await loader(snapshot.state.utc, token)
                try token.check(); closeReferencePreview(); reference = result.0; referenceGeometry = result.1; referenceProject = nil
                DispatchQueue.main.async { [weak self] in self?.alignReference(usingNASA: true) }
            } catch is CancellationError { status = "已取消下载。" }
            catch { if !token.isCancelled { nasaFailed(error) } }
        }
    }
    func loadLocalReference(_ source: URL? = nil) {
        guard let snapshot = document, !busy else { return }
        let url: URL
        if let source { url = source }
        else {
            let panel = NSOpenPanel(); panel.title = tr("选择同一拍摄时刻的已校准参考工程"); panel.allowsOtherFileTypes = true
            guard NativeDialogs.run(panel) == .OK, let selected = panel.url else { return }
            url = selected
        }
        let reader = referenceReader
        busy = true; taskStatus = "读取本地参考工程…"
        operation = Task {
            defer { busy = false; operation = nil; taskStatus = "" }
            do {
                let loaded = try await CancellableRead.run { try reader(url, snapshot.state.utc) }
                try Task.checkCancellation(); closeReferencePreview(); reference = loaded.0; referenceGeometry = loaded.1.calibration?.geometry; referenceProject = loaded.1
                DispatchQueue.main.async { [weak self] in self?.alignReference() }
            } catch is CancellationError { status = "已取消。" }
            catch { show(error) }
        }
    }
    func saveReference() {
        guard let reference, let geometry = referenceGeometry, !busy else { return }
        let panel = NSSavePanel(); panel.title = tr("保存 DEM 模拟与参考工程"); panel.nameFieldStringValue = "dem-reference.png"
        panel.allowedContentTypes = [.png]; panel.canCreateDirectories = true
        guard NativeDialogs.run(panel) == .OK, let url = panel.url else { return }
        do { try ReferenceIO.save(reference, geometry: geometry, state: workingState, to: url); status = "已保存 \(url.lastPathComponent) 和对应参考工程。" }
        catch { show(error) }
    }
    func saveLegacy() {
        guard !busy else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let snapshot = document else { return }
        let panel = NSSavePanel(); panel.title = tr("保存 MoonLabeler 工程"); panel.nameFieldStringValue = URL(fileURLWithPath: snapshot.imagePath).deletingPathExtension().lastPathComponent + ".moonlabel"
        guard NativeDialogs.run(panel) == .OK, let url = panel.url else { return }
        do { try ProjectCompatibility.writeLegacy(snapshot, to: url); status = "已保存兼容工程 \(url.lastPathComponent)" }
        catch { show(error) }
    }
    func exportSVG(to destination: URL? = nil) {
        guard !busy else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let document = displayDocument, let image = displayImage ?? self.image else { return }
        let url: URL
        if let destination { url = destination }
        else {
            let panel = NSSavePanel(); panel.title = tr("导出 SVG")
            panel.nameFieldStringValue = URL(fileURLWithPath: document.imagePath).deletingPathExtension().lastPathComponent + "-annotated.svg"
            guard NativeDialogs.run(panel) == .OK, let selected = panel.url else { return }
            url = selected
        }
        beginExport(.svg, image: image, document: document, scene: scene, to: url)
    }
}
