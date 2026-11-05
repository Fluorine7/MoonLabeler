// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI
import UniformTypeIdentifiers
import MoonCore

@MainActor
public final class EditorModel: ObservableObject {
    @Published public var document: MoonDocument?
    @Published public var image: CGImage?
    @Published public var displayImage: CGImage?
    @Published var selectedID: UUID?
    @Published var catalogQuery = "" { didSet { if catalogQuery != oldValue { catalogSelection = nil } } }
    @Published var catalogSelection: String?
    @Published var craterQuery = "" { didSet { if craterQuery != oldValue { craterSelection = nil } } }
    @Published var craterSelection: String?
    @Published var sidebarTab = 0
    @Published var placementText: String?
    @Published var placementFeatureID: String?
    @Published var busy = false
    @Published var captureDateValid = true
    @Published var captureTimeValid = true
    @Published var status = "打开照片，或导入已有工程开始。"
    @Published var zoomLabel = "适合窗口"
    @Published var fitRequest = 0
    @Published var actualSizeRequest = 0
    @Published var zoomStepRequest = 0
    var zoomStep = 0
    @Published var revision = 0
    @Published var scene: AnnotationScene?
    @Published var appliedDocument: MoonDocument?
    @Published var panelTab = 0 { didSet { if panelTab != oldValue { workspaceChanged() } } }
    @Published var manualReviewRequest = 0
    @Published var manualSectionExpanded = false { didSet { if manualSectionExpanded != oldValue { cancelCanvasInteraction() } } }
    @Published var manualPickingExpanded = false { didSet { if manualPickingExpanded != oldValue { cancelCanvasInteraction() } } }
    @Published var referencePointsExpanded = false
    @Published var canvasInteractionRevision = 0
    @Published var photoRevision = 0
    @Published var manualMirror = -1
    @Published var canvasTool = CanvasTool.pan
    @Published var showMask = false
    @Published var showAnnotations = true
    @Published var brushDiameter = 80.0
    @Published var craterCandidates: [CraterCandidate] = []
    @Published var showAllCandidateContours = false
    @Published var selectedCandidate: Int? {
        didSet {
            if selectedCandidate != oldValue {
                craterSelection = nil
                if case .candidateCenter = canvasTool { cancelCanvasInteraction() }
            }
        }
    }
    @Published var report: CalibrationReport?
    @Published var taskStatus = ""
    @Published var reference: TerrainReference?
    @Published var referenceGeometry: MoonGeometry?
    @Published var referenceState: ProjectState = {
        var state = ProjectState(), calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        state.utc = UTCClock.string(calendar.date(bySettingHour: 15, minute: 0, second: 0, of: Date()) ?? Date()); return state
    }()
    @Published var referenceProject: MoonDocument?
    var referenceWindow: ReferencePreviewController?
    @Published var computeMode = UserDefaults.standard.string(forKey: "moon-swift-compute") ?? "auto"
    @Published var uiLanguage = UserDefaults.standard.string(forKey: "swift-ui-language") ?? "简体中文"
    var viewport = CGRect.zero
    struct OverlayPreview { var key: String; var position: PixelPoint }
    var overlayPreview: OverlayPreview?
    var nativeTask: ComputeTask?
    var operation: Task<Void, Never>?
    @Published public private(set) var features: [Feature]
    private var cleanSnapshot: MoonDocument?
    private var saveURL: URL?
    private var undoHistory: [MoonDocument] = []
    private var redoHistory: [MoonDocument] = []
    private var catalogueIndex: [String: String] = [:]
    private let photoReader: @Sendable (URL) throws -> (raw: CGImage, display: CGImage)
    private let catalogueLoader: @Sendable (ComputeTask) async throws -> [Feature]
    var exportWriter: ImageExport.Writer = { try ImageExport.write($0, image: $1, document: $2, scene: $3, to: $4) }
    var referenceReader: @Sendable (URL, String) throws -> (TerrainReference, MoonDocument) = { try ReferenceIO.local($0, utc: $1) }
    var nasaLoader: @Sendable (String, ComputeTask) async throws -> (TerrainReference, MoonGeometry) = { try await ReferenceIO.nasa(utc: $0, task: $1) }

