//
//  Localization.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 27.05.18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation

func morelocalizedstrings() {
    // Some strings that are sent to us from managedsoftwareupdate. By putting
    // them here, genstrings can add them to the Localizable.strings file
    // so localizers will be able to discover them
    
    var  _ = "" // we don't actually use these values at all
    
    // Munki messages
    _ = NSLocalizedString(
        "Starting...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Finishing...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Performing preflight tasks...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Performing postflight tasks...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Checking for available updates...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Checking for additional changes...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Software installed or removed requires a restart.",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Waiting for network...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString("Done.", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Retrieving list of software for this machine...",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Verifying package integrity...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "The software was successfully installed.",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Gathering information on installed packages",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Determining which filesystem items to remove",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Removing receipt info", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Nothing to remove.", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Package removal complete.", comment: "managedsoftwareupdate message")

    // apple update messages
    _ = NSLocalizedString(
        "Checking for available Apple Software Updates...",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Checking Apple Software Update catalog...",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Downloading available Apple Software Updates...",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Installing available Apple Software Updates...",
        comment: "managedsoftwareupdate message")

    // Adobe install/uninstall messages
    _ = NSLocalizedString(
        "Running Adobe Setup", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Running Adobe Uninstall", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Starting Adobe installer...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Running Adobe Patch Installer", comment: "managedsoftwareupdate message")

    // macOS install/upgrade messages
    _ = NSLocalizedString(
        "Starting macOS upgrade...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Preparing to run macOS Installer...", comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "System will restart and begin upgrade of macOS.",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Verifying macOS installer...",
        comment: "managedsoftwareupdate message")
    _ = NSLocalizedString(
        "Launching macOS installer...",
        comment: "managedsoftwareupdate message")

}
