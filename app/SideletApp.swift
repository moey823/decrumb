// SPDX-License-Identifier: AGPL-3.0-only
import AppKit
import SwiftUI
import CoreImage

struct UserRule: Codable, Identifiable, Equatable {
    var id = UUID()
    var site = ""
    var remove: [String] = []
    var keep: [String] = []
    enum CodingKeys: String, CodingKey { case site, remove, keep }
}

struct Settings: Codable, Equatable {
    var mode = "all"
    var baseURLs: [String] = []
    var excludedURLs: [String] = []
    var rules: [UserRule] = []
    enum CodingKeys: String, CodingKey { case mode, baseURLs, excludedURLs, rules }
    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decode(String.self, forKey: .mode)
        baseURLs = try c.decode([String].self, forKey: .baseURLs)
        excludedURLs = try c.decodeIfPresent([String].self, forKey: .excludedURLs) ?? []
        rules = try c.decodeIfPresent([UserRule].self, forKey: .rules) ?? []
    }
}

struct RuleFile: Codable { var version: Int; var settings: Settings }
struct NotesOptions: Codable, Equatable {
    var include_sender = true
    var cleanup_mode = "manual"
    var lifetime_hours = 6
    var sweep_hours = 12
    var discard_on_pause = false
}
struct GeneratedNote: Decodable, Identifiable {
    var id: String
    var marker: String
    var sent_at: Double?
    var expires_at: Double?
    var state: String
    var lifetime_hours: Int?
    var attempts: Int
    var can_cleanup: Bool
    var label: String {
        switch state {
        case "available": return lifetime_hours == 0 ? "Keep until manually removed" : "Saved in Note to Self"
        case "cleanup_pending", "deleting": return "Removal queued"
        case "deletion_requested": return "Removal request accepted"
        case "offline": return "Waiting to retry"
        case "delete_uncertain": return "Removal unconfirmed"
        case "cleanup_failed": return "Removal needs attention"
        case "too_old": return "Outside supported removal window"
        case "account_mismatch": return "Belongs to a different linked account"
        case "unmanageable": return "No confirmed send receipt"
        case "pending_send": return "Waiting to send"
        case "cancelled": return "Cancelled before sending"
        case "expired": return "Expired before sending"
        default: return "Unavailable"
        }
    }
}
struct PreviewChange: Identifiable {
    let id = UUID()
    let original: String
    let cleaned: String
    let removed: [String]
}
struct AppError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

enum Backend {
    static let helpers = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers")
    static let root = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/SideletLinkCleaner")
    static func process(_ command: String) -> Process {
        let p = Process()
        p.executableURL = helpers.appendingPathComponent("sidelet-worker")
        p.arguments = ["--root", root.path, "--resources", helpers.path, command]
        p.standardError = FileHandle.nullDevice
        return p
    }
    static func request(_ command: String, input: Data? = nil) async throws -> [String: Any] {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let p = process(command), output = Pipe(), stdin = Pipe()
                p.standardOutput = output
                p.standardInput = stdin
                do {
                    try p.run()
                    if let input { try stdin.fileHandleForWriting.write(contentsOf: input) }
                    try stdin.fileHandleForWriting.close()
                    // Drain while running; output is bounded by the command contract.
                    let data = output.fileHandleForReading.readDataToEndOfFile()
                    p.waitUntilExit()
                    let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
                    if p.terminationStatus != 0 || result["error"] != nil {
                        throw AppError(message: result["error"] as? String ?? "Decrumb could not complete this action. Try again.")
                    }
                    continuation.resume(returning: result)
                } catch {
                    if p.isRunning { p.terminate() }
                    continuation.resume(throwing: AppError(message: (error as? AppError)?.message ?? "The bundled worker could not start. Rebuild or reinstall Decrumb."))
                }
            }
        }
    }
}

@MainActor final class AppModel: ObservableObject {
    @Published var page = "overview"
    @Published var linked = false
    @Published var paused = true
    @Published var state = "not_started"
    @Published var settings = Settings()
    @Published var startAtLogin = false
    @Published var busy = false
    @Published var loading = true
    @Published var pairing = false
    @Published var qr: NSImage?
    @Published var error: String?
    @Published var notice: String?
    @Published var sample = "https://www.instagram.com/p/example/?igsh=share&img_index=2"
    @Published var changes: [PreviewChange] = []
    @Published var counts: [String: Int] = [:]
    @Published var metrics: [String: Int] = [:]
    @Published var updatedAt: Double?
    @Published var needsAttention = false
    @Published var dirty = false
    @Published var notesOptions = NotesOptions()
    @Published var notesDirty = false
    @Published var notes: [GeneratedNote] = []
    @Published var noteCounts: [String: Int] = [:]
    let demo = CommandLine.arguments.contains("--demo") || CommandLine.arguments.contains("--demo-connected")
    private var pairProcess: Process?
    private var pairToken = UUID()
    private var pairCancelled = false
    @Published var attemptedPairing = false
    private var timer: Timer?
    private var refreshing = false
    private var statusWatcher: WorkerStatusWatcher?
    private var configModifiedAt: Date?
    var onChange: (() -> Void)?

