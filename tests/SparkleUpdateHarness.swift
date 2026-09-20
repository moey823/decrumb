// SPDX-License-Identifier: AGPL-3.0-only
// Test-only host: real Sparkle and the production AppUpdater, synthetic backend.
import AppKit
import Sparkle
import SwiftUI

struct AppError: LocalizedError {
    var message: String
    var errorDescription: String? { message }
}

@MainActor final class AppModel: ObservableObject {
    var demo = false
    var pairing = false
    var busy = false
    var loading = false
    var dirty = false
    var notesDirty = false
    func applySnapshot(_ snapshot: [String: Any]) {}
}

enum Backend {
    static func request(_ command: String, input: Data? = nil) async throws -> [String: Any] {
        let info = Bundle.main.infoDictionary!
        let process = Process()
        process.executableURL = URL(fileURLWithPath: info["FixturePython"] as! String)
        process.arguments = [info["FixtureBackend"] as! String, command,
                             info["FixtureRoot"] as! String, Bundle.main.bundlePath,
                             String(ProcessInfo.processInfo.processIdentifier)]
        let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        process.standardInput = stdin
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        try stdin.fileHandleForWriting.write(contentsOf: input ?? Data("{}".utf8))
        try stdin.fileHandleForWriting.close()
        let output = stdout.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let detail = stderr.fileHandleForReading.readDataToEndOfFile()
            FileHandle.standardError.write(detail)
            throw AppError(message: "Fixture backend failed for " + command)
        }
        return try JSONSerialization.jsonObject(with: output) as! [String: Any]
    }
}

@MainActor final class FixtureDriver: NSObject, SPUUserDriver {
    var beforeInstall: (() -> Void)?
    var mode: String { Bundle.main.object(forInfoDictionaryKey: "FixtureMode") as! String }
    func record(_ event: String) {
        let root = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "FixtureRoot") as! String)
        let path = root.appendingPathComponent("events.txt")
        if !FileManager.default.fileExists(atPath: path.path) { FileManager.default.createFile(atPath: path.path, contents: nil) }
        if let file = try? FileHandle(forWritingTo: path) {
            file.seekToEndOfFile()
            file.write(Data((event + "\n").utf8))
            try? file.close()
        }
    }
    func show(_ request: SPUUpdatePermissionRequest, reply: @escaping (SUUpdatePermissionResponse) -> Void) {
        reply(SUUpdatePermissionResponse(automaticUpdateChecks: false, sendSystemProfile: false))
    }
    func showUserInitiatedUpdateCheck(cancellation: @escaping () -> Void) { record("checking") }
    func showUpdateFound(with appcastItem: SUAppcastItem, state: SPUUserUpdateState, reply: @escaping (SPUUserUpdateChoice) -> Void) {
        record("found:" + appcastItem.versionString)
        reply(.install)
    }
    func showUpdateReleaseNotes(with downloadData: SPUDownloadData) {}
    func showUpdateReleaseNotesFailedToDownloadWithError(_ error: Error) {}
    func showUpdateNotFoundWithError(_ error: Error, acknowledgement: @escaping () -> Void) {
        record("not-found"); acknowledgement()
    }
    func showUpdaterError(_ error: Error, acknowledgement: @escaping () -> Void) {
        var current: NSError? = error as NSError
        var codes: [String] = []
        while let item = current {
            codes.append(String(item.code))
            current = item.userInfo[NSUnderlyingErrorKey] as? NSError
        }
        record("error:" + codes.joined(separator: ",")); acknowledgement()
    }
    func showDownloadInitiated(cancellation: @escaping () -> Void) { record("download") }
    func showDownloadDidReceiveExpectedContentLength(_ expectedContentLength: UInt64) {}
    func showDownloadDidReceiveData(ofLength length: UInt64) {}
    // Sparkle calls this UI notification before the installer validates bytes.
    func showDownloadDidStartExtractingUpdate() { record("validation-started") }
    func showExtractionReceivedProgress(_ progress: Double) {}
    func showReady(toInstallAndRelaunch reply: @escaping (SPUUserUpdateChoice) -> Void) {
        record("ready")
        beforeInstall?()
        if mode == "cancel" { reply(.skip) }
        else if mode == "quit" {
            reply(.dismiss)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { NSApp.terminate(nil) }
        } else { reply(.install) }
    }
    func showInstallingUpdate(withApplicationTerminated applicationTerminated: Bool, retryTerminatingApplication: @escaping () -> Void) { record("installing") }
    func showUpdateInstalledAndRelaunched(_ relaunched: Bool, acknowledgement: @escaping () -> Void) { record("installed"); acknowledgement() }
    func dismissUpdateInstallation() { record("dismissed") }
}

@MainActor final class FixtureDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()
    let driver = FixtureDriver()
    var updater: AppUpdater!
    func applicationDidFinishLaunching(_ notification: Notification) {
        updater = AppUpdater(model: model, userDriver: driver)
        driver.record("launch:" + (Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as! String))
        Task {
            do {
                _ = try await Backend.request("bootstrap")
                if Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String == "2" {
                    driver.record("recovered:2")
                    NSApp.terminate(nil)
                } else if driver.mode == "automatic" {
                    updater.setAutomaticChecks(true)
                    updater.setAutomaticInstallation(true)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 12) { NSApp.terminate(nil) }
                } else {
                    if driver.mode == "drafts" || driver.mode == "pairing" {
                        driver.beforeInstall = { [self] in
                            model.dirty = driver.mode == "drafts"
                            model.pairing = driver.mode == "pairing"
                            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [self] in
                                driver.record("settings-finished")
                                model.dirty = false
                                model.pairing = false
                            }
                        }
                    }
                    updater.checkForUpdates()
                }
            } catch { driver.record("bootstrap-error"); NSApp.terminate(nil) }
        }
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        updater?.shouldTerminate() ?? .terminateNow
    }
}

@main struct Harness {
    static func main() {
        let app = NSApplication.shared
        let delegate = FixtureDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
        withExtendedLifetime(delegate) {}
    }
}
