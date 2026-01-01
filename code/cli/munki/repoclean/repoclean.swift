//
//  repoclean.swift
//  repoclean
//
//  Created by Greg Neagle on 11/18/24.
//  Copyright 2024-2026 The Munki Project. All rights reserved.
//

import ArgumentParser
import Foundation

///  Returns sizes in human-readable units.
func humanReadable(_ sizeInBytes: Int) -> String {
    let kiloByte = pow(Double(2), 10)
    let units = [
        (" bytes", kiloByte),
        (" KB", pow(Double(2), 20)),
        (" MB", pow(Double(2), 30)),
        (" GB", pow(Double(2), 40)),
        (" TB", pow(Double(2), 50)),
        (" PB", pow(Double(2), 60)),
    ]
    // set suffix and limit to last items in units in case the
    // value is so big it falls off the edge
    var suffix = units.last!.0
    var limit = units.last!.1
    // find an appropriate suffix
    for (testSuffix, testLimit) in units {
        if Double(sizeInBytes) >= testLimit {
            continue
        } else {
            suffix = testSuffix
            limit = testLimit
            break
        }
    }
    if limit == kiloByte {
        // no decimal needed
        return "\(sizeInBytes) bytes"
    }
    let value = Double(sizeInBytes) / (limit / kiloByte)
    let roundedValue = round(value * 10) / 10.0
    return "\(roundedValue)\(suffix)"
}

struct RepoCleanOptions {
    var showAll = false
    var auto = false
    var keep = 2
    var repoURL: String
    var plugin = "FileRepo"
}

struct ItemWithVersion: Hashable {
    var name: String
    var version: String
}

/// Encapsulates our repo cleaning logic
class RepoCleaner {
    var repo: Repo
    var options: RepoCleanOptions
    var errors = [String]()
    var manifestItems = Set<String>()
    var manifestItemsWithVersions = Set<ItemWithVersion>()
    var pkginfoDB = PlistDict()
    var referencedPkgs = Set<String>()
    var orphanedPkgs = [String]()
    var requiredItems = Set<ItemWithVersion>()
    var pkginfoCount = 0
    var itemsToDelete = [PlistDict]()
    var pkgsToKeep = Set<String>()

    init(repo: Repo, options: RepoCleanOptions) {
        self.repo = repo
        self.options = options
    }

    /// Returns count the number of installer and uninstaller pkgs we will
    /// delete and human-readable sizes for the pkginfo items and
    /// pkgs that are to be deleted
    func getItemsToDeleteStats() -> (Int, String, String) {
        var count = orphanedPkgs.count
        var pkginfoTotalSize = 0
        var pkgTotalSize = 0
        for item in itemsToDelete {
            if let pkginfoSize = item["item_size"] as? Int {
                pkginfoTotalSize += pkginfoSize
            }
            if let pkgPath = item["pkg_path"] as? String,
               !pkgPath.isEmpty,
               !pkgsToKeep.contains(pkgPath)
            {
                count += 1
                if let pkgSize = item["pkg_size"] as? Int {
                    pkgTotalSize += pkgSize
                }
            }
            if let uninstallPkgPath = item["uninstallpkg_path"] as? String,
               !uninstallPkgPath.isEmpty,
               !pkgsToKeep.contains(uninstallPkgPath)
            {
                count += 1
                if let pkgSize = item["uninstallpkg_size"] as? Int {
                    pkgTotalSize += pkgSize
                }
            }
        }
        return (count, humanReadable(pkginfoTotalSize), humanReadable(pkgTotalSize))
    }

