// SPDX-License-Identifier: GPL-3.0-or-later
import XCTest
import AppKit
import CoreText
import ImageIO
import UniformTypeIdentifiers
import SwiftUI
@testable import MoonCore
@testable import MoonEditor

final class NativeEditorTests: XCTestCase {
    func testCalibrationMarkersAndPickingToolsStayOnTheCalibrationPage() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            var document = MoonDocument(imagePath: "markers.png")
            document.imageWidth = 240; document.imageHeight = 160
            document.state.anchors = [ControlPoint(id: "1296", point: PixelPoint(120, 80))]
            model.document = document
            model.image = PhotoPixels(width: 240, height: 160, rgba: Array(repeating: [UInt8(0), 0, 0, 255], count: 240 * 160).flatMap { $0 }).cgImage
            let canvas = MoonCanvas(frame: CGRect(x: 0, y: 0, width: 240, height: 160)); canvas.model = model
            @MainActor func markerPixels() throws -> Int {
                let context = try XCTUnwrap(CGContext(data: nil, width: 240, height: 160, bitsPerComponent: 8, bytesPerRow: 960,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
                context.translateBy(x: 0, y: 160); context.scaleBy(x: 1, y: -1)
                NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
                canvas.draw(canvas.bounds); NSGraphicsContext.restoreGraphicsState()
                let pixels = try PhotoPixels(XCTUnwrap(context.makeImage()))
                return stride(from: 0, to: pixels.rgba.count, by: 4).filter { pixels.rgba[$0 + 1] > 100 && pixels.rgba[$0 + 2] > 100 }.count
            }
            XCTAssertGreaterThan(try markerPixels(), 0)
            model.canvasTool = .paint; model.showMask = true
            model.panelTab = 1
            XCTAssertEqual(try markerPixels(), 0, "Calibration points must not appear in the annotation workspace")
            XCTAssertEqual(model.canvasTool, .pan); XCTAssertFalse(model.showMask)
            model.panelTab = 2
            XCTAssertEqual(try markerPixels(), 0)
        }
    }
    func testTaggedPhotoUsesDisplaySRGBOnTheActualCanvasAndPreservesInput() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("tagged.png")
        let bytes: [UInt8] = Array(repeating: [170,69,109,255], count: 12 * 8).flatMap { $0 }
        let provider = try XCTUnwrap(CGDataProvider(data: Data(bytes) as CFData))
        let image = try XCTUnwrap(CGImage(width: 12, height: 8, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 48,
            space: try XCTUnwrap(CGColorSpace(name: CGColorSpace.displayP3)), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue), provider: provider, decode: nil, shouldInterpolate: false, intent: .relativeColorimetric))
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, nil); XCTAssertTrue(CGImageDestinationFinalize(destination))
        let model = await MainActor.run { _ = NSApplication.shared; let model = EditorModel(); model.requestOpen(url); return model }
        for _ in 0..<200 {
            if await MainActor.run(body: { model.image != nil && !model.busy }) { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        try await MainActor.run {
            let raw = try PhotoPixels(XCTUnwrap(model.image)), display = try PhotoPixels(XCTUnwrap(model.displayImage))
            XCTAssertEqual(Array(raw.rgba.prefix(3)), [170,69,109])
            for (actual, expected) in zip(display.rgba.prefix(3), [184,60,110]) { XCTAssertEqual(Int(actual), expected, accuracy: 3) }
            let canvas = MoonCanvas(frame: NSRect(x: 0, y: 0, width: 200, height: 200))
            let window = NSWindow(contentRect: canvas.frame, styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = canvas; defer { window.close() }
            canvas.model = model; canvas.fitImage()
            // Use an explicitly tagged target. cacheDisplay's generic-RGB
            // bitmap metadata varies with the display attached to the Mac.
            let context = try XCTUnwrap(CGContext(data: nil, width: 200, height: 200, bitsPerComponent: 8, bytesPerRow: 800,
                space: try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB)), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            context.translateBy(x: 0, y: 200); context.scaleBy(x: 1, y: -1)
            NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
            canvas.draw(canvas.bounds); NSGraphicsContext.restoreGraphicsState()
            let painted = try PhotoPixels(XCTUnwrap(context.makeImage())), center = (100 * 200 + 100) * 4
            XCTAssertEqual(Int(painted.rgba[center]), 184, accuracy: 3)
            XCTAssertEqual(Int(painted.rgba[center + 1]), 60, accuracy: 3)
            XCTAssertEqual(model.document?.imageWidth, 12); XCTAssertEqual(model.document?.imageHeight, 8)
        }
    }
    func testCraterSettingsBindingsPersistAcrossNativeAndLegacyProjects() async throws {
        try await MainActor.run {
            let model = EditorModel(); model.document = try ProjectIO.read(Catalog.demoURL).document
            model.document?.imageWidth = 1600; model.document?.imageHeight = 1450
            for (key, value) in [("min_radius", 12.0), ("max_radius", 230.0), ("sensitivity", 70.0), ("max_candidates", 140.0)] {
                model.craterNumber(key, fallback: 0).wrappedValue = value
            }
            model.craterViewport.wrappedValue = true
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: directory) }
            let document = try XCTUnwrap(model.document)
            let native = directory.appendingPathComponent("settings.moonswift"), legacy = directory.appendingPathComponent("settings.moonlabel")
            try ProjectIO.write(document, to: native); try ProjectCompatibility.writeLegacy(document, to: legacy)
            for url in [native, legacy] {
                let reopened = EditorModel(); reopened.document = try ProjectIO.read(url).document
                XCTAssertEqual(reopened.craterNumber("min_radius", fallback: 8).wrappedValue, 12)
                XCTAssertEqual(reopened.craterNumber("max_radius", fallback: 180).wrappedValue, 230)
                XCTAssertEqual(reopened.craterNumber("sensitivity", fallback: 50).wrappedValue, 70)
                XCTAssertEqual(reopened.craterNumber("max_candidates", fallback: 80).wrappedValue, 140)
                XCTAssertTrue(reopened.craterViewport.wrappedValue)
            }
            model.document = MoonDocument(imagePath: "new-photo.png")
            XCTAssertEqual(model.craterNumber("max_candidates", fallback: 80).wrappedValue, 80)
            XCTAssertFalse(model.craterViewport.wrappedValue)
        }
    }
    func testRenderedMapMaskKeepsTheDarkTopAboveTheBrightBottom() throws {
        let width = 128, height = 192
        var rgba = [UInt8](repeating: 255, count: width * height * 4)
        for y in 0..<height { for x in 0..<width {
            let value: UInt8 = y < 90 || (x - 96) * (x - 96) + (y - 138) * (y - 138) < 100 ? 0 : 160
            for channel in 0..<3 { rgba[(y * width + x) * 4 + channel] = value }
        } }
        let photo = PhotoPixels(width: width, height: height, rgba: rgba)
        var document = MoonDocument(imagePath: "asymmetric-lighting.png")
        document.imageWidth = width; document.imageHeight = height
        document.changeStyle { $0.set("elevation_enabled", true); $0.set("elevation_opacity", 1.0); $0.set("map_light_mask", true) }
        var scene = AnnotationScene()
        scene.layers.lightness = try PhotoLightness(photo: photo, calibration: nil)
        scene.layers.elevation = PhotoPixels(width: width, height: height, rgba: Array(repeating: [UInt8(0),255,0,255], count: width * height).flatMap { $0 })
        scene.layers.grid = [MapLine([PixelPoint(10, 24), PixelPoint(118, 24)])]
        scene.layers.contours = [MapLine([PixelPoint(10, 40), PixelPoint(118, 40)])]
        let output = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".png")
        defer { try? FileManager.default.removeItem(at: output) }
        try PhotoIO.png(image: photo.cgImage, document: document, scene: scene, to: output)
        let firstFrame = try PhotoPixels.load(output)
        XCTAssertLessThan(firstFrame.rgba[(24 * width + 64) * 4 + 1], 5)
        XCTAssertGreaterThan(firstFrame.rgba[(140 * width + 64) * 4 + 1], 240)
        let coverage = try XCTUnwrap(scene.layers.lightness).coverage(threshold: nil)
        XCTAssertLessThan(coverage.rgba[(24 * width + 64) * 4 + 3], 5)
        XCTAssertGreaterThan(coverage.rgba[(140 * width + 64) * 4 + 3], 240)
        document.changeStyle { $0.set("map_light_mask", false) }
        try PhotoIO.png(image: photo.cgImage, document: document, scene: scene, to: output)
        let unmasked = try PhotoPixels.load(output)
        XCTAssertGreaterThan(unmasked.rgba[(24 * width + 64) * 4 + 1], 240)
        document.changeStyle { $0.set("map_light_mask", true) }
        try PhotoIO.png(image: photo.cgImage, document: document, scene: scene, to: output)
        let rendered = try PhotoPixels.load(output)
        let dark = (24 * width + 64) * 4, bright = (140 * width + 64) * 4
        XCTAssertLessThan(rendered.rgba[dark + 1], 5, "The photograph's black upper region must not receive the map overlay")
        XCTAssertGreaterThan(rendered.rgba[bright + 1], 240, "The lower illuminated terrain must receive the overlay")
        XCTAssertLessThan(rendered.rgba[bright], 5)
        XCTAssertGreaterThan(rendered.rgba[(138 * width + 96) * 4 + 1], 240, "Keep the dark floor enclosed by an illuminated crater rim")
        let svg = output.deletingPathExtension().appendingPathExtension("svg")
        defer { try? FileManager.default.removeItem(at: svg) }
        try AnnotationRenderer.svg(image: photo.cgImage, document: document, scene: scene, to: svg)
        let vector = try XCTUnwrap(NSImage(contentsOf: svg)?.cgImage(forProposedRect: nil, context: nil, hints: nil))
        let svgPixels = try PhotoPixels(vector)
        // AppKit may rasterize SVG at the Retina backing scale.
        func svgGreen(_ x: Int, _ y: Int) -> UInt8 {
            let sx = x * svgPixels.width / width, sy = y * svgPixels.height / height
            return svgPixels.rgba[(sy * svgPixels.width + sx) * 4 + 1]
        }
        XCTAssertLessThan(svgGreen(64, 24), 5)
        XCTAssertGreaterThan(svgGreen(64, 140), 240)
        let sceneID = scene.id, light = scene.layers.lightness
        document.changeStyle { $0.set("map_light_threshold", 220.0) }
        try PhotoIO.png(image: photo.cgImage, document: document, scene: scene, to: output)
        XCTAssertEqual(try PhotoPixels.load(output).rgba[bright + 1], 160)
        document.changeStyle { $0.set("map_light_threshold", "auto") }
        try PhotoIO.png(image: photo.cgImage, document: document, scene: scene, to: output)
        XCTAssertGreaterThan(try PhotoPixels.load(output).rgba[bright + 1], 240)
        XCTAssertEqual(scene.id, sceneID); XCTAssertTrue(scene.layers.lightness === light)
        XCTAssertEqual(photo.rgba, rgba)
    }
    func testFocusingALegacyFontPercentageDoesNotClampItOnBlur() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let storedPercentages: [Double?] = [0.02, 12, nil, 1.234567]
            for stored in storedPercentages {
                let percent = stored ?? 80
                let model = EditorModel()
                var document = try ProjectIO.read(Catalog.demoURL).document
                document.imageWidth = 100; document.imageHeight = 100; document.settings.fontSize = 80
                document.changeStyle { $0.values["font_percent"] = stored.map(JSONValue.number) }
                model.document = document; model.appliedDocument = document; model.panelTab = 1; model.markClean()
                let host = NSHostingView(rootView: NativeInspector(model: model))
                let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 420, height: 1100), styleMask: [.titled], backing: .buffered, defer: false)
                window.isReleasedWhenClosed = false; window.contentView = host; defer { window.close() }; host.layoutSubtreeIfNeeded()
                @MainActor func fields(_ view: NSView) -> [NSTextField] { (view as? NSTextField).map { [$0] } ?? view.subviews.flatMap(fields) }
                let field = try XCTUnwrap(fields(host).first { $0.isEditable && $0.stringValue == SafeNumberField.formatted(percent) })
                XCTAssertTrue(window.makeFirstResponder(field)); XCTAssertNotNil(field.currentEditor())
                XCTAssertTrue(window.makeFirstResponder(nil))
                XCTAssertEqual(model.document, document, "Focusing a pixel-size legacy project must also preserve an absent font_percent")
                XCTAssertEqual(field.stringValue, SafeNumberField.formatted(percent))
                XCTAssertFalse(model.dirty); XCTAssertFalse(model.canUndo)
                if percent > 8 {
                    XCTAssertTrue(window.makeFirstResponder(field))
                    let editor = try XCTUnwrap(field.currentEditor() as? NSTextView)
                    let coordinator = try XCTUnwrap(field.delegate as? SafeNumberField.Coordinator)
                    XCTAssertTrue(coordinator.control(field, textView: editor, doCommandBy: #selector(NSResponder.moveDown(_:))))
                    host.layoutSubtreeIfNeeded()
                    XCTAssertTrue(coordinator.control(field, textView: editor, doCommandBy: #selector(NSResponder.moveUp(_:))))
                    XCTAssertTrue(window.makeFirstResponder(nil))
                    XCTAssertEqual(model.document?.style.number("font_percent", 0) ?? 0, percent, accuracy: 0.000001)
                }
            }
        }
    }
    func testFocusingTheAutomaticThresholdDoesNotSwitchItToManualOnBlur() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            var document = try ProjectIO.read(Catalog.demoURL).document
            document.changeStyle { $0.set("map_light_threshold", "auto"); $0.set("font_percent", 2.5) }
            model.document = document; model.appliedDocument = document; model.panelTab = 1; model.markClean()
            let host = NSHostingView(rootView: NativeInspector(model: model))
            let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 420, height: 1100), styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = host; defer { window.close() }; host.layoutSubtreeIfNeeded()
            @MainActor func fields(_ view: NSView) -> [NSTextField] { (view as? NSTextField).map { [$0] } ?? view.subviews.flatMap(fields) }
            let field = try XCTUnwrap(fields(host).first { $0.isEditable && $0.stringValue == "1" })
            XCTAssertTrue(window.makeFirstResponder(field)); XCTAssertNotNil(field.currentEditor())
            XCTAssertTrue(window.makeFirstResponder(nil))
            XCTAssertNil(model.document?.style.threshold)
            XCTAssertEqual(model.document, document)
            XCTAssertFalse(model.dirty); XCTAssertFalse(model.canUndo)
            XCTAssertTrue(window.makeFirstResponder(field))
            let editor = try XCTUnwrap(field.currentEditor() as? NSTextView)
            let coordinator = try XCTUnwrap(field.delegate as? SafeNumberField.Coordinator)
            XCTAssertTrue(coordinator.control(field, textView: editor, doCommandBy: #selector(NSResponder.moveUp(_:))))
            XCTAssertEqual(model.document?.style.threshold, 2, "An explicit arrow-key edit still selects a manual threshold")
            XCTAssertTrue(window.makeFirstResponder(nil))
        }
    }
    func testThresholdEditsStayLiveWhileLandingSitesAwaitRegeneration() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            var document = try ProjectIO.read(Catalog.demoURL).document
            document.imageWidth = 80; document.imageHeight = 60
            document.settings.maximumLabels = 200
            document.changeStyle { $0.set("map_light_threshold", 21.0); $0.set("font_percent", 1.8) }
            model.document = document; model.appliedDocument = document; model.panelTab = 1
            let host = NSHostingView(rootView: NativeInspector(model: model))
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 420, height: 1100), styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = host; defer { window.close() }; host.layoutSubtreeIfNeeded()
            func fields(_ view: NSView) -> [NSTextField] { (view as? NSTextField).map { [$0] } ?? view.subviews.flatMap(fields) }
            let numeric = fields(host).filter(\.isEditable)
            let font = try XCTUnwrap(numeric.first { $0.stringValue == "1.8" }), count = try XCTUnwrap(numeric.first { $0.stringValue == "200" })
            let fontBox = host.convert(font.bounds, from: font), countBox = host.convert(count.bounds, from: count)
            XCTAssertEqual(fontBox.minX, countBox.minX, accuracy: 0.5)
            XCTAssertEqual(fontBox.maxX, countBox.maxX, accuracy: 0.5, "Units must not shorten one parameter field")
            let field = try XCTUnwrap(fields(host).first { $0.isEditable && $0.stringValue == "21" })
            XCTAssertTrue(window.makeFirstResponder(field))
            let editor = try XCTUnwrap(field.currentEditor() as? NSTextView)
            editor.selectAll(nil); editor.insertText("5", replacementRange: editor.selectedRange())
            XCTAssertEqual(model.document?.style.threshold, 5, "Valid typing must immediately update the slider and preview")
            window.makeFirstResponder(nil)
            model.edit { $0.changeStyle { $0.set("show_landing_sites", true) } }
            XCTAssertTrue(model.hasPendingStyle)
            XCTAssertEqual(model.document?.style.threshold, 5, "Landing sites must not change the threshold")
            XCTAssertEqual(model.displayDocument?.style.threshold, 5, "Pending layout changes must not freeze live threshold updates")
            model.edit { $0.changeStyle { $0.set("map_light_threshold", 17.0) } }
            XCTAssertEqual(model.displayDocument?.style.threshold, 17)
            let stepper = try XCTUnwrap(field.subviews.compactMap { $0 as? NSStepper }.first)
            XCTAssertEqual(stepper.frame.midY, field.bounds.midY, accuracy: 0.5, "Arrow control must share the field's vertical center")
            XCTAssertEqual(stepper.bounds.height, try XCTUnwrap(stepper.cell).cellSize.height, accuracy: 0.5, "Use the native arrow height so its artwork is centered")
            XCTAssertEqual(stepper.increment, 1)
            stepper.doubleValue = 18
            XCTAssertTrue(NSApp.sendAction(try XCTUnwrap(stepper.action), to: stepper.target, from: stepper))
            XCTAssertEqual(model.document?.style.threshold, 18)
            XCTAssertEqual(model.displayDocument?.style.threshold, 18)
        }
    }
    func testDateDraftDoesNotRollInvalidFebruaryIntoMarch() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(); model.referenceState.utc = "2026-01-31T12:34:56Z"
            let host = NSHostingView(rootView: NativeInspector(model: model))
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 420, height: 740), styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = host; defer { window.close() }; host.layoutSubtreeIfNeeded()
            func fields(_ view: NSView) -> [NSTextField] { (view as? NSTextField).map { [$0] } ?? view.subviews.flatMap(fields) }
            let all = fields(host).filter(\.isEditable), month = try XCTUnwrap(all.first { $0.stringValue == "01" }), day = try XCTUnwrap(all.first { $0.stringValue == "31" })
            XCTAssertTrue(window.makeFirstResponder(month))
            let editor = try XCTUnwrap(month.currentEditor() as? NSTextView); editor.selectAll(nil); editor.insertText("02", replacementRange: editor.selectedRange())
            XCTAssertFalse(model.captureDateValid); XCTAssertEqual(model.workingState.utc, "2026-01-31T12:34:56Z")
            let next = try XCTUnwrap(day.currentEditor() as? NSTextView); next.insertText("28", replacementRange: next.selectedRange())
            XCTAssertTrue(model.captureDateValid); XCTAssertEqual(model.workingState.utc, "2026-02-28T12:34:56Z")
        }
    }
    func testOverviewCardUsesReadableSharedVectorArtwork() async throws {
        try await MainActor.run {
        _ = NSApplication.shared
        let opened = try ProjectIO.read(Catalog.demoURL).document
        var document = opened; document.imageWidth = 1600; document.imageHeight = 1450
        let model = try XCTUnwrap(OverviewBuilder.build(document: document, task: ComputeTask()))
        let markup = try OverviewCard.markup(model, style: "standard")
        XCTAssertTrue(markup.contains("fill=\"#d7dfdd\""))
        XCTAssertTrue(markup.contains("rx=\"12\"")); XCTAssertFalse(markup.contains(">Earth<"))
        let image = try OverviewCard.image(model, style: "standard", sceneID: UUID())
        XCTAssertEqual(image.size, NSSize(width: 320, height: 366))
        XCTAssertNotNil(image.cgImage(forProposedRect: nil, context: nil, hints: nil))
        }
    }
    func testOpeningPhotoRetainsTheCaptureConditionsAlreadyEntered() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("0708.png")
        let output = try XCTUnwrap(CGImageDestinationCreateWithURL(file as CFURL, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(output, try fixture(), nil); XCTAssertTrue(CGImageDestinationFinalize(output))
        let utc = "2026-07-08T21:32:56Z"
        let model = await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(); model.panelTab = 2; model.referenceState.utc = utc; model.referenceState.latitude = 31; model.referenceState.longitude = 121
            model.requestOpen(file); return model
        }
        for _ in 0..<200 {
            if await MainActor.run(body: { model.document != nil && !model.busy }) { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        await MainActor.run {
            XCTAssertEqual(model.document?.state.utc, utc, "Opening a photo must not silently replace the entered UTC with today")
            XCTAssertEqual(model.document?.state.latitude, 31); XCTAssertEqual(model.document?.state.longitude, 121)
            XCTAssertEqual(model.panelTab, 0, "A new photograph must start on the calibration page")
        }
    }
    func testCaptureDigitsAdvanceThroughTheActualInspector() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(); model.referenceState.utc = "2025-06-15T12:34:56Z"
            let host = NSHostingView(rootView: NativeInspector(model: model))
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 420, height: 740), styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false; window.contentView = host
            defer { window.close() }; host.layoutSubtreeIfNeeded()
            func fields(_ view: NSView) -> [NSTextField] {
                (view as? NSTextField).map { [$0] } ?? view.subviews.flatMap(fields)
            }
            let all = fields(host).filter(\.isEditable)
            let year = try XCTUnwrap(all.first { $0.stringValue == "2025" })
            let month = try XCTUnwrap(all.first { $0.stringValue == "6" || $0.stringValue == "06" })
            let day = try XCTUnwrap(all.first { $0.stringValue == "15" })
            XCTAssertTrue(window.makeFirstResponder(month))
            let monthEditor = try XCTUnwrap(month.currentEditor() as? NSTextView)
            monthEditor.layoutManager?.ensureLayout(for: try XCTUnwrap(monthEditor.textContainer))
            let used = try XCTUnwrap(monthEditor.layoutManager?.usedRect(for: try XCTUnwrap(monthEditor.textContainer)))
            let textRect = month.convert(used.offsetBy(dx: monthEditor.textContainerOrigin.x, dy: monthEditor.textContainerOrigin.y), from: monthEditor)
            XCTAssertEqual(textRect.midY, month.bounds.midY, accuracy: 1.5, "Editing text must stay vertically centered")
            XCTAssertTrue(window.makeFirstResponder(year))
            let editor = try XCTUnwrap(year.currentEditor() as? NSTextView)
            editor.setSelectedRange(NSRange(location: 0, length: editor.string.utf16.count))
            editor.insertText("2026", replacementRange: editor.selectedRange())
            XCTAssertTrue((window.firstResponder as? NSTextView)?.delegate === month, "A complete year must advance to the month field")
            guard let monthEditor = month.currentEditor() as? NSTextView else { return }
            monthEditor.insertText("07", replacementRange: monthEditor.selectedRange())
            XCTAssertTrue((window.firstResponder as? NSTextView)?.delegate === day, "A complete month must advance to the day field")
            let dayEditor = try XCTUnwrap(day.currentEditor() as? NSTextView)
            dayEditor.insertText("08", replacementRange: dayEditor.selectedRange())
            XCTAssertEqual(model.workingState.utc, "2026-07-08T12:34:56Z")
        }
    }
    func testPreviewZoomDoesNotPaintOverThePanel() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            var rgba = [UInt8](repeating: 0, count: 128 * 128 * 4)
            for index in stride(from: 3, to: rgba.count, by: 4) { rgba[index] = 255 }
            model.reference = TerrainReference(image: PhotoPixels(width: 128, height: 128, rgba: rgba), matrix: [[60, 0, 64], [0, 60, 64]], validFraction: 1, resolutionKM: 1.9)
            model.showReferencePreview(); defer { model.closeReferencePreview() }
            let window = try XCTUnwrap(model.referenceWindow?.window), root = try XCTUnwrap(window.contentView)
            root.layoutSubtreeIfNeeded(); window.displayIfNeeded()
            func findCanvas(_ view: NSView) -> PhotoViewport? {
                if let canvas = view as? PhotoViewport { return canvas }
                return view.subviews.compactMap(findCanvas).first
            }
            let canvas = try XCTUnwrap(findCanvas(root))
            func corner() throws -> NSColor {
                let bitmap = try XCTUnwrap(root.bitmapImageRepForCachingDisplay(in: root.bounds))
                root.cacheDisplay(in: root.bounds, to: bitmap)
                return try XCTUnwrap(bitmap.colorAt(x: 2, y: 2)?.usingColorSpace(.sRGB))
            }
            let before = try corner(); XCTAssertGreaterThan(before.blueComponent, 0.05)
            canvas.zoom(to: 16, at: CGPoint(x: canvas.bounds.midX, y: canvas.bounds.midY))
            let after = try corner()
            XCTAssertEqual(after.redComponent, before.redComponent, accuracy: 0.01)
            XCTAssertEqual(after.greenComponent, before.greenComponent, accuracy: 0.01)
            XCTAssertEqual(after.blueComponent, before.blueComponent, accuracy: 0.01)
        }
    }
    func testReferencePreviewStartsWithUsableCanvasArea() async throws {
        await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel(), pixels = PhotoPixels(width: 128, height: 128, rgba: [UInt8](repeating: 255, count: 128 * 128 * 4))
            model.reference = TerrainReference(image: pixels, matrix: [[60, 0, 64], [0, 60, 64]], validFraction: 1, resolutionKM: 1.9)
            model.showReferencePreview()
            defer { model.closeReferencePreview() }
            let window = model.referenceWindow?.window
            window?.contentView?.layoutSubtreeIfNeeded()
            XCTAssertGreaterThanOrEqual(window?.contentLayoutRect.width ?? 0, 550)
            XCTAssertGreaterThanOrEqual(window?.contentLayoutRect.height ?? 0, 480)
        }
    }
    func testTerrainSearchSynchronizesRenderedCenterAndInvalidatesPreview() async throws {
        try await MainActor.run {
            let model = EditorModel(), feature = try XCTUnwrap(model.features.first { $0.name == "Tycho" })
            XCTAssertTrue(model.terrainSourceDescription.contains("内置"))
            model.document = try ProjectIO.read(Catalog.demoURL).document
            let calibration = model.document?.calibration
            model.referenceGeometry = calibration?.geometry
            model.searchTerrainCenter("第谷")
            XCTAssertEqual(model.workingState.terrainSettings.string("center_id"), feature.id)
            XCTAssertEqual(model.workingState.terrainSettings.number("center_lat", 999), feature.latitude)
            XCTAssertEqual(model.workingState.terrainSettings.number("center_lon", 999), feature.longitude)
            XCTAssertNil(model.referenceGeometry)
            XCTAssertEqual(model.document?.calibration, calibration)
        }
    }
    func testCurvedCaptionSurvivesLayoutExportAndPinnedRegeneration() throws {
        var document = try ProjectIO.read(Catalog.demoURL).document
        document.imageWidth = 1600; document.imageHeight = 1450; document.settings.fontSize = 22
        document.settings.kinds = ["Mons, montes"]; document.settings.minimumDiameter = 0
        document.changeStyle { $0.set("follow_feature_paths", true); $0.set("illuminated_only", false) }
        document.state.legacy["labels"] = .object([:]); document.annotations = []
        let feature = try XCTUnwrap(Catalog.load().first { $0.name == "Montes Haemus" })
        let photo = PhotoPixels(width: 1600, height: 1450, rgba: [UInt8](repeating: 180, count: 1600 * 1450 * 4))
        func build(_ input: MoonDocument) throws -> (MoonDocument, AnnotationScene) {
            try AnnotationSceneBuilder.build(document: input, photo: photo, features: [feature], dem: nil, task: ComputeTask(),
                measure: AnnotationRenderer.measure, captionBounds: AnnotationRenderer.placementBounds, configureCaption: AnnotationRenderer.configureCaption)
        }
        let rendered = try build(document), annotation = try XCTUnwrap(rendered.0.annotations.first)
        XCTAssertTrue(AnnotationSceneBuilder.visible(annotation, document: rendered.0, scene: rendered.1))
        let origin = try XCTUnwrap(annotation.visual?.pathOrigin)
        XCTAssertEqual(annotation.position.x, origin.x, accuracy: 0.02); XCTAssertEqual(annotation.position.y, origin.y, accuracy: 0.02)
        XCTAssertGreaterThan(annotation.visual?.pathGlyphs?.count ?? 0, 5)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let svg = directory.appendingPathComponent("curved.svg")
        try AnnotationRenderer.svg(image: photo.cgImage, document: rendered.0, scene: rendered.1, to: svg)
        let text = try String(contentsOf: svg, encoding: .utf8)
        XCTAssertTrue(text.contains("穆")); XCTAssertTrue(text.contains("rotate("))
        var moved = rendered.0
        moved.annotations[0].position = PixelPoint(origin.x + 40, origin.y + 25); moved.annotations[0].positionEdited = true; moved.annotations[0].automatic = false
        let file = directory.appendingPathComponent("pinned.moonswift"); try ProjectIO.write(moved, to: file)
        let regenerated = try build(ProjectIO.read(file).document)
        XCTAssertEqual(regenerated.0.annotations.first?.position, moved.annotations[0].position)
        XCTAssertEqual(regenerated.0.annotations.first?.visual?.pathGlyphs, moved.annotations[0].visual?.pathGlyphs)
    }
    func testDisabledReferenceRowsKeepTheCorrectResidualAndSuspect() async throws {
        try await MainActor.run {
            let model = EditorModel(); var document = MoonDocument(imagePath: "test.png")
            document.state.anchors = (0..<4).map { ControlPoint(id: "\($0)", point: PixelPoint(Double($0), 0), enabled: $0 != 1) }
            model.document = document
            model.report = CalibrationReport(matrix: [[1, 0, 0], [0, 1, 0]], rms: 2, residuals: [1, 2, 3], checkErrors: [], suspect: 1)
            XCTAssertEqual(model.referenceResidual(at: 0), 1); XCTAssertNil(model.referenceResidual(at: 1))
            XCTAssertEqual(model.referenceResidual(at: 2), 2); XCTAssertEqual(model.referenceResidual(at: 3), 3)
            XCTAssertEqual(model.suspectAnchorIndex, 2)
        }
    }
    struct CaptionOracle: Decodable {
        var id: String, text: String, size: Double, origin: [Double]?, glyphs: [[JSONValue]], scales: [Double], advances: [Double]
    }
    func testPreparedLandformCaptionsMatchPythonAndKeepUserPins() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "caption-0121-oracle", withExtension: "json"))
        let oracle = try JSONDecoder().decode([CaptionOracle].self, from: Data(contentsOf: url))
        var document = try ProjectIO.read(Catalog.demoURL).document; document.imageWidth = 1600; document.imageHeight = 1450
        document.settings.fontSize = 22; document.changeStyle { $0.set("follow_feature_paths", true) }
        let features = try Catalog.load()
        for item in oracle {
            let feature = try XCTUnwrap(features.first { $0.id == item.id })
            var annotation = Annotation(featureID: feature.id, text: item.text, anchor: PixelPoint(0, 0), position: PixelPoint(0, 0), automatic: true)
            annotation.visual = AnnotationVisual(); annotation.visual?.fontScale = LabelSizing.size(feature, document: document) / document.settings.fontSize
            let configured = SceneRenderer.configureCaption(annotation, feature: feature, document: document)
            guard let expected = item.origin else { XCTAssertNil(configured.visual?.pathOrigin); continue }
            let origin = try XCTUnwrap(configured.visual?.pathOrigin), glyphs = try XCTUnwrap(configured.visual?.pathGlyphs)
            XCTAssertEqual(origin.x, expected[0], accuracy: 0.02); XCTAssertEqual(origin.y, expected[1], accuracy: 0.02)
            XCTAssertEqual(document.settings.fontSize * (configured.visual?.fontScale ?? 1), item.size)
            XCTAssertEqual(glyphs.count, item.glyphs.count)
            for (index, glyph) in glyphs.enumerated() where index < item.glyphs.count {
                let target = item.glyphs[index]
                XCTAssertEqual(glyph.text, target[0].string)
                XCTAssertEqual(glyph.point.x, try XCTUnwrap(target[1].number), accuracy: 0.02); XCTAssertEqual(glyph.point.y, try XCTUnwrap(target[2].number), accuracy: 0.02)
                XCTAssertEqual(glyph.angle, try XCTUnwrap(target[3].number), accuracy: 0.02)
                XCTAssertEqual(glyph.scale, item.scales[index], accuracy: 1e-8); XCTAssertEqual(glyph.advance, item.advances[index], accuracy: 0.02)
            }
            let before = SceneRenderer.labelBounds(configured, document: document)
            var moved = configured; moved.position = PixelPoint(300, 400)
            let after = SceneRenderer.labelBounds(moved, document: document)
            XCTAssertEqual(after.minX - before.minX, 300, accuracy: 1e-8); XCTAssertEqual(after.minY - before.minY, 400, accuracy: 1e-8)
        }
    }
    func testCaptureEditsInvalidateOldRegistrationAndDisplay() async throws {
        try await MainActor.run {
            let opened = try ProjectIO.read(Catalog.demoURL).document
            for field in ["time", "site"] {
                let model = EditorModel(); model.document = opened; model.appliedDocument = opened; model.scene = AnnotationScene()
                if field == "time" { model.changeCaptureTime(hour: 13, minute: 0, second: 0) }
                else if field == "site" { model.editState { $0.latitude = 31; $0.longitude = 121 } }
                XCTAssertNil(model.document?.calibration, field)
                XCTAssertNil(model.displayDocument?.calibration, field)
                XCTAssertNil(model.scene, field)
                XCTAssertTrue(model.document?.annotations.isEmpty ?? false, field)
                XCTAssertEqual(model.document?.state.anchors, opened.state.anchors, field)
                model.undo()
                XCTAssertEqual(model.document?.calibration, opened.calibration)
                XCTAssertEqual(model.displayDocument?.calibration, opened.calibration)
                model.redo(); XCTAssertNil(model.displayDocument?.calibration)
            }
            let model = EditorModel(); model.document = opened; model.appliedDocument = opened; model.scene = AnnotationScene()
            model.editState { $0.terrainSettings.set("width_km", 500) }
            XCTAssertEqual(model.document?.calibration, opened.calibration, "Rendering parameters must not invalidate the photo pose")
            XCTAssertNotNil(model.scene)
            model.stateString(\.captureMode).wrappedValue = "afocal"
            XCTAssertEqual(model.document?.calibration, opened.calibration, "Capture mode is a search policy; existing labels must survive")
        }
    }
    func testStandardCaptionSpacingMatchesQt0121() throws {
        var document = MoonDocument(imagePath: "font.png"); document.settings.fontSize = 14
        let caption = Annotation(text: "查理士 · Challis", anchor: PixelPoint(0, 0), position: PixelPoint(0, 0))
        let box = SceneRenderer.captionPath(caption, document: document).boundingBoxOfPath
        // Strict Qt/PingFang SC Semibold oracles at 14 px for both macOS
        // providers: the variable UI face and the installed static face.
        let face = SceneRenderer.font(document, size: 14) as CTFont
        let variable = (CTFontCopyVariation(face) as? [NSNumber: NSNumber])?.isEmpty == false
        let expected = variable ? [0.5063507866806886, 2.486047438891557, 106.88378221425258, 12.637751161315439]
                                : [0.518, 2.4779999999999998, 101.958875, 12.614]
        for (actual, value) in zip([box.minX, box.minY, box.width, box.height], expected) {
            XCTAssertEqual(actual, value, accuracy: 0.001)
        }
        var featureCaption = caption; featureCaption.featureID = try XCTUnwrap(Catalog.load().first { $0.name == "Challis" }).id
        document.imageWidth = 80; document.imageHeight = 60; document.annotations = [featureCaption]
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".svg")
        defer { try? FileManager.default.removeItem(at: url) }
        try SceneRenderer.svg(image: fixture(), document: document, scene: nil, to: url)
        let svg = try String(contentsOf: url, encoding: .utf8)
        let positions = variable ? ["14.3125", "100.359375"] : ["14.0", "95.546875"]
        for position in positions { XCTAssertTrue(svg.contains("tspan x=\"\(position)\"")) }
    }
    func testLegendGeometryAndContinuousSVGRampMatch0121() throws {
        var document = MoonDocument(imagePath: "fixture.png"); document.imageWidth = 1600; document.imageHeight = 1450
        XCTAssertEqual(SceneRenderer.legendRect(document), CGRect(x: 29, y: 1334, width: 435, height: 87))
        document.changeStyle { $0.set("elevation_enabled", true); $0.values["legend_position"] = .array([.number(5000), .number(-1)]) }
        XCTAssertEqual(SceneRenderer.legendRect(document), CGRect(x: 1165, y: 0, width: 435, height: 87))
        let photo = try fixture(); var scene = AnnotationScene(); scene.layers.elevation = try PhotoPixels(photo)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".svg")
        defer { try? FileManager.default.removeItem(at: url) }
        try SceneRenderer.svg(image: photo, document: document, scene: scene, to: url)
        let svg = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(svg.contains("linearGradient id=\"elevation-ramp\"")); XCTAssertTrue(svg.contains("offset=\"0.5\" stop-color=\"#cbc89a\""))
        XCTAssertTrue(svg.contains("LOLA · km (R = 1737.4 km)")); XCTAssertTrue(svg.contains("text-anchor=\"end\">≥ +9"))
    }
    func testPathCaptionsUseSeparateChineseAndEnglishRows() throws {
        let feature = try XCTUnwrap(Catalog.load().first { $0.name == "Copernicus" })
        var document = MoonDocument(imagePath: "fixture.png"); document.imageWidth = 800; document.imageHeight = 600; document.settings.fontSize = 30
        var annotation = Annotation(featureID: feature.id, text: feature.caption(.bilingual), anchor: PixelPoint(50, 50), position: PixelPoint(0, 0), automatic: true)
        annotation.visual = AnnotationVisual(); annotation.visual?.baseline = [PixelPoint(20, 50), PixelPoint(700, 50)]
        document.annotations = [annotation]
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".svg")
        defer { try? FileManager.default.removeItem(at: url) }
        try SceneRenderer.svg(image: fixture(), document: document, scene: nil, to: url)
        let svg = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(svg.contains("font-size=\"25.0\"")); XCTAssertFalse(svg.contains(" · "))
        XCTAssertTrue(svg.contains("y=\"43.4\"")); XCTAssertTrue(svg.contains("y=\"79.4\""))
    }
    func testOverlappingCJKStrokesAreFilledAfterTheWholeHalo() throws {
        let context = try XCTUnwrap(CGContext(data: nil, width: 220, height: 180, bitsPerComponent: 8, bytesPerRow: 880, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.setFillColor(CGColor(gray: 0.4, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: 220, height: 180))
        let photo = try XCTUnwrap(context.makeImage())
        var document = MoonDocument(imagePath: "glyph.png"); document.imageWidth = 220; document.imageHeight = 180
        document.settings.fontSize = 116; document.settings.color = "#ffffff"; document.settings.showLeaders = false
        let annotation = Annotation(text: "露", anchor: PixelPoint(20, 20), position: PixelPoint(20, 20)); document.annotations = [annotation]
        let mask = try XCTUnwrap(CGContext(data: nil, width: 220, height: 180, bitsPerComponent: 8, bytesPerRow: 880, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        mask.translateBy(x: 0, y: 180); mask.scaleBy(x: 1, y: -1); mask.setFillColor(CGColor(gray: 1, alpha: 1)); mask.addPath(SceneRenderer.captionPath(annotation, document: document)); mask.fillPath()
        let expected = try pixels(XCTUnwrap(mask.makeImage()))
        context.translateBy(x: 0, y: 180); context.scaleBy(x: 1, y: -1); SceneRenderer.draw(image: photo, document: document, scene: nil, context: context)
        let actual = try pixels(XCTUnwrap(context.makeImage()))
        var interior = 0
        for i in stride(from: 0, to: expected.count, by: 4) where expected[i + 3] > 254 {
            interior += 1; XCTAssertGreaterThan(actual[i], 249, "A halo must not cut through an overlapping Chinese stroke")
        }
        XCTAssertGreaterThan(interior, 1500)
    }
    func testLiveThresholdChangesVisibilityWithoutChangingSceneOrGeometry() throws {
        let image = try fixture(), photo = try PhotoPixels(image)
        var document = MoonDocument(imagePath: "fixture.png"); document.imageWidth = 80; document.imageHeight = 60
        document.settings.fontSize = 12; document.style.set("illuminated_only", true)
        var annotation = Annotation(text: "Visible & <editable>", anchor: PixelPoint(5, 20), position: PixelPoint(10, 20))
        annotation.visual = AnnotationVisual(); annotation.visual?.lightness = 100; document.annotations = [annotation]
        let light = try PhotoLightness(photo: photo, calibration: nil)
        var scene = AnnotationScene(); scene.layers.lightness = light
        let sceneID = scene.id, original = photo.rgba
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: directory) }
        let svg = directory.appendingPathComponent("visible.svg")
        document.style.set("map_light_threshold", 50.0)
        try SceneRenderer.svg(image: image, document: document, scene: scene, to: svg)
        XCTAssertTrue(try String(contentsOf: svg, encoding: .utf8).contains("Visible &amp; &lt;editable&gt;"))
        document.style.set("map_light_threshold", 150.0)
        try SceneRenderer.svg(image: image, document: document, scene: scene, to: svg)
        XCTAssertFalse(try String(contentsOf: svg, encoding: .utf8).contains("Visible &amp; &lt;editable&gt;"))
        let png = directory.appendingPathComponent("hidden.png")
        try PhotoIO.png(image: image, document: document, scene: scene, to: png)
        XCTAssertEqual(try pixels(PhotoIO.load(png)), try pixels(image))
        XCTAssertEqual(scene.id, sceneID); XCTAssertTrue(scene.layers.lightness === light); XCTAssertEqual(photo.rgba, original)
    }
    func testInterfaceTemplatesAndTraditionalSearchAreAvailable() async throws {
        XCTAssertEqual(InterfaceText.translate("已应用 · 32 个可见地名", language: "English"), "Applied · 32 visible labels")
        XCTAssertEqual(InterfaceText.translate("高程配色", language: "繁體中文"), "高程配色")
        try await MainActor.run {
            let model = EditorModel(); model.catalogQuery = "阿爾卑斯"
            XCTAssertTrue(model.searchResults.contains { $0.name == "Vallis Alpes" })
        }
    }
    func testPNGKeepsOriginalSizeOrientationAndHiddenLabelsOut() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let image = try fixture()
        var document = MoonDocument(imagePath: "fixture.png")
        document.imageWidth = image.width; document.imageHeight = image.height; document.settings.fontSize = 12
        let plain = directory.appendingPathComponent("plain.png")
        try PhotoIO.png(image: image, document: document, to: plain)
        let decoded = try PhotoIO.load(plain)
        XCTAssertEqual(decoded.width, 80); XCTAssertEqual(decoded.height, 60)
        XCTAssertEqual(try pixels(decoded), try pixels(image), "Photo pixels and orientation must survive export")
        var annotation = Annotation(text: "Moon", anchor: PixelPoint(10, 8), position: PixelPoint(20, 12))
        document.annotations = [annotation]
        let visible = directory.appendingPathComponent("visible.png")
        try PhotoIO.png(image: image, document: document, to: visible)
        XCTAssertNotEqual(try pixels(PhotoIO.load(visible)), try pixels(image))
        annotation.hidden = true; document.annotations = [annotation]
        let hidden = directory.appendingPathComponent("hidden.png")
        try PhotoIO.png(image: image, document: document, to: hidden)
        XCTAssertEqual(try pixels(PhotoIO.load(hidden)), try pixels(image))
    }

    func testEXIFOrientationIsAppliedOnImport() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".tiff")
        defer { try? FileManager.default.removeItem(at: url) }
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, UTType.tiff.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, try fixture(), [kCGImagePropertyOrientation: 6] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let rotated = try PhotoIO.load(url)
        XCTAssertEqual(rotated.width, 60); XCTAssertEqual(rotated.height, 80)
    }

    func testWheelDoesNotChangeParametersAndForwardsScrolling() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let event = try scrollEvent()
            let probe = ScrollProbe()
            let slider = ScrollSafeSlider(value: 24, minValue: 6, maxValue: 100, target: nil, action: nil)
            slider.nextResponder = probe
            slider.scrollWheel(with: event)
            XCTAssertEqual(slider.doubleValue, 24)
            XCTAssertEqual(probe.scrolls, 1)
            let field = SafeNumberField.makeField(); field.stringValue = "40"
            XCTAssertTrue(field.isEditable); XCTAssertTrue(field.isSelectable)
            field.nextResponder = probe
            field.scrollWheel(with: event)
            XCTAssertEqual(field.stringValue, "40")
            XCTAssertEqual(probe.scrolls, 2)
            let stepper = ScrollSafeStepper(); stepper.doubleValue = 21; stepper.nextResponder = probe
            stepper.scrollWheel(with: event)
            XCTAssertEqual(stepper.doubleValue, 21); XCTAssertEqual(probe.scrolls, 3)
            let controls: [NSControl] = [slider, field, NSStepper(), NSPopUpButton(), NSComboBox(), NSDatePicker(), NSSegmentedControl()]
            for control in controls {
                XCTAssertTrue(WheelProtection.protectedControl(at: control) === control)
                let child = NSView(); control.addSubview(child)
                XCTAssertTrue(WheelProtection.protectedControl(at: child) === control)
            }
            XCTAssertNil(WheelProtection.protectedControl(at: NSView()))
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 300, height: 200),
                                  styleMask: [.titled], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            window.contentView?.addSubview(field)
            field.frame = NSRect(x: 20, y: 20, width: 80, height: 25)
            XCTAssertTrue(window.makeFirstResponder(field))
            let editor = try XCTUnwrap(field.currentEditor())
            XCTAssertTrue(WheelProtection.protectedControl(at: editor) === field)
            field.scrollWheel(with: event)
            XCTAssertEqual(field.stringValue, "40")
            var editedValue = 40.0
            let control = SafeNumberField(value: Binding(get: { editedValue }, set: { editedValue = $0 }), range: 0...100, step: 0.5)
            let coordinator = control.makeCoordinator()
            let textView = try XCTUnwrap(editor as? NSTextView)
            XCTAssertTrue(coordinator.control(field, textView: textView, doCommandBy: #selector(NSResponder.moveUp(_:))))
            XCTAssertEqual(editedValue, 40.5)
            textView.string = "42.5"; field.stringValue = textView.string; coordinator.commit(field)
            XCTAssertEqual(editedValue, 42.5)
            window.close()
        }
    }

    func testCanvasStillZoomsAndDragCanBeUndone() async throws {
        try await MainActor.run {
            _ = NSApplication.shared
            let model = EditorModel()
            var document = MoonDocument(imagePath: "fixture.png")
            document.imageWidth = 80; document.imageHeight = 60
            let annotation = Annotation(text: "Tycho", anchor: PixelPoint(20, 30), position: PixelPoint(30, 35))
            document.annotations = [annotation]
            model.document = document; model.image = try fixture(); model.selectedID = annotation.id
            let canvas = MoonCanvas(frame: NSRect(x: 0, y: 0, width: 400, height: 300))
            model.image = try fixture(); canvas.model = model; canvas.fitImage()
            let before = canvas.scale
            canvas.scrollWheel(with: try scrollEvent())
            XCTAssertNotEqual(canvas.scale, before)
            XCTAssertEqual(model.document?.settings, document.settings)
            model.moveSelected(to: PixelPoint(42, 51))
            model.endDrag(previous: document)
            XCTAssertEqual(model.selectedAnnotation?.position, PixelPoint(42, 51))
            model.undo()
            XCTAssertEqual(model.selectedAnnotation?.position, annotation.position)
            model.redo()
            XCTAssertEqual(model.selectedAnnotation?.position, PixelPoint(42, 51))
        }
    }

    func testBundledDemoCanBeRenderedAndSavedAsNativeProject() throws {
        var document = try ProjectIO.read(Catalog.demoURL).document
        let image = try PhotoIO.load(URL(fileURLWithPath: document.imagePath))
        document.imageWidth = image.width; document.imageHeight = image.height
        document.annotations = LabelLayout.generate(document: document, features: try Catalog.load(), measure: AnnotationRenderer.measure)
        XCTAssertGreaterThan(document.annotations.filter { !$0.hidden }.count, 10)
        let directory = URL(fileURLWithPath: ProcessInfo.processInfo.environment["MOON_SWIFT_TEST_ARTIFACTS"] ??
                            FileManager.default.temporaryDirectory.appendingPathComponent("moonlabeler-swift-qa").path)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let png = directory.appendingPathComponent("demo-swift.png")
        try PhotoIO.png(image: image, document: document, to: png)
        try ProjectIO.write(document, to: directory.appendingPathComponent("demo-swift.moonswift"))
        let decoded = try PhotoIO.load(png)
        XCTAssertEqual(decoded.width, image.width); XCTAssertEqual(decoded.height, image.height)
    }

    private func fixture() throws -> CGImage {
        let context = try XCTUnwrap(CGContext(data: nil, width: 80, height: 60, bitsPerComponent: 8,
                                            bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.setFillColor(CGColor(red: 1, green: 0, blue: 0, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: 80, height: 30))
        context.setFillColor(CGColor(red: 0, green: 0, blue: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 30, width: 80, height: 30))
        return try XCTUnwrap(context.makeImage())
    }
    private func pixels(_ image: CGImage) throws -> Data {
        let context = try XCTUnwrap(CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                                            bytesPerRow: image.width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        return Data(bytes: try XCTUnwrap(context.data), count: image.width * image.height * 4)
    }
    private func scrollEvent() throws -> NSEvent {
        let cg = try XCTUnwrap(CGEvent(scrollWheelEvent2Source: nil, units: .line, wheelCount: 1,
                                      wheel1: 6, wheel2: 0, wheel3: 0))
        return try XCTUnwrap(NSEvent(cgEvent: cg))
    }
}

@MainActor
private final class ScrollProbe: NSResponder {
    var scrolls = 0
    override func scrollWheel(with event: NSEvent) { scrolls += 1 }
}
