// SPDX-License-Identifier: GPL-3.0-or-later
import AppKit
import SwiftUI

/// Keep a shared draft: entering February while the day is still 31 must not
/// roll the stored date into March before the user has entered the day.
struct CaptureEntry: NSViewRepresentable {
    enum Kind { case date, time }
    @Binding var value: Date
    var kind: Kind
    var units: [String]
    var validityChanged: (Bool) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> CaptureEntryView {
        let view = CaptureEntryView(kind: kind, units: units)
        context.coordinator.view = view
        for field in view.fields { field.delegate = context.coordinator }
        context.coordinator.synchronize()
        return view
    }
    func updateNSView(_ view: CaptureEntryView, context: Context) {
        context.coordinator.parent = self
        for field in view.fields { field.isEnabled = context.environment.isEnabled }
        if !view.fields.contains(where: { $0.currentEditor() != nil }) { context.coordinator.synchronize() }
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: CaptureEntryView, context: Context) -> CGSize? {
        CGSize(width: nsView.fittingSize.width, height: 28)
    }
    final class Coordinator: NSObject, NSTextFieldDelegate {
        var parent: CaptureEntry
        weak var view: CaptureEntryView?
        private var changingFocus = false
        private var lastValues: [Int]?
        init(_ parent: CaptureEntry) { self.parent = parent }
        private var calendar: Calendar { var result = Calendar(identifier: .gregorian); result.timeZone = TimeZone(secondsFromGMT: 0)!; return result }
        func synchronize() {
            guard let view else { return }
            let values = view.components.map { calendar.component($0, from: parent.value) }
            guard values != lastValues else { return }
            for (index, field) in view.fields.enumerated() {
                field.stringValue = String(format: "%0*d", view.digits[index], values[index])
            }
            lastValues = values
        }
        func controlTextDidBeginEditing(_ notification: Notification) {
            (notification.object as? NSTextField)?.currentEditor()?.selectAll(nil)
        }
        func controlTextDidChange(_ notification: Notification) {
            guard !changingFocus, let field = notification.object as? NSTextField, let view,
                  let index = view.fields.firstIndex(where: { $0 === field }), let editor = field.currentEditor() as? NSTextView else { return }
            let filtered = String(editor.string.filter { $0.isASCII && $0.isNumber }.prefix(view.digits[index]))
            if editor.string != filtered { editor.string = filtered }
            publish()
            if filtered.count == view.digits[index], let number = Int(filtered), view.ranges[index].contains(number), index + 1 < view.fields.count {
                changingFocus = true; defer { changingFocus = false }
                field.window?.makeFirstResponder(view.fields[index + 1]); view.fields[index + 1].selectText(nil)
            }
        }
        func controlTextDidEndEditing(_ notification: Notification) {
            if let field = notification.object as? NSTextField, let view, let index = view.fields.firstIndex(where: { $0 === field }),
               let number = Int(field.stringValue), view.ranges[index].contains(number) {
                field.stringValue = String(format: "%0*d", view.digits[index], number)
            }
            publish()
        }
        private func publish() {
            guard let view else { return }
            let strings = view.fields.map { ($0.currentEditor() as? NSTextView)?.string ?? $0.stringValue }
            let numbers = strings.compactMap(Int.init)
            guard numbers.count == view.fields.count, strings.enumerated().allSatisfy({ $0.element.count == view.digits[$0.offset] }),
                  numbers.enumerated().allSatisfy({ view.ranges[$0.offset].contains($0.element) }) else { parent.validityChanged(false); return }
            var parts = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: parent.value)
            for (component, number) in zip(view.components, numbers) { parts.setValue(number, for: component) }
            guard let date = calendar.date(from: parts), zip(view.components, numbers).allSatisfy({ calendar.component($0.0, from: date) == $0.1 }) else { parent.validityChanged(false); return }
            parent.validityChanged(true)
            lastValues = numbers
            if parent.value != date { parent.value = date }
        }
        func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
            guard let view, let field = control as? NSTextField, let index = view.fields.firstIndex(where: { $0 === field }) else { return false }
            let step = selector == #selector(NSResponder.moveUp(_:)) ? 1 : selector == #selector(NSResponder.moveDown(_:)) ? -1 : 0
            guard step != 0 else { return false }
            let current = Int(textView.string) ?? calendar.component(view.components[index], from: parent.value)
            let next = min(view.ranges[index].upperBound, max(view.ranges[index].lowerBound, current + step))
            textView.string = String(format: "%0*d", view.digits[index], next); publish(); return true
        }
    }
}

final class CaptureEntryView: NSStackView {
    let fields: [ScrollSafeNumberField]
    let digits: [Int]
    let ranges: [ClosedRange<Int>]
    let components: [Calendar.Component]
    init(kind: CaptureEntry.Kind, units: [String]) {
        let date = kind == .date
        digits = date ? [4, 2, 2] : [2, 2]
        ranges = date ? [1900...2050, 1...12, 1...31] : [0...23, 0...59]
        components = date ? [.year, .month, .day] : [.hour, .minute]
        fields = digits.map { _ in SafeNumberField.makeField() }
        super.init(frame: .zero)
        orientation = .horizontal; alignment = .centerY; spacing = 5; distribution = .fill
        for index in fields.indices {
            let field = fields[index]; field.alignment = .center; field.focusRingType = .none
            field.translatesAutoresizingMaskIntoConstraints = false
            field.widthAnchor.constraint(equalToConstant: digits[index] == 4 ? 58 : 42).isActive = true
            field.heightAnchor.constraint(equalToConstant: 28).isActive = true
            addArrangedSubview(field)
            if units.indices.contains(index) {
                let label = NSTextField(labelWithString: units[index]); label.font = .systemFont(ofSize: 13); label.textColor = AnnotationRenderer.color("#dfe6ef")
                addArrangedSubview(label)
            }
        }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}
