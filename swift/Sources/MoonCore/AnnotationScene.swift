// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import simd

public struct CaptionGlyph: Codable, Equatable, Sendable {
    public var text: String, point: PixelPoint, angle: Double, scale: Double, advance: Double, family: String
    public init(text: String, point: PixelPoint, angle: Double, scale: Double, advance: Double, family: String) {
        self.text = text; self.point = point; self.angle = angle; self.scale = scale; self.advance = advance; self.family = family
    }
}

public struct AnnotationVisual: Codable, Equatable, Sendable {
    public var fontScale: Double = 1
    public var baseline: [PixelPoint]?
    public var baselineOrigin: PixelPoint?
    public var pathGlyphs: [CaptionGlyph]?
    public var pathOrigin: PixelPoint?
    public var outline: [[PixelPoint]] = []
    public var lightness: Int?
    public var landing = false
    public var color: String?
    public var layoutHidden: Bool?
    public var featureKind: String?
    public var featureDiameter: Double?
    public var hasChineseName: Bool?
    public init() {}
}
public struct AnnotationScene: Sendable {
    public var id = UUID()
    public var layers: MapLayers
    public var overview: PhotoOverview?
    public var source: String
    public var grayscale: PhotoPixels?
    public init(layers: MapLayers = MapLayers(), overview: PhotoOverview? = nil, source: String = "") {
        self.layers = layers; self.overview = overview; self.source = source
    }
}

