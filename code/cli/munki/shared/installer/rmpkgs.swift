//
//  rmpkgs.swift
//  munki
//
//  Created by Greg Neagle on 7/17/24.
//
//  Copyright 2024-2026 The Munki Project. All rights reserved.
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

import Foundation

private let display = DisplayAndLog.main

/*
 #################################################################
 # our package db schema -- a subset of Apple's schema in Leopard
 #
 # 2024-07-17 Notes:
 #     This could almost certainly be further simplified, as the only
 #     used/useful things currently stored in the pkgs_paths table
 #     are pkg_key and path_key -- uid, gid, and perms are unused.
 #     The pkgs table could probably also be simplified; for our needs
 #     we don't need timestamp, owner, version, replaces, or even
 #     (I think) pkgname
 #     Our needs are really limited to finding all the paths that a
 #     given pkgid installs that are not installed by any other pkgid.
 #
 # CREATE TABLE paths (path_key INTEGER PRIMARY KEY AUTOINCREMENT,
 #                     path VARCHAR NOT NULL UNIQUE )
 # CREATE TABLE pkgs (pkg_key INTEGER PRIMARY KEY AUTOINCREMENT,
 #                    timestamp INTEGER NOT NULL,
 #                    owner INTEGER NOT NULL,
 #                    pkgid VARCHAR NOT NULL,
 #                    vers VARCHAR NOT NULL,
 #                    ppath VARCHAR NOT NULL,
 #                    pkgname VARCHAR NOT NULL,
 #                    replaces INTEGER )
 # CREATE TABLE pkgs_paths (pkg_key INTEGER NOT NULL,
 #                          path_key INTEGER NOT NULL,
 #                          uid INTEGER,
 #                          gid INTEGER,
 #                          perms INTEGER )
 #################################################################
 */

/// Returns path to our package DB
func pkgDBPath() -> String {
    return managedInstallsDir(subpath: "b.receiptdb")
}

/// Checks to see if our internal package (receipt) DB should be rebuilt.
func shouldRebuildReceiptDB() -> Bool {
    let dbPath = pkgDBPath()
    let filemanager = FileManager.default
    if !filemanager.fileExists(atPath: dbPath) {
        return true
    }
    // has anything been installed since we built our database?
    let installHistoryPath = "/Library/Receipts/InstallHistory.plist"
    if filemanager.fileExists(atPath: installHistoryPath) {
        var installHistoryModDate = Date()
        var pkgDBModDate = Date.distantPast
        if let attributes = try? filemanager.attributesOfItem(atPath: installHistoryPath) {
            installHistoryModDate = (attributes as NSDictionary).fileModificationDate() ?? Date()
        }
        if let attributes = try? filemanager.attributesOfItem(atPath: dbPath) {
            pkgDBModDate = (attributes as NSDictionary).fileModificationDate() ?? Date.distantPast
        }
        return installHistoryModDate > pkgDBModDate
    }
    // /Library/Receipts/InstallHistory.plist doesn't exist!
    // better just rebuild the db since we don't know how accurate it is
    return true
}

/// Creates the tables needed for our internal package database.
func createReceiptDBTables(_ conn: SQL3Connection) throws {
    try conn.execute("""
    CREATE TABLE paths
        (path_key INTEGER PRIMARY KEY AUTOINCREMENT,
         path VARCHAR NOT NULL UNIQUE )
    """)
    try conn.execute("""
    CREATE TABLE pkgs
        (pkg_key INTEGER PRIMARY KEY AUTOINCREMENT,
         timestamp INTEGER NOT NULL,
         owner INTEGER NOT NULL,
         pkgid VARCHAR NOT NULL,
         vers VARCHAR NOT NULL,
         ppath VARCHAR NOT NULL,
         pkgname VARCHAR NOT NULL,
         replaces INTEGER )
    """)
    try conn.execute("""
    CREATE TABLE pkgs_paths
        (pkg_key INTEGER NOT NULL,
         path_key INTEGER NOT NULL,
         uid INTEGER,
         gid INTEGER,
         perms INTEGER )
    """)
}

struct PkgData {
    var timestamp: Int = 0
    var owner: Int = 0
    var pkgid: String
    var version: String
    var ppath: String
    var files: [String] = []
}