    /// Examine all manifests and populate our sets of manifestItems and
    /// manifestItemsWithVersions
    func analyzeManifests() async {
        print("Analyzing manifest files...")
        // look through all manifests for "Foo-1.0" style items
        // we need to note these so the specific referenced version is not
        // deleted
        var manifestsList = [String]()
        do {
            manifestsList = try await repo.list("manifests")
        } catch {
            errors.append("Repo error getting list of manifests: \(error.localizedDescription)")
        }
        for manifestName in manifestsList {
            var manifest = PlistDict()
            do {
                let data = try await repo.get("manifests/\(manifestName)")
                manifest = try readPlist(fromData: data) as? PlistDict ?? PlistDict()
            } catch {
                errors.append("Unexpected error for \(manifestName): \(error.localizedDescription)")
                continue
            }
            for key in ["managed_installs", "managed_uninstalls", "managed_updates", "optional_installs"] {
                for item in manifest[key] as? [String] ?? [] {
                    let (itemName, itemVers) = nameAndVersion(item, onlySplitOnHyphens: true)
                    manifestItems.insert(itemName)
                    if !itemVers.isEmpty {
                        manifestItemsWithVersions.insert(ItemWithVersion(name: itemName, version: itemVers))
                    }
                }
            }
            // next check conditional_items within the manifest
            for conditionalItem in manifest["conditional_items"] as? [PlistDict] ?? [] {
                for key in ["managed_installs", "managed_uninstalls", "managed_updates", "optional_installs"] {
                    for item in conditionalItem[key] as? [String] ?? [] {
                        let (itemName, itemVers) = nameAndVersion(item, onlySplitOnHyphens: true)
                        manifestItems.insert(itemName)
                        if !itemVers.isEmpty {
                            manifestItemsWithVersions.insert(ItemWithVersion(name: itemName, version: itemVers))
                        }
                    }
                }
            }
        }
    }

    /// Examines all pkginfo files and populates pkginfoDB, requiredItems and pkginfoCount
    func analyzePkgsinfo() async {
        print("Analyzing pkginfo files...")
        var pkgsinfoList = [String]()
        do {
            pkgsinfoList = try await repo.list("pkgsinfo")
        } catch {
            errors.append("Repo error getting list of pkgsinfo: \(error.localizedDescription)")
        }
        for pkginfoName in pkgsinfoList {
            let pkginfoIdentifier = "pkgsinfo/\(pkginfoName)"
            var pkginfo = PlistDict()
            var pkginfoSize = 0
            do {
                let data = try await repo.get(pkginfoIdentifier)
                pkginfo = try readPlist(fromData: data) as? PlistDict ?? PlistDict()
                pkginfoSize = data.count
            } catch {
                errors.append("Unexpected error for \(pkginfoName): \(error.localizedDescription)")
                continue
            }
            guard let name = pkginfo["name"] as? String,
                  let version = pkginfo["version"] as? String
            else {
                errors.append("Missing 'name' or 'version' keys in \(pkginfoName)")
                continue
            }
            let pkgPath = pkginfo["installer_item_location"] as? String ?? ""
            let pkgSize = (pkginfo["installer_item_size"] as? Int ?? 0) * 1024
            let uninstallPkgPath = pkginfo["uninstaller_item_location"] as? String ?? ""
            let uninstallPkgSize = (pkginfo["uninstaller_item_size"] as? Int ?? 0) * 1024

            if !pkgPath.isEmpty {
                referencedPkgs.insert(pkgPath)
            }
            if !uninstallPkgPath.isEmpty {
                referencedPkgs.insert(uninstallPkgPath)
            }

            // track required items; if these are in "Foo-1.0" format, we need
            // to note these so we don't delete the specific referenced version
            var dependencies = [String]()
            if let requires = pkginfo["requires"] as? [String] {
                dependencies = requires
            } else if let requires = pkginfo["requires"] as? String {
                // deal with case where admin defines a string instead of
                // an array of strings
                dependencies = [requires]
            }
            for dependency in dependencies {
                let (requiredName, requiredVers) = nameAndVersion(dependency, onlySplitOnHyphens: true)
                if !requiredVers.isEmpty {
                    requiredItems.insert(ItemWithVersion(name: requiredName, version: requiredVers))
                }
                // if this item is in a manifest, then anything it requires
                // should be treated as if it, too, is in a manifest.
                if manifestItems.contains(name) {
                    manifestItems.insert(requiredName)
                }
            }

            // now process update_for: if this is an update_for an item that is
            // in manifest_items, it should be treated as if it, too is in a
            // manifest
            var updateItems = [String]()
            if let updateFor = pkginfo["update_for"] as? [String] {
                updateItems = updateFor
            } else if let updateFor = pkginfo["update_for"] as? String {
                // deal with case where admin defines a string instead of
                // an array of strings
                updateItems = [updateFor]
            }
            for updateItem in updateItems {
                let (updateItemName, _) = nameAndVersion(updateItem, onlySplitOnHyphens: true)
                if manifestItems.contains(updateItemName) {
                    manifestItems.insert(name)
                }
            }

            var metakey = ""
            let keysToHash = [
                "name",
                "catalogs",
                "minimum_munki_version",
                "minimum_os_version",
                "maximum_os_version",
                "supported_architectures",
                "installable_condition",
            ]
            for key in keysToHash {
                if let value = pkginfo[key] as? String,
                   !value.isEmpty
                {
                    metakey += "\(key): \(value)\n"
                } else if let value = pkginfo[key] as? [String],
                          !value.isEmpty
                {
                    let joinedValue = value.sorted().joined(separator: ", ")
                    metakey += "\(key): \(joinedValue)\n"
                }
            }
            if (pkginfo["uninstall_method"] as? String ?? "") == "removepackages",
               let receipts = pkginfo["receipts"] as? [PlistDict]
            {
                let pkgIDs = receipts.map {
                    $0["packageid"] as? String ?? ""
                }.filter {
                    !$0.isEmpty
                }
                let joinedValue = pkgIDs.sorted().joined(separator: ", ")
                metakey += "receipts: \(joinedValue)\n"
            }
            metakey = String(metakey.dropLast())
            let itemData: PlistDict = [
                "name": name,
                "version": version,
                "resource_identifier": pkginfoIdentifier,
                "item_size": pkginfoSize,
                "pkg_path": pkgPath,
                "pkg_size": pkgSize,
                "uninstallpkg_path": uninstallPkgPath,
                "uninstallpkg_size": uninstallPkgSize,
            ]
            if !pkginfoDB.keys.contains(metakey) {
                pkginfoDB[metakey] = PlistDict()
            }
            if var metaDict = pkginfoDB[metakey] as? PlistDict {
                if !metaDict.keys.contains(version) {
                    metaDict[version] = [itemData]
                } else if var versionData = metaDict[version] as? [PlistDict] {
                    versionData.append(itemData)
                    metaDict[version] = versionData
                }
                pkginfoDB[metakey] = metaDict
            }
            pkginfoCount += 1
        }
    }

