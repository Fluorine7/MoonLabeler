// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI

struct EditorChoicePicker<Value: Hashable>: View {
    var title: String
    @Binding var selection: Value
    var options: [(Value, String)]
    var labelWidth: Double = 108
    init(_ title: String, selection: Binding<Value>, options: [(Value, String)], labelWidth: Double = 108) {
        self.title = title; _selection = selection; self.options = options; self.labelWidth = labelWidth
    }
    var body: some View {
        HStack(spacing: 10) {
            Text(title).frame(width: labelWidth, alignment: .leading)
            EditorPopup(selection: $selection, options: options, title: title).frame(maxWidth: .infinity).frame(height: 28)
        }
    }
}
private struct EditorPopup<Value: Hashable>: NSViewRepresentable {
    @Binding var selection: Value
    var options: [(Value, String)]
    var title: String
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSPopUpButton {
        let popup = NSPopUpButton(frame: .zero, pullsDown: false)
        popup.cell = EditorPopupCell(textCell: "", pullsDown: false)
        popup.target = context.coordinator; popup.action = #selector(Coordinator.changed(_:))
        popup.setContentHuggingPriority(.defaultLow, for: .horizontal)
        popup.setAccessibilityLabel(title)
        return popup
    }
    func updateNSView(_ popup: NSPopUpButton, context: Context) {
        context.coordinator.parent = self
        popup.isEnabled = context.environment.isEnabled
        let names = options.map { $0.1 }
        if popup.itemTitles != names { popup.removeAllItems(); popup.addItems(withTitles: names) }
        if let index = options.firstIndex(where: { $0.0 == selection }) { popup.selectItem(at: index) }
        popup.setAccessibilityLabel(title)
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSPopUpButton, context: Context) -> CGSize? {
        CGSize(width: proposal.width ?? 160, height: proposal.height ?? 28)
    }
    final class Coordinator: NSObject {
        var parent: EditorPopup
        init(_ parent: EditorPopup) { self.parent = parent }
        @objc func changed(_ popup: NSPopUpButton) {
            guard parent.options.indices.contains(popup.indexOfSelectedItem) else { return }
            parent.selection = parent.options[popup.indexOfSelectedItem].0
        }
    }
}
private final class EditorPopupCell: NSPopUpButtonCell {
    override func draw(withFrame frame: NSRect, in view: NSView) {
        AnnotationRenderer.color("#0f141d").setFill()
        let border = NSBezierPath(roundedRect: frame.insetBy(dx: 0.5, dy: 0.5), xRadius: 6, yRadius: 6)
        border.fill(); AnnotationRenderer.color(isHighlighted ? "#d9a96c" : "#2e3a4b").setStroke(); border.lineWidth = 1; border.stroke()
        let paragraph = NSMutableParagraphStyle(); paragraph.lineBreakMode = .byTruncatingTail
        let font = NSFont.systemFont(ofSize: 13)
        let text = NSAttributedString(string: title, attributes: [.font: font, .foregroundColor: AnnotationRenderer.color(isEnabled ? "#dfe6ef" : "#6f7e91"), .paragraphStyle: paragraph])
        let height = ceil(font.ascender - font.descender)
        text.draw(in: NSRect(x: frame.minX + 9, y: frame.midY - height / 2, width: max(0, frame.width - 30), height: height))
        AnnotationRenderer.color("#9badc0").setStroke()
        let arrow = NSBezierPath(); arrow.move(to: NSPoint(x: frame.maxX - 17, y: frame.midY - 2)); arrow.line(to: NSPoint(x: frame.maxX - 13, y: frame.midY + 2)); arrow.line(to: NSPoint(x: frame.maxX - 9, y: frame.midY - 2)); arrow.lineWidth = 1.2; arrow.stroke()
    }
}

// Protect all native value-changing controls, including focused field editors.
// A menu's own scrolling remains managed by AppKit in the separate menu window.
public enum WheelProtection {
    public static func protectedControl(at view: NSView?) -> NSControl? {
        var current = view
        if let editor = current as? NSTextView, editor.isFieldEditor,
           let owner = editor.delegate as? NSControl {
            current = owner
        }
        while let view = current {
            if let control = view as? NSControl,
               control is NSSlider || control is NSStepper || control is NSPopUpButton ||
                control is NSComboBox || control is NSDatePicker || control is NSSegmentedControl ||
                control is NSTextField {
                return control
            }
            current = view.superview
        }
        return nil
    }

    public static func install() -> Any? {
        NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { event in
            guard let window = event.window, ["moon-editor", "moon-reference", "moon-compute"].contains(window.identifier?.rawValue ?? "") || window is NSColorPanel,
                  let content = window.contentView,
                  let control = protectedControl(at: content.hitTest(content.convert(event.locationInWindow, from: nil))) else {
                return event
            }
            // Find the surrounding panel, not a text field's internal clip view.
            var ancestor = control.superview
            while let view = ancestor {
                if let scrollView = view as? NSScrollView { scrollView.scrollWheel(with: event); return nil }
                ancestor = view.superview
            }
            return nil
        }
    }
}

