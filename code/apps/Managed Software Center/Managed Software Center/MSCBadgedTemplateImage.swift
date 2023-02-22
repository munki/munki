//
//  MSCBadgedTemplateImage.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/5/18.
//  Copyright © 2018-2023 The Munki Project. All rights reserved.
//

import Cocoa

class MSCBadgedTemplateImage: NSImage {
    // Subclass to handle our updates template image with a badge
    // showing the count of available updates
    
    class func image(named name: NSImage.Name, withCount count: Int) -> NSImage? {
        // Returns a template image with a count badge composited in the upper-right
        // corner of the image

        // some magic values
        let badgeFontSize = CGFloat(11.0)
        let badgeFontFamilyName = "Helvetica"
        let rrRadius = CGFloat(7.0)
        
        if count == 0  {
            // no badge if there are no updates
            return super.init(named: name)
        }
        
        // build badge string and get its size
        let badgeString = String(count)
        let badgeFont = NSFontManager.shared.font(withFamily: badgeFontFamilyName,
                                                  traits: .boldFontMask,
                                                  weight: 0,
                                                  size: badgeFontSize)
        let stringAttributes = [ NSAttributedString.Key.font: badgeFont as Any ]
        let textSize = badgeString.size(withAttributes: stringAttributes)
        
        // use textSize as the basis for the badge outline rect
        let badgeOutlineHeight = textSize.height
        let badgeOutlineWidth = max(textSize.width + rrRadius, textSize.height)

        // get our base image
        if let baseImage = (super.init(named: name)?.copy()) as? NSImage {
        
            // size our composite image large enough to include the badge
            let compositeImageSize = NSMakeSize(baseImage.size.width + badgeOutlineHeight,
                                                baseImage.size.height + badgeOutlineHeight)

            // layout the rect for the text
            var badgeStringRect = NSMakeRect(compositeImageSize.width - textSize.width,
                                             compositeImageSize.height - textSize.height,
                                             textSize.width, textSize.height)
            
            // layout the rect for the badge outline
            var badgeOutlineRect = NSMakeRect(compositeImageSize.width - badgeOutlineWidth,
                                              compositeImageSize.height - badgeOutlineHeight,
                                              badgeOutlineWidth, badgeOutlineHeight)

            // shift the rects around to look better. These are magic numbers.
            badgeStringRect = NSOffsetRect(badgeStringRect, -4.75, -2)
            badgeOutlineRect = NSOffsetRect(badgeOutlineRect, -1, -5)
            
            // our erase rect needs to be a little bigger than the badge itself
            let badgeEraseRect = NSInsetRect(badgeOutlineRect, -1.5, -1.5)

            // build paths for the badge outline and the badge erase mask
            let badgeOutline = NSBezierPath(roundedRect: badgeOutlineRect, xRadius:rrRadius, yRadius: rrRadius)
            let badgeEraseMask = NSBezierPath(roundedRect: badgeEraseRect, xRadius:rrRadius, yRadius: rrRadius)

            // start drawing our composite image
            let compositeImage = NSImage(size: compositeImageSize)
            compositeImage.lockFocus()
            
            // draw base image
            let baseImageOrigin = NSMakePoint(badgeOutlineHeight/2, badgeOutlineHeight/2)
            baseImage.draw(at: baseImageOrigin, from: NSZeroRect, operation: .copy, fraction: 1.0)
            
            // erase the part that the badge will be drawn over
            NSGraphicsContext.saveGraphicsState()
            if let context = NSGraphicsContext.current {
                context.compositingOperation = .copy
            }
            NSColor.black.withAlphaComponent(0.0).setFill()
            badgeEraseMask.fill()
            NSGraphicsContext.restoreGraphicsState()
            
            // draw badge outline
            badgeOutline.stroke()
            
            // draw count string
            badgeString.draw(with: badgeStringRect, options: NSString.DrawingOptions(rawValue: 0), attributes:stringAttributes)
            
            // all done drawing
            compositeImage.unlockFocus()
            compositeImage.isTemplate = true
            return compositeImage
        }
        return nil
    }
}
