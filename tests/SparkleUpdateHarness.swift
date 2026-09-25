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
        let result = try JSONSerialization.jsonObject(with: output) as! [String: Any]
        if let error = result["error"] as? String { throw AppError(message: error) }
        return result
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
    var standardUITimer: Timer?
    var standardUISnapshots = Set<String>()
    var clickedStandardUpdate = false
    var clickedStandardReady = false
    var attentionWindow: NSWindow?
    var retryButton: NSButton?
    var usesStandardUI: Bool { driver.mode.hasPrefix("standard-") }

    // Inspect only this generated fixture process's own views. These identifiers
    // come from pinned Sparkle 2.10.0's SUUpdateAlert.xib and standard user driver.
    func button(in view: NSView, identifier: String) -> NSButton? {
        if let button = view as? NSButton, button.isEnabled, !button.isHidden {
            if button.accessibilityIdentifier() == identifier { return button }
            // Some AppKit versions omit XIB accessibility identifiers at runtime.
            // The observed initial Install Update button uses this pinned source action.
            if identifier == "SPUUserUpdateChoiceInstall", button.title == "Install Update",
               button.action.map(NSStringFromSelector) == "installUpdate:" { return button }
        }
        for child in view.subviews {
            if let found = button(in: child, identifier: identifier) { return found }
        }
        return nil
    }
    func standardButton(_ identifier: String) -> NSButton? {
        for window in NSApp.windows where window.isVisible {
            if let content = window.contentView, let found = button(in: content, identifier: identifier) {
                return found
            }
        }
        return nil
    }
    func startStandardUI() {
        driver.record("standard-poll-started")
        standardUITimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.advanceStandardUI() }
        }
    }
    func standardButtonDescriptions(_ view: NSView) -> [String] {
        var descriptions: [String] = []
        if let button = view as? NSButton {
            descriptions.append((button.accessibilityIdentifier() ?? "no-id") + ":" + button.title + ":" + String(button.isEnabled))
        }
        for child in view.subviews { descriptions += standardButtonDescriptions(child) }
        return descriptions
    }
    func advanceStandardUI() {
        let snapshot = NSApp.windows.filter { $0.isVisible }.map { window in
            String(describing: type(of: window)) + ":" + (window.contentView.map { standardButtonDescriptions($0).joined(separator: ",") } ?? "no-content")
        }.joined(separator: ";")
        if standardUISnapshots.insert(snapshot).inserted { driver.record("standard-ui:" + snapshot) }
        if !clickedStandardUpdate, let button = standardButton("SPUUserUpdateChoiceInstall") {
            clickedStandardUpdate = true
            driver.record("standard-update-click")
            button.performClick(nil)
        } else if !clickedStandardReady, let button = standardButton("SUStatusInstallAndRelaunch") {
            clickedStandardReady = true
            if driver.mode == "standard-quit-pending" {
                driver.record("standard-ready-visible")
                Task {
                    if await updater.prepareForCompleteQuit() {
                        driver.record("complete-quit-ready")
                        NSApp.terminate(nil)
                    } else { driver.record("complete-quit-failed") }
                }
            } else {
                driver.record("standard-ready-click")
                button.performClick(nil)
            }
        }
    }
    func showPreparationFailure() {
        guard usesStandardUI, driver.mode == "standard-prepare-failure", updater.canCheck,
              let message = updater.message, !message.isEmpty else { return }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 180),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Decrumb Update Fixture — Attention"
        window.isReleasedWhenClosed = false
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 560, height: 180))
        let explanation = NSTextField(wrappingLabelWithString: message)
        explanation.frame = NSRect(x: 20, y: 65, width: 520, height: 90)
        content.addSubview(explanation)
        let button = NSButton(title: updater.actionTitle, target: self, action: #selector(retryStandardInstall))
        button.setAccessibilityIdentifier("FixtureRetryInstall")
        button.frame = NSRect(x: 330, y: 20, width: 210, height: 32)
        button.isEnabled = updater.canCheck
        content.addSubview(button)
        window.contentView = content
        attentionWindow = window
        retryButton = button
        window.makeKeyAndOrderFront(nil)
        if window.isVisible && explanation.stringValue == message {
            driver.record("attention-visible:" + message)
            driver.record("retry-action:" + button.title)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                self?.retryButton?.performClick(nil)
            }
        }
    }
    @objc func retryStandardInstall() {
        guard updater.canCheck, attentionWindow?.isVisible == true else { return }
        driver.record("standard-retry-click")
        updater.checkForUpdates()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        updater = usesStandardUI ? AppUpdater(model: model) : AppUpdater(model: model, userDriver: driver)
        updater.onNeedsAttention = { [self] in
            driver.record("attention")
            showPreparationFailure()
            if driver.mode == "prepare-failure", updater.canCheck {
                driver.record("retry-action:" + updater.actionTitle)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [self] in updater.checkForUpdates() }
            }
        }
        driver.record("launch:" + (Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as! String))
        Task {
            do {
                driver.record("bootstrap-start")
                _ = try await Backend.request("bootstrap")
                driver.record("bootstrap-finished")
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
                    if usesStandardUI {
                        driver.record("standard-can-check:" + String(updater.canCheck))
                        startStandardUI()
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
