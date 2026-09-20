// SPDX-License-Identifier: AGPL-3.0-only
import Foundation
import CoreImage
import AppKit

// This executable uses the extracted cleaner with versioned rules and overrides.
// It has no network access and reads one bounded JSON request from stdin.
do {
    let data = FileHandle.standardInput.readData(ofLength: 2 * 1024 * 1024 + 1)
    guard data.count <= 2 * 1024 * 1024 else { exit(65) }
    if CommandLine.arguments.count == 3, CommandLine.arguments[1] == "--qr" {
        guard let filter = CIFilter(name: "CIQRCodeGenerator") else { exit(65) }
        filter.setValue(data, forKey: "inputMessage")
        filter.setValue("M", forKey: "inputCorrectionLevel")
        guard let qr = filter.outputImage else { exit(65) }
        let white = CIImage(color: CIColor.white).cropped(to: qr.extent.insetBy(dx: -4, dy: -4))
        let output = qr.composited(over: white).transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        guard let image = CIContext(options: [.useSoftwareRenderer: true]).createCGImage(output, from: output.extent),
              let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else { exit(65) }
        try png.write(to: URL(fileURLWithPath: CommandLine.arguments[2]), options: .atomic)
        exit(0)
    }
    struct Input: Decodable {
        let text: String
        let settings: DecrumbURLCleanupSettings
    }
    let input = try JSONDecoder().decode(Input.self, from: data)
    guard input.text.utf8.count <= 64 * 1024 else { exit(65) }
    let settings = try input.settings.validated()
    let executable = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    let executableDirectory = executable.deletingLastPathComponent()
    let contents = executableDirectory.deletingLastPathComponent()
    let packaged = executableDirectory.lastPathComponent == "Helpers" &&
        contents.lastPathComponent == "Contents" && contents.deletingLastPathComponent().pathExtension == "app"
    // App resources must stay outside the signed Helpers code directory. A
    // standalone development helper loads the rules placed beside its executable.
    let rules = packaged ? contents.appendingPathComponent("Resources/rules.json") :
        executableDirectory.appendingPathComponent("rules.json")
    try DecrumbURLCleaner.loadRules(from: rules)
    let detector = try NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
    let text = input.text as NSString
    var seen = Set<String>()
    var urls = [String]()
    var changes = [[String: Any]]()
    for match in detector.matches(in: input.text, range: NSRange(location: 0, length: text.length)) {
        guard let scheme = match.url?.scheme?.lowercased(), ["http", "https"].contains(scheme) else { continue }
        let original = text.substring(with: match.range)
        let cleaned = DecrumbURLCleaner.cleanURLString(original, settings: settings)
        func keys(_ value: String) -> [String] {
            let query = value.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false)[0].split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
            guard query.count == 2 else { return [] }
            return query[1].split(separator: "&").map { String($0.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false).first ?? "").removingPercentEncoding ?? "" }
        }
        let remaining = Set(keys(cleaned).map { $0.lowercased() })
        changes.append(["original": original, "cleaned": cleaned, "removed": keys(original).filter { !remaining.contains($0.lowercased()) }])
        guard cleaned != original else { continue }
        let absolute = cleaned.range(of: "^https?://", options: [.regularExpression, .caseInsensitive]) != nil ? cleaned : scheme + "://" + cleaned
        if seen.insert(absolute).inserted { urls.append(absolute) }
    }
    let normalized = try JSONSerialization.jsonObject(with: JSONEncoder().encode(settings))
    let output = try JSONSerialization.data(withJSONObject: ["urls": urls, "changes": changes, "settings": normalized, "revision": DecrumbURLCleaner.ruleSet!.revision])
    FileHandle.standardOutput.write(output)
    FileHandle.standardOutput.write(Data([10]))
} catch {
    // Never echo input, URLs, or parser error descriptions.
    FileHandle.standardError.write(Data("Invalid cleanup request.\n".utf8))
    exit(65)
}
