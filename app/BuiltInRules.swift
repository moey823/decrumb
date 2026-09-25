// SPDX-License-Identifier: AGPL-3.0-only
import AppKit
import SwiftUI

struct BuiltInRuleSet: Decodable {
    let version: Int
    let revision: String
    let globalRemove: [String]
    let protectedParameters: [String]
    let sites: [BuiltInSiteRule]

    static func load(from url: URL) throws -> BuiltInRuleSet {
        let rules = try JSONDecoder().decode(BuiltInRuleSet.self, from: Data(contentsOf: url))
        guard rules.version == 1 else { throw BuiltInRulesError.unsupportedVersion }
        return rules
    }
}

struct BuiltInSiteRule: Decodable, Identifiable {
    let site: String
    let remove: [String]
    let keep: [String]
    var id: String { site }
}

private enum BuiltInRulesError: LocalizedError {
    case unsupportedVersion
    var errorDescription: String? { "These built-in rules use an unsupported version." }
}

struct BuiltInRulesView: View {
    let rules: BuiltInRuleSet
    let onTryLink: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Built-in rules").font(.system(size: 25, weight: .semibold, design: .rounded))
                Text("The defaults included with this version of Decrumb. Your cleaning mode, excluded sites and custom Keep rules still apply.")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }.frame(maxWidth: .infinity, alignment: .leading).padding(24)
            Divider()
            ScrollView { catalog }
            Divider()
            HStack(spacing: 12) {
                Text("Rules revision: \(rules.revision)").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                Spacer()
                Button("Try a link", action: onTryLink)
                Button("Done") { dismiss() }.keyboardShortcut(.cancelAction)
            }.padding(18)
        }.frame(width: 630, height: 660)
    }

    var catalog: some View {
        VStack(alignment: .leading, spacing: 20) {
            section("Common trackers on any site", icon: "globe") {
                Text("Decrumb removes these parameters from links on any site, including domains not listed below. Parameters are the names after ? or & in a link.")
                    .font(.callout).foregroundStyle(.secondary)
                parameterNames(rules.globalRemove)
                Text("Names match exactly, ignoring capitalization. No wildcards are used.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            section("Extra rules by domain", icon: "link") {
                Text("Each domain includes its subdomains. A path rule matches that path and its subpaths, but not a longer path name. Keep takes priority over Remove.")
                    .font(.callout).foregroundStyle(.secondary)
                ForEach(Array(rules.sites.enumerated()), id: \.element.id) { index, rule in
                    if index > 0 { Divider() }
                    VStack(alignment: .leading, spacing: 8) {
                        Text(rule.site).font(.system(.callout, design: .monospaced).weight(.semibold))
                            .textSelection(.enabled)
                        if !rule.remove.isEmpty { parameterRow("Remove", names: rule.remove) }
                        if !rule.keep.isEmpty { parameterRow("Keep", names: rule.keep) }
                    }
                }
                Text("Keep protects only the listed names. Common trackers can still be removed from these links.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            section("Recognized signed links", icon: "lock.shield") {
                Text("If a link contains any of these parameters, Decrumb leaves the entire link unchanged to avoid breaking its signature.")
                    .font(.callout).foregroundStyle(.secondary)
                parameterNames(rules.protectedParameters)
            }
            section("What stays unchanged", icon: "equal.circle") {
                Text("Parameters not covered by a Remove rule stay in the link. Decrumb does not fetch links, expand short links or follow redirects. Paths and fragments (the part after #) stay untouched.")
                    .font(.callout).foregroundStyle(.secondary)
                Text("A listed domain can still have nothing to remove. If nothing is removed, no clean-link note is created. Try a link to see what your current settings would change.")
                    .font(.callout).foregroundStyle(.secondary)
            }
        }.padding(24)
    }

    private func section<Content: View>(_ title: String, icon: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 13) {
            Label(title, systemImage: icon).font(.headline)
            content()
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.primary.opacity(0.06), lineWidth: 1))
    }

    private func parameterNames(_ names: [String]) -> some View {
        LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)], alignment: .leading, spacing: 7) {
            ForEach(names, id: \.self) { name in
                Text(name).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func parameterRow(_ title: String, names: [String]) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(title).font(.callout).foregroundStyle(.secondary).frame(width: 52, alignment: .leading)
            Text(names.joined(separator: ", ")).font(.system(.callout, design: .monospaced))
                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        }
    }
}