/// Inserts a pkg row into the db, returns rowid
/// (which should be an alias for the integer primary key "pkg_key")
func insertPkgDataIntoPkgDB(pkgdata: PkgData
) throws {
    let connection = try SQL3Connection(pkgDBPath())
    try connection.execute("PRAGMA journal_mode = WAL;")
    try connection.execute("PRAGMA synchronous = normal;")
    try connection.execute("BEGIN TRANSACTION")
    let statementString = "INSERT INTO pkgs (timestamp, owner, pkgid, vers, ppath, pkgname) values (?, ?, ?, ?, ?, ?)"
    let statement = try SQL3Statement(connection: connection)
    try statement.prepare(statementString)
    try statement.bindInt64(pkgdata.timestamp, position: 1)
    try statement.bindInt64(pkgdata.owner, position: 2)
    try statement.bindText(pkgdata.pkgid, position: 3)
    try statement.bindText(pkgdata.version, position: 4)
    try statement.bindText(pkgdata.ppath, position: 5)
    try statement.bindText(pkgdata.pkgid, position: 6)
    if statement.step() != SQL3Status.done {
        throw MunkiError("Could not insert pkg data into db: \(connection.errorMessage())")
    }
    let pkgKey = connection.lastrowid()
    try statement.finalize()
    try insertFileInfoIntoPkgDB(connection: connection, pkgKey: pkgKey, pkgdata: pkgdata)
    try connection.execute("END TRANSACTION")
    try connection.close()
}

/// Inserts info into paths and pkg_paths tables
func insertFileInfoIntoPkgDB(
    connection: SQL3Connection, pkgKey: Int64, pkgdata: PkgData
) throws {
    let pathsQuery = try SQL3Statement(
        connection: connection,
        SQLString: "SELECT path_key FROM paths WHERE path = ?"
    )
    let pathsInsert = try SQL3Statement(
        connection: connection,
        SQLString: "INSERT INTO paths (path) values (?)"
    )
    let pkgsPathsInsert = try SQL3Statement(
        connection: connection,
        SQLString: "INSERT INTO pkgs_paths (pkg_key, path_key, uid, gid, perms) values (?, ?, ?, ?, ?)"
    )
    let perms = "0000"
    let uid = 0
    let gid = 0
    for file in pkgdata.files {
        if file.isEmpty { continue }
        var path = file
        if !pkgdata.ppath.isEmpty {
            // prepend ppath
            path = (pkgdata.ppath as NSString).appendingPathComponent(path)
        }
        var pathKey = Int64(0)
        try pathsQuery.reset()
        try pathsQuery.bindText(path, position: 1)
        // if we get a result of SQLITE_ROW, we found it
        if pathsQuery.step() == SQL3Status.row {
            pathKey = pathsQuery.int64(column: 0)
        } else {
            // need to insert the path
            try pathsInsert.reset()
            try pathsInsert.bindText(path, position: 1)
            if pathsInsert.step() != SQL3Status.done {
                throw MunkiError("Could not insert path data into db: \(connection.errorMessage())")
            }
            pathKey = connection.lastrowid()
        }
        // now insert into pkgs_paths table
        try pkgsPathsInsert.reset()
        try pkgsPathsInsert.bindInt64(Int(pkgKey), position: 1)
        try pkgsPathsInsert.bindInt64(Int(pathKey), position: 2)
        try pkgsPathsInsert.bindInt64(uid, position: 3)
        try pkgsPathsInsert.bindInt64(gid, position: 4)
        try pkgsPathsInsert.bindText(perms, position: 5)
        if pkgsPathsInsert.step() != SQL3Status.done {
            throw MunkiError("Could not insert pkgs_path data into db: \(connection.errorMessage())")
        }
    }
}

/// Gets info about pkg from pkgutil
func getPkgMetaData(_ pkg: String) async throws -> PkgData {
    let result = await runCliAsync(
        "/usr/sbin/pkgutil", arguments: ["--pkg-info-plist", pkg]
    )
    if result.exitcode != 0 {
        throw MunkiError("Error calling pkgutil: \(result.error)")
    }
    let (pliststr, _) = parseFirstPlist(fromString: result.output)
    guard let plist = try readPlist(fromString: pliststr) as? PlistDict else {
        throw MunkiError("Could not parse expected data from pkgutil")
    }
    var timestamp = 0
    var version = "0"
    var ppath = ""

    guard let pkgid = plist["pkgid"] as? String else {
        // something terribly wrong
        throw MunkiError("Could not parse expected data from pkgutil")
    }
    if let pkgVersion = plist["pkg-version"] as? String {
        version = pkgVersion
    }
    if let installTime = plist["install-time"] as? Int {
        timestamp = installTime
    }
    if let installLocation = plist["install-location"] as? String {
        ppath = installLocation
        if ppath.hasPrefix("./") {
            ppath.removeFirst(2)
        }
        if ppath.hasSuffix("/") {
            ppath.removeLast()
        }
    }
    return PkgData(
        timestamp: timestamp, pkgid: pkgid, version: version, ppath: ppath
    )
}

