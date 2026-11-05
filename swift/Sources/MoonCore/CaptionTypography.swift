// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import simd

/// Typography shared by font sizing, native painting and editable SVG export.
public struct CaptionTypography: Sendable {
    public static let standard = CaptionTypography()
    public var uppercase = false
    public var italic = false
    public var tracking = 0.0
    public var arc = 0.0
    public var region = false
    public var scale = 1.0
    public static func resolve(feature: Feature, art: String) -> CaptionTypography {
        resolve(kind: feature.kind, diameter: feature.diameter, art: art)
    }
    public static func resolve(kind featureKind: String, diameter: Double, art: String) -> CaptionTypography {
        let kind = featureKind.components(separatedBy: ",")[0]
        let sea = ["Mare", "Oceanus"].contains(kind), smallSea = ["Lacus", "Palus", "Sinus"].contains(kind)
        let linear = ["Mons", "Rima", "Rupes", "Vallis", "Dorsum", "Promontorium", "Catena"].contains(kind)
        if art == "redalert" {
            if sea { return CaptionTypography(uppercase: true, tracking: 0.055, region: true, scale: 1.4) }
            if smallSea { return CaptionTypography(uppercase: true, tracking: 0.025, region: true, scale: 1.1) }
            if linear { return CaptionTypography(tracking: 0.015, scale: 0.85) }
            return CaptionTypography(uppercase: true, tracking: 0.02, scale: kind == "Satellite Feature" ? 0.72 : 1)
        }
        if ["cyanotype", "copperplate", "inkwash"].contains(art) {
            let blueprint = art == "cyanotype", copper = art == "copperplate"
            if sea { return CaptionTypography(uppercase: blueprint || copper, tracking: blueprint ? 0.14 : 0.08, arc: copper ? 0.045 : 0, region: true, scale: copper ? 1.6 : 1.45) }
            if smallSea { return CaptionTypography(uppercase: blueprint || copper, tracking: 0.06, region: true, scale: 1.1) }
            if linear { return CaptionTypography(italic: copper, tracking: blueprint ? 0.025 : 0, scale: 0.85) }
            if kind == "Satellite Feature" { return CaptionTypography(uppercase: blueprint, tracking: 0.02, scale: 0.7) }
            return CaptionTypography(uppercase: blueprint, tracking: blueprint ? 0.045 : 0.015)
        }
        guard art == "manuscript" else { return CaptionTypography() }
        if sea { return CaptionTypography(uppercase: true, tracking: 0.18, arc: 0.09, region: true, scale: 1.85) }
        if smallSea { return CaptionTypography(uppercase: true, tracking: 0.08, region: true, scale: 1.12) }
        if kind == "Mons", diameter >= 80 { return CaptionTypography(uppercase: true, tracking: 0.12, arc: 0.055, region: true, scale: 1.3) }
        if linear { return CaptionTypography(italic: true, scale: 0.8) }
        if kind == "Satellite Feature" { return CaptionTypography(uppercase: true, tracking: 0.02, scale: 0.68) }
        return CaptionTypography(uppercase: !kind.isEmpty, tracking: 0.035)
    }
    public static func advance(_ character: Unicode.Scalar) -> Double {
        if character.properties.canonicalCombiningClass != .notReordered { return 0 }
        let value = character.value
        if character.properties.isIdeographic || (0x2E80...0xA4CF).contains(value) || (0xAC00...0xD7A3).contains(value) || (0xF900...0xFAFF).contains(value) || (0xFE10...0xFE19).contains(value) || (0xFE30...0xFE6F).contains(value) || (0xFF01...0xFF60).contains(value) || (0xFFE0...0xFFE6).contains(value) || (0x1F300...0x1FAFF).contains(value) { return 1 }
        if character.properties.isWhitespace { return 0.32 }
        if "Iil.,:;!|'".unicodeScalars.contains(character) { return 0.3 }
        if "MWmw".unicodeScalars.contains(character) { return 0.9 }
        return 0.66
    }
    public func span(_ text: String) -> Double {
        text.unicodeScalars.reduce(0) { $0 + Self.advance($1) } + tracking * Double(max(0, text.unicodeScalars.count - 1))
    }
}
