// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI
import MoonCore

@MainActor
extension EditorModel {
    var availableFeatureKinds: [String] { Array(Set(features.map(\.kind) + (document?.settings.kinds ?? []))).sorted() }
    var allFeatureKinds: Binding<Bool> {
        Binding(get: { self.document?.settings.matchesAllKinds ?? true }, set: { value in self.edit { $0.settings.allKinds = value } })
    }
    func featureKind(_ kind: String) -> Binding<Bool> {
        Binding(get: { self.document?.settings.kinds.contains(kind) ?? false }, set: { selected in
            self.edit { document in
                document.settings.kinds.removeAll { $0 == kind }
                if selected { document.settings.kinds.append(kind); document.settings.kinds.sort() }
            }
        })
    }
    var featureKindSummary: String {
        if document?.settings.matchesAllKinds != false { return tr("全部") }
        let count = document?.settings.kinds.count ?? 0
        return count == 0 ? tr("未选择") : tr("已选 \(count) 类")
    }
    var candidateOverlaysVisible: Bool { panelTab == 0 && manualSectionExpanded && !manualPickingExpanded }
    var referenceMarkersVisible: Bool { panelTab == 0 && (!candidateOverlaysVisible || referencePointsExpanded) }
    func workspaceChanged() {
        cancelCanvasInteraction()
        if panelTab != 0 { showMask = false }
    }
    func cancelCanvasInteraction() {
        canvasTool = .pan; placementText = nil; placementFeatureID = nil; canvasInteractionRevision += 1
    }
    var craterSearchResults: [Feature] {
        func normalized(_ value: String) -> String {
            value.folding(options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive], locale: Locale(identifier: "en_US_POSIX"))
        }
        let query = normalized(craterQuery.trimmingCharacters(in: .whitespacesAndNewlines))
        guard !query.isEmpty else { return [] }
        return Array(features.filter {
            ["Crater, craters", "Satellite Feature"].contains($0.kind) && normalized($0.searchText).contains(query)
        }.sorted {
            let exactLeft = normalized($0.name) == query, exactRight = normalized($1.name) == query
            if exactLeft != exactRight { return exactLeft }
            return $0.diameter > $1.diameter
        }.prefix(100))
    }
    var chosenCraterFeature: Feature? { craterSearchResults.first { $0.id == craterSelection } }
    var canConfirmCandidate: Bool { !busy && chosenCraterFeature != nil && craterCandidates.contains { $0.id == selectedCandidate } }
    @discardableResult
    func useSelectedCandidate() throws -> Bool {
        guard !busy, let document, let index = craterCandidates.firstIndex(where: { $0.id == selectedCandidate }), let feature = chosenCraterFeature else { return false }
        if let geometry = document.calibration?.geometry ?? document.state.geometry,
           !geometry.project(latitude: feature.latitude, longitude: feature.longitude).visible {
            throw MoonError.invalid("此地形位于月球背面。请核对拍摄时间或地形名称。")
        }
        let point = craterCandidates[index].center
        guard point.isFinite, point.x >= 0, point.y >= 0, point.x < Double(document.imageWidth), point.y < Double(document.imageHeight) else { return false }
        addAnchor(id: feature.id, point: point)
        let name = uiLanguage == "English" ? feature.name : feature.caption(.bilingual)
        status = "已确认候选 \(String(format: "%02d", index + 1))：\(name)"
        return true
    }
    func setAnnotationVisible(_ id: UUID, _ visible: Bool) {
        selectedID = id
        changeSelected { $0.hidden = !visible }
        relayoutLabels()
    }
    func relayoutLabels(resetLayout: Bool = false, resetEdits: Bool = false) {
        guard !busy, var snapshot = displayDocument, snapshot.calibration != nil, let image else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        if resetLayout || resetEdits { ProjectCompatibility.resetAnnotations(&snapshot, layoutOnly: !resetEdits) }
        let immutable = snapshot, cached = scene, features = features, display = displayImage
        busy = true; taskStatus = "正在重新排布标签…"
        let token = ComputeTask(); nativeTask = token
        operation = Task {
            defer { busy = false; operation = nil; nativeTask = nil; taskStatus = "" }
            do {
                let result = try await Task.detached(priority: .userInitiated) {
                    let path = immutable.state.terrainPath
                    let dem = !path.isEmpty && FileManager.default.fileExists(atPath: path) ? try ElevationMap(url: URL(fileURLWithPath: path)) : nil
                    return try AnnotationSceneBuilder.build(document: immutable, photo: PhotoPixels(image), features: features, dem: dem, task: token,
                        measure: AnnotationRenderer.measure, captionBounds: SceneRenderer.labelBounds,
                        configureCaption: { SceneRenderer.configureCaption($0, feature: $1, document: $2) },
                        displayPhoto: display.map { try PhotoPixels($0) }, reusingScene: cached)
                }.value
                try token.check(); try Task.checkCancellation()
                guard var current = document else { return }
                if resetLayout || resetEdits { remember(current) }
                current.annotations = result.0.annotations
                current.state.legacy["labels"] = result.0.state.legacy["labels"]
                document = current; appliedDocument = result.0; scene = result.1; revision += 1
                status = "已应用 · \(result.0.annotations.filter { AnnotationSceneBuilder.visible($0, document: result.0, scene: result.1) }.count) 个可见地名"
            } catch is CancellationError { status = "已中止图层生成，保留当前显示。" }
            catch { if !token.isCancelled { show(error) } }
        }
    }
}