/// Returns a list of files installed by pkg
func getFilesForPkg(_ pkg: String) async throws -> [String] {
    let result = await runCliAsync("/usr/sbin/pkgutil", arguments: ["--files", pkg])
    if result.exitcode != 0 {
        throw MunkiError("Error calling pkgutil: \(result.error)")
    }
    return result.output.components(separatedBy: "\n").filter { !$0.isEmpty }
}

/// Adds metadata for pkgid to our database
func getPkgDataAndAddtoDB(pkgid: String) async throws {
    async let tempPkgdata = try getPkgMetaData(pkgid)
    async let fileList = try getFilesForPkg(pkgid)
    var pkgdata = try await tempPkgdata
    pkgdata.files = try await fileList
    try insertPkgDataIntoPkgDB(pkgdata: pkgdata)
}

/// Imports package data from pkgutil into our internal package database.
func importFromPkgutil() async throws {
    let result = await runCliAsync("/usr/sbin/pkgutil", arguments: ["--pkgs"])
    if result.exitcode != 0 {
        throw MunkiError("Error calling pkgutil: \(result.error)")
    }
    let pkglist = result.output.components(separatedBy: "\n").filter { !$0.isEmpty }
    let pkgCount = pkglist.count
    var current = 0
    displayPercentDone(current: current, maximum: pkgCount)
    for pkg in pkglist {
        if stopRequested() {
            throw UserCancelled()
        }
        current += 1
        display.detail("Importing \(pkg)...")
        try await getPkgDataAndAddtoDB(pkgid: pkg)
        displayPercentDone(current: current, maximum: pkgCount)
    }
}

/// Builds or rebuilds our internal package database.
func initReceiptDB(forcerebuild: Bool = false) async throws {
    if !shouldRebuildReceiptDB(), !forcerebuild {
        // we'll use existing db
        return
    }

    display.minorStatus("Gathering information on installed packages")

    let pkgdb = pkgDBPath()
    let filemanager = FileManager.default
    if filemanager.fileExists(atPath: pkgdb) {
        do {
            try filemanager.removeItem(atPath: pkgdb)
        } catch {
            throw MunkiError("Could not remove out-of-date receipt database.")
        }
    }

    let conn = try SQL3Connection(pkgdb)
    try conn.execute("PRAGMA journal_mode = WAL;")
    try conn.execute("PRAGMA synchronous = normal;")
    try createReceiptDBTables(conn)
    try conn.close()
    try await importFromPkgutil()
}

/// Prepares a list of values for use in a SQL query
func quoteAndJoin(_ stringList: [String]) -> String {
    let quotedStrings = stringList.map { "\"\($0)\"" }
    return "(" + quotedStrings.joined(separator: ",") + ")"
}

/// Given a list of package ids, returns
/// a list of pkg_keys from the pkgs table in our database.
func getPkgKeysFromPkgDB(pkgids: [String]) throws -> [String] {
    var keys = [String]()
    let sqlString = "SELECT pkg_key FROM pkgs WHERE pkgid IN " + quoteAndJoin(pkgids)
    let connection = try SQL3Connection(pkgDBPath())
    let query = try SQL3Statement(connection: connection, SQLString: sqlString)
    while query.step() == SQL3Status.row {
        keys.append(query.text(column: 0))
    }
    return keys
}

/// Queries our database for paths to remove.
func getPathsToRemove(pkgKeys: [String]) throws -> [String] {
    var pathsToRemove = [String]()
    let keyList = quoteAndJoin(pkgKeys)
    let selectedPkgs = "SELECT DISTINCT path_key FROM pkgs_paths WHERE pkg_key IN " + keyList
    let otherPkgs = "SELECT DISTINCT path_key FROM pkgs_paths WHERE pkg_key NOT IN " + keyList
    let combinedQuerySQL = """
        SELECT path FROM paths WHERE (
            path_key IN (\(selectedPkgs)) AND path_key NOT IN (\(otherPkgs)))
    """

    let connection = try SQL3Connection(pkgDBPath())
    let query = try SQL3Statement(connection: connection, SQLString: combinedQuerySQL)
    while query.step() == SQL3Status.row {
        pathsToRemove.append(query.text(column: 0))
    }
    return pathsToRemove
}

