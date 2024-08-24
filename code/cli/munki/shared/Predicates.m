//
//  Predicates.m
//  munki
//
//  Created by Greg Neagle on 8/24/24.
//

#import <Foundation/Foundation.h>

int objCpredicateEvaluatesAsTrue(NSString *predicateString,
                                 NSDictionary *infoObject)
{
    // Evaluates predicate against the info object; returns a boolean
    // Written in Objective-C because NSPredicate methods can throw NSExceptions, which
    // Swift can't catch
    @try {
        NSPredicate *predicate = [NSPredicate predicateWithFormat:predicateString];
        BOOL result = [predicate evaluateWithObject: infoObject];
        if (result) {
            return 1;
        }
    }
    @catch(NSException *exception) {
        // TODO: maybe extact info from the exception
        // and set an NSError
        return -1;
    }
    return 0;
}

