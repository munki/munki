//
//  rmpkgs.swift
//  munki
//
//  Created by Greg Neagle on 7/17/24.
//
//  Copyright 2024 Greg Neagle.
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

func pkgDBPath() -> String {
    // returns path to our package DB
    // let dbDir = pref("ManagedInstallDir") as? String ?? DEFAULT_MANAGED_INSTALLS_DIR
    let dbDir = "/tmp"
    return (dbDir as NSString).appendingPathComponent("b.receiptdb")
}

func shouldRebuildReceiptDB() -> Bool {
    // Checks to see if our internal package (receipt) DB should be rebuilt.
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

func createReceiptDBTables(_ conn: SQL3Connection) throws {
    // Creates the tables needed for our internal package database.
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

func insertPkgDataIntoPkgDB(
    connection: SQL3Connection, pkgdata: PkgData
) throws {
    // inserts a pkg row into the db, returns rowid (which should be an alias for
    // the integer primary key "pkg_key"
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
    try insertFileInfoIntoPkgDB(connection: connection, pkgKey: pkgKey, pkgdata: pkgdata)
}

func insertFileInfoIntoPkgDB(
    connection: SQL3Connection, pkgKey: Int64, pkgdata: PkgData
) throws {
    // inserts info into paths and pkg_paths tables
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

func getFilesForPkg(_ pkg: String) async throws -> [String] {
    // Returns a list of files installed by pkg
    let result = await runCliAsync("/usr/sbin/pkgutil", arguments: ["--files", pkg])
    if result.exitcode != 0 {
        throw MunkiError("Error calling pkgutil: \(result.error)")
    }
    return result.output.components(separatedBy: "\n").filter { !$0.isEmpty }
}

func getPkgData(connection: SQL3Connection, pkgid: String) async throws -> PkgData {
    async let tempPkgdata = try getPkgMetaData(pkgid)
    async let fileList = try getFilesForPkg(pkgid)
    var pkgdata = try await tempPkgdata
    pkgdata.files = try await fileList
    try insertPkgDataIntoPkgDB(connection: connection, pkgdata: pkgdata)
    return pkgdata
}

func importFromPkgutil(connection: SQL3Connection) async throws {
    // Imports package data from pkgutil into our internal package database.
    let result = await runCliAsync("/usr/sbin/pkgutil", arguments: ["--pkgs"])
    if result.exitcode != 0 {
        throw MunkiError("Error calling pkgutil: \(result.error)")
    }
    let pkglist = result.output.components(separatedBy: "\n").filter { !$0.isEmpty }
    try connection.execute("BEGIN TRANSACTION")
    let pkgCount = pkglist.count
    var currentIndex = 0
    await withThrowingTaskGroup(of: PkgData.self) { group in
        for pkg in pkglist {
            // TODO: handle user cancellation requests
            // currentIndex += 1
            // displayDetail("Importing \(pkg)...")
            // displayPercentDone(current: currentIndex, maximum: pkgCount)
            group.addTask {
                try await getPkgData(connection: connection, pkgid: pkg)
            }
        }
    }
    try connection.execute("END TRANSACTION")
    displayPercentDone(current: pkgCount, maximum: pkgCount)
}

func initReceiptDB(forcerebuild: Bool = false) async throws {
    // Builds or rebuilds our internal package database.
    //
    // This is currently about 1/3 as fast as the Python version.
    // Much of the slowdown appears to be in the calling of the various CLI tools
    // Is this NSTask/Process 's fault?

    if !shouldRebuildReceiptDB(), !forcerebuild {
        // we'll use existing db
        return
    }

    displayMinorStatus("Gathering information on installed packages")

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
    try await importFromPkgutil(connection: conn)
}

func quoteAndJoin(_ stringList: [String]) -> String {
    // prepares a list of values for use in a SQL query
    let quotedStrings = stringList.map { "\"\($0)\"" }
    return "(" + quotedStrings.joined(separator: ",") + ")"
}

func getPkgKeysFromPkgDB(pkgids: [String]) throws -> [String] {
    // Given a list of package ids, returns
    // a list of pkg_keys from the pkgs table in our database.
    var keys = [String]()
    let sqlString = "SELECT pkg_key FROM pkgs WHERE pkgid IN " + quoteAndJoin(pkgids)
    let connection = try SQL3Connection(pkgDBPath())
    let query = try SQL3Statement(connection: connection, SQLString: sqlString)
    while query.step() == SQL3Status.row {
        keys.append(query.text(column: 0))
    }
    return keys
}

func getPathsToRemove(pkgKeys: [String]) throws -> [String] {
    // Queries our database for paths to remove.
    var pathsToRemove = [String]()
    let keyList = quoteAndJoin(pkgKeys)
    let selectedPkgs = "SELECT DISTINCT path_key FROM pkgs_paths WHERE pkg_key IN " + keyList
    let otherPkgs = "SELECT DISTINCT path_key FROM pkgs_paths WHERE pkg_key NOT IN " + keyList
    let combinedQuerySQL = """
        SELECT path FROM paths WHERE (
            path_key IN (\(selectedPkgs)) AND path_key NOT IN (\(otherPkgs)))
    """
    // TODO: move this output to a calling function. This is the wrong place for this
    displayMinorStatus("Determining which filesystem items to remove")
    // TODO: add munkistatus output
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

func forgetPkgFromAppleDB(_ pkgid: String) {
    let result = runCLI("/usr/sbin/pkgutil", arguments: ["--forget", pkgid])
    if result.exitcode == 0 {
        if !result.output.isEmpty {
            displayDetail(result.output)
        }
    } else {
        // maybe a warning?
    }
}

func removePkgReceipts(pkgKeys: [String], updateApplePkgDB: Bool = true) throws {
    // Removes receipt data from our internal package database,
    // and optionally Apple's package database.
    var taskCount = pkgKeys.count

    displayMinorStatus("Removing receipt info")
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
            displayDetail("Removing package data from internal database...")
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

func removeFilesystemItems(pathsToRemove: [String], forceDeleteBundles: Bool) {
    // Attempts to remove all the paths in the pathsToRemove list
    var removalErrors = [String]()
    let itemCount = pathsToRemove.count
    displayMajorStatus("Removing \(itemCount) filesystem items")
    let filemanager = FileManager.default

    var itemIndex = 0
    displayPercentDone(current: itemIndex, maximum: itemCount)
    for item in pathsToRemove.sorted().reversed() {
        itemIndex += 1
        let pathToRemove = "/" + item
        if pathIsRegularFile(item) || pathIsSymlink(item) {
            displayDetail("Removing : \(pathToRemove)")
            do {
                try filemanager.removeItem(atPath: item)
            } catch {
                let msg = "Couldn't remove item \(item): \(error)"
                displayError(msg)
                removalErrors.append(msg)
            }
        } else if pathIsDirectory(item) {
            // it can't be a symlink to a directory
        }
    }
}