func deletePkgKeyFromDB(connection: SQL3Connection, pkgKey: Int) throws {
    let pkgsPathsDelete = try SQL3Statement(
        connection: connection,
        SQLString: "DELETE FROM pkgs_paths WHERE pkg_key = ?"
    )
    try pkgsPathsDelete.bindInt64(pkgKey, position: 1)
    if pkgsPathsDelete.step() != SQL3Status.done {
        // maybe print an error or warning?
    }
    let pkgsDelete = try SQL3Statement(
        connection: connection,
        SQLString: "DELETE FROM pkgs WHERE pkg_key = ?"
    )
    try pkgsDelete.bindInt64(pkgKey, position: 1)
    if pkgsDelete.step() != SQL3Status.done {
        // maybe print an error or warning?
    }
}

/// Removes info about pkgid from Apple's pkgutil database
func forgetPkgFromAppleDB(_ pkgid: String) {
    let result = runCLI("/usr/sbin/pkgutil", arguments: ["--forget", pkgid])
    if result.exitcode == 0 {
        if !result.output.isEmpty {
            display.detail(result.output)
        }
    } else {
        // maybe a warning?
    }
}

/// Removes receipt data from our internal package database,
/// and optionally Apple's package database.
func removePkgReceipts(pkgKeys: [String], updateApplePkgDB: Bool = true) throws {
    let taskCount = pkgKeys.count

    display.minorStatus("Removing receipt info")
    displayPercentDone(current: 0, maximum: taskCount)
    var taskIndex = 0
    let connection = try SQL3Connection(pkgDBPath())

    for pkgKey in pkgKeys {
        taskIndex += 1
        guard let intPkgKey = Int(pkgKey) else {
            continue
        }
        var pkgid = ""
        let query = try SQL3Statement(
            connection: connection,
            SQLString: "SELECT pkgid FROM pkgs WHERE pkg_key = ?"
        )
        try query.bindInt64(intPkgKey, position: 1)
        if query.step() == SQL3Status.row {
            pkgid = query.text(column: 0)
            display.detail("Removing package data from internal database...")
            try deletePkgKeyFromDB(connection: connection, pkgKey: intPkgKey)
            if updateApplePkgDB {
                forgetPkgFromAppleDB(pkgid)
            }
        }
        displayPercentDone(current: taskIndex, maximum: taskCount)
    }
    // new remove orphaned paths from DB
    let statement = try SQL3Statement(
        connection: connection,
        SQLString: "DELETE FROM paths WHERE path_key NOT IN (SELECT DISTINCT path_key FROM pkgs_paths)"
    )
    if statement.step() != SQL3Status.done {
        // maybe print an error or warning?
        // Not really fatal, we just have some extra paths hanging around
    }
    displayPercentDone(current: taskCount, maximum: taskCount)
}

/// Returns true if path is a bundle-style directory.
func pathIsBundle(_ path: String) -> Bool {
    let bundleExtensions = [".action",
                            ".app",
                            ".bundle",
                            ".clr",
                            ".colorPicker",
                            ".component",
                            ".dictionary",
                            ".docset",
                            ".framework",
                            ".fs",
                            ".kext",
                            ".loginPlugin",
                            ".mdiimporter",
                            ".monitorPanel",
                            ".mpkg",
                            ".osax",
                            ".pkg",
                            ".plugin",
                            ".prefPane",
                            ".qlgenerator",
                            ".saver",
                            ".service",
                            ".slideSaver",
                            ".SpeechRecognizer",
                            ".SpeechSynthesizer",
                            ".SpeechVoice",
                            ".spreporter",
                            ".wdgt"]
    return pathIsDirectory(path) &&
        bundleExtensions.contains((path as NSString).pathExtension)
}

/// Check the path to see if it's inside a bundle.
func pathIsInsideBundle(_ path: String) -> Bool {
    var currentPath = path
    while currentPath.count > 1 {
        if pathIsBundle(currentPath) {
            return true
        }
        // chop off last item in path
        currentPath = (currentPath as NSString).deletingLastPathComponent
    }
    // if we get here, we didn't find a bundle path
    return false
}

