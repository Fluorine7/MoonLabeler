// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import MoonCore

@MainActor enum EditorCredits {
    private static let paragraphs: [(String, String)] = [
        ("作者：Fluorine Zhu\n开源许可：GNU GPL v3.0 或更新版本",
         "Author: Fluorine Zhu\nLicence: GNU GPL v3.0 or later"),
        ("致敬 Jim Mosher 与 Henrik Bondo 创建的 Lunar Terminator Visualization Tool。原版参考其地形点校准与 DEM 光照思路，使用 Python / Qt 独立实现；Swift 版采用 Swift / AppKit 与原生 C/C++ 移植。",
         "In tribute to Jim Mosher and Henrik Bondo, creators of the Lunar Terminator Visualization Tool. The original independently implemented its approach to feature-point calibration and DEM lighting in Python / Qt; this port uses Swift / AppKit and native C/C++."),
        ("感谢樊仕达（[10deg](https://github.com/10deg/tsukikage)）提供 moonlib 代码参考及 LPND 中文地名资料。",
         "Thanks to 樊仕达 (Fan Shida, [10deg](https://github.com/10deg/tsukikage)) for moonlib code references and LPND Chinese feature-name data."),
        ("感谢蔡明翰（[Evan Tsai](https://www.facebook.com/mjrt.mj)）贡献繁体中文支持及 Windows 部分问题修复。",
         "Thanks to 蔡明翰 ([Evan Tsai](https://www.facebook.com/mjrt.mj)) for Traditional Chinese support and fixes for several Windows issues."),
        ("感谢 [sothic](https://github.com/sothic) 贡献工具栏缩放、原始大小按钮及快捷键。",
         "Thanks to [sothic](https://github.com/sothic) for toolbar zoom controls, the actual-size button and keyboard shortcuts."),
        ("地名：USGS / IAU；中文译名优先采用 LPND，补录来源单独保留。\n月面高程：LRO / LOLA；星历：JPL DE421；着陆点：NASA NSSDCA / LROC。",
         "Feature names: USGS / IAU. Chinese names prefer LPND, with supplementary sources recorded separately.\nLunar elevation: LRO / LOLA; ephemeris: JPL DE421; landing sites: NASA NSSDCA / LROC."),
        ("疑似坑检测改编自 Ram Maruboina 的 [Lunar Crater Detector](https://github.com/rammaruboina-rgb/lunar-crater-detector)（MIT）。",
         "Crater-candidate detection is adapted from Ram Maruboina’s [Lunar Crater Detector](https://github.com/rammaruboina-rgb/lunar-crater-detector) (MIT)."),
        ("完整贡献者、方法、数据来源与许可信息见本窗口的“完整致谢”和“第三方声明”，以及随 Swift 应用附带的说明文件。",
         "See “Full acknowledgements”, “Third-party notices” and the documents bundled with the Swift app for all contributors, methods, data sources and licence details.")
    ]

    private static func translated(_ chinese: String, _ english: String, language: String) -> String {
        language == "English" ? english : InterfaceText.translate(chinese, language: language)
    }
    static func show(language: String) {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""
        let alert = NSAlert(); alert.messageText = "MoonLabeler Swift \(version)" + (build.isEmpty ? "" : " (\(build))")
        alert.addButton(withTitle: translated("关闭", "Close", language: language))
        alert.addButton(withTitle: translated("完整致谢", "Full acknowledgements", language: language))
        alert.addButton(withTitle: translated("第三方声明", "Third-party notices", language: language))
        let markdown = paragraphs.map { translated($0.0, $0.1, language: language) }.joined(separator: "\n\n")
        alert.accessoryView = scrollView(markdown: markdown)
        alert.window.initialFirstResponder = alert.buttons.first
        switch NativeDialogs.run(alert) {
        case .alertSecondButtonReturn: showDocument("ACKNOWLEDGEMENTS", title: translated("完整致谢", "Full acknowledgements", language: language))
        case .alertThirdButtonReturn: showDocument("THIRD_PARTY_NOTICES", title: translated("第三方声明", "Third-party notices", language: language))
        default: break
        }
    }
    private static func showDocument(_ name: String, title: String) {
        guard let url = Bundle.main.url(forResource: name, withExtension: "md") ?? Catalog.resource(name, "md"),
              let markdown = try? String(contentsOf: url, encoding: .utf8) else { return }
        let alert = NSAlert(); alert.messageText = title
        let provenance = Catalog.resource("moon_albedo_2k.provenance", "json")
        let content = provenance.map { markdown.replacingOccurrences(of: "Sources/MoonCore/Resources/moon_albedo_2k.provenance.json", with: $0.absoluteString) } ?? markdown
        alert.accessoryView = scrollView(markdown: content, baseURL: url.deletingLastPathComponent())
        alert.window.initialFirstResponder = alert.buttons.first
        _ = NativeDialogs.run(alert)
    }
    private static func scrollView(markdown: String, baseURL: URL? = nil) -> NSScrollView {
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 600, height: 430))
        scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true; scroll.drawsBackground = false
        let text = NSTextView(frame: NSRect(x: 0, y: 0, width: 580, height: 430))
        text.isEditable = false; text.isSelectable = true; text.drawsBackground = false
        text.isVerticallyResizable = true; text.isHorizontallyResizable = false; text.autoresizingMask = [.width]
        text.textContainer?.widthTracksTextView = true; text.textContainerInset = NSSize(width: 6, height: 6)
        text.linkTextAttributes = [.foregroundColor: NSColor.linkColor, .underlineStyle: NSUnderlineStyle.single.rawValue]
        let content = NSMutableAttributedString(string: "")
        func append(_ line: String, heading: Bool = false) {
            let parsed = (try? AttributedString(markdown: line, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace), baseURL: baseURL)) ?? AttributedString(line)
            let attributed = NSMutableAttributedString(attributedString: NSAttributedString(parsed))
            let paragraph = NSMutableParagraphStyle(); paragraph.paragraphSpacing = heading ? 5 : 11; paragraph.lineSpacing = 3
            attributed.addAttributes([.font: heading ? NSFont.boldSystemFont(ofSize: 14) : NSFont.systemFont(ofSize: 13),
                .foregroundColor: NSColor.labelColor, .paragraphStyle: paragraph], range: NSRange(location: 0, length: attributed.length))
            content.append(attributed); content.append(NSAttributedString(string: "\n"))
        }
        for raw in markdown.components(separatedBy: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }
            if line.hasPrefix("|") {
                let columns = line.split(separator: "|", omittingEmptySubsequences: true).map { $0.trimmingCharacters(in: .whitespaces) }
                guard columns.count == 2, !columns[0].hasPrefix("---"), !columns[0].contains("贡献者 / Contributors") else { continue }
                append(columns[0], heading: true); append(columns[1])
            } else if line.hasPrefix("#") { append(line.drop(while: { $0 == "#" || $0 == " " }).description, heading: true) }
            else { append(line) }
        }
        text.textStorage?.setAttributedString(content)
        scroll.documentView = text
        text.scrollRangeToVisible(NSRange(location: 0, length: 0))
        return scroll
    }
}
