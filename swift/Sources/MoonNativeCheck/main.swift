// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import MoonCore
import MoonEditor
import ImageIO

let arguments = CommandLine.arguments
guard arguments.count >= 2 else {
    print("Usage: MoonNativeCheck project.moonlabel [dem.LBL] [output.moonswift]")
    exit(2)
}
do {
    let start = Date(), url = URL(fileURLWithPath: arguments[1])
    var document = try ProjectIO.read(url).document
    let photo = try PhotoPixels.load(URL(fileURLWithPath: document.imagePath))
    if arguments.count > 3, arguments[2] == "--lightness" {
        let directory = URL(fileURLWithPath: arguments[3], isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let field = try PhotoLightness(photo: photo, calibration: document.calibration)
        try Data(field.values).write(to: directory.appendingPathComponent("native-lightness.bin"))
        for level in [nil, 5, 21] as [Int?] {
            let coverage = try field.coverage(threshold: level)
            let alpha = stride(from: 3, to: coverage.rgba.count, by: 4).map { coverage.rgba[$0] }
            try Data(alpha).write(to: directory.appendingPathComponent("native-coverage-\(level.map(String.init) ?? "auto").bin"))
        }
        print("Automatic threshold: \(field.automaticThreshold), lightness \(field.width)x\(field.height)")
        exit(0)
    }
    if arguments.count > 2, arguments[2] == "--check-ui-input" {
        let ui = try PhotoPixels(PhotoIO.load(URL(fileURLWithPath: document.imagePath)))
        let differences = zip(photo.rgba, ui.rgba).map { abs(Int($0) - Int($1)) }
        print("GUI input: \(ui.width)x\(ui.height), mean pixel difference \(Double(differences.reduce(0,+)) / Double(differences.count)), max \(differences.max() ?? 0)")
        exit(differences.max() == 0 ? 0 : 1)
    }
    if arguments.count > 3, arguments[2] == "--render" {
        let directory = URL(fileURLWithPath: arguments[3], isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        document.imageWidth = photo.width; document.imageHeight = photo.height
        document.settings.fontSize = LabelSizing.tierSizes(document)[0]
        if arguments.count > 4 { document.changeStyle { $0.applyArt(arguments[4]) } }
        let dem = try Catalog.resource("LDEM_16", "LBL").map { try ElevationMap(url: $0) }
        let display = try PhotoPixels.display(URL(fileURLWithPath: document.imagePath), raw: photo)
        let rendered = try AnnotationSceneBuilder.build(document: document, photo: photo, features: Catalog.load(), dem: dem, task: ComputeTask(), measure: AnnotationRenderer.measure, captionBounds: AnnotationRenderer.placementBounds, configureCaption: AnnotationRenderer.configureCaption, displayPhoto: display)
        try PhotoIO.png(image: display.cgImage, document: rendered.0, scene: rendered.1, to: directory.appendingPathComponent("native.png"))
        try AnnotationRenderer.svg(image: display.cgImage, document: rendered.0, scene: rendered.1, to: directory.appendingPathComponent("native.svg"))
        try ProjectIO.write(rendered.0, to: directory.appendingPathComponent("native.moonswift"))
        print("Rendered \(rendered.0.annotations.filter { AnnotationSceneBuilder.visible($0, document: rendered.0, scene: rendered.1) }.count) visible labels in \(Date().timeIntervalSince(start)) seconds.")
        exit(0)
    }
    let kernels = arguments.count > 3 && arguments[2] == "--ephemeris" ? URL(fileURLWithPath: arguments[3], isDirectory: true) : nil
    let geometry = try NativeCompute.ephemeris(utc: document.state.utc, latitude: document.state.latitude, longitude: document.state.longitude, kernelDirectory: kernels)
    if arguments.count > 3, arguments[2] == "--ephemeris" { print("Ephemeris ready: \(geometry.utc), distance \(geometry.distanceKM) km"); exit(0) }
    if arguments.count > 3, arguments[2] == "--sources" {
        let directory = URL(fileURLWithPath: arguments[3], isDirectory: true), task = ComputeTask()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let names = try await CatalogueUpdate.refresh(task: task, directory: directory)
        print("USGS: \(names.count) names downloaded and parsed."); fflush(stdout)
        let nasa = try await ReferenceIO.nasa(utc: document.state.utc, task: task, directory: directory)
        try ReferenceIO.save(nasa.0, geometry: nasa.1, state: document.state, to: directory.appendingPathComponent("nasa-reference.png"))
        print("USGS: \(names.count) names; NASA: \(nasa.0.image.width) × \(nasa.0.image.height); compatible reference saved.")
        exit(0)
    }
    if arguments.count > 3, arguments[2] == "--atlas" || arguments[2] == "--terrain" {
        let atlas: TerrainReference
        if arguments[2] == "--terrain" {
            guard arguments.count > 4 else { throw MoonError.invalid("--terrain DEM output-directory") }
            atlas = try ReferenceRenderer.terrain(dem: ElevationMap(url: URL(fileURLWithPath: arguments[3])), geometry: geometry, task: ComputeTask())
        } else { atlas = try ReferenceRenderer.atlas(geometry: geometry, task: ComputeTask()) }
        let directory = URL(fileURLWithPath: arguments[arguments[2] == "--terrain" ? 4 : 3], isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        for (name, image) in [("native-atlas.png", atlas.image.cgImage), ("native-photo.png", photo.cgImage)] {
            let target = directory.appendingPathComponent(name)
            guard let destination = CGImageDestinationCreateWithURL(target as CFURL, "public.png" as CFString, 1, nil) else { throw MoonError.invalid("PNG destination failed") }
            CGImageDestinationAddImage(destination, image, nil)
            if !CGImageDestinationFinalize(destination) { throw MoonError.invalid("PNG encode failed") }
        }
        print("Rendered native diagnostic images.")
        exit(0)
    }
    let dem = arguments.count > 2 ? try ElevationMap(url: URL(fileURLWithPath: arguments[2])) : nil
    let features = try Catalog.load(), original = document.calibration
    let result = try RecognitionEngine.identify(photo: photo, geometry: geometry, state: document.state, features: features, dem: dem, task: ComputeTask()) { message in
        FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    }
    var errors: [Double] = []
    if let original {
        for feature in features {
            let before = original.project(feature), after = result.calibration.project(feature)
            if before.visible && after.visible && before.point.x >= 0 && before.point.y >= 0 && before.point.x < Double(photo.width) && before.point.y < Double(photo.height) {
                errors.append(hypot(before.point.x - after.point.x, before.point.y - after.point.y))
            }
        }
    }
    errors.sort()
    let summary: [String: Any] = ["method": result.method, "matches": result.matches, "rms_px": result.rms,
                                "coverage": result.coverage, "seconds": Date().timeIntervalSince(start),
                                "median_difference_from_saved_pose_px": errors.isEmpty ? -1 : errors[errors.count / 2]]
    print(String(data: try JSONSerialization.data(withJSONObject: summary, options: [.prettyPrinted, .sortedKeys]), encoding: .utf8)!)
    if arguments.count > 3 {
        try document.applyIdentification(result); document.imageWidth = photo.width; document.imageHeight = photo.height
        try ProjectIO.write(document, to: URL(fileURLWithPath: arguments[3]))
    }
} catch {
    FileHandle.standardError.write((error.localizedDescription + "\n").data(using: .utf8)!)
    exit(1)
}