    /// Finds installer items that are not referred to by any pkginfo file
    func findOrphanedPkgs() async {
        print("Analyzing installer items...")
        var pkgsList = [String]()
        do {
            pkgsList = try await repo.list("pkgs")
        } catch {
            errors.append("Repo error getting list of pkgs: \(error.localizedDescription)")
        }
        for pkg in pkgsList {
            if !referencedPkgs.contains(pkg) {
                orphanedPkgs.append(pkg)
            }
        }
    }

    /// Using the info on manifests and pkgsinfo, find items to clean up.
    /// Populates itemsToDelete: a list of pkginfo items to remove,
    /// and pkgsToKeep: pkgs (install and uninstall items) that we need
    /// to keep.
    func findCleanupItems() {
        for key in pkginfoDB.keys.sorted() {
            guard let dbItem = pkginfoDB[key] as? PlistDict else {
                continue
            }
            let printThis = options.showAll || dbItem.keys.count > options.keep
            var dbItemKeys = Array(dbItem.keys)
            guard !dbItemKeys.isEmpty else { continue }
            guard let firstItemList = dbItem[dbItemKeys[0]] as? [PlistDict],
                  !firstItemList.isEmpty,
                  let itemName = firstItemList[0]["name"] as? String
            else {
                continue
            }
            if printThis {
                print(key)
                if !manifestItems.contains(itemName) {
                    print("[not in any manifests]")
                }
                print("versions:")
            }
            // sort dbItemKeys so latest is first
            dbItemKeys.sort {
                MunkiVersion($0) > MunkiVersion($1)
            }
            var index = 0
            for version in dbItemKeys {
                var lineInfo = ""
                index += 1
                let itemList = dbItem[version] as? [PlistDict] ?? []
                if itemList.isEmpty { continue }
                let itemName = itemList[0]["name"] as? String ?? "UNKNOWN"
                let itemNameWithVersion = ItemWithVersion(name: itemName, version: version)
                if manifestItemsWithVersions.contains(itemNameWithVersion) {
                    for item in itemList {
                        if let pkgPath = item["pkg_path"] as? String,
                           !pkgPath.isEmpty
                        {
                            pkgsToKeep.insert(pkgPath)
                        }
                        if let uninstallPkgPath = item["uninstallpkg_path"] as? String,
                           !uninstallPkgPath.isEmpty
                        {
                            pkgsToKeep.insert(uninstallPkgPath)
                        }
                    }
                    lineInfo = "(REQUIRED by a manifest)"
                } else if requiredItems.contains(itemNameWithVersion) {
                    for item in itemList {
                        if let pkgPath = item["pkg_path"] as? String,
                           !pkgPath.isEmpty
                        {
                            pkgsToKeep.insert(pkgPath)
                        }
                        if let uninstallPkgPath = item["uninstallpkg_path"] as? String,
                           !uninstallPkgPath.isEmpty
                        {
                            pkgsToKeep.insert(uninstallPkgPath)
                        }
                    }
                    lineInfo = "(REQUIRED by another pkginfo item)"
                } else if index <= options.keep {
                    for item in itemList {
                        if let pkgPath = item["pkg_path"] as? String,
                           !pkgPath.isEmpty
                        {
                            pkgsToKeep.insert(pkgPath)
                        }
                        if let uninstallPkgPath = item["uninstallpkg_path"] as? String,
                           !uninstallPkgPath.isEmpty
                        {
                            pkgsToKeep.insert(uninstallPkgPath)
                        }
                    }
                } else {
                    for item in itemList {
                        itemsToDelete.append(item)
                    }
                    lineInfo = "[to be DELETED]"
                }
                if itemList.count > 1 {
                    lineInfo = "(multiple items share this version number) " + lineInfo
                } else {
                    let resourceIdentifier = itemList[0]["resource_identifier"] as? String ?? "UNKNOWN IDENTIFIER"
                    lineInfo = "(\(resourceIdentifier)) \(lineInfo)"
                }
                if printThis {
                    print("    ", version, lineInfo)
                    if itemList.count > 1 {
                        for item in itemList {
                            let resourceIdentifier = item["resource_identifier"] as? String ?? "UNKNOWN IDENTIFIER"
                            print("    ", String(repeating: " ", count: version.count), terminator: " ")
                            print("(\(resourceIdentifier))")
                        }
                    }
                }
            }
            if printThis {
                print()
            }
        }
        if !orphanedPkgs.isEmpty {
            print("The following pkgs are not referred to by any pkginfo item:")
            for pkg in orphanedPkgs {
                print("\t\(pkg)")
            }
        }
        /* if printThis {
             print()
         } */

        print("Total pkginfo items:     \(pkginfoCount)")
        print("Item variants:           \(Array(pkginfoDB.keys).count)")
        /* for variant in Array(pkginfoDB.keys).sorted() {
             print(variant)
         } */
        print("pkginfo items to delete: \(itemsToDelete.count)")
        let (pkgCount, pkginfoSize, pkgSize) = getItemsToDeleteStats()
        print("pkgs to delete:          \(pkgCount)")
        print("pkginfo space savings:   \(pkginfoSize)")
        print("pkg space savings:       \(pkgSize)")
        if !orphanedPkgs.isEmpty {
            print("                         (Unknown additional pkg space savings from \(orphanedPkgs.count) orphaned pkgs)")
        }
        if !errors.isEmpty {
            printStderr("\nErrors encountered when processing repo:\n")
            for error in errors {
                printStderr(error)
            }
        }
    }

