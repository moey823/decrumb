// SPDX-License-Identifier: AGPL-3.0-only

import Foundation

public struct SidecarSiteRule: Codable, Equatable, Sendable {
    public var site: String
    public var remove: [String]
    public var keep: [String]
}

public struct SidecarRuleSet: Codable, Sendable {
    public var version: Int
    public var revision: String
    public var globalRemove: [String]
    public var protectedParameters: [String]
    public var sites: [SidecarSiteRule]
}

public struct SidecarURLCleanupSettings: Codable, Equatable, Sendable {
    public enum Mode: String, Codable, CaseIterable, Sendable {
        case off, selected, all
    }

    public var mode: Mode
    public var baseURLs: [String]
    public var excludedURLs: [String]
    public var rules: [SidecarSiteRule]
    public static let didChange = Notification.Name("SidecarURLCleanupSettingsDidChange")
    private static let storageKey = "Sidecar.URLCleanup.v1"

    public init(mode: Mode = .all, baseURLs: [String] = [], excludedURLs: [String] = [], rules: [SidecarSiteRule] = []) {
        self.mode = mode
        self.baseURLs = baseURLs
        self.excludedURLs = excludedURLs
        self.rules = rules
    }

    private enum CodingKeys: String, CodingKey { case mode, baseURLs, excludedURLs, rules }
    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        mode = try values.decode(Mode.self, forKey: .mode)
        baseURLs = try values.decode([String].self, forKey: .baseURLs)
        excludedURLs = try values.decodeIfPresent([String].self, forKey: .excludedURLs) ?? []
        rules = try values.decodeIfPresent([SidecarSiteRule].self, forKey: .rules) ?? []
    }

    public func validated() throws -> Self {
        func sites(_ values: [String]) throws -> [String] {
            guard values.count <= 100 else { throw RuleError.invalid }
            return try values.map {
                guard let site = SidecarURLCleaner.normalizedBaseURL($0) else { throw RuleError.invalid }
                return site
            }
        }
        func parameters(_ values: [String]) throws -> [String] {
            guard values.count <= 50 else { throw RuleError.invalid }
            return try values.map {
                guard $0.range(of: "^[A-Za-z0-9_.~-]{1,128}$", options: .regularExpression) != nil else { throw RuleError.invalid }
                return $0.lowercased()
            }
        }
        guard rules.count <= 100 else { throw RuleError.invalid }
        return try Self(mode: mode, baseURLs: sites(baseURLs), excludedURLs: sites(excludedURLs), rules: rules.map {
            SidecarSiteRule(site: try sites([$0.site])[0], remove: try parameters($0.remove), keep: try parameters($0.keep))
        })
    }

    public enum RuleError: Error { case invalid }

    public static var current: Self { load(from: .standard) }

    public static func load(from defaults: UserDefaults) -> Self {
        guard let data = defaults.data(forKey: storageKey) else { return Self() }
        return (try? JSONDecoder().decode(Self.self, from: data)) ?? Self(mode: .off)
    }

    public func save(to defaults: UserDefaults = .standard) {
        guard let data = try? JSONEncoder().encode(self) else { return }
        defaults.set(data, forKey: Self.storageKey)
        NotificationCenter.default.post(name: Self.didChange, object: nil)
    }
}

/// Removes only listed query keys, preserving every other byte of a link.
/// No redirects, URL expansion, requests, or message-content logging occur here.
public enum SidecarURLCleaner {
    // Sources and update notes are recorded in docs/URL-CLEANUP.md.
    public static var ruleSet: SidecarRuleSet?

