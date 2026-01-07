//
//  main.swift
//  precache_agent
//
//  Created by Greg Neagle on 4/28/25.
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

// turn off Munki status output; this should be silent
DisplayOptions.munkistatusoutput = false
// precache any optional_installs that are marked to precache
precache()
// sleep 10 seconds to prevent launchd from complaining
usleep(10_000_000)
