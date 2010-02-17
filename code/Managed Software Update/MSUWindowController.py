#
#  MSUWindowController.py
#  Managed Software Update
#
#  Created by Greg Neagle on 2/11/10.
#  Copyright 2009-2010 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#      http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from objc import YES, NO, IBAction, IBOutlet
from Foundation import *
from AppKit import *

class MSUWindowController(NSWindowController):

    restartInfoFld = IBOutlet()
    restartImageFld = IBOutlet()
    descriptionView = IBOutlet()
    tableView = IBOutlet()
    theWindow = IBOutlet()
    
    _updatelist = NSArray.arrayWithArray_([{"image": NSImage.imageNamed_("Empty.png"), "name": "", "version": "", "description": ""}])
    
    def updatelist(self):
        return self._updatelist
    objc.accessor(updatelist) # PyObjC KVO hack
    
    def setUpdatelist_(self, newlist):
        self._updatelist = NSArray.arrayWithArray_(newlist)
    objc.accessor(setUpdatelist_) # PyObjC KVO hack
    
    @IBAction
    def laterBtnClicked_(self, sender):
        NSApp.terminate_(self)
        
    @IBAction
    def updateNowBtnClicked_(self, sender):
        # alert the user to logout, proceed without logout, or cancel
        NSApp.delegate().confirmInstallUpdates()
        
    def windowShouldClose_(self, sender):
        # just quit
        NSApp.terminate_(self)
