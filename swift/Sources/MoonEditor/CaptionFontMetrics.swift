// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import CoreText

enum CaptionFontMetrics {
    private static let cache = NSCache<NSString, NSNumber>()

    /// Match the original pixel-sized Qt captions' AAT optical tracking.
    /// Table format: https://developer.apple.com/fonts/TrueType-Reference-Manual/RM06/Chap6trak.html
    /// Tracking comparison: https://github.com/harfbuzz/harfbuzz/blob/main/src/hb-aat-layout-trak-table.hh
    /// Qt's 96 DPI font point size is 3/4 of the caption's pixel size.
    static func opticalTracking(_ font: CTFont) -> Double {
        let name = CTFontCopyPostScriptName(font) as String
        let variable = (CTFontCopyVariation(font) as? [NSNumber: NSNumber])?.isEmpty == false
        // Qt applies trak to the variable PingFang UI face, but not the
        // separately installed static PingFang face with the same name.
        if name.hasPrefix("PingFang"), !variable { return 0 }
        let size = CTFontGetSize(font), key = "\(name)|\(variable)|\(size)" as NSString
        if let value = cache.object(forKey: key) { return value.doubleValue }
        let value = tracking(font, pointSize: size * 0.75)
        cache.countLimit = 512; cache.setObject(NSNumber(value: value), forKey: key); return value
    }
    static func fixed(_ value: Double) -> Double { (value * 64).rounded(.towardZero) / 64 }

    private static func tracking(_ font: CTFont, pointSize: Double) -> Double {
        guard let table = CTFontCopyTable(font, 0x7472616b, []) else { return 0 }
        let bytes = [UInt8](table as Data)
        func u16(_ offset: Int) -> Int? {
            guard offset >= 0, offset + 2 <= bytes.count else { return nil }
            return Int(bytes[offset]) << 8 | Int(bytes[offset + 1])
        }
        func u32(_ offset: Int) -> UInt32? {
            guard let a = u16(offset), let b = u16(offset + 2) else { return nil }
            return UInt32(a) << 16 | UInt32(b)
        }
        guard u32(0) == 0x00010000, u16(4) == 0, let horizontal = u16(6), horizontal > 0,
              let count = u16(horizontal), let sizes = u16(horizontal + 2), count > 0, count <= 256, sizes > 0, sizes <= 4096,
              let rawOffset = u32(horizontal + 4) else { return 0 }
        let sizeOffset = Int(rawOffset)
        guard sizeOffset + sizes * 4 <= bytes.count, horizontal + 8 + count * 8 <= bytes.count else { return 0 }
        var nodes: [Double] = []
        for index in 0..<sizes {
            guard let raw = u32(sizeOffset + index * 4) else { return 0 }
            let value = Double(Int32(bitPattern: raw)) / 65536
            guard nodes.last.map({ value > $0 }) ?? true else { return 0 }; nodes.append(value)
        }
        var tracks: [(axis: Double, value: Double)] = []
        for index in 0..<count {
            let entry = horizontal + 8 + index * 8
            guard let axis = u32(entry), let offset = u16(entry + 6), offset + sizes * 2 <= bytes.count else { return 0 }
            func sample(_ index: Int) -> Double { Double(Int16(bitPattern: UInt16(u16(offset + index * 2)!))) }
            let value: Double
            if pointSize <= nodes[0] { value = sample(0) }
            else if pointSize >= nodes.last! { value = sample(sizes - 1) }
            else {
                let upper = nodes.firstIndex(where: { $0 >= pointSize })!, lower = upper - 1
                let fraction = (pointSize - nodes[lower]) / (nodes[upper] - nodes[lower])
                value = sample(lower) * (1 - fraction) + sample(upper) * fraction
            }
            tracks.append((Double(Int32(bitPattern: axis)) / 65536, value))
        }
        tracks.sort { $0.axis < $1.axis }
        let units: Double
        if tracks.count == 1 || tracks[0].axis >= 0 { units = tracks[0].value }
        else if tracks.last!.axis <= 0 { units = tracks.last!.value }
        else {
            let upper = tracks.firstIndex(where: { $0.axis >= 0 })!, lower = upper - 1
            let span = tracks[upper].axis - tracks[lower].axis
            units = span > 0 ? (tracks[lower].value * tracks[upper].axis - tracks[upper].value * tracks[lower].axis) / span : tracks[lower].value
        }
        let pixels = units * CTFontGetSize(font) / Double(max(1, CTFontGetUnitsPerEm(font)))
        return (pixels * 64).rounded() / 64
    }
}
