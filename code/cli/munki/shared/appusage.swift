//
//  appusage.swift
//  munki
//
//  Created by Greg Neagle on 8/2/24.
//

import Foundation

func appUsageDBPath() -> String {
    // returns path to our appusage DB
    // let dbDir = pref("ManagedInstallDir") as? String ?? DEFAULT_MANAGED_INSTALLS_DIR
    let dbDir = "/tmp"
    return (dbDir as NSString).appendingPathComponent("application_usage.sqlite")
}

class ApplicationUsageRecorder {
    // Tracks application launches, activations, and quits.
    // Also tracks Munki selfservice install and removal requests.

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

    func _detect_table(_ conn: SQL3Connection, detectQuery: String) throws -> Bool {
        // Detect whether a table exists by trying to perform a query against it
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

    func _detect_application_usage_table(_ conn: SQL3Connection) throws -> Bool {
        // Detect whether the application usage table exists
        let APPLICATION_USAGE_TABLE_DETECT = "SELECT * FROM application_usage LIMIT 1"
        return try _detect_table(conn, detectQuery: APPLICATION_USAGE_TABLE_DETECT)
    }

    func _detect_install_request_table(_ conn: SQL3Connection) throws -> Bool {
        // Detect whether the install request table exists
        let INSTALL_REQUEST_TABLE_DETECT = "SELECT * FROM install_requests LIMIT 1"
        return try _detect_table(conn, detectQuery: INSTALL_REQUEST_TABLE_DETECT)
    }

    func _create_application_usage_table(_ conn: SQL3Connection) throws {
        // Create application usage table when it does not exist
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

    func _create_install_request_table(_ conn: SQL3Connection) throws {
        // Create install request table when it does not exist
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

    func _insert_application_usage(_ conn: SQL3Connection, event: String, appData: [String: String]) throws {
        // Insert usage data into application usage table.
        // Uses an "upsert" statement so one action either creates a new record
        // or updates an existing record
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

    func _insert_install_request(_ conn: SQL3Connection, request: [String: String]) throws {
        // Insert install request into install request table.
        // Uses an "upsert" statement so one action either creates a new record
        // or updates an existing record
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

    func log_application_usage(event: String, appData: [String: String]) {
        // log application usage and add to database
        if appData["bundle_id"] == nil {
            // TODO: log.warning "Application object had no bundle_id"
            return
        }
        // TODO: log.debug
        /* logging.debug('%s: bundle_id: %s version: %s path: %s', event,
         app_dict.get('bundle_id'),
         app_dict.get('version'),
         app_dict.get('path')) */

        do {
            let conn = try _connect()
            defer { _close(conn) }
            if try !_detect_application_usage_table(conn) {
                try _create_application_usage_table(conn)
            }
            try _insert_application_usage(conn, event: event, appData: appData)
        } catch {
            // TODO: logging.error("Could not add app launch/quit event to database")
        }
    }

    func log_install_request(_ request: [String: String]) {
        // log install requests and add to database
        if request["event"] == nil || request["name"] == nil {
            // TODO: logging.warning("Request dict is missing event or name:")
            return
        }
        // TODO: log.debug
        /* logging.debug('%s: name: %s version: %s',
         request_dict.get('event'),
         request_dict.get('name'),
         request_dict.get('version')) */
        do {
            let conn = try _connect()
            defer { _close(conn) }
            if try !_detect_install_request_table(conn) {
                try _create_install_request_table(conn)
            }
            try _insert_install_request(conn, request: request)
        } catch {
            // TODO: logging.error("Could not add install/remove event to database")
        }
    }
}
