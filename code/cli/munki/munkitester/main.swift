//
//  main.swift
//  munkitester
//
//  Created by Greg Neagle on 6/25/24.
//

// this is a temporary target to use to test things

import Foundation

DisplayOptions.shared.verbose = 3
let options = GurlOptions(
    url: "https://github.com/macadmins/munki-builds/releases/download/v6.5.1.4661/munkitools-6.5.1.4661.pkg",
    destinationPath: "/tmp/munkitools-6.5.1.4661.pkg",
    followRedirects: "all",
    canResume: true,
    downloadOnlyIfChanged: true
)

let connection = Gurl(options: options)
connection.start()
while true {
    let done = connection.isDone()
    if String(connection.status).hasPrefix("2"),
       connection.percentComplete != -1 {
        displayPercentDone(current: connection.percentComplete, maximum: 100)
    } else if connection.bytesReceived > 0 {
        displayDetail("Bytes received: \(connection.bytesReceived)")
    }
    if done {
        break
    }
}

if let error = connection.error {
    print(error)
}
