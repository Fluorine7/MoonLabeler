// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

public struct ComputePolicy: Equatable, Sendable {
    public let mode: String
    public let overrideVariable: String?
    public init(preference: String, environment: [String: String] = ProcessInfo.processInfo.environment) {
        func normalize(_ value: String?) -> String? {
            guard let value = value?.lowercased() else { return nil }
            return value == "metal" ? "auto" : ["auto", "cpu"].contains(value) ? value : nil
        }
        for key in ["MOONLABELER_COMPUTE", "MOON_SWIFT_COMPUTE"] {
            if let override = normalize(environment[key]) { mode = override; overrideVariable = key; return }
        }
        mode = normalize(preference) ?? "auto"; overrideVariable = nil
    }
    public static var current: ComputePolicy {
        ComputePolicy(preference: UserDefaults.standard.string(forKey: "moon-swift-compute") ?? "auto")
    }
}
