//
//  appusage.swift
//  munki
//
//  Created by Greg Neagle on 8/2/24.
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

let APPUSAGED_LOGFILENAME = "appusaged.log"

/// Returns path to our appusage DB
func appUsageDBPath() -> String {
    return managedInstallsDir(subpath: "application_usage.sqlite")
}

/// Tracks application launches, activations, and quits.
/// Also tracks Munki selfservice install and removal requests.
class ApplicationUsageRecorder {
    var logger = MunkiLogger(logname: APPUSAGED_LOGFILENAME)

    func _connect(_ databasePath: String = "") throws -> SQL3Connection {
        var db = ""
        if !databasePath.isEmpty {
            db = databasePath
        } else {
            db = appUsageDBPath()
        }
        return try SQL3Connection(db)
    }

    func _close(_ conn: SQL3Connection) {
        try? conn.close()
    }

    /// Detect whether a table exists by trying to perform a query against it
    func _detect_table(_ conn: SQL3Connection, detectQuery: String) throws -> Bool {
        do {
            let _ = try SQL3Statement(connection: conn, SQLString: detectQuery)
            // don't even have to run the query: if the table doesn't exist, the
            // statement prepare will throw an exception
            return true
        } catch let error as SQL3Error {
            if error.description.hasPrefix("Could not prepare statement: no such table:") {
                return false
            }
            throw SQL3Error(error.description)
        }
    }

    /// Detect whether the application usage table exists
    func _detect_application_usage_table(_ conn: SQL3Connection) throws -> Bool {
        let APPLICATION_USAGE_TABLE_DETECT = "SELECT * FROM application_usage LIMIT 1"
        return try _detect_table(conn, detectQuery: APPLICATION_USAGE_TABLE_DETECT)
    }

    /// Detect whether the install request table exists
    func _detect_install_request_table(_ conn: SQL3Connection) throws -> Bool {
        let INSTALL_REQUEST_TABLE_DETECT = "SELECT * FROM install_requests LIMIT 1"
        return try _detect_table(conn, detectQuery: INSTALL_REQUEST_TABLE_DETECT)
    }

    /// Create application usage table when it does not exist
    func _create_application_usage_table(_ conn: SQL3Connection) throws {
        try conn.execute("""
            CREATE TABLE application_usage (
                event TEXT,
                bundle_id TEXT,
                app_version TEXT,
                app_path TEXT,
                last_time INTEGER DEFAULT 0,
                number_times INTEGER DEFAULT 0,
                PRIMARY KEY (event, bundle_id)
            )
        """)
    }

    /// Create install request table when it does not exist
    func _create_install_request_table(_ conn: SQL3Connection) throws {
        try conn.execute("""
            CREATE TABLE install_requests (
                event TEXT,
                item_name TEXT,
                item_version TEXT,
                last_time INTEGER DEFAULT 0,
                number_times INTEGER DEFAULT 0,
                PRIMARY KEY (event, item_name)
            )
        """)
    }

    /// Insert usage data into application usage table.
    /// Uses an "upsert" statement so one action either creates a new record
    /// or updates an existing record
    func _insert_application_usage(_ conn: SQL3Connection, event: String, appData: [String: String]) throws {
        let now = Int(Date().timeIntervalSince1970)
        let bundleID = appData["bundle_id"] ?? "UNKNOWN_APP"
        let appVersion = appData["version"] ?? "0"
        let appPath = appData["path"] ?? ""
        let upsert = try SQL3Statement(
            connection: conn,
            SQLString: """
                INSERT INTO application_usage VALUES (
                    ?, ?, ?, ?, ?, 1
                )
                ON CONFLICT(event, bundle_id) DO UPDATE SET
                    app_version=excluded.app_version,
                    app_path=excluded.app_path,
                    last_time=excluded.last_time,
                    number_times=number_times+1
            """
        )
        try upsert.bindText(event, position: 1)
        try upsert.bindText(bundleID, position: 2)
        try upsert.bindText(appVersion, position: 3)
        try upsert.bindText(appPath, position: 4)
        try upsert.bindInt64(now, position: 5)

        let result = upsert.step()
        if result != SQL3Status.done {
            throw SQL3Error("Unexpected SQL insert/update result: \(result)")
        }
    }

    /// Insert install request into install request table.
    /// Uses an "upsert" statement so one action either creates a new record
    /// or updates an existing record
    func _insert_install_request(_ conn: SQL3Connection, request: [String: String]) throws {
        let now = Int(Date().timeIntervalSince1970)
        let event = request["event"] ?? "UNKNOWN_EVENT"
        let name = request["name"] ?? "UNKNOWN_ITEM"
        let version = request["version"] ?? "0"
        let upsert = try SQL3Statement(
            connection: conn,
            SQLString: """
                INSERT INTO install_requests VALUES (
                    ?, ?, ?, ?, 1
                )
                ON CONFLICT (event, item_name) DO UPDATE SET
                    item_version=excluded.item_version,
                    last_time=excluded.last_time,
                    number_times=number_times+1
            """
        )
        try upsert.bindText(event, position: 1)
        try upsert.bindText(name, position: 2)
        try upsert.bindText(version, position: 3)
        try upsert.bindInt64(now, position: 4)

        let result = upsert.step()
        if result != SQL3Status.done {
            throw SQL3Error("Unexpected SQL insert/update result: \(result)")
        }
    }

