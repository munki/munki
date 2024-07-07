//
//  makecatalogslib.swift
//  munki
//
//  Created by Greg Neagle on 6/27/24.
//

import CryptoKit
import Foundation

enum MakeCatalogsError: Error {
    case PkginfoAccessError(description: String)
    case CatalogWriteError(description: String)
}

struct MakeCatalogOptions {
    var skipPkgCheck: Bool = false
    var force: Bool = false
    var verbose: Bool = false
}

struct CatalogsMaker {
    var repo: Repo
    var options: MakeCatalogOptions
    var pkgsinfoList: [String]
    var pkgsList: [String]
    var catalogs: [String: [PlistDict]]
    var errors: [String]
    
    init(repo: Repo,
         options: MakeCatalogOptions = MakeCatalogOptions()) throws
    {
        self.repo = repo
        self.options = options
        catalogs = [String: [PlistDict]]()
        errors = [String]()
        pkgsinfoList = [String]()
        pkgsList = [String]()
        try getPkgsinfoList()
        try getPkgsList()
    }
    
    mutating func getPkgsinfoList() throws {
        // returns a list of pkginfo identifiers
        do {
            pkgsinfoList = try listItemsOfKind(repo, "pkgsinfo")
        } catch is RepoError {
            throw MakeCatalogsError.PkginfoAccessError(
                description: "Error getting list of pkgsinfo items")
        }
    }
    
    mutating func getPkgsList() throws {
        // returns a list of pkg identifiers
        do {
            pkgsList = try listItemsOfKind(repo, "pkgs")
        } catch is RepoError {
            throw MakeCatalogsError.PkginfoAccessError(
                description: "Error getting list of pkgs items")
        }
    }
    
    mutating func hashIcons() -> [String: String] {
        // Builds a dictionary containing hashes for all our repo icons
        if options.verbose {
            print("Getting list of icons...")
        }
        var iconHashes = [String: String]()
        if var iconList = try? repo.list("icons") {
            // remove plist of hashes from the list
            if let index = iconList.firstIndex(of: "_icon_hashes.plist") {
                iconList.remove(at: index)
            }
            for icon in iconList {
                if options.verbose {
                    print("Hashing \(icon)...")
                }
                do {
                    let icondata = try repo.get("icons/" + icon)
                    iconHashes[icon] = sha256hash(data: icondata)
                } catch let RepoError.error(description) {
                    errors.append("RepoError reading icons/\(icon): \(description)")
                } catch {
                    errors.append("Unexpected error reading icons/\(icon): \(error)")
                }
            }
        }
        return iconHashes
    }
    
    func caseInsensitivePkgsListContains(_ installer_item: String) -> String? {
        // returns a case-insentitive match for installer_item from pkgsList, if any
        for repo_pkg in pkgsList {
            if installer_item.lowercased() == repo_pkg.lowercased() {
                return repo_pkg
            }
        }
        return nil
    }
    
    mutating func verify(_ identifier: String, _ pkginfo: PlistDict) -> Bool {
        // Returns true if referenced installer items are present,
        // false otherwise. Updates list of errors.
        if let installer_type = pkginfo["installer_type"] as? String {
            if ["nopkg", "apple_update_metadata"].contains(installer_type) {
                // no associated installer item (pkg) for these types
                return true
            }
        }
        if !((pkginfo["PackageCompleteURL"] as? String ?? "").isEmpty) {
            // installer item may be on a different server
            return true
        }
        if !((pkginfo["PackageURL"] as? String ?? "").isEmpty) {
            // installer item may be on a different server
            return true
        }
        
        // Build path to installer item
        let installeritemlocation = pkginfo["installer_item_location"] as? String ?? ""
        if installeritemlocation.isEmpty {
            errors.append(
                "WARNING: empty or invalid installer_item_location in \(identifier)")
            return false
        }
        let installeritempath = "pkgs/" + installeritemlocation
        
        // Check if the installer item actually exists
        if !(pkgsList.contains(installeritempath)) {
            // didn't find it in the pkgsList; let's look case-insensitive
            if let match = caseInsensitivePkgsListContains(installeritempath) {
                errors.append(
                    "WARNING: \(identifier) refers to installer item: \(installeritemlocation). The pathname of the item in the repo has different case: \(match). This may cause issues depending on the case-sensitivity of the underlying filesystem."
                )
            } else {
                errors.append(
                    "WARNING: \(identifier) refers to missing installer item: \(installeritemlocation)"
                )
                return false
            }
        }
        
        // uninstaller checking
        if let uninstalleritemlocation = pkginfo["uninstaller_item_location"] as? String {
            if uninstalleritemlocation.isEmpty {
                errors.append(
                    "WARNING: empty or invalid uninstaller_item_location in \(identifier)")
                return false
            }
            let uninstalleritempath = "pkgs/" + uninstalleritemlocation
            // Check if the uninstaller item actually exists
            if !(pkgsList.contains(uninstalleritempath)) {
                // didn't find it in the pkgsList; let's look case-insensitive
                if let match = caseInsensitivePkgsListContains(uninstalleritempath) {
                    errors.append(
                        "WARNING: \(identifier) refers to uninstaller item: \(uninstalleritemlocation). The pathname of the item in the repo has different case: \(match). This may cause issues depending on the case-sensitivity of the underlying filesystem."
                    )
                } else {
                    errors.append(
                        "WARNING: \(identifier) refers to missing uninstaller item: \(uninstalleritemlocation)"
                    )
                    return false
                }
            }
        }
        // if we get here we passed all the checks
        return true
    }
    