    public init(photoReader: @escaping @Sendable (URL) throws -> (raw: CGImage, display: CGImage) = { try PhotoIO.open($0) },
                catalogueLoader: @escaping @Sendable (ComputeTask) async throws -> [Feature] = { try await CatalogueUpdate.refresh(task: $0) }) {
        self.photoReader = photoReader; self.catalogueLoader = catalogueLoader
        do { features = try Catalog.load() }
        catch { features = []; status = error.localizedDescription }
        catalogueIndex = Dictionary(uniqueKeysWithValues: features.map { ($0.id, $0.searchText) })
    }
    var dirty: Bool { document != cleanSnapshot }
    var canUndo: Bool { !undoHistory.isEmpty && !busy }
    var canRedo: Bool { !redoHistory.isEmpty && !busy }
    var selectedAnnotation: Annotation? { document?.annotations.first { $0.id == selectedID } }
    var title: String {
        saveURL?.deletingPathExtension().lastPathComponent ?? document.map { URL(fileURLWithPath: $0.imagePath).lastPathComponent } ?? "MoonLabeler Swift"
    }
    var searchResults: [Feature] {
        searchFeatures(catalogQuery)
    }
    func searchFeatures(_ text: String) -> [Feature] {
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if query.isEmpty { return features.filter { Catalog.commonNames.contains($0.name) }.sorted { $0.diameter > $1.diameter } }
        return Array(features.lazy.filter {
            (self.catalogueIndex[$0.id] ?? $0.name).localizedStandardContains(query)
        }.prefix(100))
    }
    func searchTerrainFeatures(_ text: String) -> [Feature] {
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return Array(features.filter { query.isEmpty || (catalogueIndex[$0.id] ?? $0.name).localizedStandardContains(query) }
            .sorted { $0.diameter > $1.diameter }.prefix(100))
    }
    func refreshCatalogue() {
        guard !busy else { return }; busy = true; taskStatus = tr("正在更新 USGS 地名…")
        let token = ComputeTask(); nativeTask = token
        operation = Task {
            var refreshLabels = false
            defer {
                busy = false; nativeTask = nil; operation = nil; taskStatus = ""
                if refreshLabels { relayoutLabels() }
            }
            do {
                let values = try await catalogueLoader(token)
                try token.check(); features = values; catalogueIndex = Dictionary(values.map { ($0.id, $0.searchText) }, uniquingKeysWith: { first, _ in first })
                document?.state.legacy.removeValue(forKey: "annotation_relief")
                appliedDocument?.state.legacy.removeValue(forKey: "annotation_relief")
                report = document?.referenceReport(features: values)
                refreshLabels = true
                status = "USGS · \(values.count) 个地名"
            } catch is CancellationError { status = tr("已取消。") }
            catch { if !token.isCancelled { show(error) } }
        }
    }