    var statusTitle: String {
        if pairing { return "Waiting for your phone" }
        if !linked { return "Ready to connect" }
        if paused { return "Paused" }
        switch state {
        case "running": return "Cleaning is on"
        case "starting": return "Starting up"
        case "error", "stale": return "Needs attention"
        default: return "Worker is stopped"
        }
    }
    var running: Bool { linked && !paused && ["running", "starting"].contains(state) }

    func start() {
        if demo {
            linked = CommandLine.arguments.contains("--demo-connected")
            paused = !linked
            state = linked ? "running" : "not_started"
            counts = linked ? ["sent": 24, "pending": 0] : [:]
            if linked {
                let now = Date().timeIntervalSince1970 * 1000
                notes = [GeneratedNote(id: "decrumb_demo_a1b2", marker: "decrumb_demo_a1b2", sent_at: now - 3600000,
                                       expires_at: nil, state: "available", lifetime_hours: 0, attempts: 0, can_cleanup: true)]
                noteCounts = ["total": 1, "manageable": 1, "available": 1]
            }
            loading = false
            return
        }
        Task { [self] in
            do { applySnapshot(try await Backend.request("bootstrap"), loadSettings: true) }
            catch { self.error = error.localizedDescription }
            loading = false
            statusWatcher = WorkerStatusWatcher(root: Backend.root) { [weak self] in
                Task { @MainActor in await self?.refresh() }
            }
            // File changes drive updates. This coarse timer only detects a stalled worker.
            timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
                Task { @MainActor in await self?.refresh() }
            }
            timer?.tolerance = 10
            await refresh()
            onChange?()
        }
    }
    func applySnapshot(_ value: [String: Any], loadSettings: Bool = false) {
        configModifiedAt = configModificationDate()
        linked = value["linked"] as? Bool ?? false
        paused = value["paused"] as? Bool ?? true
        state = value["state"] as? String ?? "not_started"
        counts = value["counts"] as? [String: Int] ?? [:]
        metrics = value["metrics"] as? [String: Int] ?? [:]
        noteCounts = value["note_counts"] as? [String: Int] ?? noteCounts
        needsAttention = value["needs_attention"] as? Bool ?? false
        updatedAt = value["updated_at"] as? Double
        if loadSettings, let raw = value["settings"], let data = try? JSONSerialization.data(withJSONObject: raw), let decoded = try? JSONDecoder().decode(Settings.self, from: data) {
            settings = decoded
            startAtLogin = value["start_at_login"] as? Bool ?? false
            dirty = false
        }
        if (loadSettings || !notesDirty), let raw = value["notes_options"],
           let data = try? JSONSerialization.data(withJSONObject: raw), let decoded = try? JSONDecoder().decode(NotesOptions.self, from: data) {
            notesOptions = decoded
        }
        onChange?()
    }
    private func configModificationDate() -> Date? {
        (try? Backend.root.appendingPathComponent("config.json").resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
    }
    func refresh() async {
        guard !demo, !busy, !pairing, !refreshing, !loading else { return }
        refreshing = true
        defer { refreshing = false }
        // Explicit configuration changes need one bridge call, including when paused.
        // Heartbeats and idle refreshes never launch a process.
        if configModificationDate() != configModifiedAt {
            do { applySnapshot(try await Backend.request("snapshot")) }
            catch { self.error = error.localizedDescription }
        }
        guard linked, !paused else { return }
        if let value = WorkerStatus.read(from: Backend.root) {
            state = value.state ?? "not_started"
            counts = value.counts ?? [:]
            metrics = value.metrics ?? [:]
            noteCounts = value.note_counts ?? noteCounts
            updatedAt = value.updated_at
            needsAttention = value.needsAttention
            onChange?()
        } else {
            state = "stale"
            needsAttention = true
            onChange?()
        }
    }
    func toggle() {
        guard !busy, !pairing else { return }
        if demo { paused.toggle(); state = paused ? "stopped" : "running"; onChange?(); return }
        busy = true; error = nil; notice = nil
        Task {
            defer { busy = false; onChange?() }
            do { applySnapshot(try await Backend.request(paused || !running ? "resume" : "pause")) }
            catch { self.error = error.localizedDescription }
        }
    }
    func draft() -> Settings {
        var value = settings
        func nonempty(_ values: [String]) -> [String] { values.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } }
        value.baseURLs = nonempty(value.baseURLs)
        value.excludedURLs = nonempty(value.excludedURLs)
        value.rules = value.rules.map { var rule = $0; rule.remove = nonempty(rule.remove); rule.keep = nonempty(rule.keep); return rule }
        return value
    }
    func save() {
        guard !busy, !pairing else { return }
        busy = true; error = nil; notice = nil
        Task {
            defer { busy = false }
            do {
                let raw = try JSONSerialization.jsonObject(with: JSONEncoder().encode(draft()))
                let input = try JSONSerialization.data(withJSONObject: ["settings": raw, "start_at_login": startAtLogin])
                if demo { _ = try await localPreview(text: ""); dirty = false; notice = "Rules validated. Demo settings stay in memory."; return }
                applySnapshot(try await Backend.request("apply", input: input), loadSettings: true)
                notice = "Settings saved. Previously queued links were cleared."
            } catch { self.error = error.localizedDescription }
        }
    }
    func localPreview(text: String) async throws -> [String: Any] {
        let raw = try JSONSerialization.jsonObject(with: JSONEncoder().encode(draft()))
        let data = try JSONSerialization.data(withJSONObject: ["text": text, "settings": raw])
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let p = Process(), stdin = Pipe(), stdout = Pipe()
                p.executableURL = Backend.helpers.appendingPathComponent("url-cleaner")
                p.standardInput = stdin; p.standardOutput = stdout; p.standardError = FileHandle.nullDevice
                let deadline = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
                deadline.schedule(deadline: .now() + 10)
                deadline.setEventHandler { if p.isRunning { p.terminate() } }
                deadline.resume()
                defer { deadline.cancel() }
                do {
                    try p.run(); try stdin.fileHandleForWriting.write(contentsOf: data); try stdin.fileHandleForWriting.close()
                    let result = stdout.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
                    guard p.terminationStatus == 0, let object = try JSONSerialization.jsonObject(with: result) as? [String: Any] else { throw AppError(message: "Check your site names and parameter names.") }
                    continuation.resume(returning: object)
                } catch {
                    if p.isRunning { p.terminate(); p.waitUntilExit() }
                    continuation.resume(throwing: AppError(message: "Preview could not finish. Check your rules and try again."))
                }
            }
        }
    }
    func preview() {
        guard !busy else { return }
        busy = true; error = nil; notice = nil
        Task {
            defer { busy = false }
            do {
                let result = try await localPreview(text: sample)
                changes = (result["changes"] as? [[String: Any]] ?? []).map {
                    PreviewChange(original: $0["original"] as? String ?? "", cleaned: $0["cleaned"] as? String ?? "", removed: $0["removed"] as? [String] ?? [])
                }
                if changes.isEmpty { notice = "No HTTP or HTTPS links found in this sample." }
            } catch { self.error = error.localizedDescription }
        }
    }

    private func applyNotes(_ value: [String: Any]) {
        noteCounts = value["note_counts"] as? [String: Int] ?? noteCounts
        if let raw = value["notes"], let data = try? JSONSerialization.data(withJSONObject: raw),
           let decoded = try? JSONDecoder().decode([GeneratedNote].self, from: data) { notes = decoded }
    }
    func loadNotes() {
        guard !demo, !busy, !loading else { return }
        busy = true; error = nil
        Task {
            defer { busy = false }
            do { applyNotes(try await Backend.request("notes-list")) }
            catch { self.error = error.localizedDescription }
        }
    }
    func noteAction(_ command: String, values: [String: Any] = [:]) {
        guard !busy, !pairing, !loading else { return }
        busy = true; error = nil; notice = nil
        Task {
            defer { busy = false; onChange?() }
            do {
                var input = values
                if command == "notes-settings" {
                    input["notes"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode(notesOptions))
                }
                if demo {
                    if command == "notes-settings" { notesDirty = false }
                    notice = "Preview only. No Signal messages or local records were changed."
                    return
                }
                let result = try await Backend.request(command, input: try JSONSerialization.data(withJSONObject: input))
                applySnapshot(result); applyNotes(result)
                switch command {
                case "notes-settings": notesDirty = false; notice = "Note preferences saved. Default lifetimes apply to new notes."
                case "clear-queue": notice = "Cleared \(result["changed"] as? Int ?? 0) queued links from this Mac."
                case "cleanup":
                    let queued = noteCounts["cleanup_pending", default: 0] + noteCounts["offline", default: 0] + noteCounts["deleting", default: 0]
                    notice = result["cleanup_notice"] as? String ?? (queued > 0
                        ? "Removal requests saved. \(queued) remain queued; resume cleaning or retry cleanup to process them."
                        : "Removal requests processed. Accepted means transmitted; Signal may leave a deleted-message marker.")
                default: notice = "This note’s lifetime was updated."
                }
            } catch { self.error = error.localizedDescription }
        }
    }
    func connect() {
        guard !pairing, !busy, !loading else { return }
        error = nil; notice = nil; pairing = true; qr = nil; pairCancelled = false; attemptedPairing = true
        if demo {
            let filter = CIFilter(name: "CIQRCodeGenerator")!
            filter.setValue(Data("Decrumb preview only — not a Signal pairing code".utf8), forKey: "inputMessage")
            if let image = filter.outputImage, let cg = CIContext(options: [.useSoftwareRenderer: true]).createCGImage(image, from: image.extent) {
                qr = NSImage(cgImage: cg, size: NSSize(width: 240, height: 240))
            }
            return
        }
        let p = Backend.process("pair"), output = Pipe(), token = UUID()
        pairToken = token; pairProcess = p
        p.standardOutput = output; p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch { self.error = "Could not start pairing. Try again."; pairing = false; pairProcess = nil; return }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var pending = Data()
            do {
                while true {
                    let chunk = output.fileHandleForReading.availableData
                    if chunk.isEmpty { break }
                    pending.append(chunk)
                    while let newline = pending.firstIndex(of: 10) {
                        let line = pending[..<newline]
                        pending.removeSubrange(...newline)
                        let value = (try? JSONSerialization.jsonObject(with: Data(line))) as? [String: Any] ?? [:]
                        Task { @MainActor [weak self] in
                            guard let self, self.pairToken == token else { return }
                            if let message = value["error"] as? String, !self.pairCancelled { self.error = message }
                            if value["event"] as? String == "qr_ready" {
                                self.qr = NSImage(contentsOf: Backend.root.appendingPathComponent("pairing.png"))
                            }
                            if value["event"] as? String == "linked" {
                                self.linked = true; self.qr = nil; self.notice = "Signal connected. Turn cleaning on when you’re ready."
                            }
                        }
                    }
                }
                p.waitUntilExit()
            }
            Task { @MainActor [weak self] in
                guard let self, self.pairToken == token else { return }
                self.pairing = false; self.qr = nil; self.pairProcess = nil
                if !self.linked && self.error == nil && !self.pairCancelled { self.error = "Pairing ended. Generate a new code to try again." }
                do { self.applySnapshot(try await Backend.request("snapshot")) }
                catch { if !self.pairCancelled { self.error = error.localizedDescription } }
                self.onChange?()
            }
        }
    }
    func cancelPairing() {
        if demo { pairing = false; qr = nil; return }
        // Keep pairing busy until the child has cleaned up the QR and released its lock.
        pairCancelled = true
        if let process = pairProcess, process.isRunning { process.terminate() }
        qr = nil
    }
    func exportRules() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "Decrumb Rules.json"
        panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do { try JSONEncoder().encode(RuleFile(version: 1, settings: draft())).write(to: url, options: .atomic) }
        catch { self.error = "Could not export rules to that location." }
    }
    func importRules() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let data = try Data(contentsOf: url)
            guard data.count <= 2 * 1024 * 1024 else { throw AppError(message: "Rules file is too large.") }
            let file = try JSONDecoder().decode(RuleFile.self, from: data)
            guard file.version == 1 else { throw AppError(message: "This rules file uses an unsupported version.") }
            settings = file.settings; dirty = true; changes = []; notice = "Rules imported. Preview or save to validate and apply them."
        } catch { self.error = (error as? AppError)?.message ?? "This is not a valid Decrumb rules file." }
    }
}