    public static func loadRules(from url: URL) throws {
        var rules = try JSONDecoder().decode(SidecarRuleSet.self, from: Data(contentsOf: url))
        guard rules.version == 1, !rules.protectedParameters.isEmpty else { throw SidecarURLCleanupSettings.RuleError.invalid }
        rules.sites = try SidecarURLCleanupSettings(rules: rules.sites).validated().rules
        let global = try SidecarURLCleanupSettings(rules: [SidecarSiteRule(site: "example.invalid", remove: rules.globalRemove, keep: rules.protectedParameters)]).validated().rules[0]
        rules.globalRemove = global.remove
        rules.protectedParameters = global.keep
        ruleSet = rules
    }
    private static let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)

    public struct Result {
        public let text: String
        public let removedRanges: [NSRange]

        /// UTF-16 offsets remain valid for mentions, styles, and cursor positions.
        public func map(_ range: NSRange) -> NSRange {
            func mapIndex(_ index: Int) -> Int {
                index - removedRanges.reduce(0) { total, removed in
                    total + min(max(index - removed.location, 0), removed.length)
                }
            }
            let start = mapIndex(range.location)
            return NSRange(location: start, length: max(0, mapIndex(NSMaxRange(range)) - start))
        }
    }

    /// A host (including its subdomains) and optional path prefix. Explicit ports
    /// must match; otherwise only the normal HTTP/HTTPS ports are included.
    public static func normalizedBaseURL(_ input: String) -> String? {
        let value = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, value.count <= 2048,
              value.rangeOfCharacter(from: .whitespacesAndNewlines) == nil,
              !value.contains("\\"), !value.contains("*")
        else { return nil }
        guard var components = components(for: value),
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil
        else { return nil }
        components.scheme = components.scheme?.lowercased()
        components.host = components.host?.lowercased()
        while components.percentEncodedPath.hasSuffix("/") {
            components.percentEncodedPath.removeLast()
        }
        return components.string
    }

    public static func clean(_ url: URL, settings: SidecarURLCleanupSettings = .current) -> URL {
        URL(string: cleanURLString(url.absoluteString, settings: settings)) ?? url
    }

    public static func cleanURLString(_ value: String, settings: SidecarURLCleanupSettings) -> String {
        applying(removals(in: value, settings: settings), to: value).text
    }

    public static func cleanText(
        _ text: String,
        settings: SidecarURLCleanupSettings = .current,
        protectedRanges: [NSRange] = [],
    ) -> Result {
        guard settings.mode != .off, text.contains("?"), let detector else {
            return Result(text: text, removedRanges: [])
        }
        let nsText = text as NSString
        var ranges = [NSRange]()
        for match in detector.matches(in: text, range: NSRange(location: 0, length: nsText.length)) {
            guard let scheme = match.url?.scheme?.lowercased(), ["http", "https"].contains(scheme) else { continue }
            let localRanges = removals(in: nsText.substring(with: match.range), settings: settings)
            let absoluteRanges = localRanges.map { NSRange(location: match.range.location + $0.location, length: $0.length) }
            // A mention can theoretically occur inside a query value. Keep that
            // entire URL rather than deleting a semantic mention from the message.
            guard !absoluteRanges.contains(where: { removed in
                protectedRanges.contains { NSIntersectionRange(removed, $0).length > 0 }
            }) else { continue }
            ranges.append(contentsOf: absoluteRanges)
        }
        return applying(ranges, to: text)
    }

    private static func components(for value: String) -> URLComponents? {
        let hasScheme = value.range(of: "^[A-Za-z][A-Za-z0-9+.-]*://", options: .regularExpression) != nil
        let absolute = hasScheme ? value : "https://" + value
        guard let components = URLComponents(string: absolute),
              let scheme = components.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = components.host, !host.isEmpty,
              !host.contains("%"), !host.contains("://")
        else { return nil }
        return components
    }

    private static func matches(_ url: URLComponents, base: String) -> Bool {
        guard let rule = components(for: base),
              let host = url.host?.lowercased(), let baseHost = rule.host?.lowercased(),
              host == baseHost || host.hasSuffix("." + baseHost)
        else { return false }
        let defaultPort = url.scheme?.lowercased() == "https" ? 443 : 80
        if let port = rule.port {
            guard (url.port ?? defaultPort) == port else { return false }
        } else if let port = url.port, port != defaultPort {
            return false
        }
        let path = rule.percentEncodedPath
        return path.isEmpty || path == "/" || url.percentEncodedPath == path || url.percentEncodedPath.hasPrefix(path + "/")
    }

    private static func removals(in value: String, settings: SidecarURLCleanupSettings) -> [NSRange] {
        guard let rules = ruleSet, settings.mode != .off, let url = components(for: value),
              !settings.excludedURLs.contains(where: { matches(url, base: $0) }),
              settings.mode == .all || settings.baseURLs.contains(where: { matches(url, base: $0) })
        else { return [] }
        let string = value as NSString
        let question = string.range(of: "?")
        let fragment = string.range(of: "#")
        let queryEnd = fragment.location == NSNotFound ? string.length : fragment.location
        guard question.location != NSNotFound, question.location < queryEnd else { return [] }
        let queryStart = question.location + 1
        let query = string.substring(with: NSRange(location: queryStart, length: queryEnd - queryStart))
        let parts = query.components(separatedBy: "&")
        let names = parts.map { part -> String in
            let name = String(part.prefix { $0 != "=" })
            return (name.removingPercentEncoding ?? name).lowercased()
        }
        // Signed links may cover the entire query, including tracking fields.
        guard Set(rules.protectedParameters).isDisjoint(with: names) else { return [] }
        let matching = (rules.sites + settings.rules).filter { matches(url, base: $0.site) }
        let removed = Set(rules.globalRemove + matching.flatMap(\.remove))
        let preserved = Set(matching.flatMap(\.keep))
        let remove = names.map { removed.contains($0) && !preserved.contains($0) }
        guard remove.contains(true) else { return [] }
        if remove.allSatisfy({ $0 }) {
            return [NSRange(location: question.location, length: queryEnd - question.location)]
        }
        var offsets = [Int]()
        var position = queryStart
        for part in parts {
            offsets.append(position)
            position += (part as NSString).length + 1
        }
        var ranges = [NSRange]()
        var index = 0
        while index < parts.count {
            guard remove[index] else { index += 1; continue }
            let first = index
            while index < parts.count, remove[index] { index += 1 }
            if index < parts.count {
                ranges.append(NSRange(location: offsets[first], length: offsets[index] - offsets[first]))
            } else {
                let start = offsets[first] - 1 // preceding ampersand
                ranges.append(NSRange(location: start, length: queryEnd - start))
            }
        }
        return ranges
    }

    private static func applying(_ ranges: [NSRange], to text: String) -> Result {
        let result = NSMutableString(string: text)
        for range in ranges.reversed() { result.deleteCharacters(in: range) }
        return Result(text: result as String, removedRanges: ranges)
    }
}
