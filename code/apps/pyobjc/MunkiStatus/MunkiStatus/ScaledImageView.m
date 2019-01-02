//
//  ScaledImageView.m
//
//  Created by Greg Neagle on 5/27/09.
//
// Copyright 2009-2019 Greg Neagle.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
// 
//      https://www.apache.org/licenses/LICENSE-2.0
// 
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//


#import "ScaledImageView.h"


@implementation ScaledImageView

-(void)drawRect:(NSRect)rect {
	
	NSRect dstRect = [self bounds];
	
	float sourceWidth = [[self image] size].width;
    float sourceHeight = [[self image] size].height;
	float targetWidth = dstRect.size.width;
    float targetHeight = dstRect.size.height;
	
	// Calculate aspect ratios
    float sourceRatio = sourceWidth / sourceHeight;
    float targetRatio = targetWidth / targetHeight;

	// Determine what side of the source image to use for proportional scaling
    BOOL scaleWidth = (sourceRatio <= targetRatio);
	
	// Proportionally scale source image
    float scalingFactor, scaledWidth, scaledHeight;
    if (scaleWidth) {
        scalingFactor = 1.0 / sourceRatio;
        scaledWidth = targetWidth;
        scaledHeight = round(targetWidth * scalingFactor);
    } else {
        scalingFactor = sourceRatio;
        scaledWidth = round(targetHeight * scalingFactor);
        scaledHeight = targetHeight;
    }
    float scaleFactor = scaledHeight / sourceHeight;
    
    // Calculate compositing rectangles
    NSRect sourceRect;
	float destX, destY;
	
	// Crop from center
	destX = round((scaledWidth - targetWidth) / 2.0);
	destY = round((scaledHeight - targetHeight) / 2.0);
	
	sourceRect = NSMakeRect(destX / scaleFactor, destY / scaleFactor, 
							targetWidth / scaleFactor, targetHeight / scaleFactor);
	

	[[self image] drawInRect:dstRect
					fromRect:sourceRect 
				    operation:NSCompositeSourceOver 
					fraction:1.0];
	
}


@end
