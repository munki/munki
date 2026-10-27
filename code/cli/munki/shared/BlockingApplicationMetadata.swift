//
//  BlockingApplicationMetadata.swift
//  munki
//
//  Copyright 2026 The Munki Project. All rights reserved.
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
//

import Foundation

func blockingApplicationsForItem(_ pkginfo: PlistDict) -> [String] {
    let blockingApplications = pkginfo["blocking_applications"] as? [String]
    let configuredApplications = pkginfo["blocking_applications_with_launch_args"] as? [String: Any]
    if blockingApplications != nil || configuredApplications != nil {
        return Array(Set((blockingApplications ?? []) + (configuredApplications?.keys.map { $0 } ?? []))).sorted()
    }
    if let installs = pkginfo["installs"] as? [PlistDict] {
        return installs.filter {
            $0["type"] as? String ?? "" == "application"
        }.map {
            ($0["path"] as? NSString)?.lastPathComponent ?? ""
        }.filter { !$0.isEmpty }
    }
    return []
}
