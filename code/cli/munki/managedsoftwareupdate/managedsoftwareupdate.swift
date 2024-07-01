//
//  managedsoftwareupdate.swift
//  munki
//
//  Created by Greg Neagle on 6/24/24.
//

import ArgumentParser
import Foundation

@main
struct ManagedSoftwareUpdate: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "managedsoftwareupdate",
        usage: "maangedsoftwareupdate [options]"
    )

    @Flag(name: [.long, .customShort("V")],
          help: "Print the version of the munki tools and exit.")
    var version = false

    @Flag(name: .long,
          help: "Print the current configuration and exit.")
    var showConfig = false

    mutating func run() throws {
        if version {
            print(getVersion())
            return
        }
        if showConfig {
            printConfig()
            return
        }
        print("Nothing much implemented yet!")
    }
}