    /// Deletes items from the repo
    func deleteItems() async {
        // remove old pkginfo and referenced pkgs
        for item in itemsToDelete {
            if let resourceIdentifier = item["resource_identifier"] as? String {
                print("Removing \(resourceIdentifier)")
                do {
                    try await repo.delete(resourceIdentifier)
                } catch {
                    printStderr("Error deleting \(resourceIdentifier): \(error.localizedDescription)")
                }
            }
            for key in ["pkg_path", "uninstallpkg_path"] {
                if let pkgPath = item[key] as? String,
                   !pkgPath.isEmpty,
                   !pkgsToKeep.contains(pkgPath)
                {
                    let pkgToRemove = "pkgs/" + pkgPath
                    print("Removing \(pkgToRemove)")
                    do {
                        try await repo.delete(pkgToRemove)
                    } catch {
                        printStderr("Error deleting \(pkgToRemove): \(error.localizedDescription)")
                    }
                }
            }
        }
        // remove orphaned pkgs
        for pkg in orphanedPkgs {
            let pkgToRemove = "pkgs/" + pkg
            print("Removing \(pkgToRemove)")
            do {
                try await repo.delete(pkgToRemove)
            } catch {
                printStderr("Error deleting \(pkgToRemove): \(error.localizedDescription)")
            }
        }
    }

