# encoding: utf-8
#
# MSCBadgedTemplateImage.py
# Managed Software Center
#
# Copyright 2014-2019 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# builtin super doesn't work with Cocoa classes in recent PyObjC releases.
from objc import super

#from Foundation import *
#from AppKit import *
# pylint: disable=wildcard-import
from CocoaWrapper import *
# pylint: enable=wildcard-import


class MSCBadgedTemplateImage(NSImage):
    '''Subclass to handle our updates template image with a badge showing the count
    of available updates'''
    
    @classmethod
    def imageNamed_withCount_(self, name, count):
        '''Returns a template image with a count badge composited in the upper-right
        corner of the image'''
        
        # some magic values
        NSBoldFontMask = 2
        badgeFontSize = 11
        badgeFontFamilyName = u'Helvetica'
        rrRadius = 7.0
        
        if count == 0:
            # no badge if there are no updates
            return super(MSCBadgedTemplateImage, self).imageNamed_(name)
        # build badge string and get its size
        badgeString = NSString.stringWithString_(unicode(count))
        badgeFont = NSFontManager.sharedFontManager().fontWithFamily_traits_weight_size_(
                        badgeFontFamilyName, NSBoldFontMask, 0, badgeFontSize)
        stringAttributes = { NSFontAttributeName: badgeFont }
        textSize = badgeString.sizeWithAttributes_(stringAttributes)
        
        # use textSize as the basis for the badge outline rect
        badgeOutlineHeight = textSize.height
        badgeOutlineWidth = textSize.width + rrRadius
        if textSize.height > badgeOutlineWidth:
            badgeOutlineWidth = badgeOutlineHeight
        
        # get our base image
        baseImage = super(MSCBadgedTemplateImage, self).imageNamed_(name).copy()
        
        # size our composite image large enough to include the badge
        compositeImageSize = NSMakeSize(baseImage.size().width + badgeOutlineHeight,
                                        baseImage.size().height + badgeOutlineHeight)
        # layout the rect for the text
        badgeStringRect = NSMakeRect(compositeImageSize.width - textSize.width,
                                     compositeImageSize.height - textSize.height,
                                     textSize.width, textSize.height)
        # layout the rect for the badge outline
        badgeOutlineRect = NSMakeRect(compositeImageSize.width - badgeOutlineWidth,
                                      compositeImageSize.height - badgeOutlineHeight,
                                      badgeOutlineWidth, badgeOutlineHeight)
                                      
        # shift the rects around to look better. These are magic numbers.
        badgeStringRect = NSOffsetRect(badgeStringRect, -4.75, -2)
        badgeOutlineRect = NSOffsetRect(badgeOutlineRect, -1, -5)
        
        # our erase rect needs to be a little bigger than the badge itself
        badgeEraseRect = NSInsetRect(badgeOutlineRect, -1.5, -1.5)
        
        # build paths for the badge outline and the badge erase mask
        badgeOutline = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                           badgeOutlineRect, rrRadius, rrRadius)
        badgeEraseMask = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                             badgeEraseRect, rrRadius, rrRadius)
                             
        # start drawing our composite image
        compositeImage = NSImage.alloc().initWithSize_(compositeImageSize)
        compositeImage.lockFocus()
        
        # draw base image
        baseImageOrigin = NSMakePoint(badgeOutlineHeight/2, badgeOutlineHeight/2)
        baseImage.drawAtPoint_fromRect_operation_fraction_(
            baseImageOrigin, NSZeroRect, NSCompositeCopy, 1.0)
            
        # erase the part that the badge will be drawn over
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.currentContext().setCompositingOperation_(NSCompositeCopy)
        NSColor.blackColor().colorWithAlphaComponent_(0.0).setFill()
        badgeEraseMask.fill()
        NSGraphicsContext.restoreGraphicsState()
        
        # draw badge outline
        badgeOutline.stroke()
        
        # draw count string
        badgeString.drawWithRect_options_attributes_(badgeStringRect, 0, stringAttributes)
        
        # all done drawing!
        compositeImage.unlockFocus()
        compositeImage.setTemplate_(True)
        return compositeImage
