//
//  networkconditions.swift
//  munki
//
//  Created by Graham Gilbert on 7/20/26.
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
import Network

/// Returns true if the current default network path is a "low data" connection:
/// either cellular/personal hotspot (`path.isExpensive`) or an interface the
/// user has placed into Low Data Mode (`path.isConstrained`). Either signal is
/// enough; these are the same signals the OS uses for its own Low Data Mode
/// restrictions and require no admin configuration of SSIDs or interfaces.
///
/// NWPathMonitor is an asynchronous API, but managedsoftwareupdate samples the
/// network state at a defined point in a run, so we bridge to a synchronous
/// answer with a one-shot monitor and a semaphore. (Note this is *not* the same
/// as the natively-synchronous IOKit power-source APIs in powermanager.swift --
/// NWPathMonitor genuinely requires the async-to-sync bridge.) We bound the
/// wait and fail *open* -- reporting "not a low data connection" -- if the path
/// handler does not fire in time, so a stalled monitor can never hang a run or
/// silently block downloads that would otherwise proceed.
func isOnLowDataConnection() -> Bool {
    let monitor = NWPathMonitor()
    let queue = DispatchQueue(label: "com.googlecode.munki.networkconditions")
    let semaphore = DispatchSemaphore(value: 0)
    var isLowData = false
    monitor.pathUpdateHandler = { path in
        isLowData = path.isExpensive || path.isConstrained
        semaphore.signal()
    }
    monitor.start(queue: queue)
    // The handler normally fires almost immediately with the current path;
    // the timeout only guards against a monitor that never reports.
    let waitResult = semaphore.wait(timeout: .now() + 5.0)
    monitor.cancel()
    if waitResult == .timedOut {
        return false
    }
    return isLowData
}

private var cachedLowDataConnection: Bool? = nil

/// Cached, once-per-run answer to isOnLowDataConnection(). managedsoftwareupdate
/// runs as a one-shot process, so sampling a single time keeps every per-item
/// download decision in a run consistent and avoids starting an NWPathMonitor
/// for every item we evaluate.
func onLowDataConnection() -> Bool {
    if let cached = cachedLowDataConnection {
        return cached
    }
    let sampled = isOnLowDataConnection()
    cachedLowDataConnection = sampled
    return sampled
}
