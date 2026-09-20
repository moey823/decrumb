// SPDX-License-Identifier: AGPL-3.0-only
import Foundation
import Dispatch
import Darwin

@main enum StatusTests {
    static func main() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let path = root.appendingPathComponent("status.json")
        let now = Date().timeIntervalSince1970 * 1000
        func write(_ value: [String: Any]) throws {
            try JSONSerialization.data(withJSONObject: value).write(to: path, options: .atomic)
        }
        let valid: [String: Any] = ["state": "running", "updated_at": now, "pid": getpid(),
            "counts": ["sent": 1, "unrecognized": 20], "metrics": ["last_sent_at": Int64(now)],
            "note_counts": ["available": 1, "private": 20], "ignored_private_field": "synthetic"]
        try write(valid)
        let status = WorkerStatus.read(from: root, now: now)!
        precondition(status.state == "running" && !status.needsAttention)
        precondition(status.counts == ["sent": 1])
        precondition(status.note_counts == ["available": 1])
        precondition(WorkerStatus.read(from: root, now: now + 90001)?.state == "stale")
        try write(["state": "starting", "updated_at": now, "pid": 0])
        precondition(WorkerStatus.read(from: root)?.state == "stale")
        try write(["state": "error", "counts": ["uncertain": 1]])
        precondition(WorkerStatus.read(from: root)?.needsAttention == true)
        try write(["state": "stopped", "note_counts": ["delete_uncertain": 1]])
        precondition(WorkerStatus.read(from: root)?.needsAttention == true)
        try Data(repeating: 65, count: 65537).write(to: path)
        precondition(WorkerStatus.read(from: root) == nil)
        try write(valid)
        let semaphore = DispatchSemaphore(value: 0)
        let watcher = WorkerStatusWatcher(root: root) { semaphore.signal() }!
        try write(["state": "stopped", "counts": ["sent": 2]])
        precondition(semaphore.wait(timeout: .now() + 3) == .success)
        withExtendedLifetime(watcher) {
            precondition(WorkerStatus.read(from: root)?.counts?["sent"] == 2)
        }
        let began = DispatchTime.now().uptimeNanoseconds
        for _ in 0..<1000 { precondition(WorkerStatus.read(from: root) != nil) }
        let microseconds = Double(DispatchTime.now().uptimeNanoseconds - began) / 1_000_000
        print(String(format: "Native status tests passed; 1,000 fixture reads averaged %.2f microseconds each.", microseconds))
    }
}