    /// Rebuilds our catalogs
    func makeCatalogs() async {
        let options = MakeCatalogOptions(
            skipPkgCheck: false,
            force: false,
            verbose: false
        )
        do {
            var catalogsmaker = try await CatalogsMaker(repo: repo, options: options)
            await catalogsmaker.makecatalogs()
            if !catalogsmaker.errors.isEmpty {
                print("\nThe following issues occurred while building catalogs:\n")
                for error in catalogsmaker.errors {
                    printStderr(error)
                }
            }
        } catch {
            printStderr("Error building catalogs: \(error.localizedDescription)")
        }
    }

    ///  Clean our repo!
    func clean() async {
        await analyzeManifests()
        await analyzePkgsinfo()
        await findOrphanedPkgs()
        findCleanupItems()
        if !itemsToDelete.isEmpty || !orphanedPkgs.isEmpty {
            print()
            if !options.auto {
                print("Delete pkginfo and pkg items marked as [to be DELETED]? WARNING: This action cannot be undone. [y/N] ", terminator: "")
                let answer = readLine() ?? ""
                if answer.lowercased().hasPrefix("y") {
                    print("Are you sure? This action cannot be undone. [y/N] ", terminator: "")
                    let answer = readLine() ?? ""
                    if answer.lowercased().hasPrefix("y") {
                        await deleteItems()
                        await makeCatalogs()
                    }
                }
            } else {
                print("Auto mode selected, deleting pkginfo and pkg items marked as [to be DELETED]")
                await deleteItems()
                await makeCatalogs()
            }
        }
    }
}

@main
struct RepoClean: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "repoclean",
        abstract: "Cleans up older packages and pkginfos from a repo"
    )

    @Flag(name: [.long, .customShort("V")],
          help: "Print the version of the munki tools and exit.")
    var version = false

    @Option(name: .shortAndLong,
            help: "Keep this many versions of a specific variation.")
    var keep = 2

    @Flag(name: .long,
          help: "Show all items even if none will be deleted.")
    var showAll = false

    @Option(name: [.customLong("repo-url"), .customLong("repo_url")],
            help: "Optional repo URL. Supply this or a repo_path as an argument.")
    var repoURL = ""

    @Option(name: .long,
            help: "Specify a custom plugin to connect to the Munki repo.")
    var plugin = "FileRepo"

    @Flag(name: .shortAndLong,
          help: "Do not prompt for confirmation before deleting repo items. Use with caution.")
    var auto = false

    @Argument(help: "Path to Munki repo")
    var repo_path = ""

    var actualRepoUrl = ""

    mutating func validate() throws {
        if version {
            // asking for version info; we don't need to validate there's a repo URL
            return
        }
        // figure out what repo we're working with: we can get a repo URL one of three ways:
        //   - as a file path provided at the command line
        //   - as a --repo_url option
        //   - as a preference stored in the com.googlecode.munki.munkiimport domain
        if !repo_path.isEmpty, !repoURL.isEmpty {
            // user has specified _both_ repo_path and repo_url!
            throw ValidationError("Please specify only one of --repo_url or <repo_path>!")
        }
        if !repo_path.isEmpty {
            // convert path to file URL
            if let repo_url_string = NSURL(fileURLWithPath: repo_path).absoluteString {
                actualRepoUrl = repo_url_string
            }
        } else if !repoURL.isEmpty {
            actualRepoUrl = repoURL
            /* } else if let pref_repo_url = adminPref("repo_url") as? String {
             actual_repo_url = pref_repo_url */
        }

        if actualRepoUrl.isEmpty {
            throw ValidationError("Please specify --repo_url or a repo path.")
        }
    }

    mutating func run() async throws {
        if version {
            print(getVersion())
            return
        }

        do {
            let repo = try repoConnect(url: actualRepoUrl, plugin: plugin)
            let options = RepoCleanOptions(
                showAll: showAll,
                auto: auto,
                keep: keep,
                repoURL: actualRepoUrl,
                plugin: plugin
            )
            let cleaner = RepoCleaner(repo: repo, options: options)
            await cleaner.clean()
        } catch let error as MunkiError {
            printStderr("Repo error: \(error.description)")
            throw ExitCode(-1)
        } catch {
            printStderr("Unexpected error: \(error)")
            throw ExitCode(-1)
        }
    }
}
