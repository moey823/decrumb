// SPDX-License-Identifier: AGPL-3.0-only
import AppKit
import Sparkle

/// Sparkle owns network verification, atomic replacement and relaunch. This
/// coordinator only protects Decrumb's worker and user preferences at handoff.
@MainActor final class AppUpdater: NSObject, ObservableObject, SPUUpdaterDelegate {
    @Published var automaticChecks = false
    @Published var automaticInstallation = false
    @Published var installing = false
    @Published var message: String?
    weak var model: AppModel?
    private var controller: SPUStandardUpdaterController!
    private var core: SPUUpdater!
    private var observers: [NSKeyValueObservation] = []
    private var preparedToken: String?
    private var verifiedQuiesced = false
    private var preparation: Task<Bool, Never>?
    private var pendingInstallation = false
    private var installRequested = false
    private var onQuitInstallation: (() -> Void)?
    private var targetBuild = ""
    private var postponedInstallation: (() -> Void)?
    private var postponement: Task<Void, Never>?

    init(model: AppModel, userDriver: SPUUserDriver? = nil) {
        self.model = model
        super.init()
        guard !model.demo else { return }
        if let userDriver {
            core = SPUUpdater(hostBundle: .main, applicationBundle: .main, userDriver: userDriver, delegate: self)
        } else {
            controller = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: self, userDriverDelegate: nil)
            core = controller.updater
        }
        core.sendsSystemProfile = false
        core.userAgentString = "Decrumb/" + (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1")
        do { try core.start() }
        catch { message = "Updates could not start. Download the latest Decrumb from mkships.app/decrumb/download/." }
        synchronizePreferences()
        observers = [core.observe(\.automaticallyChecksForUpdates, options: [.new]) { [weak self] _, _ in
            Task { @MainActor in self?.synchronizePreferences() }
        }, core.observe(\.automaticallyDownloadsUpdates, options: [.new]) { [weak self] _, _ in
            Task { @MainActor in self?.synchronizePreferences() }
        }]
    }

