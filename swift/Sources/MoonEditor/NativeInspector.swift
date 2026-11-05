// SPDX-License-Identifier: GPL-3.0-or-later
import SwiftUI
import AppKit
import MoonCore

struct NativeInspector: View {
    @ObservedObject var model: EditorModel
    @State private var maskExpanded = false
    @State private var timeExpanded = false
    @State private var detectionExpanded = false
    @State private var craterToolsExpanded = false
    @State private var manualAdvanced = false
    @State private var referenceTab = 0
    @State private var terrainAdvanced = false
    @State private var terrainQuery = ""
    @State private var filterExpanded = false
    @State private var textExpanded = false
    @State private var layoutExpanded = false
    @State private var mapExpanded = false
    @State private var listExpanded = false

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 4) {
                ForEach(Array(["校准", "标注", "参考"].enumerated()), id: \.offset) { index, name in
                    Button { model.panelTab = index } label: {
                        Text(model.tr(name)).font(.system(size: 12, weight: .semibold)).frame(maxWidth: .infinity).padding(.vertical, 8)
                            .foregroundStyle(model.panelTab == index ? EditorPalette.text : EditorPalette.secondary)
                            .background(model.panelTab == index ? Color(nsColor: AnnotationRenderer.color("#2c3950")) : Color(nsColor: AnnotationRenderer.color("#1d2532")), in: RoundedRectangle(cornerRadius: 6))
                    }.buttonStyle(.plain)
                }
            }
            if model.panelTab == 1 {
                VStack(spacing: 8) {
                    Button { model.applyNativeScene() } label: { Text(model.tr("重新生成标注")).frame(maxWidth: .infinity) }.buttonStyle(EditorButtonStyle(primary: true)).disabled(model.document == nil || model.busy)
                    HStack {
                        Toggle(model.tr("沿地形排列名称"), isOn: model.styleBool("follow_feature_paths", fallback: true))
                        Spacer(minLength: 0)
                        if model.hasPendingStyle { Text(model.tr("设置已改，需重新生成")).font(.system(size: 11)).foregroundStyle(EditorPalette.secondary) }
                    }
                }
            }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        if model.panelTab == 0 { calibration }
                        else if model.panelTab == 1 { annotation }
                        else { references }
                        Spacer(minLength: 4)
                    }.padding(.horizontal, 10).padding(.top, 8).padding(.bottom, 14).frame(maxWidth: .infinity, alignment: .leading)
                        .disabled(model.busy || (model.document == nil && model.panelTab == 1))
                }.onChange(of: model.manualReviewRequest) { _, _ in
                    // Match Python's deferred reveal after the page is laid out.
                    DispatchQueue.main.async {
                        guard model.panelTab == 0, model.manualSectionExpanded else { return }
                        proxy.scrollTo(model.craterCandidates.isEmpty ? "crater-detect" : "crater-search", anchor: .center)
                    }
                }
            }.id(model.photoRevision)
            if model.panelTab == 0 && model.manualSectionExpanded && !model.manualPickingExpanded && model.selectedCandidate != nil {
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.craterCandidates.firstIndex(where: { $0.id == model.selectedCandidate }).map { model.tr("候选") + " \($0 + 1)" } ?? model.tr("未选择候选坑")).fontWeight(.semibold)
                    Text(model.chosenCraterFeature.map { featureName($0) } ?? model.tr("地名：未选择")).foregroundStyle(EditorPalette.secondary)
                    Button(model.tr("确认地名，加入参考点")) { model.confirmCandidate() }.buttonStyle(EditorButtonStyle(primary: true)).disabled(!model.canConfirmCandidate)
                    if model.document?.state.anchors.isEmpty == false {
                        Button(model.tr("查看已确认的参考点并校准")) { model.cancelCanvasInteraction(); model.referencePointsExpanded = true }
                    }
                }.padding(10).frame(maxWidth: .infinity, alignment: .leading).background(Color(nsColor: AnnotationRenderer.color("#1c2432")))
            }
        }.padding(.horizontal, 14).padding(.top, 12).padding(.bottom, 12)
            .font(.system(size: 13)).toggleStyle(.checkbox).background(EditorPalette.panel)
            .onChange(of: model.photoRevision) { _, _ in maskExpanded = false; detectionExpanded = false; craterToolsExpanded = false }
            .onChange(of: maskExpanded) { _, expanded in if !expanded { model.cancelCanvasInteraction() } }
    }

    private var calibration: some View {
        Group {
            section("拍摄条件") {
                EditorChoicePicker(model.tr("拍摄方式"), selection: model.stateString(\.captureMode), options: choices([("auto", "自动"), ("direct", "相机直拍"), ("afocal", "目镜后")]), labelWidth: 64)
                HStack(spacing: 5) {
                    Text(model.tr("拍摄日期")).frame(width: 64, alignment: .leading)
                    CaptureEntry(value: captureDate, kind: .date, units: ["年", "月", "日"].map(model.tr), validityChanged: { model.captureDateValid = $0 }).frame(height: 28).id(model.document?.imagePath ?? "reference-date")
                }
                DisclosureGroup(model.tr("具体时间") + " · UTC " + captureTime, isExpanded: $timeExpanded) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(model.tr("时间（UTC）")); Spacer()
                            CaptureEntry(value: captureDate, kind: .time, units: ["时", "分"].map(model.tr), validityChanged: { model.captureTimeValid = $0 }).frame(height: 28).id(model.document?.imagePath ?? "reference-time")
                        }
                        Button(model.tr("恢复默认 15:00:00 UTC")) { model.changeCaptureTime(hour: 15, minute: 0, second: 0) }
                    }.padding(.top, 8)
                }
                if !model.captureDateValid || !model.captureTimeValid { Text(model.tr("请输入完整、有效的拍摄日期和时间。")).foregroundStyle(.orange) }
                Toggle(model.tr("使用拍摄地点"), isOn: Binding(get: { model.workingState.latitude != nil }, set: { value in model.editState { $0.latitude = value ? 0 : nil; $0.longitude = value ? 0 : nil } }))
                if model.workingState.latitude != nil {
                    input("纬度（北为正）", value: location(\.latitude), range: -90...90)
                    input("经度（东为正）", value: location(\.longitude), range: -180...180)
                }
            }
            section("自动识别") {
                DisclosureGroup(model.tr("排除干扰区域（可选）"), isExpanded: $maskExpanded) { maskTools.padding(.top, 8) }
                Button { model.startAutomatic() } label: { Text(model.tr("自动识别并标注")).frame(maxWidth: .infinity) }.buttonStyle(EditorButtonStyle(primary: true)).disabled(model.image == nil || !model.captureDateValid || !model.captureTimeValid)
                Text(model.tr(model.document?.calibration == nil ? "未识别" : "已配准")).foregroundStyle(EditorPalette.secondary)
            }
            fold("辅助找坑与参考点", expanded: $model.manualSectionExpanded) {
                DisclosureGroup(model.tr("检测设置"), isExpanded: $detectionExpanded) {
                    VStack(spacing: 8) {
                        input("最小半径", value: model.craterNumber("min_radius", fallback: 8), range: 3...4000, suffix: "px")
                        input("最大半径", value: model.craterNumber("max_radius", fallback: 180), range: 3...4000, suffix: "px")
                        input("灵敏度", value: model.craterNumber("sensitivity", fallback: 50), range: 0...100)
                        input("候选上限", value: model.craterNumber("max_candidates", fallback: 80), range: 1...500)
                        Toggle(model.tr("只检测当前视野"), isOn: model.craterViewport)
                    }.padding(.top, 8)
                }
                Button(model.tr("检测候选坑缘")) { model.detectCandidates() }.buttonStyle(EditorButtonStyle(primary: true)).id("crater-detect")
                if !model.craterCandidates.isEmpty {
                    HStack {
                        Text(model.tr("1  选择候选坑")); Spacer()
                        Button(model.tr("更多操作")) { craterToolsExpanded.toggle() }.buttonStyle(.plain)
                    }
                    ScrollView {
                        VStack(spacing: 3) {
                            ForEach(Array(model.craterCandidates.enumerated()), id: \.element.id) { index, candidate in
                                Button { model.selectedCandidate = candidate.id } label: {
                                    HStack { Text("\(index + 1)"); Spacer(); Text("(\(Int(candidate.center.x)), \(Int(candidate.center.y))) · \(Int(candidate.major)) px") }
                                        .padding(5).background(candidate.id == model.selectedCandidate ? Color(nsColor: AnnotationRenderer.color("#31435c")) : .clear)
                                }.buttonStyle(.plain)
                            }
                        }
                    }.frame(height: min(96, Double(model.craterCandidates.count) * 28)).background(EditorPalette.surface)
                    if craterToolsExpanded {
                        HStack { Button(model.tr("重选中心")) { if let id = model.selectedCandidate { model.canvasTool = .candidateCenter(id) } }; Button(model.tr("移除候选")) { model.craterCandidates.removeAll { $0.id == model.selectedCandidate }; model.selectedCandidate = model.craterCandidates.first?.id }; Button(model.tr("导出 CSV")) { model.exportCraterCandidates() } }
                        Toggle(model.tr("显示全部候选轮廓"), isOn: $model.showAllCandidateContours)
                    }
                    Text(model.tr("2  选择地名"))
                    featureSearch(cratersOnly: true).id("crater-search")
                }
                DisclosureGroup(model.tr("手动补点"), isExpanded: $model.manualPickingExpanded) {
                    VStack(alignment: .leading, spacing: 8) {
                        note("没有合适候选时，选择地名后在照片中取点。")
                        featureSearch()
                        Button(model.tr("在照片中取点")) { model.pickAnchor() }.disabled(model.chosenFeature == nil)
                        if case .anchor = model.canvasTool { Button(model.tr("取消取点")) { model.canvasTool = .pan } }
                    }.padding(.top, 8)
                }
                DisclosureGroup(model.tr("参考点与配准"), isExpanded: $model.referencePointsExpanded) { controlPoints.padding(.top, 8) }
            }
        }
    }
    private var maskTools: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(model.tr("启用排除区域"), isOn: Binding(get: { model.workingState.recognitionMask.enabled }, set: { value in model.editState { $0.recognitionMask.enabled = value } }))
            HStack { tool("画笔", mode: .paint); tool("橡皮擦", mode: .erase); tool("多边形", mode: .polygon) }
            slider("画笔直径", value: $model.brushDiameter, range: 2...2000)
            HStack { Button(model.tr("撤销")) { model.undo() }.disabled(!model.canUndo); Button(model.tr("重做")) { model.redo() }.disabled(!model.canRedo); Button(model.tr("清空")) { model.editState { $0.recognitionMask.operations = [] } }; Button(model.tr("完成")) { model.cancelCanvasInteraction() } }
            note("红色区域不参与识别和辅助找坑；原图与导出保持不变。拖动涂抹，空格加拖动平移，滚轮缩放，Esc 取消。")
        }
    }
    private func featureSearch(cratersOnly: Bool = false) -> some View {
        let query = cratersOnly ? $model.craterQuery : $model.catalogQuery
        let selection = cratersOnly ? $model.craterSelection : $model.catalogSelection
        let results = cratersOnly ? model.craterSearchResults : model.searchResults
        return VStack(alignment: .leading, spacing: 6) {
            TextField(model.tr(cratersOnly ? "搜索环形山：Hadley C / 哥白尼" : "输入中英文地名"), text: query).textFieldStyle(.roundedBorder)
                .onSubmit { if let first = results.first { selection.wrappedValue = first.id } }
            if !cratersOnly || !results.isEmpty {
                ScrollView {
                    VStack(spacing: 2) {
                        ForEach(results) { feature in
                            Button { selection.wrappedValue = feature.id } label: {
                                Text(featureName(feature)).frame(maxWidth: .infinity, alignment: .leading).padding(5)
                                    .background(selection.wrappedValue == feature.id ? Color(nsColor: AnnotationRenderer.color("#31435c")) : .clear)
                            }.buttonStyle(.plain)
                        }
                    }
                }.frame(height: query.wrappedValue.isEmpty ? 82 : min(104, Double(results.count) * 30)).background(EditorPalette.surface)
            }
        }
    }
    private var controlPoints: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(model.tr("参考点") + "（\(model.document?.state.anchors.count ?? 0)）").fontWeight(.semibold)
            ForEach(Array((model.document?.state.anchors ?? []).enumerated()), id: \.offset) { index, anchor in
                HStack(spacing: 5) {
                    Toggle("", isOn: Binding(get: { model.document?.state.anchors[index].enabled != false }, set: { value in model.editState { $0.anchors[index].enabled = value } })).labelsHidden()
                    Text(model.features.first(where: { $0.id == anchor.id }).map(featureName) ?? anchor.id).lineLimit(1)
                    Spacer(minLength: 0)
                    if let residual = model.referenceResidual(at: index) { Text("\(residual, specifier: "%.1f") px").monospacedDigit() }
                    Button(model.tr("重选")) { model.canvasTool = .anchor(anchor.id) }
                    Button(model.tr("移除")) { model.editState { $0.anchors.remove(at: index) } }
                }.font(.system(size: 12)).foregroundStyle(model.suspectAnchorIndex == index ? EditorPalette.accent : EditorPalette.text)
                    .contentShape(Rectangle()).onTapGesture(count: 2) { model.canvasTool = .anchor(anchor.id) }
            }
            if let suspect = model.suspectAnchorIndex { Text(model.tr("请复核参考点") + " \(suspect + 1)").foregroundStyle(EditorPalette.accent) }
            Button(model.tr("用参考点自动配准")) { model.startAutomatic() }.disabled(model.document?.state.anchors.isEmpty != false)
            Button(model.tr("按参考点手动校准")) { model.manualCalibration() }.buttonStyle(EditorButtonStyle(primary: true)).disabled((model.document?.state.anchors.filter { $0.enabled != false }.count ?? 0) < (model.manualMirror == -1 ? 3 : 2))
            note("双击重选 · 取消勾选停用")
            DisclosureGroup(model.tr("高级 · 镜像与月面几何"), isExpanded: $manualAdvanced) {
                VStack(alignment: .leading, spacing: 8) {
                    EditorChoicePicker(model.tr("镜像判定"), selection: $model.manualMirror, options: choices([(-1, "自动判断镜像（至少三点）"), (0, "不镜像"), (1, "镜像")]), labelWidth: 64)
                    Button(model.tr("重新计算月面几何")) { model.calculateGeometry() }.disabled(model.image == nil)
                    if let geometry = model.document?.state.geometry { Text(model.tr("天平动") + String(format: "：%.3f° / %.3f°", asin(geometry.observer[2]) * 180 / .pi, atan2(geometry.observer[1], geometry.observer[0]) * 180 / .pi)).foregroundStyle(EditorPalette.secondary) }
                    else { note("未计算") }
                }.padding(.top, 8)
            }
        }
    }

    private var annotation: some View {
        Group {
            EditorChoicePicker(model.tr("艺术样式"), selection: Binding(get: { model.document?.style.art ?? "standard" }, set: { value in model.edit { $0.changeStyle { $0.applyArt(value) } } }), options: choices([("standard", "原始标注"), ("manuscript", "中世纪风"), ("topographic", "旷野地形图"), ("cyanotype", "蓝晒星图"), ("copperplate", "铜版图录"), ("inkwash", "水墨朱砂"), ("redalert", "红警地形图")]))
            EditorChoicePicker(model.tr("名称语言"), selection: language, options: [NameLanguage.bilingual, .bilingualTraditional, .chinese, .traditional, .english].map { ($0, model.tr(languageName($0))) })
            input("字号（短边比例）", value: fontPercentage, range: 0.05...8, suffix: "%", step: 0.05, includesInitialValue: true)
            input("最多显示", value: Binding(get: { Double(model.document?.settings.maximumLabels ?? 200) }, set: { value in model.edit { $0.settings.maximumLabels = Int(value.rounded()) } }), range: 1...1000)
            VStack(alignment: .leading, spacing: 5) {
                Text(model.tr("受光阈值"))
                HStack(spacing: 8) {
                    SafeSlider(value: threshold, range: 0...255).frame(height: 28)
                    SafeNumberField(value: threshold, range: 0...255).frame(width: 68, height: 28)
                    Button(model.tr("自动")) { model.edit { $0.changeStyle { $0.set("map_light_threshold", "auto") } } }
                }
            }
            Toggle(model.tr("仅标注受光地形"), isOn: model.styleBool("illuminated_only", fallback: true))
            Toggle(model.tr("地图仅覆盖受光区域"), isOn: model.styleBool("map_light_mask"))
            Toggle(model.tr("照片区域示意图"), isOn: Binding(get: { model.document?.style.bool("overview_enabled") ?? false }, set: { model.toggleOverview($0) }))
            fold("筛选 · 类别、直径、着陆点", expanded: $filterExpanded) {
                DisclosureGroup(model.tr("地形类别") + " · " + model.featureKindSummary) {
                    Toggle(model.tr("全部"), isOn: model.allFeatureKinds)
                    ForEach(model.availableFeatureKinds, id: \.self) { kind in
                        Toggle(model.tr(kindName(kind)), isOn: model.featureKind(kind)).disabled(model.document?.settings.matchesAllKinds ?? true)
                    }
                }
                input("最小直径", value: Binding(get: { model.document?.settings.minimumDiameter ?? 40 }, set: { value in model.edit { $0.settings.minimumDiameter = value } }), range: 0...3000, suffix: "km")
                HStack { Toggle(model.tr("着陆点（阿波罗 / 嫦娥）"), isOn: model.styleBool("show_landing_sites")); Spacer(); ColorPicker(model.tr("颜色"), selection: landingColor).labelsHidden().disabled(model.document?.style.bool("show_landing_sites") != true) }
            }
            fold("文字样式 · 字体、颜色、透明度", expanded: $textExpanded) {
                fontPicker
                input("字号递减", value: model.styleNumber("font_step_percent", fallback: 0.3), range: 0...8, suffix: "%", step: 0.05, includesInitialValue: true)
                EditorChoicePicker(model.tr("字重"), selection: model.styleString("font_weight", fallback: "bold"), options: choices([("bold", "粗体"), ("normal", "常规")]))
                ColorPicker(model.tr("选择文字与引线颜色"), selection: textColor)
                percent("文字不透明度", key: "label_opacity", fallback: 1)
            }
            fold("排版 · 避让、坑缘圈", expanded: $layoutExpanded) {
                Toggle(model.tr("自动避让"), isOn: model.styleBool("optimize_layout", fallback: true))
                Toggle(model.tr("大坑显示坑缘圈"), isOn: model.styleBool("crater_outlines", fallback: true))
                EditorChoicePicker(model.tr("轮廓形状"), selection: model.styleString("crater_outline_shape", fallback: "ellipse"), options: choices([("ellipse", "椭圆"), ("terrain", "坑缘轮廓（手绘风）")]))
            }
            fold("地图图层 · 高程、等高线、经纬网", expanded: $mapExpanded) { mapSettings }
            fold("标签列表 · 隐藏、改名、重排", expanded: $listExpanded) {
                ScrollView {
                    VStack(spacing: 3) {
                        ForEach(model.document?.annotations ?? []) { annotation in
                            HStack {
                                Toggle("", isOn: Binding(get: { !annotation.hidden }, set: { model.setAnnotationVisible(annotation.id, $0) })).labelsHidden()
                                Button { model.selectedID = annotation.id } label: {
                                    Text(annotation.text + (annotation.visual?.layoutHidden == true ? model.tr("  · 避让收起") : "")).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                                }.buttonStyle(.plain).foregroundStyle(annotation.visual?.layoutHidden == true ? EditorPalette.secondary : EditorPalette.text)
                                    .simultaneousGesture(TapGesture(count: 2).onEnded { model.selectedID = annotation.id; model.editSelectedLabel() })
                            }.padding(4)
                        }
                    }
                }.frame(height: 170).background(EditorPalette.surface)
                Button(model.tr("重新自动排布标签")) { model.relayoutLabels(resetLayout: true) }
                Button(model.tr("重置手工编辑")) { model.relayoutLabels(resetEdits: true) }
                Button(model.tr("更新 USGS 地名") + "（\(model.features.count)）") { model.refreshCatalogue() }
            }
        }
    }
    private var mapSettings: some View {
        VStack(alignment: .leading, spacing: 10) {
            Toggle(model.tr("叠加高程着色"), isOn: model.styleBool("elevation_enabled"))
            EditorChoicePicker(model.tr("高程配色"), selection: model.styleString("elevation_palette", fallback: "terrain"), options: choices([("terrain", "地形色"), ("antique", "靛蓝与古金"), ("wilderness", "旷野橄榄棕"), ("cyanotype", "普鲁士蓝"), ("copperplate", "铜橙与青绿"), ("inkwash", "墨灰与暖白"), ("redalert", "草绿与沙土")]))
            percent("高程不透明度", key: "elevation_opacity", fallback: 0.35)
            Toggle(model.tr("叠加等高线"), isOn: model.styleBool("contour_enabled"))
            EditorChoicePicker(model.tr("等高距"), selection: Binding(get: { model.document?.style.contourInterval ?? 0 }, set: { value in model.edit { $0.changeStyle { if value == 0 { $0.set("contour_interval", "auto") } else { $0.set("contour_interval", value) } } } }), options: [(0, model.tr("自动")), (0.25, "0.25 km"), (0.5, "0.5 km"), (1, "1 km"), (2, "2 km")])
            percent("等高线不透明度", key: "contour_opacity", fallback: 0.65)
            HStack { Button(model.tr("下载基础高程")) { model.downloadDEM() }; Button(model.tr("导入高程")) { model.importDEM() } }
            EditorChoicePicker(model.tr("月面经纬网"), selection: model.styleNumber("grid_spacing", fallback: 0), options: [(0, model.tr("关闭")), (10, "10°"), (15, "15°"), (30, "30°")])
            percent("网格不透明度", key: "grid_opacity", fallback: 0.45)
            Toggle(model.tr("叠加晨昏线"), isOn: model.styleBool("terminator_enabled"))
            EditorChoicePicker(model.tr("晨昏线依据"), selection: model.styleString("terminator_source", fallback: "photo"), options: choices([("photo", "照片估计"), ("ephemeris", "工程时间（理论）")]))
            percent("晨昏线不透明度", key: "terminator_opacity", fallback: 1)
            if model.scene?.layers.terminatorUnreliable == true { note("照片明暗分界不够可靠，未显示晨昏线。") }
        }
    }
    private var references: some View {
        Group {
            note("校准页的自动识别不理想时，可在此用参考影像自动配准，或生成 DEM 模拟图核对地形。")
            HStack(spacing: 14) {
                ForEach(Array(["影像匹配", "DEM 模拟"].enumerated()), id: \.offset) { index, name in
                    Button { referenceTab = index } label: { Text(model.tr(name)).padding(.vertical, 5).overlay(alignment: .bottom) { if referenceTab == index { Rectangle().fill(EditorPalette.accent).frame(height: 2) } } }.buttonStyle(.plain)
                }
            }
            if referenceTab == 0 {
                Button(model.tr("自动配准 · NASA 同时刻影像")) { model.loadNASA() }.disabled(model.image == nil)
                Button(model.tr("使用本地参考工程…")) { model.loadLocalReference() }.disabled(model.image == nil)
                note("NASA 参考支持 2026 年，需联网。")
            } else {
                Text(model.tr(model.terrainSourceDescription)).foregroundStyle(EditorPalette.secondary)
                HStack { Button(model.tr("导入高程")) { model.importDEM() }; Button(model.tr(DataStore.bundledDEM == nil ? "下载基础高程" : "使用基础高程")) { model.downloadDEM() } }
                TextField(model.tr("搜索模拟区域的地名"), text: $terrainQuery).textFieldStyle(.roundedBorder)
                    .onAppear {
                        terrainQuery = model.features.first(where: { $0.id == model.workingState.terrainSettings.string("center_id") })?.name ?? "Aristarchus"
                        model.searchTerrainCenter(terrainQuery)
                    }
                    .onChange(of: terrainQuery) { _, query in model.searchTerrainCenter(query) }
                    .onSubmit { model.searchTerrainCenter(terrainQuery) }
                EditorChoicePicker(model.tr("区域中心"), selection: Binding(get: { model.workingState.terrainSettings.string("center_id", model.searchTerrainFeatures(terrainQuery).first?.id ?? "") }, set: model.selectTerrainCenter), options: model.searchTerrainFeatures(terrainQuery).map { ($0.id, featureName($0)) }, labelWidth: 64)
                input("视野宽度", value: terrainNumber("width_km", 300), range: 10...2000, suffix: "km")
                DisclosureGroup(model.tr("渲染参数 · 图像尺寸 / 光照 / 投影"), isExpanded: $terrainAdvanced) {
                    VStack(spacing: 8) {
                        EditorChoicePicker(model.tr("图像边长"), selection: terrainNumber("size", 768), options: [512.0, 768, 1024, 1536].map { ($0, String(Int($0))) })
                        EditorChoicePicker(model.tr("光照模型"), selection: terrainString("model", "Lommel-Seeliger"), options: [("Lommel-Seeliger", "Lommel-Seeliger"), ("Lambert", "Lambert")])
                        input("提亮 Gamma", value: terrainNumber("gamma", 1.6), range: 0.3...4, step: 0.1)
                        Toggle(model.tr("计算地形投影（耗时稍长）"), isOn: Binding(get: { model.workingState.terrainSettings.bool("shadows", true) }, set: { value in model.editState { $0.terrainSettings.set("shadows", value) } }))
                    }.padding(.top, 8)
                }
                Button(model.tr("生成模拟图")) { model.renderRegion() }.buttonStyle(EditorButtonStyle(primary: true)).disabled(model.searchTerrainFeatures(terrainQuery).isEmpty)
                note("基础采样约 1.9 km，近月缘区域不适用。")
            }
        }
    }

    private var language: Binding<NameLanguage> { Binding(get: { model.document?.settings.language ?? .bilingual }, set: { value in model.edit { $0.settings.language = value } }) }
    private var fontPercentage: Binding<Double> {
        model.styleNumber("font_percent", fallback: model.document.map { $0.settings.fontSize * 100 / Double(min($0.imageWidth, $0.imageHeight)) } ?? 1.8)
    }
    private var threshold: Binding<Double> { Binding(get: { Double(model.document?.style.threshold ?? model.scene?.layers.lightness?.automaticThreshold ?? 1) }, set: { value in model.edit { $0.changeStyle { $0.set("map_light_threshold", value.rounded()) } } }) }
    private var captureTime: String { let date = UTCClock.parse(model.workingState.utc) ?? Date(); let f = DateFormatter(); f.timeZone = TimeZone(secondsFromGMT: 0); f.dateFormat = "HH:mm:ss"; return f.string(from: date) }
    private var captureDate: Binding<Date> { Binding(get: { UTCClock.parse(model.workingState.utc) ?? Date() }, set: { date in model.editState { $0.utc = UTCClock.string(date) } }) }
    private func featureName(_ feature: Feature) -> String { model.uiLanguage == "English" ? feature.name : model.tr(feature.caption(.bilingual)) }
    private func languageName(_ value: NameLanguage) -> String { switch value { case .bilingual: return "双语（简体）"; case .bilingualTraditional: return "双语（繁体）"; case .chinese: return "简体中文"; case .traditional: return "繁体中文"; case .english: return "英语" } }
    private func choices<Value>(_ values: [(Value, String)]) -> [(Value, String)] { values.map { ($0.0, model.tr($0.1)) } }
    private var fontPicker: some View {
        let family = model.document?.style.fontFamily ?? ""
        var options = [("", model.tr("默认字体"))] + LabelFonts.families.map { ($0, $0) }
        if !family.isEmpty, LabelFonts.installedFamily(family) == nil {
            options.append((family, model.tr("{family}（未安装）").replacingOccurrences(of: "{family}", with: family)))
        }
        let selection = Binding(get: {
            let value = model.document?.style.fontFamily ?? ""
            return LabelFonts.installedFamily(value) ?? value
        }, set: { model.styleString("font_family").wrappedValue = $0 })
        return EditorChoicePicker(model.tr("字体"), selection: selection, options: options)
            .disabled(model.document?.style.isArt == true)
            .help(model.tr("选择本机字体。缺少的字符用默认字体显示；选好后点击重新生成标注。"))
    }
    private func kindName(_ kind: String) -> String {
        let key = kind.components(separatedBy: ",")[0]
        return ["Albedo Feature": "反照率特征", "Astronaut-named features": "宇航员命名地形", "Catena": "坑链", "Crater": "环形山", "Dorsum": "月脊", "Lacus": "月湖", "Mare": "月海", "Mons": "山与山脉", "Oceanus": "月洋", "Palus": "月沼", "Planitia": "平原", "Promontorium": "月岬", "Rima": "月溪", "Rupes": "月崖", "Satellite Feature": "附属地形", "Sinus": "月湾", "Statio": "着陆基地", "Vallis": "月谷"][key] ?? key
    }
    private func location(_ key: WritableKeyPath<ProjectState, Double?>) -> Binding<Double> { Binding(get: { model.workingState[keyPath: key] ?? 0 }, set: { value in model.editState { $0[keyPath: key] = value } }) }
    private func terrainNumber(_ key: String, _ fallback: Double) -> Binding<Double> { Binding(get: { model.workingState.terrainSettings.number(key, fallback) }, set: { value in model.editState { $0.terrainSettings.set(key, value) } }) }
    private func terrainString(_ key: String, _ fallback: String) -> Binding<String> { Binding(get: { model.workingState.terrainSettings.string(key, fallback) }, set: { value in model.editState { $0.terrainSettings.set(key, value) } }) }
    private var textColor: Binding<Color> { Binding(get: { Color(nsColor: AnnotationRenderer.color(model.document?.settings.color ?? "#f5f5f2")) }, set: { color in if let hex = hex(color) { model.edit { $0.settings.color = hex } } }) }
    private var landingColor: Binding<Color> { Binding(get: { Color(nsColor: AnnotationRenderer.color(model.document?.style.string("landing_color", "#f2b05e") ?? "#f2b05e")) }, set: { color in if let hex = hex(color) { model.edit { $0.changeStyle { $0.set("landing_color", hex) } } } }) }
    private func hex(_ color: Color) -> String? { guard let c = NSColor(color).usingColorSpace(.sRGB) else { return nil }; return String(format: "#%02x%02x%02x", Int((c.redComponent * 255).rounded()), Int((c.greenComponent * 255).rounded()), Int((c.blueComponent * 255).rounded())) }
    private func input(_ title: String, value: Binding<Double>, range: ClosedRange<Double>, suffix: String = "", step: Double = 1, includesInitialValue: Bool = false) -> some View {
        HStack(spacing: 10) { Text(model.tr(title)).frame(width: 108, alignment: .leading); SafeNumberField(value: value, range: range, step: step, suffix: suffix, includesInitialValue: includesInitialValue).frame(width: 100, height: 28); Spacer(minLength: 0) }
    }
    private func slider(_ title: String, value: Binding<Double>, range: ClosedRange<Double>) -> some View {
        VStack(alignment: .leading, spacing: 4) { Text(model.tr(title)); HStack { SafeSlider(value: value, range: range).frame(height: 28); SafeNumberField(value: value, range: range).frame(width: 64, height: 28) } }
    }
    private func percent(_ title: String, key: String, fallback: Double) -> some View {
        let value = Binding(get: { (model.document?.style.number(key, fallback) ?? fallback) * 100 }, set: { value in model.edit { $0.changeStyle { $0.set(key, value / 100) } } })
        return slider(title, value: value, range: 0...100)
    }
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 9) { Text(model.tr(title)).font(.system(size: 12, weight: .semibold)).foregroundStyle(EditorPalette.secondary); Rectangle().fill(EditorPalette.line).frame(height: 1); content() }
    }
    private func fold<Content: View>(_ title: String, expanded: Binding<Bool>, @ViewBuilder content: @escaping () -> Content) -> some View {
        VStack(spacing: 4) { Rectangle().fill(EditorPalette.line).frame(height: 1); DisclosureGroup(model.tr(title), isExpanded: expanded) { VStack(alignment: .leading, spacing: 10) { content() }.padding(.top, 9) }.font(.system(size: 12)).foregroundStyle(EditorPalette.text) }
    }
    private func note(_ text: String) -> some View { Text(model.tr(text)).font(.system(size: 12)).foregroundStyle(EditorPalette.secondary).fixedSize(horizontal: false, vertical: true) }
    private func tool(_ title: String, mode: CanvasTool) -> some View { Button(model.tr(title)) { model.canvasTool = model.canvasTool == mode ? .pan : mode }.buttonStyle(EditorButtonStyle(primary: model.canvasTool == mode)) }
}