    func edit(_ change: (inout MoonDocument) -> Void) {
        guard !busy, var next = document else { return }
        change(&next)
        guard next != document else { return }
        remember(document!)
        document = next; revision += 1
    }
    func remember(_ previous: MoonDocument) {
        undoHistory.append(previous)
        if undoHistory.count > 80 { undoHistory.removeFirst() }
        redoHistory.removeAll()
    }
    func undo() {
        guard !busy, let current = document, let previous = undoHistory.popLast() else { return }
        redoHistory.append(current); document = previous; revision += 1; restoreHistoryDisplay()
    }
    func redo() {
        guard !busy, let current = document, let next = redoHistory.popLast() else { return }
        undoHistory.append(current); document = next; revision += 1; restoreHistoryDisplay()
    }
    private func restoreHistoryDisplay() {
        guard document?.calibration != appliedDocument?.calibration else { return }
        appliedDocument = document; scene = nil; report = document?.referenceReport(features: features)
        if document?.calibration != nil && image != nil { applyNativeScene(initialLoad: true) }
    }
    func endDrag(previous: MoonDocument) {
        if document != previous { remember(previous); revision += 1 }
    }
    func moveSelected(to point: PixelPoint, anchor: Bool = false) {
        guard var next = document, let index = next.annotations.firstIndex(where: { $0.id == selectedID }) else { return }
        if anchor { next.annotations[index].anchor = point; next.annotations[index].anchorEdited = true }
        else { next.annotations[index].position = point; next.annotations[index].positionEdited = true }
        next.annotations[index].automatic = false
        document = next
    }
    func changeSelected(_ change: (inout Annotation) -> Void) {
        edit { document in
            guard let index = document.annotations.firstIndex(where: { $0.id == selectedID }) else { return }
            let before = document.annotations[index]
            change(&document.annotations[index])
            if before.text != document.annotations[index].text { document.annotations[index].textEdited = true }
            if before.position != document.annotations[index].position { document.annotations[index].positionEdited = true }
            if before.anchor != document.annotations[index].anchor { document.annotations[index].anchorEdited = true }
            document.annotations[index].automatic = false
        }
    }
    func deleteSelected() {
        guard selectedID != nil else { return }
        edit { document in
            guard let index = document.annotations.firstIndex(where: { $0.id == selectedID }) else { return }
            if document.annotations[index].featureID == nil { document.annotations.remove(at: index) }
            else { document.annotations[index].hidden = true; document.annotations[index].automatic = false }
        }
        selectedID = nil
    }
    func placeFeature(_ feature: Feature) {
        guard document != nil, !busy else { return }
        placementFeatureID = feature.id; placementText = feature.caption(document!.settings.language)
        catalogSelection = feature.id
        status = "在照片上点击 \(feature.chinese.isEmpty ? feature.name : feature.chinese) 的位置。按 Esc 取消。"
    }
    func placeFreeText() {
        guard document != nil else { return }
        placementFeatureID = nil; placementText = "新标注"
        status = "在照片上点击放置文字，再在右侧编辑。按 Esc 取消。"
    }
    func finishPlacement(at point: PixelPoint) {
        guard let text = placementText, let current = document else { return }
        let size = AnnotationRenderer.measure(text, current.settings.fontSize)
        let annotation = Annotation(featureID: placementFeatureID, text: text, anchor: point,
                                    position: PixelPoint(max(0, min(point.x + 25, Double(current.imageWidth) - size.0)),
                                                         max(0, min(point.y - size.1 / 2, Double(current.imageHeight) - size.1))))
        edit { $0.annotations.append(annotation) }
        selectedID = annotation.id; placementText = nil; placementFeatureID = nil
        status = "已添加标注。拖动文字调整位置；按住 Option 拖动圆点可调整指向。"
    }
    func generate() {
        guard let current = document, current.calibration != nil else { return }
        let annotations = LabelLayout.generate(document: current, features: features, measure: AnnotationRenderer.measure)
        edit { $0.annotations = annotations }
        status = "已排布 \(annotations.filter { !$0.hidden }.count) 个可见标注，保留了手工修改。"
    }
    func changeCaptureComponent(_ component: Calendar.Component, value: Int) {
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        var parts = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: UTCClock.parse(workingState.utc) ?? Date())
        parts.setValue(value, for: component)
        if component == .year || component == .month {
            let day = parts.day ?? 1; parts.day = 1
            if let first = calendar.date(from: parts), let range = calendar.range(of: .day, in: .month, for: first) { parts.day = min(day, range.count) }
        }
        if let date = calendar.date(from: parts) { editState { $0.utc = UTCClock.string(date) } }
    }
    func changeCaptureTime(hour: Int, minute: Int, second: Int) {
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let date = UTCClock.parse(workingState.utc) ?? Date()
        if let next = calendar.date(bySettingHour: hour, minute: minute, second: second, of: date) { editState { $0.utc = UTCClock.string(next) } }
    }
    func editSelectedLabel() {
        guard let annotation = selectedAnnotation, !busy else { return }
        let alert = NSAlert(); alert.messageText = tr("编辑标注文字")
        let field = NSTextField(string: annotation.text); field.frame = NSRect(x: 0, y: 0, width: 380, height: 50)
        field.isEditable = true; field.isSelectable = true; alert.accessoryView = field
        alert.addButton(withTitle: tr("确定")); alert.addButton(withTitle: tr("取消"))
        if NativeDialogs.run(alert) == .alertFirstButtonReturn {
            let text = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty { changeSelected { $0.text = text }; relayoutLabels() }
        }
    }

    func requestOpen(_ url: URL? = nil) {
        guard !busy else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard confirmClose() else { return }
        var selected = url
        if selected == nil {
            let panel = NSOpenPanel()
            panel.title = tr("打开月面照片或工程")
            panel.allowedContentTypes = [.image, UTType(filenameExtension: "moonlabel") ?? .json,
                                         UTType(filenameExtension: "moonswift") ?? .json]
            panel.allowsOtherFileTypes = true
            guard NativeDialogs.run(panel) == .OK else { return }
            selected = panel.url
        }
        guard let selected else { return }
        busy = true; taskStatus = "正在读取照片与工程…"
        operation = Task { await open(selected) }
    }
    func openDemo() { requestOpen(Catalog.demoURL) }

    private func open(_ url: URL) async {
        defer { busy = false; operation = nil; taskStatus = "" }
        do {
            var opened: OpenedProject?
            var imageURL = url
            if ["moonlabel", "moonswift"].contains(url.pathExtension.lowercased()) {
                opened = try await CancellableRead.run { try ProjectIO.read(url) }
                imageURL = URL(fileURLWithPath: opened!.document.imagePath)
                if !FileManager.default.fileExists(atPath: imageURL.path) {
                    let panel = NSOpenPanel()
                    panel.title = tr("工程照片已移动，请选择原始照片")
                    panel.message = tr("需要原照片：") + imageURL.lastPathComponent
                    panel.allowedContentTypes = [.image]
                    guard NativeDialogs.run(panel) == .OK, let replacement = panel.url else { return }
                    imageURL = replacement
                }
            }
            let loadingURL = imageURL
            let reader = photoReader
            let loaded = try await CancellableRead.run { try reader(loadingURL) }
            try Task.checkCancellation()
            let photo = loaded.raw
            if let expected = opened?.expectedSize, expected != [photo.width, photo.height] {
                throw MoonError.invalid("照片尺寸与工程记录不同，请选择同一张原始照片。")
            }
            var next = opened?.document ?? MoonDocument(imagePath: imageURL.path)
            if opened == nil {
                var state = next.state
                let entered = workingState
                state.utc = UTCClock.filenameDate(imageURL.lastPathComponent).map(UTCClock.string) ?? entered.utc
                state.latitude = entered.latitude; state.longitude = entered.longitude; state.captureMode = entered.captureMode
                state.terrainPath = entered.terrainPath; state.terrainSettings = entered.terrainSettings
                next.state = state
                next.settings.maximumLabels = 200; next.settings.color = "#f5f5f2"
                next.style = ProjectStyle(["font_percent": .number(1.8), "font_step_percent": .number(0.3), "font_weight": .string("bold"), "follow_feature_paths": .bool(true)])
            }
            next.imagePath = imageURL.path; next.imageWidth = photo.width; next.imageHeight = photo.height
            if let overrides = opened?.legacyOverrides {
                next.annotations = LabelLayout.generate(document: next, features: features, overrides: overrides,
                                                        measure: AnnotationRenderer.measure)
            }
            try next.validate()
            closeReferencePreview(); reference = nil; referenceGeometry = nil; referenceProject = nil
            image = photo; displayImage = loaded.display; document = next; selectedID = nil; placementText = nil; placementFeatureID = nil
            if opened == nil { panelTab = 0 }
            captureDateValid = true; captureTimeValid = true
            scene = nil; SceneRenderer.releaseSceneTextures(); OverviewCard.clearCache()
            appliedDocument = next; report = next.referenceReport(features: features)
            craterCandidates = []; selectedCandidate = nil; craterQuery = ""; craterSelection = nil; catalogSelection = nil
            manualSectionExpanded = false; manualPickingExpanded = false; referencePointsExpanded = false; manualMirror = -1; showAllCandidateContours = false
            cancelCanvasInteraction(); showMask = false; photoRevision += 1
            undoHistory.removeAll(); redoHistory.removeAll()
            let native = url.pathExtension.lowercased() == "moonswift"
            saveURL = native ? url : nil
            revision += 1; fitRequest += 1
            status = "已打开 \(url.lastPathComponent)"
            if next.state.utc.isEmpty {
                var state = next.state
                var calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(secondsFromGMT: 0)!
                let fallback = calendar.date(bySettingHour: 15, minute: 0, second: 0, of: Date()) ?? Date()
                state.utc = UTCClock.string(UTCClock.filenameDate(imageURL.lastPathComponent) ?? fallback)
                document?.state = state
            }
            markClean()
            if next.calibration != nil {
                DispatchQueue.main.async { [weak self] in self?.applyNativeScene(initialLoad: true) }
            }
        } catch is CancellationError { status = "已中止读取，保留原有照片和工程。" }
        catch { show(error) }
    }

    @discardableResult
    func save(asNew: Bool = false) -> Bool {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let snapshot = document, !busy else { return false }
        var destination = saveURL
        if destination == nil || asNew {
            let panel = NSSavePanel()
            panel.title = tr("保存工程")
            panel.allowedContentTypes = [UTType(filenameExtension: "moonswift") ?? .json]
            panel.nameFieldStringValue = URL(fileURLWithPath: snapshot.imagePath).deletingPathExtension().lastPathComponent + ".moonswift"
            panel.canCreateDirectories = true
            guard NativeDialogs.run(panel) == .OK, let url = panel.url else { return false }
            destination = url
        }
        guard let destination else { return false }
        do {
            try ProjectIO.write(snapshot, to: destination)
            saveURL = destination; cleanSnapshot = snapshot; revision += 1
            status = "已保存 \(destination.lastPathComponent)"; return true
        } catch { show(error); return false }
    }

    func exportPNG(to destination: URL? = nil) {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let snapshot = displayDocument, let photo = displayImage ?? image, !busy else { return }
        let url: URL
        if let destination { url = destination }
        else {
            let panel = NSSavePanel()
            panel.title = tr("导出原尺寸 PNG")
            panel.allowedContentTypes = [.png]
            panel.nameFieldStringValue = URL(fileURLWithPath: snapshot.imagePath).deletingPathExtension().lastPathComponent + "-swift.png"
            guard NativeDialogs.run(panel) == .OK, let selected = panel.url else { return }
            url = selected
        }
        beginExport(.png, image: photo, document: snapshot, scene: scene, to: url)
    }

    func confirmClose() -> Bool {
        guard dirty else { return true }
        let alert = NSAlert()
        alert.messageText = tr("保存对 {name} 的修改？").replacingOccurrences(of: "{name}", with: title)
        alert.informativeText = tr("保存后可以继续编辑标注。")
        alert.addButton(withTitle: tr("保存")); alert.addButton(withTitle: tr("取消")); alert.addButton(withTitle: tr("不保存"))
        switch NativeDialogs.run(alert) {
        case .alertFirstButtonReturn: return save()
        case .alertThirdButtonReturn: return true
        default: return false
        }
    }
    func acceptWindowClose() -> Bool {
        guard !busy, confirmClose() else { return false }
        cleanSnapshot = document
        return true
    }
    func markClean() { cleanSnapshot = document }
    func show(_ error: Error) {
        status = tr(error.localizedDescription)
        let alert = NSAlert(error: error)
        alert.messageText = tr(alert.messageText); alert.informativeText = tr(alert.informativeText)
        for button in alert.buttons { button.title = tr(button.title) }
        NativeDialogs.run(alert)
    }
    func showCredits() {
        guard !busy else { return }
        EditorCredits.show(language: uiLanguage)
    }
}
