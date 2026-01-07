//
//  Predicates.m
//  munki
//
//  Created by Greg Neagle on 8/24/24.
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

#import <Foundation/Foundation.h>

/// Evaluates predicate against the info object; returns a boolean
/// Written in Objective-C because NSPredicate methods can throw NSExceptions, which
/// Swift can't catch. Error reason is returned in NSError
int objCpredicateEvaluatesAsTrue(NSString *predicateString,
                                 NSDictionary *infoObject,
                                 NSError **errorPtr)
{
    @try {
        NSPredicate *predicate = [NSPredicate predicateWithFormat:predicateString];
        BOOL result = [predicate evaluateWithObject: infoObject];
        if (result) {
            return 1;
        }
    }
    @catch(NSException *exception) {
        if (errorPtr != NULL) {
            NSDictionary *userInfo = @{ NSLocalizedDescriptionKey : [exception reason] };
            *errorPtr = [NSError errorWithDomain: @"com.googlecode.munki.ErrorDomain"
                                 code: -1
                                 userInfo: userInfo
            ];
        }
        return -1;
    }
    return 0;
}