private let accent = Color(red: 0.29, green: 0.34, blue: 0.82)

struct RootView: View {
    @ObservedObject var model: AppModel
    @State private var confirmAllRemoval = false
    @State private var confirmQueueClear = false
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 28) {
                HStack(spacing: 10) {
                    Image(systemName: "link").font(.system(size: 23, weight: .semibold)).foregroundStyle(accent)
                    Text("Decrumb").font(.system(size: 22, weight: .semibold, design: .rounded))
                }.padding(.top, 22)
                VStack(spacing: 6) {
                    navigation("overview", "Overview", "circle.grid.2x2")
                    navigation("rules", "Cleaning rules", "slider.horizontal.3")
                    navigation("notes", "Saved notes", "note.text")
                    navigation("preview", "Try a link", "wand.and.stars")
                }
                Spacer()
                VStack(alignment: .leading, spacing: 8) {
                    Label(model.statusTitle, systemImage: model.running ? "checkmark.circle.fill" : "circle.dashed")
                        .font(.system(size: 11, weight: .medium)).foregroundStyle(model.running ? Color.green : Color.secondary)
                    Text("PRIVATE BY DESIGN").font(.system(size: 9, weight: .semibold)).tracking(1.2).foregroundStyle(.tertiary)
                    Text("Your links stay on your Mac until sent to Note to Self.").font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    if model.demo { Text("OFFLINE PREVIEW").font(.system(size: 10, weight: .bold)).foregroundStyle(accent) }
                }.padding(.bottom, 22)
            }.padding(.horizontal, 20).frame(width: 180).frame(maxHeight: .infinity)
                .background(Color(nsColor: .controlBackgroundColor))
            Divider()
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        if model.page == "overview" { overview }
                        else if model.page == "rules" { rules }
                        else if model.page == "notes" { savedNotes }
                        else { preview }
                        if let error = model.error {
                            Label(error, systemImage: "exclamationmark.circle.fill").foregroundStyle(.red).font(.callout).textSelection(.enabled)
                        }
                        if let notice = model.notice { Label(notice, systemImage: "checkmark.circle").foregroundStyle(.secondary).font(.callout) }
                    }.padding(32).frame(maxWidth: .infinity, alignment: .leading)
                }
                if model.page == "rules" || model.page == "notes" {
                    Divider()
                    HStack {
                        Text((model.page == "notes" ? model.notesDirty : model.dirty) ? "Unsaved changes" : "Preferences saved").foregroundStyle(.secondary).font(.caption)
                        Spacer()
                        Button("Save settings") {
                            if model.page == "notes" { model.noteAction("notes-settings") } else { model.save() }
                        }.buttonStyle(.borderedProminent).tint(accent).disabled(model.busy || model.pairing || model.loading)
                    }.padding(18)
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
        }.frame(minWidth: 830, minHeight: 650).tint(accent)
            .onChange(of: model.page) { if model.page == "notes" { model.loadNotes() } }
            .confirmationDialog("Request removal of all eligible Decrumb notes?", isPresented: $confirmAllRemoval) {
                Button("Request removal", role: .destructive) { model.noteAction("cleanup") }
            } message: {
                Text("Includes notes marked Keep. Only notes with Decrumb’s recorded send receipts are targeted. Personal notes and older untracked notes are untouched. Signal may leave deleted-message markers.")
            }
            .confirmationDialog("Discard queued links?", isPresented: $confirmQueueClear) {
                Button("Clear queued links", role: .destructive) { model.noteAction("clear-queue") }
            } message: {
                Text("Clears unsent links from this Mac. Notes already sent to Signal are unaffected.")
            }
    }
    func navigation(_ id: String, _ title: String, _ icon: String) -> some View {
        Button { model.page = id; model.error = nil; model.notice = nil } label: {
            Label(title, systemImage: icon).font(.system(size: 13, weight: model.page == id ? .semibold : .regular))
                .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 10).padding(.horizontal, 10)
                .background(model.page == id ? accent.opacity(0.1) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
                .foregroundStyle(model.page == id ? accent : .primary)
        }.buttonStyle(.plain)
    }
    func heading(_ eyebrow: String, _ title: String, _ subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(eyebrow).font(.system(size: 10, weight: .semibold)).tracking(1.6).foregroundStyle(accent)
            Text(title).font(.system(size: 29, weight: .semibold, design: .rounded))
            Text(subtitle).font(.system(size: 13)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
    }
    func card<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 16, content: content).padding(22).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.primary.opacity(0.06), lineWidth: 1))
    }
    var overview: some View {
        VStack(alignment: .leading, spacing: 24) {
            heading("A LITTLE LESS TRACKING", "Clean links. Quietly.", "Decrumb removes known tracking parameters from incoming Signal links and saves the clean version to Note to Self.")
            if model.loading { ProgressView("Preparing Decrumb…").padding() }
            else if !model.linked { onboarding }
            else {
                card {
                    HStack {
                        Image(systemName: model.running ? "checkmark.shield.fill" : "pause.circle.fill").font(.system(size: 32)).foregroundStyle(model.running ? Color.green : accent)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(model.statusTitle).font(.title3.weight(.semibold))
                            Text(model.running ? "Listening for new incoming links." : "Resume whenever you’re ready.").font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button(model.running ? "Pause" : "Resume", action: model.toggle).buttonStyle(.borderedProminent).disabled(model.busy)
                    }
                    Divider()
                    HStack(spacing: 32) {
                        metric("Sent", model.counts["sent", default: 0])
                        metric("Queued", model.counts["pending", default: 0])
                        metric("Unconfirmed", model.counts["uncertain", default: 0])
                    }
                    Text("Sent means Signal acknowledged the note; it doesn’t confirm display on your phone.").font(.caption).foregroundStyle(.secondary)
                }
                if model.needsAttention {
                    card {
                        Label("Some work needs attention", systemImage: "exclamationmark.triangle").font(.headline).foregroundStyle(.orange)
                        Text("Delivery can be interrupted by a lost connection, an unlinked device, or a full queue. Unconfirmed sends are never automatically repeated.").font(.callout).foregroundStyle(.secondary)
                        HStack(spacing: 24) {
                            metric("Dropped", model.metrics["receive_dropped", default: 0] + model.metrics["outbox_dropped", default: 0] + model.metrics["oversize_dropped", default: 0])
                            metric("Cleanup errors", model.metrics["helper_failures", default: 0])
                        }
                    }
                }
                card {
                    Label("Connected as a linked device", systemImage: "iphone.and.arrow.forward").font(.headline)
                    Text("Manage or revoke Decrumb in Signal → Settings → Linked devices. Your Mac must be awake and online for cleaning to work.").font(.callout).foregroundStyle(.secondary)
                    if let timestamp = model.updatedAt {
                        Text("Last worker update: \(Date(timeIntervalSince1970: timestamp / 1000).formatted(date: .omitted, time: .shortened))").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            HStack(alignment: .top, spacing: 22) {
                promise("lock.shield", "Stays local", "No link fetching or tracking service.")
                promise("note.text", "Only Note to Self", "Never replies to people or groups.")
                promise("eye.slash", "Respects privacy", "Skips disappearing and spoiler messages.")
            }
        }
    }
    var onboarding: some View {
        card {
            if model.pairing {
                HStack(alignment: .top, spacing: 24) {
                    Group {
                        if let qr = model.qr { Image(nsImage: qr).interpolation(.none).resizable().scaledToFit().padding(12).background(.white) }
                        else { ProgressView("Generating your code…").frame(maxWidth: .infinity, maxHeight: .infinity) }
                    }.frame(width: 200, height: 200).clipShape(RoundedRectangle(cornerRadius: 10))
                    VStack(alignment: .leading, spacing: 14) {
                        Text("Scan with Signal").font(.title3.weight(.semibold))
                        Text("1. Open Signal on your phone.\n\n2. Go to Settings → Linked devices → Link a new device.\n\n3. Scan this code and confirm.").font(.callout).foregroundStyle(.secondary)
                        Button("Cancel", action: model.cancelPairing)
                    }
                }
                Text(model.demo ? "This is a preview code. It cannot link a Signal account." : "This code expires shortly. If it expires, generate a new one here.").font(.caption).foregroundStyle(.secondary)
            } else {
                Label("Connect your Signal account", systemImage: "qrcode").font(.title3.weight(.semibold))
                Text("Scan a QR code with your phone to add Decrumb as a linked device. Your existing Signal app stays exactly where it is.").font(.callout).foregroundStyle(.secondary)
                Button(model.attemptedPairing ? "Generate a new code" : "Connect Signal", action: model.connect).buttonStyle(.borderedProminent).controlSize(.large).disabled(model.busy)
                Text("Requires an existing Signal account. No phone number or password to type here.").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
    func metric(_ title: String, _ value: Int) -> some View {
        VStack(alignment: .leading, spacing: 4) { Text(value.formatted()).font(.system(size: 25, weight: .medium, design: .rounded)); Text(title).font(.caption).foregroundStyle(.secondary) }
    }
    func promise(_ icon: String, _ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 7) { Image(systemName: icon).foregroundStyle(accent); Text(title).font(.system(size: 12, weight: .semibold)); Text(text).font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }.frame(maxWidth: .infinity, alignment: .leading)
    }
    func lines(_ value: Binding<[String]>) -> Binding<String> {
        Binding(get: { value.wrappedValue.joined(separator: "\n") }, set: { value.wrappedValue = $0.components(separatedBy: "\n"); model.dirty = true })
    }
    func params(_ value: Binding<[String]>) -> Binding<String> {
        Binding(get: { value.wrappedValue.joined(separator: ", ") }, set: { value.wrappedValue = $0.components(separatedBy: ",").map { $0.trimmingCharacters(in: .whitespaces) }; model.dirty = true })
    }
    var rules: some View {
        VStack(alignment: .leading, spacing: 22) {
            heading("YOUR LINKS, YOUR RULES", "A careful clean.", "Built-in rules remove known trackers. Add site-specific rules when you want more control.")
            card {
                Text("Where to clean").font(.headline)
                Picker("Mode", selection: $model.settings.mode) { Text("All sites").tag("all"); Text("Selected sites").tag("selected"); Text("Off").tag("off") }.pickerStyle(.segmented).labelsHidden().onChange(of: model.settings.mode) { model.dirty = true }
                if model.settings.mode == "selected" {
                    Text("Selected sites · one per line").font(.caption).foregroundStyle(.secondary)
                    TextField("example.com\nexample.org/news", text: lines($model.settings.baseURLs), axis: .vertical).lineLimit(3...6).textFieldStyle(.roundedBorder)
                }
                Text("Excluded sites · one per line").font(.caption).foregroundStyle(.secondary)
                TextField("Sites to always leave untouched", text: lines($model.settings.excludedURLs), axis: .vertical).lineLimit(2...5).textFieldStyle(.roundedBorder)
                Text("A site includes its subdomains. You can also specify a path, such as example.com/news.").font(.caption).foregroundStyle(.secondary)
            }
            card {
                HStack { Text("Custom parameters").font(.headline); Spacer(); Button { model.settings.rules.append(UserRule()); model.dirty = true } label: { Label("Add site", systemImage: "plus") } }
                if model.settings.rules.isEmpty { Text("The built-in rules are a good starting point. Add a site to remove extra parameters or preserve a parameter it needs.").font(.callout).foregroundStyle(.secondary) }
                ForEach($model.settings.rules) { $rule in
                    VStack(alignment: .leading, spacing: 9) {
                        HStack {
                            TextField("Site, e.g. example.com", text: $rule.site).textFieldStyle(.roundedBorder).onChange(of: rule.site) { model.dirty = true }
                            Button { model.settings.rules.removeAll { $0.id == rule.id }; model.dirty = true } label: { Image(systemName: "minus.circle") }.help("Remove this site rule")
                        }
                        HStack { Text("Remove").frame(width: 62, alignment: .leading); TextField("share_id, campaign", text: params($rule.remove)).textFieldStyle(.roundedBorder) }
                        HStack { Text("Keep").frame(width: 62, alignment: .leading); TextField("ref", text: params($rule.keep)).textFieldStyle(.roundedBorder) }
                        Divider()
                    }.font(.callout)
                }
                Text("Exact parameter names, separated by commas. Keep wins over remove. Recognized signed links are always protected.").font(.caption).foregroundStyle(.secondary)
            }
            card {
                Toggle("Start Decrumb at login", isOn: $model.startAtLogin).onChange(of: model.startAtLogin) { model.dirty = true }
                Text("Pausing persists across login. Your Mac must be awake and online.").font(.caption).foregroundStyle(.secondary)
                Divider()
                HStack { Button("Import rules…", action: model.importRules); Button("Export rules…", action: model.exportRules); Spacer(); Button("Restore defaults") { model.settings = Settings(); model.dirty = true } }
                Text("Saving rule changes clears links queued under the previous rules.").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
    var preview: some View {
        VStack(alignment: .leading, spacing: 22) {
            heading("SEE WHAT CHANGES", "Try a link.", "Preview your current rules, including unsaved changes. Nothing is opened, sent to Signal, or saved.")
            card {
                TextField("Paste a link or sample text", text: $model.sample, axis: .vertical).lineLimit(3...7).textFieldStyle(.roundedBorder)
                HStack { Button("Preview cleanup", action: model.preview).buttonStyle(.borderedProminent).disabled(model.busy); Spacer(); Button("Clear") { model.sample = ""; model.changes = [] } }
            }
            ForEach(model.changes) { change in
                card {
                    Label(change.removed.isEmpty ? "Unchanged" : "Tracking removed", systemImage: change.removed.isEmpty ? "equal.circle" : "checkmark.circle.fill").font(.headline).foregroundStyle(change.removed.isEmpty ? Color.secondary : Color.green)
                    Text(change.original).font(.system(.callout, design: .monospaced)).foregroundStyle(.secondary).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    if !change.removed.isEmpty {
                        Image(systemName: "arrow.down").foregroundStyle(.tertiary)
                        Text(change.cleaned).font(.system(.callout, design: .monospaced)).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                        Text("Removed: " + change.removed.joined(separator: ", ")).font(.caption).foregroundStyle(.secondary)
                    } else { Text("No removable parameters matched, or this link is protected by your rules.").font(.caption).foregroundStyle(.secondary) }
                }
            }
        }
    }

    var savedNotes: some View {
        VStack(alignment: .leading, spacing: 22) {
            heading("A TIDIER NOTE TO SELF", "Keep what you need.", "Every new Decrumb note has a searchable code. Choose a lifetime, run regular cleanup, or request removal yourself.")
            if model.busy { ProgressView("Updating saved notes…") }
            card {
                Text("Make notes recognizable").font(.headline)
                Toggle("Include the original sender’s name", isOn: $model.notesOptions.include_sender)
                    .onChange(of: model.notesOptions.include_sender) { model.notesDirty = true }
                Text("Uses the available Signal display name. Unknown senders stay unnamed; phone numbers and account IDs are never substituted.").font(.caption).foregroundStyle(.secondary)
                Text("Decrumb · From Alex\nhttps://example.com/article\n#decrumb_a1b2c3…")
                    .font(.system(.callout, design: .monospaced)).padding(12).frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 8))
                Text("The code helps you search in Signal. Decrumb uses its private send records to identify which notes it can remove.").font(.caption).foregroundStyle(.secondary)
            }
            card {
                Text("Automatic cleanup").font(.headline)
                Picker("Cleanup", selection: $model.notesOptions.cleanup_mode) {
                    Text("Manual").tag("manual"); Text("Note lifetime").tag("lifetime"); Text("Regular sweep").tag("schedule")
                }.pickerStyle(.segmented).labelsHidden().onChange(of: model.notesOptions.cleanup_mode) { model.notesDirty = true }
                if model.notesOptions.cleanup_mode == "lifetime" {
                    Picker("Remove new notes after", selection: $model.notesOptions.lifetime_hours) {
                        Text("1 hour").tag(1); Text("6 hours").tag(6); Text("12 hours").tag(12); Text("23 hours").tag(23)
                    }.onChange(of: model.notesOptions.lifetime_hours) { model.notesDirty = true }
                    Text("Each new note gets its own deadline from its send time. Change an individual note below.").font(.caption).foregroundStyle(.secondary)
                } else if model.notesOptions.cleanup_mode == "schedule" {
                    Picker("Sweep every", selection: $model.notesOptions.sweep_hours) {
                        Text("1 hour").tag(1); Text("6 hours").tag(6); Text("12 hours").tag(12)
                    }.onChange(of: model.notesOptions.sweep_hours) { model.notesDirty = true }
                    Text("Requests removal of eligible notes at each interval while cleaning is on. Notes explicitly marked Keep are excluded.").font(.caption).foregroundStyle(.secondary)
                } else {
                    Text("New notes have no deadline. Existing note deadlines continue; choose Keep below to cancel one.").font(.callout).foregroundStyle(.secondary)
                }
                Divider()
                Label("Signal supports removal requests within 24 hours of sending.", systemImage: "clock").font(.callout)
                Text("Automatic cleanup needs this Mac awake, connected and cleaning enabled. Pauses or time offline can miss the window. Accepted requests may leave a “message deleted” marker and aren’t proof that every device removed the content. Your Note to Self disappearing-message timer is unchanged.").font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            card {
                Text("Local queue").font(.headline)
                Toggle("Discard unsent links when I pause", isOn: $model.notesOptions.discard_on_pause)
                    .onChange(of: model.notesOptions.discard_on_pause) { model.notesDirty = true }
                HStack {
                    Text("Unsent cleaned links are temporarily stored on this Mac.").font(.callout).foregroundStyle(.secondary)
                    Spacer()
                    Button("Clear queued links…") { confirmQueueClear = true }.disabled(model.busy || model.pairing || model.loading)
                }
            }
            card {
                HStack {
                    Text("Tracked notes").font(.headline)
                    Spacer()
                    Button("Refresh", action: model.loadNotes).disabled(model.busy || model.loading)
                    Button("Remove all eligible…") { confirmAllRemoval = true }.disabled(!model.linked || model.busy || model.pairing || model.loading || model.noteCounts["manageable", default: 0] == 0)
                }
                HStack(spacing: 24) {
                    metric("Tracked", model.noteCounts["total", default: 0])
                    metric("Request accepted", model.noteCounts["deletion_requested", default: 0])
                    metric("Outside window", model.noteCounts["too_old", default: 0])
                }
                if model.paused {
                    Text("While paused, each removal action attempts up to three queued notes. Repeat the action, or resume cleaning to process the remaining requests.").font(.caption).foregroundStyle(.secondary)
                }
                if model.noteCounts["legacy_unmanageable", default: 0] > 0 {
                    Text("Older notes without saved send receipts must be removed in Signal.").font(.caption).foregroundStyle(.secondary)
                }
                if model.notes.isEmpty { Text("New Decrumb notes will appear here. This list stores timing and status, without a copy of the link or sender name.").font(.callout).foregroundStyle(.secondary) }
                LazyVStack(alignment: .leading, spacing: 16) {
                    ForEach(model.notes) { note in
                        noteRow(note)
                        Divider()
                    }
                }
                if model.noteCounts["total", default: 0] > model.notes.count {
                    Text("Showing the most recent \(model.notes.count) records. Remove all eligible includes all tracked records.").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }
    func noteRow(_ note: GeneratedNote) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(note.marker.hasPrefix("#") ? note.marker : "#" + note.marker).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                Spacer()
                if note.can_cleanup {
                    Menu("Lifetime") {
                        Button("Keep until manually removed") { model.noteAction("note-lifetime", values: ["id": note.id, "hours": 0]) }
                        ForEach([1, 6, 12, 23], id: \.self) { hours in
                            Button("\(hours) hours from sending") { model.noteAction("note-lifetime", values: ["id": note.id, "hours": hours]) }
                        }
                    }.disabled(model.busy || model.pairing)
                    Button("Request removal") { model.noteAction("cleanup", values: ["ids": [note.id]]) }
                        .disabled(!model.linked || model.busy || model.pairing)
                }
            }
            Text(note.label).font(.callout)
            if let timestamp = note.sent_at {
                Text("Sent \(Date(timeIntervalSince1970: timestamp / 1000).formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary)
            }
            if let timestamp = note.expires_at {
                Text("Removal due \(Date(timeIntervalSince1970: timestamp / 1000).formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let model = AppModel()
    var window: NSWindow!
    var item: NSStatusItem!
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "link", accessibilityDescription: "Decrumb")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 710), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Decrumb"
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: RootView(model: model))
        window.delegate = self
        window.center()
        model.onChange = { [weak self] in self?.updateMenu() }
        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        let showItem = appMenu.addItem(withTitle: "Open Decrumb", action: #selector(show), keyEquivalent: "o"); showItem.target = self
        let settingsItem = appMenu.addItem(withTitle: "Settings…", action: #selector(settings), keyEquivalent: ","); settingsItem.target = self
        appMenu.addItem(.separator())
        let quitItem = appMenu.addItem(withTitle: "Quit Decrumb", action: #selector(quit), keyEquivalent: "q"); quitItem.target = self
        appItem.submenu = appMenu; mainMenu.addItem(appItem)
        let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit; mainMenu.addItem(editItem); NSApp.mainMenu = mainMenu
        updateMenu()
        model.start()
        if !CommandLine.arguments.contains("--background") { show() }
    }
    func updateMenu() {
        let menu = NSMenu()
        menu.addItem(withTitle: model.statusTitle, action: nil, keyEquivalent: "")
        menu.addItem(.separator())
        let open = menu.addItem(withTitle: "Open Decrumb…", action: #selector(show), keyEquivalent: "o"); open.target = self
        if model.linked {
            let toggle = menu.addItem(withTitle: model.running ? "Pause cleaning" : "Resume cleaning", action: #selector(toggle), keyEquivalent: ""); toggle.target = self; toggle.isEnabled = !model.busy
        }
        let settings = menu.addItem(withTitle: "Settings…", action: #selector(settings), keyEquivalent: ","); settings.target = self
        menu.addItem(.separator())
        let quit = menu.addItem(withTitle: model.running ? "Quit interface (keep cleaning)" : "Quit Decrumb", action: #selector(quit), keyEquivalent: "q"); quit.target = self
        item.menu = menu
    }
    @objc func show() { NSApp.activate(ignoringOtherApps: true); window.makeKeyAndOrderFront(nil) }
    @objc func settings() { model.page = "rules"; show() }
    @objc func toggle() { model.toggle() }
    @objc func quit() {
        if model.pairing { model.cancelPairing() }
        NSApp.terminate(nil)
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if model.pairing { model.cancelPairing() }
        return .terminateNow
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { show(); return true }
}

@main enum DecrumbApp {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
