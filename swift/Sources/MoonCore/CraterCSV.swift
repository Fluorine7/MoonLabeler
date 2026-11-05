// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

public enum CraterCSV {
    public static func data(candidates: [CraterCandidate], imageName: String) -> Data {
        func quoted(_ value: String) -> String {
            value.contains(where: { ",\"\r\n".contains($0) }) ? "\"" + value.replacingOccurrences(of: "\"", with: "\"\"") + "\"" : value
        }
        func number(_ value: Double) -> String { String(format: "%.3f", locale: Locale(identifier: "en_US_POSIX"), value) }
        var rows = ["image,candidate,center_x_px,center_y_px,semimajor_px,semiminor_px,angle_deg,edge_support,method"]
        for (index, candidate) in candidates.enumerated() {
            rows.append([quoted(imageName), String(index + 1), number(candidate.center.x), number(candidate.center.y), number(candidate.major), number(candidate.minor), number(candidate.angle), candidate.support.isFinite ? number(candidate.support) : "", quoted(candidate.method)].joined(separator: ","))
        }
        return Data([0xef, 0xbb, 0xbf]) + Data((rows.joined(separator: "\r\n") + "\r\n").utf8)
    }
}