    func _recover_database() {
        // TODO: implement this
    }

    func verify_database() {
        // TODO: implement this
    }

    /// log application usage and add to database
    func log_application_usage(event: String, appData: [String: String]) {
        guard let bundleId = appData["bundle_id"] else {
            logger.warning("Application object had no bundle_id")
            return
        }
        let version = appData["version"] ?? "<no version>"
        let path = appData["path"] ?? "<no path>"
        logger.debug("\(event): bundle_id: \(bundleId) version: \(version) path:\(path)")

        do {
            let conn = try _connect()
            defer { _close(conn) }
            if try !_detect_application_usage_table(conn) {
                try _create_application_usage_table(conn)
            }
            try _insert_application_usage(conn, event: event, appData: appData)
        } catch {
            logger.error("Could not add app launch/quit event to database")
        }
    }

    /// log install requests and add to database
    func log_install_request(_ request: [String: String]) {
        guard let event = request["event"],
              let name = request["name"]
        else {
            logger.warning("Request dict is missing event or name")
            return
        }
        let version = request["version"] ?? "<no_version>"
        logger.debug("\(event): name: \(name) version: \(version)")

        do {
            let conn = try _connect()
            defer { _close(conn) }
            if try !_detect_install_request_table(conn) {
                try _create_install_request_table(conn)
            }
            try _insert_install_request(conn, request: request)
        } catch {
            logger.error("Could not add install/remove event to database")
        }
    }
}

/// A class to query our application usage db to determine the last time
/// an application was activated
class ApplicationUsageQuery {
    let db = appUsageDBPath()
    let dayInSeconds = 24 * 60 * 60
    var conn: SQL3Connection?
    var logger: MunkiLogger

    // open connection to DB
    init(logger: MunkiLogger) {
        self.logger = logger
        do {
            try conn = SQL3Connection(db)
        } catch {
            logger.error("Error connecting to \(db): \(error.localizedDescription)")
            conn = nil
        }
    }

    // close connection to DB
    deinit {
        if let conn {
            try? conn.close()
        }
    }

    /// Return how many days of data we have on file
    func daysOfData() -> Int {
        guard let connection = conn else { return 0 }
        let oldestRecordQuery = "SELECT last_time FROM application_usage ORDER BY last_time ASC LIMIT 1"
        do {
            let query = try SQL3Statement(
                connection: connection, SQLString: oldestRecordQuery
            )
            if query.step() == SQL3Status.row {
                let lastTime = Int(query.int64(column: 0))
                let now = Int(Date().timeIntervalSince1970)
                let timeDiff = now - lastTime
                return Int(timeDiff / dayInSeconds)
            }
        } catch {
            logger.error("Error querying \(db): \(error.localizedDescription)")
        }
        return 0
    }

    /// Perform db query and return the number of days since the last event
    /// occurred for bundle_id.
    /// Returns -2 if database is missing or broken;
    /// Returns -1 if there is no event record for the bundle_id
    /// Returns int number of days since last event otherwise
    func daysSinceLastUsageEvent(_ event: String, bundleID: String) -> Int {
        guard let connection = conn else { return -2 }
        let usageQuery = "SELECT last_time FROM application_usage WHERE event=? AND bundle_id=?"
        do {
            let query = try SQL3Statement(connection: connection)
            try query.prepare(usageQuery)
            try query.bindText(event, position: 1)
            try query.bindText(bundleID, position: 2)
            if query.step() == SQL3Status.row {
                let lastTime = Int(query.int64(column: 0))
                let now = Int(Date().timeIntervalSince1970)
                let timeDiff = now - lastTime
                return Int(timeDiff / dayInSeconds)
            } else {
                // no data for that event and bundleID
                return -1
            }
        } catch {
            logger.error("Error querying \(db): \(error.localizedDescription)")
            return -2
        }
    }

    /// Perform db query and return the number of days since the last
    /// install request occurred for itemName..
    /// Returns -2 if database is missing or broken;
    /// Returns -1 if there are no matching records for the itemName
    /// Returns int number of days since last event otherwise
    func daysSinceLastInstallEvent(_ event: String, itemName: String) -> Int {
        guard let connection = conn else { return -2 }
        let usageQuery = "SELECT last_time FROM install_requests WHERE event=? AND item_name=?"
        do {
            let query = try SQL3Statement(connection: connection)
            try query.prepare(usageQuery)
            try query.bindText(event, position: 1)
            try query.bindText(itemName, position: 2)
            if query.step() == SQL3Status.row {
                let lastTime = Int(query.int64(column: 0))
                let now = Int(Date().timeIntervalSince1970)
                let timeDiff = now - lastTime
                return Int(timeDiff / dayInSeconds)
            } else {
                // no data for that itemName
                return -1
            }
        } catch {
            logger.error("Error querying \(db): \(error.localizedDescription)")
            return -2
        }
    }
}