    mutating func processPkgsinfo() {
        // Processes pkginfo files and updates catalogs and errors instance variables
        catalogs["all"] = [PlistDict]()
        // Walk through the pkginfo files
        for pkginfoIdentifier in pkgsinfoList {
            // Try to read the pkginfo file
            var pkginfo = PlistDict()
            do {
                let data = try repo.get(pkginfoIdentifier)
                pkginfo = try readPlistFromData(data) as? PlistDict ?? PlistDict()
            } catch {
                errors.append("Unexpected error reading \(pkginfoIdentifier): \(error)")
                continue
            }
            if !(pkginfo.keys.contains("name")) {
                errors.append("WARNING: \(pkginfoIdentifier)is missing name key")
                continue
            }
            // don't copy admin notes to catalogs
            if pkginfo.keys.contains("notes") {
                pkginfo["notes"] = nil
            }
            // strip out any keys that start with "_"
            for key in pkginfo.keys {
                if key.hasPrefix("_") {
                    pkginfo[key] = nil
                }
            }
            // sanity checking
            if !options.skipPkgCheck {
                let verified = verify(pkginfoIdentifier, pkginfo)
                if !verified, !options.force {
                    // Skip this pkginfo unless we're running with force flag
                    continue
                }
            }
            // append the pkginfo to the relevant catalogs
            catalogs["all"]?.append(pkginfo)
            if let catalog_list = pkginfo["catalogs"] as? [String] {
                if catalog_list.isEmpty {
                    errors.append("WARNING: \(pkginfoIdentifier)) has an empty catalogs array!")
                } else {
                    for catalog in catalog_list {
                        if !catalogs.keys.contains(catalog) {
                            catalogs[catalog] = [PlistDict]()
                        }
                        catalogs[catalog]?.append(pkginfo)
                        if options.verbose {
                            print("Adding \(pkginfoIdentifier) to \(catalog)...")
                        }
                    }
                }
            } else {
                errors.append("WARNING: \(pkginfoIdentifier)) has no catalogs array!")
            }
        }
        // look for catalog names that differ only in case
        var duplicateCatalogs = [String]()
        for name in catalogs.keys {
            let filtered_lowercase_names = catalogs.keys.filter { $0 != name }.map { $0.lowercased() }
            if filtered_lowercase_names.contains(name.lowercased()) {
                duplicateCatalogs.append(name)
            }
        }
        if !duplicateCatalogs.isEmpty {
            errors.append(
                "WARNING: There are catalogs with names that differ only by case. " +
                    "This may cause issues depending on the case-sensitivity of the " +
                    "underlying filesystem: \(duplicateCatalogs)")
        }
    }
    
    mutating func cleanupCatalogs() {
        // clear out old catalogs
        do {
            let catalogList = try repo.list("catalogs")
            for catalogName in catalogList {
                if !(catalogs.keys.contains(catalogName)) {
                    let catalogIdentifier = "catalogs/" + catalogName
                    do {
                        try repo.delete(catalogIdentifier)
                    } catch {
                        errors.append("Could not delete catalog \(catalogName): \(error)")
                    }
                }
            }
        } catch {
            errors.append("Could not get list of current catalogs to clean up: \(error)")
        }
    }
    
    mutating func makecatalogs() -> [String] {
        // Assembles all pkginfo files into catalogs.
        // User calling this needs to be able to write to the repo/catalogs
        // directory.
        // Returns a list of any errors it encountered
        
        // process pkgsinfo items
        processPkgsinfo()
        
        // clean up old catalogs no longer needed
        cleanupCatalogs()
        
        // write the new catalogs
        for key in catalogs.keys {
            if !(catalogs[key]?.isEmpty ?? true) {
                let catalogIdentifier = "catalogs/" + key
                do {
                    if let value = catalogs[key] {
                        let data = try plistToData(value)
                        try repo.put(catalogIdentifier, content: data)
                        if options.verbose {
                            print("Created \(catalogIdentifier)...")
                        }
                    }
                } catch let PlistError.writeError(description) {
                    errors.append("Could not serialize catalog \(key): \(description)")
                } catch let RepoError.error(description) {
                    errors.append("Failed to create catalog \(key): \(description)")
                } catch {
                    errors.append("Unexpected error creating catalog \(key): \(error)")
                }
            }
        }
 
        // make icon hashes
        let iconHashes = hashIcons()
        // create icon_hashes resource
        if !iconHashes.isEmpty {
            let iconHashesIdentifier = "icons/_icon_hashes.plist"
            do {
                let iconHashesData = try plistToData(iconHashes)
                try repo.put(iconHashesIdentifier, content: iconHashesData)
                if options.verbose {
                    print("Created \(iconHashesIdentifier)...")
                }
            } catch let PlistError.writeError(description) {
                errors.append("Could not serialize icon hashes: \(description)")
            } catch let RepoError.error(description) {
                errors.append("Failed to create \(iconHashesIdentifier): \(description)")
            } catch {
                errors.append("Unexpected error creating \(iconHashesIdentifier): \(error)")
            }
        }
        return errors
    }
}
