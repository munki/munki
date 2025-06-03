//
//  MUrunInteractive.swift
//  manifestutil
//
//  Created by Greg Neagle on 4/15/25.
//
//  Copyright 2024-2025 Greg Neagle.
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//       https://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.

import ArgumentParser
import Foundation
import OSLog

struct commandInfo {
    var shortOptions: [String]
    var longOptions: [String]
    var arguments: [String]
}

class TabCompleter {
    static var shared = TabCompleter()

    let commands = [
        "add-pkg": ["pkgs", "--manifest", "--section"],
        "add-catalog": ["catalogs", "--manifest"],
        "add-included-manifest": ["manifests", "--manifest"],
        "remove-pkg": ["pkgs", "--manifest", "--section"],
        "move-install-to-uninstall": ["pkgs", "--manifest"],
        "remove-catalog": ["catalogs", "--manifest"],
        "remove-included-manifest": ["manifests", "--manifest"],
        "list-manifests": [],
        "list-catalogs": [],
        "list-catalog-items": ["catalogs"],
        "display-manifest": ["manifests", "--expand", "--xml"],
        "expand-included-manifests": ["manifests", "--xml"],
        "find": ["--section"],
        "new-manifest": [],
        "copy-manifest": ["manifests"],
        "rename-manifest": ["manifests"],
        "delete-manifest": ["manifests"],
        // "refresh-cache":           [],
        "exit": [],
        "help": [],
        "configure": [],
        "version": [],
    ]

    let sections = [
        "managed_installs",
        "managed_uninstalls",
        "managed_updates",
        "optional_installs",
        "featured_items",
        "default_installs",
    ]

    let specialOptions = [
        "--manifest": "manifests",
        "--section": "sections",
    ]

    var manifests = [String]()
    var pkgs = [String]()
    var catalogs = [String]()

    private init() {}

    func cache(manifestsOnly: Bool = false) async {
        debugLog("Caching completion data. manifestsOnly: \(manifestsOnly)")
        if let repo = RepoConnection.shared.repo {
            manifests = await getManifestNames(repo: repo) ?? []
            if !manifestsOnly {
                catalogs = await getCatalogNames(repo: repo) ?? []
                pkgs = await getInstallerItemNames(
                    repo: repo,
                    catalogs: catalogs
                )
            }
        }
    }

    func completions(for text: String, partialLine: String) -> [String] {
        let tokens = tokenize(partialLine)
        debugLog("Tokens: \(tokens)")
        if tokens.isEmpty || tokens[0] == text {
            debugLog("We're completing the command")
            return commands.keys.filter {
                $0.hasPrefix(text)
            }.sorted()
        }
        // figure out which token we're editing
        var editToken = 0
        debugLog("rl_point: \(rl_point), rl_end: \(rl_end)")
        if rl_point == rl_end, text == "" {
            editToken = tokens.count
        } else {
            for (i, token) in tokens.enumerated() {
                if token == text {
                    editToken = i
                    break
                }
            }
        }
        let subcommand = tokens[0]
        debugLog("Subcommand: \(subcommand)")
        debugLog("Edit token: \(editToken)")
        if editToken > 0, commands.keys.contains(subcommand) {
            debugLog("We're completing options")
            let previousToken = tokens[editToken - 1]
            debugLog("previousToken: \(previousToken)")

            if let options = commands[subcommand] {
                if options.isEmpty {
                    return ["--help"]
                }
                if previousToken.hasPrefix("--") {
                    if let specialOption = specialOptions[previousToken] {
                        switch specialOption {
                        case "manifests":
                            return manifests.filter { $0.hasPrefix(text) }
                        case "sections":
                            return sections.filter { $0.hasPrefix(text) }
                        default:
                            return []
                        }
                    }
                    return []
                }
                let firstOption = options[0]
                switch firstOption {
                case "pkgs":
                    let wordList = pkgs + options.dropFirst() + ["--help"]
                    return wordList.filter { $0.hasPrefix(text) }
                case "catalogs":
                    let wordList = catalogs + options.dropFirst() + ["--help"]
                    return wordList.filter { $0.hasPrefix(text) }
                case "manifests":
                    let wordList = manifests + options.dropFirst() + ["--help"]
                    return wordList.filter { $0.hasPrefix(text) }
                default:
                    let wordList = options + ["--help"]
                    return wordList.filter { $0.hasPrefix(text) }
                }
            }
        }
        return []
    }
}