    private func synchronizePreferences() {
        automaticChecks = core?.automaticallyChecksForUpdates ?? false
        automaticInstallation = core?.automaticallyDownloadsUpdates ?? false
    }
    func setAutomaticChecks(_ enabled: Bool) {
        guard let updater = core else { return }
        if !enabled { updater.automaticallyDownloadsUpdates = false }
        updater.automaticallyChecksForUpdates = enabled
        synchronizePreferences()
    }
    func setAutomaticInstallation(_ enabled: Bool) {
        guard let updater = core else { return }
        updater.automaticallyDownloadsUpdates = enabled && automaticChecks
        synchronizePreferences()
    }
    var canCheck: Bool { (core?.canCheckForUpdates == true || postponedInstallation != nil) && !installing }
    @objc func checkForUpdates() {
        guard canCheck else { return }
        if postponedInstallation != nil { continuePostponedInstallation(); return }
        core.checkForUpdates()
    }
    func updater(_ updater: SPUUpdater, mayPerform updateCheck: SPUUpdateCheck) throws {
        guard model?.pairing != true, model?.busy != true, !installing else {
            throw AppError(message: "Finish the current action before checking for updates.")
        }
    }
    func feedParameters(for updater: SPUUpdater, sendingSystemProfile: Bool) -> [[String: String]] { [] }
    func updater(_ updater: SPUUpdater, didExtractUpdate item: SUAppcastItem) {
        pendingInstallation = true
        targetBuild = item.versionString
    }
    func updater(_ updater: SPUUpdater, willInstallUpdate item: SUAppcastItem) {
        installRequested = true
        pendingInstallation = true
        targetBuild = item.versionString
    }
    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                 untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        pendingInstallation = true
        targetBuild = item.versionString
        postponedInstallation = installHandler
        continuePostponedInstallation()
        return true
    }
    func updater(_ updater: SPUUpdater, willInstallUpdateOnQuit item: SUAppcastItem,
                 immediateInstallationBlock immediateInstallHandler: @escaping () -> Void) -> Bool {
        pendingInstallation = true
        targetBuild = item.versionString
        onQuitInstallation = immediateInstallHandler
        return true
    }
    private func continuePostponedInstallation() {
        guard postponement == nil else { return }
        postponement = Task {
            defer { postponement = nil }
            while model?.pairing == true || (model?.busy == true && !verifiedQuiesced) || model?.loading == true || model?.dirty == true || model?.notesDirty == true {
                message = (model?.dirty == true || model?.notesDirty == true)
                    ? "Save or discard your pending settings before this update installs."
                    : "The update will install after the current action finishes."
                try? await Task.sleep(nanoseconds: 250_000_000)
                if Task.isCancelled { return }
            }
            if await prepare(), let handler = postponedInstallation {
                postponedInstallation = nil
                installRequested = true
                handler()
            }
        }
    }
    func updaterShouldRelaunchApplication(_ updater: SPUUpdater) -> Bool { true }

    private func prepare() async -> Bool {
        if verifiedQuiesced { return true }
        if let preparation { return await preparation.value }
        guard let model, !model.pairing, !model.busy, !model.loading, !model.dirty, !model.notesDirty else {
            message = "The update is waiting. Finish pairing, save or discard pending settings, then try again."
            return false
        }
        installing = true
        model.busy = true
        let task = Task { [self] in
            do {
                let input = try JSONSerialization.data(withJSONObject: ["target_build": targetBuild])
                let result = try await Backend.request("update-prepare", input: input)
                guard let token = result["token"] as? String, result["ready"] as? Bool == true else { throw AppError(message: "The worker could not prepare for this update.") }
                preparedToken = token
                verifiedQuiesced = true
                return true
            } catch {
                message = error.localizedDescription
                installing = false
                model.busy = false
                return false
            }
        }
        preparation = task
        let result = await task.value
        preparation = nil
        return result
    }

    func resumeInterruptedUpdate() {
        guard let core, core.canCheckForUpdates else { return }
        Task {
            do {
                let result = try await Backend.request("update-claim")
                preparedToken = result["token"] as? String
                message = "Finishing an interrupted update before cleaning resumes."
                core.checkForUpdates()
            } catch { message = error.localizedDescription }
        }
    }

    /// Covers Sparkle's install-on-quit path, which may skip its relaunch delegate.
    func shouldTerminate() -> NSApplication.TerminateReply? {
        guard pendingInstallation else { return nil }
        if verifiedQuiesced && preparedToken != nil && installRequested { return .terminateNow }
        if let handler = onQuitInstallation {
            Task {
                if await prepare() {
                    installRequested = true
                    handler() // request a relaunch so enabled cleaning resumes
                }
            }
            return .terminateCancel
        }
        if !installRequested {
            message = "Finish the downloaded update before quitting. Decrumb will relaunch and restore cleaning."
            core.checkForUpdates()
            return .terminateCancel
        }
        Task {
            let ready = await prepare()
            if ready { installRequested = true }
            NSApp.reply(toApplicationShouldTerminate: ready)
        }
        return .terminateLater
    }
    func updater(_ updater: SPUUpdater, didAbortWithError error: Error) { restoreAfterAbort() }
    func updater(_ updater: SPUUpdater, didFinishUpdateCycleFor updateCheck: SPUUpdateCheck, error: Error?) {
        if error != nil { restoreAfterAbort() }
    }
    private func restoreAfterAbort() {
        pendingInstallation = false
        installRequested = false
        onQuitInstallation = nil
        postponedInstallation = nil
        postponement?.cancel(); postponement = nil
        Task {
            defer { preparedToken = nil; verifiedQuiesced = false; installing = false; model?.busy = false }
            guard let token = preparedToken else { return }
            do {
                let input = try JSONSerialization.data(withJSONObject: ["token": token])
                let result = try await Backend.request("update-abort", input: input)
                model?.applySnapshot(result)
                message = "The update did not finish. Your previous cleaning preference has been restored."
            } catch { message = error.localizedDescription }
        }
    }
}

import SwiftUI
struct UpdatePreferences: View {
    @ObservedObject var updater: AppUpdater
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("App updates").font(.largeTitle.bold())
            Text("Keep Decrumb and its bundled Signal connection up to date.").foregroundStyle(.secondary)
            Button("Check for Updates…") { updater.checkForUpdates() }.disabled(!updater.canCheck)
            Toggle("Automatically check for updates", isOn: Binding(get: { updater.automaticChecks }, set: updater.setAutomaticChecks))
            Toggle("Automatically download and install updates when Decrumb quits", isOn: Binding(get: { updater.automaticInstallation }, set: updater.setAutomaticInstallation))
                .disabled(!updater.automaticChecks)
            Text("Both options are off initially. Updates are verified before installation. Pairing and settings changes must finish first; Decrumb reopens after installation and restores your cleaning preference.").font(.callout).foregroundStyle(.secondary)
            Text("Update checks contact mkships.app and downloads contact GitHub. These services receive ordinary connection information, including your IP address. No Signal identity, contacts, message content, rules, note IDs, or system profile are sent.").font(.callout).foregroundStyle(.secondary)
            if let message = updater.message { Text(message).font(.callout) }
        }
    }
}
