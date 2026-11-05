// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CoreGraphics

public enum LabelLayout {
    // Existing manual placements and text survive generation. Hidden legacy labels stay hidden.
    public static func generate(document: MoonDocument, features: [Feature],
                                overrides: [String: LegacyOverride] = [:],
                                measure: ((String, Double) -> (Double, Double))? = nil) -> [Annotation] {
        guard let calibration = document.calibration else { return document.annotations }
        let settings = document.settings, width = Double(document.imageWidth), height = Double(document.imageHeight)
        var overrides = overrides
        var previous: [String: Annotation] = [:]
        for annotation in document.annotations {
            guard let id = annotation.featureID else { continue }
            previous[id] = annotation
            if !annotation.automatic || annotation.hidden {
                var edit = overrides[id] ?? LegacyOverride(text: nil, position: nil, hidden: false, force: false)
                if annotation.hasTextEdit { edit.text = annotation.text }
                if annotation.hasPositionEdit { edit.position = annotation.position }
                edit.hidden = annotation.hidden; edit.force = true; overrides[id] = edit
            }
        }
        var preserved = document.annotations.filter { $0.featureID == nil }
        let existingIDs = Set(preserved.compactMap(\.featureID))
        for feature in features where overrides[feature.id]?.hidden == true && !existingIDs.contains(feature.id) {
            let edit = overrides[feature.id]!
            let point = calibration.project(feature).point
            var annotation = Annotation(featureID: feature.id, text: edit.text ?? feature.caption(settings.language),
                                        anchor: point, position: edit.position ?? point)
            annotation.hidden = true
            annotation.textEdited = edit.text != nil; annotation.positionEdited = edit.position != nil
            if let old = previous[feature.id] { annotation.id = old.id }
            preserved.append(annotation)
        }
        var result = preserved
        var visibleCount = preserved.filter { !$0.hidden && $0.visual?.landing != true }.count
        let preservedIDs = Set(preserved.compactMap(\.featureID))
        let maxCount = settings.maximumLabels
        var occupied = preserved.filter { !$0.hidden }.map { bounds($0.text, $0.position, settings.fontSize, measure) }
        let sorted = features.sorted {
            let leftForced = overrides[$0.id]?.force == true
            let rightForced = overrides[$1.id]?.force == true
            if leftForced != rightForced { return leftForced }
            let leftCommon = Catalog.commonNames.contains($0.name), rightCommon = Catalog.commonNames.contains($1.name)
            if leftCommon != rightCommon { return leftCommon }
            return $0.diameter == $1.diameter ? $0.id < $1.id : $0.diameter > $1.diameter
        }
        for feature in sorted {
            let landing = feature.kind == "Landing Site"
            if visibleCount >= maxCount && !landing { continue }
            let edit = overrides[feature.id]
            if preservedIDs.contains(feature.id) || edit?.hidden == true { continue }
            if !landing && (feature.diameter < settings.minimumDiameter || !settings.includes(kind: feature.kind)) { continue }
            let projected = calibration.project(feature)
            let point = projected.point
            guard projected.visible, point.isFinite, point.x >= 0, point.y >= 0,
                  point.x < width, point.y < height else { continue }
            let text = edit?.text ?? feature.caption(settings.language)
            let size = textSize(text, settings.fontSize, measure)
            let gap = settings.fontSize * 0.65
            let offsets = [(gap, -size.1 / 2), (-size.0 - gap, -size.1 / 2),
                           (-size.0 / 2, -size.1 - gap), (-size.0 / 2, gap),
                           (gap, -size.1 - gap), (-size.0 - gap, gap),
                           (gap, gap), (-size.0 - gap, -size.1 - gap)]
            let candidates = offsets.map { PixelPoint(point.x + $0.0, point.y + $0.1) }
            let position = edit?.position ?? candidates.first(where: { candidate in
                let rect = bounds(text, candidate, settings.fontSize, measure)
                return rect.minX >= 2 && rect.minY >= 2 && rect.maxX <= width - 2 && rect.maxY <= height - 2 &&
                    (!document.style.bool("optimize_layout", true) || !occupied.contains(where: { $0.intersects(rect.insetBy(dx: -3, dy: -3)) }))
            })
            guard let position else { continue }
            var annotation = Annotation(featureID: feature.id, text: text, anchor: point, position: position,
                                        automatic: edit?.text == nil && edit?.position == nil)
            annotation.hidden = edit?.hidden ?? false
            annotation.textEdited = edit?.text != nil; annotation.positionEdited = edit?.position != nil
            if let old = previous[feature.id] {
                annotation.id = old.id; annotation.anchorEdited = old.hasAnchorEdit
                if old.hasAnchorEdit { annotation.anchor = old.anchor }
            }
            result.append(annotation)
            if !landing { visibleCount += 1 }
            occupied.append(bounds(text, position, settings.fontSize, measure))
        }
        return result
    }

    private static func textSize(_ text: String, _ size: Double,
                                 _ measure: ((String, Double) -> (Double, Double))?) -> (Double, Double) {
        if let measure { return measure(text, size) }
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        let width = lines.map { line in line.reduce(0.0) { $0 + ($1.isASCII ? 0.6 : 1) * size } }.max() ?? size
        return (max(size, width), Double(lines.count) * size * 1.3)
    }

    private static func bounds(_ text: String, _ point: PixelPoint, _ size: Double,
                               _ measure: ((String, Double) -> (Double, Double))?) -> CGRect {
        let (width, height) = textSize(text, size, measure)
        return CGRect(x: point.x, y: point.y, width: width, height: height)
    }
}