struct SafeSlider: NSViewRepresentable {
    @Binding var value: Double
    var range: ClosedRange<Double>
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSSlider {
        let slider = ScrollSafeSlider(value: value, minValue: range.lowerBound, maxValue: range.upperBound,
                                      target: context.coordinator, action: #selector(Coordinator.changed(_:)))
        slider.cell = EditorSliderCell(); slider.minValue = range.lowerBound; slider.maxValue = range.upperBound; slider.doubleValue = value
        slider.target = context.coordinator; slider.action = #selector(Coordinator.changed(_:))
        slider.isContinuous = true
        return slider
    }
    func updateNSView(_ view: NSSlider, context: Context) {
        context.coordinator.parent = self
        view.isEnabled = context.environment.isEnabled
        view.minValue = range.lowerBound; view.maxValue = range.upperBound; view.doubleValue = value
    }
    final class Coordinator: NSObject {
        var parent: SafeSlider
        init(_ parent: SafeSlider) { self.parent = parent }
        @objc func changed(_ slider: NSSlider) { parent.value = slider.doubleValue }
    }
}

public final class ScrollSafeSlider: NSSlider {
    public override func scrollWheel(with event: NSEvent) { nextResponder?.scrollWheel(with: event) }
}
private final class EditorSliderCell: NSSliderCell {
    override func drawBar(inside rect: NSRect, flipped: Bool) {
        let bar = NSRect(x: rect.minX, y: rect.midY - 2, width: rect.width, height: 4)
        AnnotationRenderer.color("#344052").setFill(); NSBezierPath(roundedRect: bar, xRadius: 2, yRadius: 2).fill()
        let fraction = maxValue > minValue ? min(1, max(0, (doubleValue - minValue) / (maxValue - minValue))) : 0
        AnnotationRenderer.color(isEnabled ? "#d9a96c" : "#4a5361").setFill(); NSBezierPath(roundedRect: NSRect(x: bar.minX, y: bar.minY, width: bar.width * fraction, height: 4), xRadius: 2, yRadius: 2).fill()
    }
    override func drawKnob(_ knobRect: NSRect) {
        let rect = NSRect(x: knobRect.midX - 7, y: knobRect.midY - 7, width: 14, height: 14)
        AnnotationRenderer.color(isEnabled ? "#e8be86" : "#4a5361").setFill(); NSBezierPath(ovalIn: rect).fill()
    }
}

struct SafeNumberField: NSViewRepresentable {
    @Binding var value: Double
    var range: ClosedRange<Double>
    var step: Double = 1
    var suffix: String = ""
    var includesInitialValue = false
    static func formatted(_ value: Double) -> String {
        String(format: "%.4f", value).replacingOccurrences(of: #"0+$"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"\.$"#, with: "", options: .regularExpression)
    }
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSTextField {
        let field = Self.makeField()
        let stepper = ScrollSafeStepper()
        stepper.controlSize = .mini; stepper.valueWraps = false; stepper.autorepeat = true
        stepper.target = context.coordinator; stepper.action = #selector(Coordinator.stepped(_:))
        field.addSubview(stepper)
        field.positionStepper()
        context.coordinator.field = field
        field.delegate = context.coordinator
        field.target = context.coordinator; field.action = #selector(Coordinator.commit(_:))
        return field
    }
    static func makeField() -> ScrollSafeNumberField {
        let field = ScrollSafeNumberField()
        field.cell = EditorNumberCell(textCell: "")
        field.isEditable = true; field.isSelectable = true
        field.cell?.isScrollable = true; field.cell?.wraps = false; field.cell?.usesSingleLineMode = true
        field.alignment = .right
        field.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        field.isBezeled = false; field.isBordered = false; field.drawsBackground = false
        field.backgroundColor = AnnotationRenderer.color("#0f141d"); field.textColor = AnnotationRenderer.color("#dfe6ef")
        field.wantsLayer = true; field.layer?.cornerRadius = 6; field.layer?.borderWidth = 1; field.layer?.borderColor = AnnotationRenderer.color("#2e3a4b").cgColor
        field.layer?.backgroundColor = AnnotationRenderer.color("#0f141d").cgColor
        return field
    }
    func updateNSView(_ view: NSTextField, context: Context) {
        context.coordinator.parent = self
        view.isEnabled = context.environment.isEnabled
        if let cell = view.cell as? EditorNumberCell {
            cell.suffix = suffix
            cell.trailingInset = 17 + (suffix.isEmpty ? 0 : (suffix as NSString).size(withAttributes: [.font: view.font ?? NSFont.systemFont(ofSize: 12)]).width + 5)
            view.needsDisplay = true
        }
        if let stepper = view.subviews.first(where: { $0 is NSStepper }) as? NSStepper {
            let editingRange = context.coordinator.editingRange
            stepper.isEnabled = view.isEnabled; stepper.minValue = editingRange.lowerBound; stepper.maxValue = editingRange.upperBound
            stepper.increment = step; stepper.doubleValue = value
        }
        if view.currentEditor() == nil { view.stringValue = Self.formatted(value) }
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSTextField, context: Context) -> CGSize? {
        CGSize(width: proposal.width ?? 80, height: proposal.height ?? 28)
    }
    final class Coordinator: NSObject, NSTextFieldDelegate {
        var parent: SafeNumberField
        weak var field: NSTextField?
        private let initialValue: Double
        init(_ parent: SafeNumberField) { self.parent = parent; initialValue = parent.value }
        var editingRange: ClosedRange<Double> {
            guard parent.includesInitialValue else { return parent.range }
            return min(parent.range.lowerBound, initialValue)...max(parent.range.upperBound, initialValue)
        }
        @objc func commit(_ field: NSTextField) {
            // Visiting a field preserves automatic/default settings and stored
            // precision beyond the displayed digits.
            if field.stringValue != SafeNumberField.formatted(parent.value),
               let number = Double(field.stringValue), number.isFinite {
                setValue(min(max(number, editingRange.lowerBound), editingRange.upperBound))
            }
            field.stringValue = SafeNumberField.formatted(parent.value)
        }
        func controlTextDidEndEditing(_ notification: Notification) {
            if let field = notification.object as? NSTextField { commit(field) }
        }
        func controlTextDidChange(_ notification: Notification) {
            guard let field = notification.object as? NSTextField,
                  let number = Double((field.currentEditor() as? NSTextView)?.string ?? field.stringValue),
                  number.isFinite, editingRange.contains(number) else { return }
            setValue(number)
        }
        @objc func stepped(_ stepper: NSStepper) {
            setValue(stepper.doubleValue)
            field?.stringValue = SafeNumberField.formatted(parent.value)
            (field?.currentEditor() as? NSTextView)?.string = SafeNumberField.formatted(parent.value)
        }
        func control(_ control: NSControl, textView: NSTextView, doCommandBy commandSelector: Selector) -> Bool {
            let direction: Double
            if commandSelector == #selector(NSResponder.moveUp(_:)) { direction = 1 }
            else if commandSelector == #selector(NSResponder.moveDown(_:)) { direction = -1 }
            else { return false }
            let current = Double(textView.string) ?? parent.value
            setValue(min(editingRange.upperBound, max(editingRange.lowerBound, current + direction * parent.step)))
            textView.string = SafeNumberField.formatted(parent.value); return true
        }
        private func setValue(_ value: Double) { if value != parent.value { parent.value = value } }
    }
}

private final class EditorNumberCell: NSTextFieldCell {
    private var positioningEditor = false
    var trailingInset: CGFloat = 0
    var suffix = ""
    override func drawInterior(withFrame rect: NSRect, in view: NSView) {
        super.drawInterior(withFrame: rect, in: view)
        guard !suffix.isEmpty else { return }
        let attributes: [NSAttributedString.Key: Any] = [.font: font ?? NSFont.systemFont(ofSize: 12), .foregroundColor: AnnotationRenderer.color("#9badc0")]
        let size = (suffix as NSString).size(withAttributes: attributes)
        (suffix as NSString).draw(in: NSRect(x: rect.maxX - 24 - size.width, y: rect.midY - size.height / 2, width: size.width, height: size.height), withAttributes: attributes)
    }
    override func drawingRect(forBounds rect: NSRect) -> NSRect {
        if positioningEditor { return rect }
        let height = min(rect.height, ceil((font?.ascender ?? 12) - (font?.descender ?? -3) + (font?.leading ?? 0)))
        return NSRect(x: rect.minX + 7, y: rect.midY - height / 2, width: max(0, rect.width - 14 - trailingInset), height: height)
    }
    override func edit(withFrame rect: NSRect, in view: NSView, editor: NSText, delegate: Any?, event: NSEvent?) {
        let content = drawingRect(forBounds: rect); positioningEditor = true; defer { positioningEditor = false }
        super.edit(withFrame: content, in: view, editor: editor, delegate: delegate, event: event)
    }
    override func select(withFrame rect: NSRect, in view: NSView, editor: NSText, delegate: Any?, start: Int, length: Int) {
        let content = drawingRect(forBounds: rect); positioningEditor = true; defer { positioningEditor = false }
        super.select(withFrame: content, in: view, editor: editor, delegate: delegate, start: start, length: length)
    }
}

public final class ScrollSafeNumberField: NSTextField {
    public override func scrollWheel(with event: NSEvent) { nextResponder?.scrollWheel(with: event) }
    public override func layout() { super.layout(); positionStepper() }
    public override func setFrameSize(_ newSize: NSSize) { super.setFrameSize(newSize); positionStepper() }
    func positionStepper() {
        guard let stepper = subviews.first(where: { $0 is NSStepper }) as? NSStepper else { return }
        let size = stepper.intrinsicContentSize
        stepper.frame = NSRect(x: bounds.maxX - size.width - 3, y: bounds.midY - size.height / 2, width: size.width, height: size.height)
    }
}

public final class ScrollSafeStepper: NSStepper {
    public override func scrollWheel(with event: NSEvent) { nextResponder?.scrollWheel(with: event) }
}