private let DEBUG_LOGGING = false
func debugLog(_ message: String) {
    if !DEBUG_LOGGING { return }
    // log to Apple unified logging
    if #available(macOS 11.0, *) {
        let subsystem = "com.googlecode.munki.manifestutil.tabCompleter"
        let logger = Logger(subsystem: subsystem, category: "")
        logger.log("\(message, privacy: .public)")
    }
}

/// Turns out that `rl_line_buffer` is not always zero-terminated, so
/// to accurately get the contents as a Swift string we have to copy bytes around like animals
func get_rl_line_buffer() -> String {
    let bufferLength = Int(rl_end)
    var buffer: [CChar] = Array(repeating: 0, count: bufferLength + 1)
    if bufferLength > 0 {
        strncpy(&buffer, rl_line_buffer!, bufferLength)
    }
    return String(cString: buffer)
}

@_cdecl("tabCompleter")
func tabCompleter(_ text: UnsafePointer<CChar>?, _ state: Int32) -> UnsafeMutablePointer<CChar>? {
    guard let text else { return nil }
    let textToComplete = String(cString: text)
    debugLog("textToComplete: \(textToComplete)")
    let partialLine = get_rl_line_buffer()
    debugLog("rl_end: \(rl_end)")
    debugLog("partialLine: \(partialLine)")
    let completions = TabCompleter.shared.completions(
        for: textToComplete,
        partialLine: partialLine
    )
    debugLog("completions: \(completions)")
    if completions.count > state {
        let completion = completions[Int(state)]
        debugLog("current completion: \(completion)")
        return strdup(completion)
    }
    debugLog("returning nil")
    return nil
}

func setupTabCompleter() {
    rl_completion_entry_function = tabCompleter
    rl_parse_and_bind("bind ^I rl_complete")
}

extension ManifestUtil {
    struct RunInteractive: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Runs this utility in interactive mode.",
            shouldDisplay: false
        )

        func run() async throws {
            // install handlers for SIGINT and SIGTERM
            let sigintSrc = installSignalHandler(SIGINT, cleanUpFunction: cleanupReadline)
            sigintSrc.activate()
            let sigtermSrc = installSignalHandler(SIGTERM, cleanUpFunction: cleanupReadline)
            sigtermSrc.activate()

            // since we're running interactively, the subcommands
            // now act as top-level commands. So we manually parse
            // the first arg to get the subcommand
            let subcommands: [String: ParsableCommand.Type] = [
                "add-pkg": AddPkg.self,
                "add-catalog": AddCatalog.self,
                "add-included-manifest": AddIncludedManifest.self,
                "remove-pkg": RemovePkg.self,
                "move-install-to-uninstall": MoveInstallToUninstall.self,
                "remove-catalog": RemoveCatalog.self,
                "remove-included-manifest": RemoveIncludedManifest.self,
                "list-manifests": ListManifests.self,
                "list-catalogs": ListCatalogs.self,
                "list-catalog-items": ListCatalogItems.self,
                "display-manifest": DisplayManifest.self,
                "expand-included-manifests": ExpandIncludedManifests.self,
                "find": Find.self,
                "new-manifest": NewManifest.self,
                "copy-manifest": CopyManifest.self,
                "rename-manifest": RenameManifest.self,
                "delete-manifest": DeleteManifest.self,
                // "refresh-cache":           RefreshCache.self,
                "exit": Exit.self,
                "help": ManifestUtil.self,
                "configure": Configure.self,
                "version": Version.self,
            ]

            let recacheManifestCmds = [
                "new-manifest",
                "copy-manifest",
                "rename-manifest",
                "delete-manifest",
            ]

            rl_initialize()
            rl_readline_name = strdup("com.googlecode.munki.manifestutil")
            setupTabCompleter()

            print("Entering interactive mode... (type \"help\" for commands, \"exit\" to quit)")
            // guard RepoConnection.shared.repo != nil else { return }
            await TabCompleter.shared.cache()

            // loop forever until the user signals they want to quit
            while true {
                let commandLine = getInput(prompt: "> ") ?? ""

                var args = tokenize(commandLine)
                if args.isEmpty { continue }
                add_history(commandLine)

                guard let subcommand = subcommands[args[0]] else {
                    print("No such command: \(args[0])")
                    continue
                }

                let commandString = args[0]
                if args[0] != "help" {
                    args.removeFirst()
                }

                do {
                    var command = try subcommand.parseAsRoot(args)
                    if var asyncCommand = command as? AsyncParsableCommand {
                        try await asyncCommand.run()
                    } else {
                        try command.run()
                    }
                    if recacheManifestCmds.contains(commandString) {
                        await TabCompleter.shared.cache(manifestsOnly: true)
                    }
                } catch {
                    print(subcommand.fullMessage(for: error))
                }
            }
        }
    }
}
