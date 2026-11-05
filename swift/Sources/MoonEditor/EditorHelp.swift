// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit

enum EditorHelp {
    static let paragraphs: [(String, String)] = [
        ("自动：打开照片，设置拍摄日期，点击“自动识别并标注”。时间默认 UTC 15:00，展开可修改；北京时间请减去 8 小时。星历和基础高程已内置；在线参考与地名更新需要联网。",
         "Automatic: open a photo, set the capture date and click “Recognize and label”. The default time is 15:00 UTC; expand the time controls to change it. Convert local time to UTC. Ephemerides and basic elevation data are bundled; online references and catalogue updates require internet access."),
        ("辅助找坑：自动识别失败后，先检测候选坑缘，选候选，搜索并点击环形山名称，再确认加入参考点。按 Enter 可选首条地名。",
         "Crater assistance: if automatic registration fails, detect crater candidates, select one, search and choose its name, then confirm it as a control point. Press Enter to choose the first search result."),
        ("参考点辅助自动：确认一两个已知点后，点击“用参考点自动配准”或“自动识别并标注”。程序搜索附近地形，验证通过后生成标注。",
         "Guided registration: after confirming one or two known points, click “Register using control points” or “Recognize and label”. The app searches nearby terrain and generates labels after validation."),
        ("手动补点：展开“手动补点”，搜索地名，点击取点按钮，再点照片中同一个坑的完整坑缘中心。不要点亮斑或阴影中心。取 3–6 个分散、不共线的点，再完成校准。Esc 取消取点；双击参考点行重选，取消勾选停用。橙色行需核对。月溪、山脉等也可在此选择。",
         "Manual points: expand “Add control point”, find a feature, click the picking button and mark the center of its complete rim in the photo. Avoid bright spots and shadow centers. Use 3–6 well-spread, non-collinear points. Esc cancels picking; double-click a point row to repick or uncheck it to disable it. Check orange rows. Rilles and mountain ranges can also be selected here."),
        ("标注：改设置后点击“重新生成标注”。按住 Cmd 拖动标签、图例或示意图，双击标签编辑文字；直接拖动可平移画面。字号按照片短边计算，按视直径分大、中、小三档；字号递减设为 0 则统一字号。可保存工程或导出 PNG / SVG。",
         "Labels: click “Regenerate labels” after changing settings. Cmd-drag labels, legends or the overview to move them; double-click a label to edit its text. Drag normally to pan. Font sizes scale with the photo’s shorter side and use three apparent-diameter tiers; set the decrement to zero for one size. Save a project or export PNG / SVG."),
        ("滚轮和触控板用于画布缩放、列表与面板滚动；停在参数上不会改值。参数可通过键盘、加减按钮、拖动滑块或选择菜单修改。",
         "Scroll or pinch to zoom the canvas; scroll lists and panels normally. Scrolling over a parameter never changes its value. Use the keyboard, stepper buttons, slider dragging or an explicit menu choice to edit parameters."),
        ("DEM：可导入或下载高程数据，选择区域生成光照参考。基础采样约 1.9 km；不适用于近月缘区域。模拟窗口支持缩放、平移、保存参考工程和匹配当前照片。",
         "DEM: import or download elevation data and select a region to render a lighting reference. Basic sampling is about 1.9 km; it is unsuitable near the lunar limb. The preview supports zooming, panning, saving a reference project and matching the current photo."),
        ("坑缘圈是目录投影参考，可能偏离实际坑缘。拟合残差只表示一致性；数据来源和模型说明见 Swift 版 README。",
         "Crater outlines are catalogue projections and can differ from the actual rim. Fit residuals measure consistency. See the Swift README for models and data sources.")
    ]
}

@MainActor extension EditorModel {
    func showHelp() {
        guard !busy else { return }
        let alert = NSAlert(); alert.messageText = tr("使用 MoonLabeler"); alert.addButton(withTitle: tr("关闭"))
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 570, height: 460))
        scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true; scroll.drawsBackground = false
        let text = NSTextView(frame: NSRect(x: 0, y: 0, width: 550, height: 460))
        text.isEditable = false; text.isSelectable = true; text.drawsBackground = false
        text.font = .systemFont(ofSize: 13); text.textColor = .labelColor
        text.isVerticallyResizable = true; text.isHorizontallyResizable = false; text.autoresizingMask = [.width]
        text.textContainer?.widthTracksTextView = true; text.textContainerInset = NSSize(width: 6, height: 6)
        text.string = EditorHelp.paragraphs.map { uiLanguage == "English" ? $0.1 : tr($0.0) }.joined(separator: "\n\n")
        scroll.documentView = text; alert.accessoryView = scroll
        _ = NativeDialogs.run(alert)
    }
}
