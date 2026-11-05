// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import MoonCore

enum InterfaceText {
    static let languages = ["简体中文", "繁體中文", "English"]
    static let english: [String: String] = {
        var result: [String: String] = [:]
        if let url = Catalog.resource("ui_en", "json"), let data = try? Data(contentsOf: url),
           let root = try? JSONDecoder().decode(JSONValue.self, from: data) {
            let entries = root.object["strings"]?.object ?? root.object
            for (key, value) in entries { if let text = value.string { result[key] = text } }
        }
        let native = [
            "正在读取照片与工程…": "Reading photo and project…",
            "已中止读取，保留原有照片和工程。": "Reading cancelled; the current photo and project were kept.",
            "正在重新排布标签…": "Reflowing labels…",
            "页面": "Panel", "拍摄信息": "Capture", "使用拍摄地点": "Use observing location",
            "请核对 UTC 时间，北京时间减 8 小时。": "Check the capture time in UTC (Beijing time minus 8 hours).",
            "排除干扰区域（可选）": "Exclude interference (optional)", "多边形": "Polygon", "清空": "Clear",
            "红色区域不参与识别；空格拖动平移，Esc 取消，双击或回车完成多边形。": "Red areas are excluded. Space-drag to pan; Esc cancels; double-click or Return completes a polygon.",
            "检测候选坑缘": "Detect candidate rims", "已选地名": "Selected feature", "先在左侧搜索并选中地名。": "Search and select a feature on the left.",
            "手动取参考点": "Pick a control point", "请复核参考点": "Review control point", "设置待应用": "Unapplied settings",
            "名称语言": "Name language", "全部": "All", "最小直径 · km": "Minimum diameter · km", "数量上限": "Maximum labels",
            "恢复自动阈值": "Restore automatic threshold", "经纬网": "Graticule", "网格不透明度": "Grid opacity",
            "高程不透明度": "Elevation opacity", "等高线不透明度": "Contour opacity", "晨昏线依据": "Terminator source",
            "照片估计": "Estimate from photo", "工程时间": "Project time", "文字": "Text", "最大字号 · %": "Maximum font size · %",
            "字号递减 · %": "Size decrement · %", "文字粗细": "Font weight", "常规": "Regular", "大坑轮廓": "Crater outlines",
            "坑缘形状": "Rim shape", "参考椭圆": "Reference ellipse", "手绘风坑缘": "Terrain rim", "排版与编辑": "Layout and editing",
            "自动避让": "Avoid overlaps", "显示 / 隐藏": "Show / hide", "标注文字": "Label text",
            "Cmd 拖动标签、图例或示意图；双击标签改名。": "Cmd-drag labels, the legend or overview; double-click a label to rename it.",
            "离线高程数据": "Offline elevation data", "下载 LOLA": "Download LOLA", "导入 DEM…": "Import DEM…",
            "局部地形参考": "Local terrain reference", "中心纬度": "Center latitude", "中心经度": "Center longitude",
            "视野宽度 · km": "Field width · km", "图像尺寸": "Image size", "亮度 Gamma": "Brightness gamma",
            "投射阴影": "Cast shadows", "生成局部模拟图": "Render local reference", "用参考图自动配准": "Register with reference",
            "月面资料库": "Lunar catalogue", "地名": "Features", "标注": "Labels", "常用地名": "Common features",
            "搜索中英文地名或编号": "Search names or IAU IDs", "打开演示工程": "Open demo project", "打开": "Open",
            "添加文字": "Add text", "保存": "Save", "导出 PNG": "Export PNG", "显示标注": "Show labels", "显示蒙版": "Show mask",
            "校准": "Calibrate", "参考": "Reference", "给月亮写下注脚": "Write a note to the Moon",
            "打开月面照片，拖放地名，留住一次观测。": "Open a lunar photo and annotate your observation.", "打开照片或工程…": "Open photo or project…",
            "试用演示": "Open demo", "支持拖入照片、.moonlabel 或 .moonswift 工程": "Drop a photo, .moonlabel or .moonswift project",
            "中止当前任务": "Cancel current task", "沿地形排列名称": "Follow landform paths", "标注内容": "Label content",
            "辅助图示": "Auxiliary figures", "照片区域示意图": "Photo field overview", "地形类别": "Feature types",
            "艺术与地图图层": "Art and map layers", "艺术样式": "Art style", "高程配色": "Elevation palette",
            "仅标注受光地形": "Label illuminated features only", "地图仅覆盖受光区域": "Maps on illuminated terrain only",
            "受光阈值": "Illumination threshold", "显示着陆点": "Show landing sites", "文字不透明度": "Text opacity",
            "重新生成标注": "Regenerate labels", "相机直拍": "Direct camera", "目镜后": "Afocal / eyepiece",
            "自动": "Auto", "关闭": "Off", "纬度": "Latitude", "经度": "Longitude", "拍摄方式": "Capture mode",
            "画笔": "Brush", "橡皮擦": "Eraser", "画笔直径": "Brush diameter", "撤销": "Undo", "重做": "Redo",
            "最小半径": "Minimum radius", "最大半径": "Maximum radius", "灵敏度": "Sensitivity", "光照模型": "Lighting model",
            "照片参考配准": "Register from a reference", "使用本地参考工程…": "Use a local reference project…",
            "计算方式": "Compute mode", "自动 · Metal 优先": "Auto · prefer Metal", "以选中地形为中心": "Center on selected feature",
            "保存参考图与工程…": "Save reference and project…", "保存 Swift 工程": "Save Swift project", "保存兼容 .moonlabel 工程…": "Save compatible .moonlabel…",
            "撤销标注修改": "Undo annotation edit", "重做标注修改": "Redo annotation edit", "画布": "Canvas",
            "试用演示工程": "Open demo project", "滚轮缩放画布；参数面板上的滚动只滚动面板。": "Scroll to zoom the canvas; scrolling over controls scrolls the panel.",
            "没有匹配的地名": "No matching features", "浏览": "Browse", "在照片上放置": "Place on photo",
            "在照片上放置此地名": "Place this feature on the photo", "打开照片或工程（⌘O）": "Open photo or project (⌘O)",
            "适合窗口（⌘0）": "Fit in window (⌘0)", "滚轮 / 双指缩放 · 拖动空白处平移": "Scroll or pinch to zoom · drag to pan",
            "点击照片放置标注 · Esc 取消": "Click to place a label · Esc cancels", "正在处理…": "Working…",
            "已中止。": "Cancelled.", "已取消。": "Cancelled.", "正在中止…": "Cancelling…",
            "中止": "Cancel", "候选": "Candidate", "具体时间": "Time", "参考点": "Control points", "取消取点": "Cancel picking",
            "在照片中取点": "Pick on photo", "更新 USGS 地名": "Update USGS catalogue", "未导入高程数据": "No elevation data loaded",
            "检测设置": "Detection settings", "滚轮缩放 · 按住 Cmd 拖动标签 · 双击编辑文字": "Scroll to zoom · Cmd-drag labels · Double-click to edit text",
            "照片明暗分界不够可靠，未显示晨昏线。": "The photo's day/night boundary is unreliable; the terminator is hidden.",
            "移除": "Remove", "输入中英文地名": "Search feature names", "重选": "Repick", "高级设置": "Advanced settings",
            "区域中心": "Region center", "搜索模拟区域的地名": "Search the region to simulate",
            "查看模拟图": "View simulation", "视野": "Field width", "采样": "Sampling",
            "可用设备：": "Available device: ", "使用 CPU。未找到可用的 Metal 设备。": "Using CPU. No usable Metal device was found.",
            "当前由环境变量指定，界面设置暂不生效。": "An environment variable overrides this setting.",
            "拍摄条件已改，需重新校准": "Capture conditions changed; register the photo again",
            "参考点已改，需重新校准": "Control points changed; register the photo again",
            "拍摄方式已改，下次识别生效": "Capture mode changed; applies to the next recognition",
            "CSV 已保存": "CSV saved",
            "取景范围": "Field of view", "请输入完整、有效的拍摄日期和时间。": "Enter a complete, valid capture date and time.",
            "候选检测设置无效。": "Invalid crater detection settings.",
            "内置基础高程 · LOLA 1.9 km": "Bundled elevation · LOLA 1.9 km", "使用基础高程": "Use basic elevation",
            "加速高程与阴影参考；其余步骤使用 CPU。": "Accelerates terrain and shadow references; other steps use CPU.",
            "原图比例 1:1": "Actual size 1:1", "另存为…": "Save As…", "导出 PNG…": "Export PNG…", "导出 SVG…": "Export SVG…",
            "正在更新 USGS 地名…": "Updating USGS catalogue…", "编辑标注文字": "Edit label text",
            "好": "OK",
            "无法打开 FITS 文件。": "Cannot open the FITS file.",
            "无法读取 FITS 图像尺寸。": "Cannot read the FITS image dimensions.",
            "FITS 需要二维灰度图或 RGB 图像。": "FITS requires a two-dimensional grayscale, RGB or RGBA image.",
            "FITS 图像尺寸超出范围。": "The FITS image dimensions exceed the supported range.",
            "FITS 像素读取失败。": "Cannot read the FITS image pixels.",
            "FITS 文件没有可用的二维图像。": "The FITS file contains no usable two-dimensional image.",
            "图像没有有效的数值像素。": "The image contains no valid numeric pixels.",
            "已中止导出，保留原有文件。": "Export cancelled; existing files were kept.",
            "导出原尺寸 PNG": "Export full-size PNG",
            "请换一个导出文件名，保留原始照片。": "Choose a different export filename to keep the original photo.",
            "已导出 {width} × {height} PNG · {name}": "Exported {width} × {height} PNG · {name}",
            "打开月面照片或工程": "Open lunar photo or project",
            "工程照片已移动，请选择原始照片": "The project photo has moved; select the original photo",
            "需要原照片：": "Original photo required: ",
            "保存 MoonLabeler 工程": "Save MoonLabeler project",
            "保存对 {name} 的修改？": "Save changes to {name}?",
            "保存后可以继续编辑标注。": "You can continue editing labels after saving.",
            "不保存": "Don’t Save",
            "NASA 配准失败，可用手动校准": "NASA registration failed; manual calibration is available",
        ]
        result.merge(native) { _, new in new }; return result
    }()
    private static let templates: [(NSRegularExpression, [String], String)] = {
        guard let url = Catalog.resource("ui_en", "json"), let data = try? Data(contentsOf: url), let root = try? JSONDecoder().decode(JSONValue.self, from: data) else { return [] }
        var values = (root.object["templates"]?.object ?? [:]).compactMapValues(\.string)
        for (key, translation) in english where key.contains("{") && key.contains("}") && values[key] == nil {
            values[key] = translation
        }
        values.merge(["已应用 · {count} 个可见地名": "Applied · {count} visible labels", "已打开 {name}": "Opened {name}",
                      "局部参考已生成 · 有效覆盖 {coverage}%": "Local reference ready · {coverage}% coverage",
                      "配准通过 · {count} 个对应点 · RMS {rms} px": "Registration passed · {count} correspondences · RMS {rms} px",
                      "正在验证高程区域 {row} · {column}…": "Validating terrain tile {row} · {column}…",
                      "{width} × {height}  ·  {count} 个标注": "{width} × {height}  ·  {count} labels"]) { _, new in new }
        let fields = try! NSRegularExpression(pattern: "\\{([^{}]+)\\}")
        return values.sorted { $0.key.count > $1.key.count }.compactMap { key, translation in
            let matches = fields.matches(in: key, range: NSRange(key.startIndex..., in: key)); var pattern = "^", names: [String] = [], cursor = key.startIndex
            for match in matches {
                guard let range = Range(match.range, in: key), let name = Range(match.range(at: 1), in: key) else { continue }
                pattern += NSRegularExpression.escapedPattern(for: String(key[cursor..<range.lowerBound])) + "([\\s\\S]+?)"; cursor = range.upperBound; names.append(String(key[name]))
            }
            pattern += NSRegularExpression.escapedPattern(for: String(key[cursor...])) + "$"
            return (try? NSRegularExpression(pattern: pattern)).map { ($0, names, translation) }
        }
    }()
    static func translate(_ text: String, language: String) -> String {
        if language == "繁體中文" { return ChineseConversion.traditional(text) }
        if language == "English" {
            if let translated = english[text], !translated.isEmpty { return translated }
            for (regex, names, template) in templates {
                guard let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) else { continue }
                var result = template
                for (index, name) in names.enumerated() {
                    if let range = Range(match.range(at: index + 1), in: text) { let value = String(text[range]); result = result.replacingOccurrences(of: "{\(name)}", with: english[value] ?? value) }
                }
                return result
            }
        }
        return text
    }
}
@MainActor extension EditorModel {
    func setInterfaceLanguage(_ language: String) {
        guard !busy, InterfaceText.languages.contains(language) else { return }
        UserDefaults.standard.set(language, forKey: "swift-ui-language")
        uiLanguage = language
    }
    func tr(_ text: String) -> String { InterfaceText.translate(text, language: uiLanguage) }
}
