//
//  sqlite3.swift
//  munki
//
//  Created by Greg Neagle on 7/17/24.
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
import SQLite3

/// Yes this is yet another wrapper around the SQLite3 C API.
/// Munki doesn't need a wide range of functionality, and I'm porting from python's sqlite3
/// implementation, which doesn't necessarily map well to some of the existing sqlite3 packages
/// for Swift.
/// We might revisit this in the future.

/// Some common SQLite3 status codes to share with calling code
/// so it does not also have to import sqlite3
enum SQL3Status {
    static let ok = SQLITE_OK
    static let error = SQLITE_ERROR
    static let row = SQLITE_ROW
    static let done = SQLITE_DONE
}

/// General error class for errors
struct SQL3Error: Error, CustomStringConvertible {
    public internal(set) var message: String

    /// Creates a new error with the given message.
    public init(_ message: String) {
        self.message = message
    }

    public var description: String {
        return message
    }
}

let SQLITE_STATIC = unsafeBitCast(0, to: sqlite3_destructor_type.self)
let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

/// Class wrapper for sqlite3 statements
class SQL3Statement {
    var conn: SQL3Connection
    var statement: OpaquePointer?

    init(connection: SQL3Connection) throws {
        conn = connection
    }

    init(connection: SQL3Connection, SQLString: String) throws {
        conn = connection
        try prepare(SQLString)
    }

    deinit {
        try? finalize()
    }

    func prepare(_ str: String) throws {
        let resultcode = sqlite3_prepare_v2(conn.db, str, -1, &statement, nil)
        if resultcode != SQLITE_OK {
            throw SQL3Error("Could not prepare statement: \(conn.errorMessage())")
        }
    }

    func bindText(_ text: String, position: Int32) throws {
        let resultcode = sqlite3_bind_text(statement, position, text, -1, SQLITE_TRANSIENT)
        if resultcode != SQLITE_OK {
            throw SQL3Error("Could not bind text to statement: \(conn.errorMessage())")
        }
    }

    func bindInt64(_ int: Int, position: Int32) throws {
        let resultcode = sqlite3_bind_int64(statement, position, sqlite3_int64(int))
        if resultcode != SQLITE_OK {
            throw SQL3Error("Could not bind text to statement: \(conn.errorMessage())")
        }
    }

    func step() -> Int32 {
        return sqlite3_step(statement)
    }

    func reset() throws {
        let resultcode = sqlite3_reset(statement)
        if resultcode != SQLITE_OK {
            throw SQL3Error("Could not reset statement: \(conn.errorMessage())")
        }
    }

    func finalize() throws {
        if statement != nil {
            let resultcode = sqlite3_finalize(statement)
            statement = nil
            if resultcode != SQLITE_OK {
                throw SQL3Error("Could not finalize statement: \(conn.errorMessage())")
            }
        }
    }

    func int64(column: Int32) -> Int64 {
        return sqlite3_column_int64(statement, column)
    }

    func text(column: Int32) -> String {
        if let cString = sqlite3_column_text(statement, column) {
            return String(cString: cString)
        } else {
            return ""
        }
    }
}

/// Class wrapper for sqlite3 connections
class SQL3Connection {
    var db: OpaquePointer?

    init(_ path: String) throws {
        try open(path)
    }

    deinit {
        try? close()
    }

    func close() throws {
        if db != nil {
            let resultcode = sqlite3_close(db)
            db = nil
            if resultcode != SQLITE_OK {
                throw SQL3Error("Error closing database: \(resultcode)")
            }
        }
    }

    func open(_ path: String) throws {
        if db != nil {
            try close()
        }
        let resultcode = sqlite3_open_v2(path, &db, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_NOMUTEX, nil)
        if resultcode != SQLITE_OK {
            try? close()
            db = nil
            throw SQL3Error("Error opening database: \(resultcode)")
        }
    }

    func errorMessage() -> String {
        if let cstr = sqlite3_errmsg(db) {
            return String(cString: cstr)
        }
        return ""
    }

    func execute(_ text: String) throws {
        let resultcode = sqlite3_exec(db, text, nil, nil, nil)
        if resultcode != SQLITE_OK {
            throw SQL3Error("Could not execute: \(errorMessage())")
        }
    }

    func lastrowid() -> Int64 {
        return sqlite3_last_insert_rowid(db)
    }
}
