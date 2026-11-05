// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import ImageIO

enum PhotoOrientation {
    static func value(_ properties: [CFString: Any], url: URL, source: CGImageSource) -> Int32 {
        func valid(_ value: Any?) -> Int32? {
            guard let number = value as? NSNumber, (1...8).contains(number.int64Value) else { return nil }
            return number.int32Value
        }
        let declared = valid(properties[kCGImagePropertyOrientation]) ??
            valid((properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any])?[kCGImagePropertyTIFFOrientation])
        guard (CGImageSourceGetType(source) as String?) == "public.tiff" else { return declared ?? 1 }
        return tiffValue(url) ?? declared ?? 1
    }

    // Read only the first IFD's scalar orientation. Pixel decoding stays in
    // ImageIO; its BigTIFF properties can omit this tag. Format reference:
    // https://libtiff.gitlab.io/libtiff/specification/bigtiff.html
    private static func tiffValue(_ url: URL) -> Int32? {
        guard url.isFileURL else { return nil }
        do {
            let file = try FileHandle(forReadingFrom: url)
            defer { try? file.close() }
            let length = try file.seekToEnd()
            func read(_ offset: UInt64, _ count: Int) throws -> Data? {
                guard offset <= length, UInt64(count) <= length - offset else { return nil }
                try file.seek(toOffset: offset)
                guard let data = try file.read(upToCount: count), data.count == count else { return nil }
                return data
            }
            guard let header = try read(0, 16) else { return nil }
            let little = header[0] == 0x49 && header[1] == 0x49
            guard little || (header[0] == 0x4d && header[1] == 0x4d) else { return nil }
            func unsigned(_ data: Data, _ offset: Int, _ count: Int) -> UInt64 {
                var value: UInt64 = 0
                for index in 0..<count {
                    let shift = (little ? index : count - 1 - index) * 8
                    value |= UInt64(data[offset + index]) << shift
                }
                return value
            }
            let version = unsigned(header, 2, 2), big = version == 43
            guard version == 42 || (big && unsigned(header, 4, 2) == 8 && unsigned(header, 6, 2) == 0) else { return nil }
            let first = unsigned(header, big ? 8 : 4, big ? 8 : 4), countBytes = big ? 8 : 2, entryBytes = big ? 20 : 12
            guard let directory = try read(first, countBytes) else { return nil }
            let count = unsigned(directory, 0, countBytes), start = first + UInt64(countBytes)
            guard count <= (length - start) / UInt64(entryBytes) else { return nil }
            var index: UInt64 = 0
            while index < count {
                let batch = Int(min(count - index, 512))
                guard let entries = try read(start + index * UInt64(entryBytes), batch * entryBytes) else { return nil }
                for item in 0..<batch {
                    let offset = item * entryBytes
                    guard unsigned(entries, offset, 2) == 274 else { continue }
                    let type = unsigned(entries, offset + 2, 2), values = unsigned(entries, offset + 4, big ? 8 : 4)
                    guard values == 1, type == 3 || type == 4 || (big && type == 16) else { return nil }
                    let value = unsigned(entries, offset + (big ? 12 : 8), type == 3 ? 2 : type == 4 ? 4 : 8)
                    return (1...8).contains(value) ? Int32(value) : nil
                }
                index += UInt64(batch)
            }
        } catch { return nil }
        return nil
    }
}
