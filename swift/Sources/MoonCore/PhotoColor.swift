// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import CoreGraphics
import ImageIO

extension PhotoPixels {
    /// Decode measurements in the file's encoding. Display conversion belongs
    /// to a separate copy, so ICC profiles cannot change registration input.
    static func rawDecoded(_ image: CGImage) throws -> PhotoPixels {
        let encoding = image.colorSpace ?? CGColorSpace(name: CGColorSpace.sRGB)!
        if encoding.model == .cmyk, image.bitsPerComponent == 8, image.bitsPerPixel == 32,
           let data = image.dataProvider?.data {
            let bytes = CFDataGetBytePtr(data)!, count = image.width * image.height
            guard CFDataGetLength(data) >= image.bytesPerRow * image.height else { throw MoonError.invalid("CMYK 图像数据不完整。") }
            var rgba = [UInt8](repeating: 255, count: count * 4)
            for y in 0..<image.height { for x in 0..<image.width {
                let p = y * image.bytesPerRow + x * 4, target = (y * image.width + x) * 4, k = 255 - Int(bytes[p + 3])
                for c in 0..<3 { rgba[target + c] = UInt8(((255 - Int(bytes[p + c])) * k + 127) / 255) }
            } }
            return PhotoPixels(width: image.width, height: image.height, rgba: rgba)
        }
        if encoding.model == .monochrome {
            var gray = [UInt8](repeating: 0, count: image.width * image.height)
            try gray.withUnsafeMutableBytes { buffer in
                guard let context = CGContext(data: buffer.baseAddress, width: image.width, height: image.height, bitsPerComponent: 8,
                    bytesPerRow: image.width, space: encoding, bitmapInfo: CGImageAlphaInfo.none.rawValue) else { throw MoonError.invalid("无法读取灰度图像。") }
                context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
            }
            return PhotoPixels(width: image.width, height: image.height, rgba: gray.flatMap { [$0, $0, $0, 255] })
        }
        let rgb = encoding.model == .rgb ? encoding : encoding.baseColorSpace ?? CGColorSpace(name: CGColorSpace.sRGB)!
        return try PhotoPixels(image, colorSpace: rgb)
    }

    /// Match Python's display_srgb: untagged files retain their samples; tagged
    /// files use relative-colorimetric conversion on a display-only copy.
    public static func display(_ url: URL, raw: PhotoPixels) throws -> PhotoPixels {
        if ["fit", "fits", "fts"].contains(url.pathExtension.lowercased()) { return raw }
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              properties[kCGImagePropertyProfileName] != nil,
              let original = CGImageSourceCreateImageAtIndex(source, 0, nil), let encoding = original.colorSpace else { return raw }
        let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
        if CFEqual(encoding, srgb) { return raw }
        if encoding.model == .cmyk {
            return try PhotoPixels(original, intent: .relativeColorimetric).oriented(PhotoOrientation.value(properties, url: url, source: source))
        }
        let gray = encoding.model == .monochrome
        let bytes = gray ? stride(from: 0, to: raw.rgba.count, by: 4).map { raw.rgba[$0] } : raw.rgba
        guard let provider = CGDataProvider(data: Data(bytes) as CFData),
              let tagged = CGImage(width: raw.width, height: raw.height, bitsPerComponent: 8, bitsPerPixel: gray ? 8 : 32,
                bytesPerRow: raw.width * (gray ? 1 : 4), space: encoding,
                bitmapInfo: CGBitmapInfo(rawValue: gray ? CGImageAlphaInfo.none.rawValue : CGImageAlphaInfo.premultipliedLast.rawValue),
                provider: provider, decode: nil, shouldInterpolate: false, intent: .relativeColorimetric) else { throw MoonError.invalid("无法将照片的 ICC 色彩配置转换为 sRGB。") }
        return try PhotoPixels(tagged, intent: .relativeColorimetric)
    }
}
