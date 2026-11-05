// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit

enum LabelFonts {
    static let families = NSFontManager.shared.availableFontFamilies
        .filter { !$0.isEmpty && !$0.hasPrefix(".") }
        .sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
    private static let installed = Dictionary(families.map { ($0.lowercased(), $0) }, uniquingKeysWith: { first, _ in first })
    private static let faces = NSCache<NSString, NSFont>()

    static func installedFamily(_ name: String) -> String? { installed[name.lowercased()] }

    static func preferredFace(_ name: String, fallback: NSFont, regular: Bool, italic: Bool) -> NSFont? {
        guard let family = installedFamily(name) else { return nil }
        let size = fallback.pointSize
        let key = "\(family)|\(fallback.fontName)|\(size)|\(regular)|\(italic)" as NSString
        if let face = faces.object(forKey: key) { return face }
        let manager = NSFontManager.shared, weight = regular ? 5 : 9
        let traits: NSFontTraitMask = regular ? [] : .boldFontMask
        guard var face = manager.font(withFamily: family, traits: traits, weight: weight, size: size)
            ?? manager.font(withFamily: family, traits: [], weight: weight, size: size),
            face.familyName?.caseInsensitiveCompare(family) == .orderedSame else { return nil }
        if italic { face = manager.convert(face, toHaveTrait: .italicFontMask) }
        var cascade = [fallback.fontDescriptor]
        if fallback.familyName == "PingFang TC" {
            cascade.append(NSFontDescriptor(fontAttributes: [.family: "PingFang SC"]))
        }
        cascade.append(NSFontDescriptor(fontAttributes: [.family: "Hiragino Sans"]))
        let resolved = NSFont(descriptor: face.fontDescriptor.addingAttributes([.cascadeList: cascade]), size: size) ?? face
        faces.countLimit = 256
        faces.setObject(resolved, forKey: key)
        return resolved
    }
}