/// Attempts to remove all the paths in the pathsToRemove list
func removeFilesystemItems(pathsToRemove: [String], forceDeleteBundles: Bool) {
    var removalErrors = [String]()
    let itemCount = pathsToRemove.count
    display.majorStatus("Removing \(itemCount) filesystem items")
    let filemanager = FileManager.default

    func removeItemOrRecordError(_ item: String) {
        do {
            try filemanager.removeItem(atPath: item)
        } catch {
            let msg = "Couldn't remove item \(item): \(error)"
            display.error(msg)
            removalErrors.append(msg)
        }
    }

    var itemIndex = 0
    displayPercentDone(current: itemIndex, maximum: itemCount)
    for item in pathsToRemove.sorted().reversed() {
        itemIndex += 1
        let pathToRemove = "/" + item
        if pathIsRegularFile(pathToRemove) || pathIsSymlink(pathToRemove) {
            display.detail("Removing : \(pathToRemove)")
            removeItemOrRecordError(pathToRemove)
            continue
        }
        if !pathIsDirectory(pathToRemove) {
            // filetype we don't know how to handle
            let msg = "Couldn't remove item \(item): unsupported filesystem type"
            display.error(msg)
            removalErrors.append(msg)
            continue
        }
        // it must be a directory
        var dirContents = [String]()
        do {
            dirContents = try filemanager.contentsOfDirectory(atPath: pathToRemove)
        } catch {
            let msg = "Couldn't get contents of directory \(item): \(error)"
            display.error(msg)
            removalErrors.append(msg)
            continue
        }
        if dirContents.isEmpty || dirContents == [".DS_Store"] {
            // directory is empty, so remove it
            // If there's only a .DS_Store file we'll consider it empty
            removeItemOrRecordError(pathToRemove)
            continue
        }
        // the directory is marked for deletion but isn't empty.
        // if so directed, if it's a bundle (like .app), we should
        // remove it anyway - no use having a broken bundle hanging
        // around
        if forceDeleteBundles, pathIsBundle(pathToRemove) {
            removeItemOrRecordError(pathToRemove)
        } else {
            // if this path is inside a bundle, and we've been
            // directed to force remove bundles,
            // we don't need to warn because it's going to be
            // removed with the bundle.
            // Otherwise, we should warn about non-empty
            // directories.
            if !forceDeleteBundles || !pathIsInsideBundle(pathToRemove) {
                let msg = "Did not remove \(pathToRemove) because it is not empty."
                display.error(msg)
                removalErrors.append(msg)
            }
        }
    }
    if !removalErrors.isEmpty {
        display.info("---------------------------------------------------")
        display.info("There were problems removing some filesystem items.")
        display.info("---------------------------------------------------")
        display.info(removalErrors.joined(separator: "\n"))
    }
}

/// Our main function, called to remove items based on receipt info.
/// if listFiles is true, this is a dry run
func removePackages(
    _ pkgids: [String],
    forceDeleteBundles: Bool = false,
    listFiles: Bool = false,
    rebuildPkgDB: Bool = false,
    noRemoveReceipts: Bool = false,
    noUpdateApplePkgDB: Bool = false
) async -> Int {
    if pkgids.isEmpty {
        display.error("You must specify at least one package to remove!")
        return -2
    }
    do {
        try await initReceiptDB(forcerebuild: rebuildPkgDB)
    } catch _ as UserCancelled {
        return -128
    } catch {
        display.error("Could not initialize receipt database: \(error)")
        return -3
    }
    var pkgKeys = [String]()
    do {
        pkgKeys = try getPkgKeysFromPkgDB(pkgids: pkgids)
        if pkgKeys.isEmpty {
            throw MunkiError("No matching pkgs found in database")
        }
    } catch {
        display.error("Error retrieving pkg keys: \(error)")
        return -4
    }
    if stopRequested() {
        return -128
    }
    var pathsToRemove = [String]()
    do {
        display.minorStatus("Determining which filesystem items to remove")
        munkiStatusPercent(-1)
        pathsToRemove = try getPathsToRemove(pkgKeys: pkgKeys)
    } catch {
        display.error("Error getting paths to remove: \(error)")
        return -4
    }
    if pathsToRemove.isEmpty {
        display.minorStatus("Nothing to remove.")
    } else if listFiles {
        // only print the paths to be removed; don't actually remove them
        print("The following filesystem items would be removed:")
        for path in pathsToRemove.sorted() {
            print("    /" + path)
        }
    } else {
        munkiStatusDisableStopButton()
        removeFilesystemItems(
            pathsToRemove: pathsToRemove, forceDeleteBundles: forceDeleteBundles
        )
        if !noRemoveReceipts {
            do {
                try removePkgReceipts(pkgKeys: pkgKeys, updateApplePkgDB: !noUpdateApplePkgDB)
            } catch {
                display.error("Failed to remove pkg receipts: \(error)")
            }
        }
        munkiStatusEnableStopButton()
        display.minorStatus("Package removal finished.")
    }
    return 0
}
