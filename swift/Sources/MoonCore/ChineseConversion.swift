// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

public enum ChineseConversion {
    private static let phrases: [String: String] = table("STPhrases")
    private static let characters: [String: String] = table("STCharacters")
    private static let maximum = phrases.keys.map(\.count).max() ?? 1
    private static func table(_ name: String) -> [String: String] {
        guard let url = Catalog.resource(name, "txt"), let text = try? String(contentsOf: url, encoding: .utf8) else { return [:] }
        var result: [String: String] = [:]
        for line in text.split(separator: "\n") where !line.hasPrefix("#") {
            let pair = line.split(separator: "\t", maxSplits: 1)
            if pair.count == 2 { result[String(pair[0])] = pair[1].split(separator: " ").first.map(String.init) }
        }
        return result
    }
    public static func traditional(_ text: String) -> String {
        guard !characters.isEmpty else { return text.applyingTransform(StringTransform("Simplified-Traditional"), reverse: false) ?? text }
        let chars = Array(text); var output = "", index = 0
        while index < chars.count {
            var matched = false
            for length in stride(from: min(maximum, chars.count - index), through: 1, by: -1) {
                let key = String(chars[index..<(index + length)])
                if let value = phrases[key] { output += value; index += length; matched = true; break }
            }
            if !matched { let key = String(chars[index]); output += characters[key] ?? key; index += 1 }
        }
        return output
    }
}
