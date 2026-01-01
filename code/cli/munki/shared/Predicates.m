//
//  Predicates.m
//  munki
//
//  Created by Greg Neagle on 8/24/24.
//  Copyright 2024-2026 The Munki Project.
//

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

