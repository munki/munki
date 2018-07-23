//
//  authrestart.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/29/18.
//  Copyright © 2018 The Munki Project. All rights reserved.
//

import Foundation

class AuthRestartClient {
    // Handles communication with authrestartd daemon
    //var socket: SocketPort
    
    func connect() {
        // Connect to authrestartd
        let socket_file = "/var/run/authrestartd"
        let name = sockaddr()
        let socket_addr = socket_file.data(using: .utf8)!
        if let temp_socket = SocketPort(
                protocolFamily: AF_UNIX, socketType: SOCK_STREAM,
                protocol: PF_UNIX, address: socket_addr) {
            //socket = temp_socket
        }
    }
}

// Higher-level wrapper functions that swallow AuthRestartClientErrors

func fvIsActive() -> Bool {
    // Returns true if FileVault can be verified to be active,
    // false otherwise
    // TO-DO: implement!
    return false
}

func verifyUser(_ username: String) -> Bool {
    // Returns true if user can be verified to be able to perform an
    // authrestart, false otherwise
    // TO-DO: implement!
    return false
}

func verifyRecoveryKeyPresent() -> Bool {
    // Returns true if we have a plist with a FileVault recovery key,
    // false otherwise
    // TO-DO: implement!
    return false
}

func verifyCanAttemptAuthRestart() -> Bool {
    // Returns true if we have what we need to attempt an auth restart
    // TO-DO: implement!
    return false
}

func storePassword(_ password: String, forUserName username: String = "") -> Bool {
    // Stores a password for later authrestart usage.
    // Returns boolean to indicate success/failure
    // TO-DO: implement!
    return false
}
