//
//  bootstrapping.swift
//  munki
//
//  Created by Greg Neagle on 9/3/24.
//  Copyright 2024-2026 The Munki Project.
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

/// Disables autologin to the unlocking user's account on a FileVault-
/// encrypted machines.
///
/// See https://support.apple.com/en-us/HT202842
func disableFDEAutoLogin() {
    // We attempt to store the original value of com.apple.loginwindow
    // DisableFDEAutoLogin so if the local admin has set it to True for #reasons
    // we don't inadvertently clear it when clearing bootstrap mode

    // is OriginalDisableFDEAutoLogin already set? If so, bootstrap mode was
    // already enabled, and never properly cleared. Don't stomp on it.
    let originalValue = CFPreferencesCopyValue(
        "OriginalDisableFDEAutoLogin" as CFString,
        "com.apple.loginwindow" as CFString,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost
    )
    if originalValue == nil {
        // store the current value of DisableFDEAutoLogin if any
        let currentValue = CFPreferencesCopyValue(
            "DisableFDEAutoLogin" as CFString,
            "com.apple.loginwindow" as CFString,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost
        )
        let valueToSet: CFPropertyList? = if currentValue == nil {
            "<not set>" as CFString
        } else {
            currentValue!
        }
        CFPreferencesSetValue(
            "OriginalDisableFDEAutoLogin" as CFString,
            valueToSet,
            "com.apple.loginwindow" as CFString,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost
        )
    }
    // set com.apple.loginwindow DisableFDEAutoLogin to True
    CFPreferencesSetValue(
        "DisableFDEAutoLogin" as CFString,
        true as CFPropertyList?,
        "com.apple.loginwindow" as CFString,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost
    )
    CFPreferencesAppSynchronize("com.apple.loginwindow" as CFString)
}

/// Resets the state of com.apple.loginwindow DisableFDEAutoLogin
/// to its value before we set it to true
func resetFDEAutoLogin() {
    // get the previous value of DisableFDEAutoLogin if any
    var originalValue = CFPreferencesCopyValue(
        "OriginalDisableFDEAutoLogin" as CFString,
        "com.apple.loginwindow" as CFString,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost
    )
    if let value = originalValue as? String,
       value == "<not set>"
    {
        originalValue = nil
    }
    // reset DisableFDEAutoLogin to original value (if originalValue is nil,
    // the key gets deleted)
    CFPreferencesSetValue(
        "DisableFDEAutoLogin" as CFString,
        originalValue,
        "com.apple.loginwindow" as CFString,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost
    )
    // delete the OriginalDisableFDEAutoLogin key
    CFPreferencesSetValue(
        "OriginalDisableFDEAutoLogin" as CFString,
        nil,
        "com.apple.loginwindow" as CFString,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost
    )
    CFPreferencesAppSynchronize("com.apple.loginwindow" as CFString)
}

/// Set up bootstrap mode
func setBootstrapMode() throws {
    // turn off auto login of FV unlocking user
    disableFDEAutoLogin()
    // create CHECKANDINSTALLATSTARTUPFLAG file
    if !FileManager.default.createFile(
        atPath: CHECKANDINSTALLATSTARTUPFLAG, contents: nil
    ) {
        resetFDEAutoLogin()
        throw MunkiError("Could not create bootstrapping flag file")
    }
}

/// Clear bootstrap mode
func clearBootstrapMode() throws {
    resetFDEAutoLogin()
    if pathExists(CHECKANDINSTALLATSTARTUPFLAG) {
        do {
            try FileManager.default.removeItem(atPath: CHECKANDINSTALLATSTARTUPFLAG)
        } catch {
            throw MunkiError("Could not remove bootstrapping flag file: \(error.localizedDescription)")
        }
    }
}
