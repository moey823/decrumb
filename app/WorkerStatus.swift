// SPDX-License-Identifier: AGPL-3.0-only
import Foundation
import Dispatch
import Darwin

/// Shared wording for the overview and menu: a stopped connection is not a pause.
struct CleaningPresentation {
    var linked: Bool
    var paused: Bool
    var pairing: Bool = false
    var loading: Bool = false
    var state: String

    var active: Bool { linked && !paused && ["running", "starting"].contains(state) }
    var title: String {
        if loading { return "Preparing Decrumb" }
        if pairing { return "Connecting Signal" }
        if !linked { return "Connect Signal to start" }
        if paused { return "Cleaning is paused" }
        switch state {
        case "running": return "Cleaning is on"
        case "starting": return "Starting cleaning"
        case "error", "stale": return "Connection needs attention"
        default: return "Cleaning has stopped"
        }
    }
    var detail: String {
        if paused { return "Paused for now. Reopen Decrumb or choose Resume cleaning to start again." }
        if state == "starting" { return "Connecting to Signal. Cleaning starts automatically." }
        if state == "running" { return "Cleaned links are saved to Note to Self automatically." }
        return "Decrumb couldn’t start or lost its connection. Check that your Mac is online, then retry."
    }
    var action: String { active ? "Pause cleaning" : (paused ? "Resume cleaning" : "Retry connection") }
    var symbol: String {
        if paused { return "pause.circle.fill" }
        if state == "starting" { return "clock.arrow.circlepath" }
        return state == "running" ? "checkmark.shield.fill" : "exclamationmark.triangle.fill"
    }
}

/// launchd starts asynchronously. Ignore the previous run's status briefly,
/// but never hide a fresh failure or claim startup succeeded without a heartbeat.
func startupState(_ state: String, updatedAt: Double?, requestedAt: Double?, now: Double) -> String {
    if let requestedAt, now - requestedAt < 15_000, (updatedAt ?? 0) < requestedAt { return "starting" }
    return state
}

/// Reads only the worker's content-free status file, never account configuration.
struct WorkerStatus: Decodable {
    var state: String?
    var updated_at: Double?
    var pid: Int32?
    var counts: [String: Int]?
    var metrics: [String: Int]?
    var note_counts: [String: Int]?

    static func read(from root: URL, now: Double = Date().timeIntervalSince1970 * 1000) -> WorkerStatus? {
        do {
            let input = try FileHandle(forReadingFrom: root.appendingPathComponent("status.json"))
            defer { try? input.close() }
            let data = try input.read(upToCount: 65537) ?? Data()
            guard data.count <= 65536 else { return nil }
            var value = try JSONDecoder().decode(Self.self, from: data)
            let states: Set<String> = ["starting", "running", "stopped", "error"]
            guard let state = value.state, states.contains(state) else { return nil }
            value.counts = value.counts?.filter { ["pending", "inflight", "sent", "uncertain", "expired", "cancelled"].contains($0.key) && $0.value >= 0 }
            value.metrics = value.metrics?.filter { ["receive_dropped", "outbox_dropped", "oversize_dropped", "helper_failures", "last_sent_at"].contains($0.key) && $0.value >= 0 }
            value.note_counts = value.note_counts?.filter {
                ["total", "manageable", "legacy_unmanageable", "pending_send", "available", "cleanup_pending", "deleting", "deletion_requested", "offline", "delete_uncertain", "cleanup_failed", "too_old", "unmanageable", "account_mismatch", "cancelled", "expired"].contains($0.key) && $0.value >= 0
            }
            if state == "starting" || state == "running" {
                let alive = value.pid.map { $0 > 0 && (kill($0, 0) == 0 || errno == EPERM) } ?? false
                if !alive || now - (value.updated_at ?? 0) > 90000 { value.state = "stale" }
            }
            return value
        } catch { return nil }
    }

    var needsAttention: Bool {
        ["error", "stale"].contains(state ?? "") || (counts?["uncertain"] ?? 0) > 0 ||
        (metrics ?? [:]).contains { $0.key != "last_sent_at" && $0.value > 0 } ||
        ["delete_uncertain", "cleanup_failed", "account_mismatch"].contains { (note_counts?[$0] ?? 0) > 0 }
    }
}

/// Watch the containing directory because the worker replaces status.json atomically.
final class WorkerStatusWatcher {
    private let source: DispatchSourceFileSystemObject
    init?(root: URL, onChange: @escaping () -> Void) {
        let descriptor = open(root.path, O_EVTONLY)
        guard descriptor >= 0 else { return nil }
        source = DispatchSource.makeFileSystemObjectSource(fileDescriptor: descriptor, eventMask: [.write, .rename, .delete], queue: DispatchQueue(label: "decrumb.status"))
        source.setEventHandler(handler: onChange)
        source.setCancelHandler { close(descriptor) }
        source.resume()
    }
    deinit { source.cancel() }
}
