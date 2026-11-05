// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

public enum DataStore {
    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30; configuration.timeoutIntervalForResource = 120
        // URLSession reads macOS system proxies, but unlike the Python client it
        // does not pick up shell proxy variables used by a source checkout.
        let environment = ProcessInfo.processInfo.environment
        func variable(_ name: String) -> String? { environment[name.lowercased()] ?? environment[name] }
        var proxies: [AnyHashable: Any] = [:]
        for (scheme, prefix) in [("HTTP", "HTTP"), ("HTTPS", "HTTPS")] {
            guard let address = variable("\(scheme)_PROXY") ?? variable("ALL_PROXY"),
                  let url = URL(string: address), let host = url.host else { continue }
            if url.scheme?.lowercased() == "http" {
                proxies["\(prefix)Enable"] = 1; proxies["\(prefix)Proxy"] = host; proxies["\(prefix)Port"] = url.port ?? 80
            } else if ["socks", "socks5", "socks5h"].contains(url.scheme?.lowercased() ?? "") {
                proxies["SOCKSEnable"] = 1; proxies["SOCKSProxy"] = host; proxies["SOCKSPort"] = url.port ?? 1080
            }
        }
        if !proxies.isEmpty {
            if let exclusions = variable("NO_PROXY") {
                proxies["ExceptionsList"] = exclusions.split(separator: ",").map {
                    let host = $0.trimmingCharacters(in: .whitespaces)
                    return host.hasPrefix(".") ? "*\(host)" : host
                }
            }
            configuration.connectionProxyDictionary = proxies
        }
        return URLSession(configuration: configuration)
    }()
    public static var cache: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MoonLabelerSwift/Cache", isDirectory: true)
    }
    public static var bundledDEM: URL? {
        guard let label = Catalog.resource("LDEM_16", "LBL"),
              FileManager.default.fileExists(atPath: label.deletingPathExtension().appendingPathExtension("IMG").path) else { return nil }
        return label
    }
    public static func download(_ url: URL, to destination: URL, task: ComputeTask, force: Bool = false) async throws -> URL {
        try task.check()
        if !force && FileManager.default.fileExists(atPath: destination.path) { return destination }
        try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        let temporary: URL, response: URLResponse
        do { (temporary, response) = try await session.download(from: url) }
        catch {
            if Task.isCancelled || task.isCancelled || (error as NSError).code == NSURLErrorCancelled { throw CancellationError() }
            let detail = (error as NSError).code == NSURLErrorTimedOut ? "连接或读取超时" : "连接未完成"
            var message = "无法下载 \(url.host ?? "数据服务") 的参考数据：\(detail)。"
            if url.host == "svs.gsfc.nasa.gov" {
                message += "\n\n可检查代理中此域名的线路，或在浏览器打开 https://svs.gsfc.nasa.gov/5587/。\n\n当前照片和已有配准仍保留。也可用至少三个已知地形点手动校准。"
            }
            throw MoonError.invalid(message)
        }
        defer { try? FileManager.default.removeItem(at: temporary) }
        try Task.checkCancellation(); try task.check()
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw MoonError.invalid("无法下载 \(url.host ?? "数据服务") 的参考数据：HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)。")
        }
        if FileManager.default.fileExists(atPath: destination.path) { _ = try FileManager.default.replaceItemAt(destination, withItemAt: temporary) }
        else { try FileManager.default.moveItem(at: temporary, to: destination) }
        return destination
    }
    public static func basicDEM(task: ComputeTask, directory: URL? = nil) async throws -> URL {
        if directory == nil, let bundled = bundledDEM { return bundled }
        let root = (directory ?? cache).appendingPathComponent("terrain", isDirectory: true)
        let base = URL(string: "https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/")!
        let label = try await download(base.appendingPathComponent("LDEM_16.LBL"), to: root.appendingPathComponent("LDEM_16.LBL"), task: task)
        _ = try await download(base.appendingPathComponent("LDEM_16.IMG"), to: root.appendingPathComponent("LDEM_16.IMG"), task: task)
        return label
    }
}