public enum AnnotationSceneBuilder {
    public static func build(document: MoonDocument, photo: PhotoPixels, features: [Feature], dem: ElevationMap?,
                             task: ComputeTask, measure: ((String, Double) -> (Double, Double))? = nil,
                             captionBounds: ((Annotation, MoonDocument) -> CGRect)? = nil,
                             configureCaption: ((Annotation, Feature, MoonDocument) -> Annotation)? = nil,
                             displayPhoto: PhotoPixels? = nil, reusingScene: AnnotationScene? = nil) throws -> (MoonDocument, AnnotationScene) {
        var document = document
        ProjectCompatibility.captureEdits(&document)
        guard let calibration = document.calibration else { return (document, AnnotationScene()) }
        let style = document.style, short = Double(min(document.imageWidth, document.imageHeight))
        var allFeatures = features
        if style.bool("show_landing_sites") { allFeatures += try landings() }
        if document.state.projectionSurface == "terrain", document.state.legacy["annotation_relief"]?.object.isEmpty ?? true, let dem {
            document.state.legacy["annotation_relief"] = try AnnotationSurface.snapshot(features: features + landings(), camera: calibration, width: document.imageWidth, height: document.imageHeight, dem: dem, task: task)
        }
        let snapshot = document, surface = try AnnotationSurface(document: snapshot)
        let layers = try reusingScene?.layers ?? MapBuilder.build(document: snapshot, photo: photo, dem: dem, task: task)
        let overrides = ProjectCompatibility.labelOverrides(snapshot)
        let previous = Dictionary(snapshot.annotations.compactMap { annotation in annotation.featureID.map { ($0, annotation) } }, uniquingKeysWith: { first, _ in first })
        let relief = snapshot.state.legacy["annotation_relief"]?.object ?? [:]
        let savedRims = (relief["rims"]?.object ?? [:]).merging(snapshot.state.legacy["terrain_rims"]?.object ?? [:]) { _, edited in edited }
        var anchors: [String: PixelPoint] = [:]
        func rawRim(_ feature: Feature, traced: [JSONValue]? = nil) -> ([PixelPoint], [Bool]) {
            surface.rim(feature, coordinates: traced)
        }
        func anchor(_ feature: Feature) -> PixelPoint? {
            if let existing = anchors[feature.id] { return existing }
            if let old = previous[feature.id], old.hasAnchorEdit { anchors[feature.id] = old.anchor; return old.anchor }
            let projected = surface.position(feature)
            guard projected.visible else { return nil }
            anchors[feature.id] = projected.point; return projected.point
        }
        let ranked = try FeatureRanking.rank(features: allFeatures, document: snapshot, photo: photo, overrides: overrides, anchor: anchor, task: task)
        func prepare(_ item: RankedFeature) -> Annotation {
            let feature = item.feature, edit = item.edit, typography = CaptionTypography.resolve(feature: item.feature, art: style.art)
            let kind = feature.kind.components(separatedBy: ",")[0]
            var text = edit?.text ?? feature.caption(snapshot.settings.language)
            if edit?.text == nil && typography.uppercase { text = text.uppercased() }
            var annotation = Annotation(featureID: feature.id, text: text, anchor: item.anchor, position: PixelPoint(0, 0), automatic: edit?.text == nil && edit?.position == nil && edit?.hidden != true)
            if let old = previous[feature.id] { annotation.id = old.id; annotation.anchorEdited = old.hasAnchorEdit }
            annotation.textEdited = edit?.text != nil; annotation.positionEdited = edit?.position != nil; annotation.hidden = edit?.hidden ?? false
            var visual = AnnotationVisual(); visual.fontScale = LabelSizing.size(feature, document: snapshot) / snapshot.settings.fontSize
            visual.featureKind = feature.kind; visual.featureDiameter = feature.diameter; visual.hasChineseName = !feature.chinese.isEmpty
            visual.landing = feature.kind == "Landing Site"
            if style.art == "inkwash" && (["Mare", "Oceanus", "Lacus", "Palus", "Sinus"].contains(kind) || feature.diameter >= 80) { visual.color = "#a63f32" }
            if style.art == "topographic" && feature.kind == "Satellite Feature" { visual.color = "#d5c798" }
            visual.lightness = layers.lightness?.score(feature: feature, anchor: annotation.anchor, calibration: calibration)
            if !style.isArt && style.bool("crater_outlines", true) && ["Crater, craters", "Satellite Feature"].contains(feature.kind) && feature.diameter >= 35 {
                var rim = rawRim(feature)
                let x = rim.0.map(\.x), y = rim.0.map(\.y), spanX = (x.max() ?? 0) - (x.min() ?? 0), spanY = (y.max() ?? 0) - (y.min() ?? 0)
                if min(spanX, spanY) >= LabelSizing.tierSizes(snapshot)[1] * 1.6 && max(spanX, spanY) >= short * 0.055 {
                    if style.string("crater_outline_shape", "ellipse") == "terrain", savedRims[feature.id] == nil, let dem,
                       feature.diameter >= max(35, 6 * dem.resolutionKM), let traced = traceRim(feature, dem: dem) { rim = rawRim(feature, traced: traced) }
                    if style.string("crater_outline_shape", "ellipse") != "terrain", let ellipse = NativeCompute.ellipse(rim.0) { rim.0 = ellipse.points }
                    var current: [PixelPoint] = []
                    for (point, visible) in zip(rim.0, rim.1) { if visible { current.append(point) } else { if current.count >= 2 { visual.outline.append(current) }; current = [] } }
                    if current.count >= 2 { visual.outline.append(current) }
                }
            }
            annotation.visual = visual; return configureCaption?(annotation, feature, snapshot) ?? annotation
        }
        var objects: [String: Annotation] = [:], bounds: [String: CGRect] = [:], index = 0
        func next() -> PlacementRequest? {
            while index < ranked.count {
                let item = ranked[index]; index += 1
                if item.edit?.hidden == true { continue }
                let feature = item.feature, annotation = prepare(item), size = snapshot.settings.fontSize * (annotation.visual?.fontScale ?? 1)
                let measured = measure?(annotation.text, size) ?? (Double(annotation.text.count) * size * 0.7, size * 1.3)
                let rect = captionBounds?(annotation, snapshot) ?? CGRect(x: -5, y: -5, width: measured.0 + 10, height: measured.1 + 10)
                objects[feature.id] = annotation; bounds[feature.id] = rect
                var radius = ["Crater, craters", "Satellite Feature"].contains(feature.kind) ? min(short * 0.12, max(4, feature.diameter * calibration.scale / (2 * moonRadius))) : min(size * 1.3, max(4, feature.diameter * calibration.scale / (4 * moonRadius)))
                if style.art == "topographic" { radius = max(4, size * 0.25) }
                else if style.isArt { radius = min(radius, max(size * 0.6, short * 0.025)) }
                let preferred = annotation.visual?.pathOrigin.map { PixelPoint($0.x + rect.minX, $0.y + rect.minY) }
                let fixed = item.edit?.position.map { PixelPoint($0.x + rect.minX, $0.y + rect.minY) }
                let region = preferred != nil || style.art == "topographic" || CaptionTypography.resolve(feature: feature, art: style.art).region
                return PlacementRequest(key: feature.id, anchor: annotation.anchor, width: rect.width, height: rect.height, radius: radius, fixed: fixed, force: item.edit?.force ?? false,
                                        important: preferred != nil || Catalog.commonNames.contains(feature.name) || annotation.visual?.landing == true,
                                        region: region, preferred: preferred, outline: annotation.visual?.outline ?? [])
            }
            return nil
        }
        var obstacles: [CGRect] = []
        if style.elevationEnabled || style.contourEnabled {
            let unit = short / 100, width = min(30 * unit, Double(snapshot.imageWidth) - 4 * unit), height = 6 * unit, position = style.values["legend_position"]?.array.compactMap(\.number) ?? []
            obstacles.append(CGRect(x: min(max(0, position.first ?? 2 * unit), Double(snapshot.imageWidth) - width), y: min(max(0, position.count == 2 ? position[1] : Double(snapshot.imageHeight) - 8 * unit), Double(snapshot.imageHeight) - height), width: width, height: height))
        }
        if style.bool("overview_enabled") { let w = short * 0.25, h = w * 366 / 320, p = style.values["overview_position"]?.array.compactMap(\.number) ?? []; obstacles.append(CGRect(x: min(max(0, p.first ?? short * 0.02), Double(snapshot.imageWidth) - w), y: min(max(0, p.count == 2 ? p[1] : short * 0.02), Double(snapshot.imageHeight) - h), width: w, height: h)) }
        var placements: [String: CGRect] = [:], omitted = Set<String>()
        if style.bool("optimize_layout", true) {
            let result = LabelPlacement.arrange(next: next, width: Double(snapshot.imageWidth), height: Double(snapshot.imageHeight), gap: max(5, LabelSizing.tierSizes(snapshot)[1] * (style.art == "topographic" ? 0.8 : 0.4)), maximum: snapshot.settings.maximumLabels, obstacles: obstacles)
            placements = result.placements; omitted = result.omitted
        } else {
            for _ in 0..<snapshot.settings.maximumLabels { guard let request = next() else { break }; let p = request.fixed ?? request.preferred ?? PixelPoint(request.anchor.x + request.radius + 8, request.anchor.y - request.height / 2); placements[request.key] = CGRect(x: p.x, y: p.y, width: request.width, height: request.height) }
        }
        try task.check()
        document.annotations = ranked.compactMap { item in
            let id = item.feature.id
            if item.edit?.hidden == true { return prepare(item) }
            guard var annotation = objects[id], let rect = bounds[id] else { return nil }
            if let placement = placements[id] { annotation.position = PixelPoint(placement.minX - rect.minX, placement.minY - rect.minY) }
            annotation.visual?.layoutHidden = omitted.contains(id); return annotation
        } + snapshot.annotations.filter { $0.featureID == nil }
        let overview = style.bool("overview_enabled") ? try reusingScene?.overview ?? OverviewBuilder.build(document: document, task: task) : nil
        var scene = AnnotationScene(layers: layers, overview: overview, source: dem?.name ?? reusingScene?.source ?? "")
        if style.isArt, let grayscale = reusingScene?.grayscale { scene.grayscale = grayscale }
        else if style.isArt {
            scene.grayscale = (displayPhoto ?? photo).desaturated()
        }
        return (document, scene)
    }
    public static func visible(_ annotation: Annotation, document: MoonDocument, scene: AnnotationScene?) -> Bool {
        guard !annotation.hidden, annotation.visual?.layoutHidden != true else { return false }
        if annotation.visual?.landing == true && !document.style.bool("show_landing_sites") { return false }
        guard document.style.illuminatedOnly, let score = annotation.visual?.lightness else { return true }
        let threshold = document.style.threshold ?? scene?.layers.lightness?.automaticThreshold ?? 1
        return score >= threshold
    }
    public static func landings() throws -> [Feature] {
        guard let url = Catalog.resource("landing_sites", "json") else { return [] }
        let root = try JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: url))
        return (root.object["sites"]?.array ?? []).compactMap { item in
            let value = item.object
            guard let id = value["id"]?.string, let name = value["name"]?.string, let lat = value["lat"]?.number, let lon = value["lon"]?.number else { return nil }
            return Feature(id: id, name: name, chinese: value["name_zh"]?.string ?? "", latitude: lat, longitude: lon, diameter: 0, kind: "Landing Site")
        }
    }
    private static func projectedRim(coordinates: [JSONValue], calibration: Calibration) -> [[PixelPoint]] {
        var result: [[PixelPoint]] = [], current: [PixelPoint] = []
        for item in coordinates {
            let v = item.array.compactMap(\.number); guard v.count >= 2 else { continue }
            let point = calibration.geometry.project(latitude: v[0], longitude: v[1], height: v.count > 2 ? v[2] : 0)
            if point.visible { current.append(calibration.photoPoint(point.point)) }
            else if current.count > 1 { result.append(current); current = [] }
        }
        if current.count > 1 { result.append(current) }; return result
    }
    public static func traceRim(_ feature: Feature, dem: ElevationMap) -> [JSONValue]? {
        let radius = feature.diameter / 2
        guard radius >= 3 * dem.resolutionKM else { return nil }
        let center = surfaceVector(latitude: feature.latitude, longitude: feature.longitude), lon = feature.longitude * .pi / 180
        let east = SIMD3(-sin(lon), cos(lon), 0), north = simd_cross(center, east)
        let factors = (0..<71).map { 0.65 + Double($0) * 0.01 }
        var height = [[Double]](), tangents = [SIMD3<Double>]()
        for row in 0..<128 {
            let theta = Double(row) / 128 * 2 * .pi, tangent = cos(theta) * north + sin(theta) * east
            tangents.append(tangent)
            let values = factors.map { factor -> Double in let angle = radius / moonRadius * factor; let (lat, lon) = coordinates(cos(angle) * center + sin(angle) * tangent); return dem.sample(lat, lon) }
            guard values.allSatisfy(\.isFinite) else { return nil }; height.append(values)
        }
        let ranges = height.map { $0.max()! - $0.min()! }.sorted()
        guard ranges[64] >= 0.25 else { return nil }
        let score = height.map { row -> [Double] in let low = row.min()!, span = max(0.2, row.max()! - low); return factors.enumerated().map { (row[$0.offset] - low) / span - 0.25 * pow(($0.element - 1) / 0.35, 2) } }
        func transition(_ a: Int, _ b: Int) -> Double { 0.03 * pow((factors[a] - factors[b]) / 0.035, 2) }
        var end = 35, selected = [Int](repeating: 0, count: 128)
        for _ in 0..<2 {
            var state = (0..<71).map { score[0][$0] - transition(end, $0) }, trace = [[Int]]()
            for row in 1..<128 {
                var previous = [Int](repeating: 0, count: 71), next = [Double](repeating: 0, count: 71)
                for current in 0..<71 {
                    let best = (0..<71).max { state[$0] - transition($0, current) < state[$1] - transition($1, current) }!
                    previous[current] = best; next[current] = state[best] - transition(best, current) + score[row][current]
                }
                trace.append(previous); state = next
            }
            selected[127] = state.indices.max { state[$0] < state[$1] }!
            for row in stride(from: 126, through: 0, by: -1) { selected[row] = trace[row][selected[row + 1]] }
            end = selected[127]
        }
        guard selected.filter({ $0 > 1 && $0 < 69 }).count >= 109 else { return nil }
        var result: [JSONValue] = [], total = 0.0
        for row in 0..<128 {
            let weights = [1.0, 2, 3, 2, 1]
            let factor = (-2...2).enumerated().reduce(0) { $0 + weights[$1.offset] * factors[selected[(row + $1.element + 128) % 128]] } / 9
            let angle = radius / moonRadius * factor, (lat, lon) = coordinates(cos(angle) * center + sin(angle) * tangents[row]), h = dem.sample(lat, lon)
            guard h.isFinite else { return nil }; total += h
            result.append(.array([.number(lat), .number(lon), .number(h)]))
        }
        guard total / 128 - dem.sample(feature.latitude, feature.longitude) >= 0.15 else { return nil }
        result.append(result[0]); return result
    }
}
