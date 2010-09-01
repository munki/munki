#
#  MSUupdatesViewController.py
#  Managed Software Update
#
#  Created by Greg Neagle on 7/8/10.
#  Copyright 2010 Greg Neagle.
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

class MSUupdatesViewController(NSViewController):
    '''
    Controls the updates view of the main window
    '''
    
    restartInfoFld = IBOutlet()
    restartImageFld = IBOutlet()
    descriptionView = IBOutlet()
    tableView = IBOutlet()
    optionalSoftwareBtn = IBOutlet()
    array_controller = IBOutlet()
    window_controller = IBOutlet()
    updateNowBtn = IBOutlet()
    
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
        
    @IBAction
    def optionalSoftwareBtnClicked_(self, sender):
        # switch to optional software pane
        self.window_controller.theTabView.selectNextTabViewItem_(sender)
        NSApp.delegate().optional_view_controller.AddRemoveBtn.setEnabled_(NO)
        NSApp.delegate().buildOptionalInstallsData()
        
    def updateDescriptionView(self):
        if len(self.array_controller.selectedObjects()):
            row = self.array_controller.selectedObjects()[0]
            description = row.get("description","")
            if "</html>" in description or "</HTML>" in description:
                self.descriptionView.mainFrame().loadHTMLString_baseURL_(description, None)
            else:
                self.descriptionView.mainFrame().loadData_MIMEType_textEncodingName_baseURL_(
                                                  buffer(description),
                                                  u"text/plain", u"utf-8", None)
        else:
            self.descriptionView.mainFrame().loadHTMLString_baseURL_(u"", None)
        
    def tableViewSelectionDidChange_(self, sender):
        self.performSelectorOnMainThread_withObject_waitUntilDone_(self.updateDescriptionView, None, NO)
            

