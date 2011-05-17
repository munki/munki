#
#  MSUOptionalInstallsViewController.py
#  Managed Software Update
#
#  Created by Greg Neagle on 7/8/10.
#  Copyright 2010-2011 Greg Neagle.
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

class MSUOptionalInstallsViewController(NSViewController):
    '''
    Controls the optional software view of the main window
    '''

    descriptionView = IBOutlet()
    tableView = IBOutlet()
    theWindow = IBOutlet()
    array_controller = IBOutlet()
    window_controller = IBOutlet()
    AddRemoveBtn = IBOutlet()
    searchField = IBOutlet()
    
    _EMPTYOPTIONALLIST = NSArray.arrayWithArray_([{"installed": NO, 
                                                   "managed": NO, 
                                                   "original_managed": NO,
                                                   "name": "", 
                                                   "version": "", 
                                                   "description": "", 
                                                   "size": "", 
                                                   "enabled": NO, 
                                                   "status": "", 
                                                   "original_status": ""}])

    _optionallist = []
    _filteredlist = []
        
    def setOptionallist_(self, newlist):
        self._optionallist = NSArray.arrayWithArray_(newlist)
        self.setFilteredlist_(newlist)
    
    def filteredlist(self):
        #NSLog(u"MSUOptionalInstallsViewController.optionallist")
        return self._filteredlist or self._EMPTYOPTIONALLIST
    objc.accessor(filteredlist) # PyObjC KVO hack
    
    def setFilteredlist_(self, newlist):
        #NSLog(u"MSUOptionalInstallsViewController.setOptionallist_")
        self._filteredlist = NSArray.arrayWithArray_(newlist)
    objc.accessor(setFilteredlist_) # PyObjC KVO hack

    @IBAction
    def searchFilterChanged_(self, sender):
        filterString = self.searchField.stringValue().lower()
        self.setFilteredlist_([item for item in self._optionallist
            if filterString in item['name'].lower() or
               filterString in item['description'].lower()])
        self.updateDescriptionView()
    
    @IBAction
    def itemCheckBoxClicked_(self, sender):
        self.updateRowStatus()
        #self.updateAddRemoveBtnState()
        
    def updateRowStatus(self):
        #NSLog(u"MSUOptionalInstallsViewController.updateRowStatus")
        if len(self.array_controller.selectedObjects()):
            row = self.array_controller.selectedObjects()[0]
            if row['managed'] == row['original_managed']:
                # restore original status
                row['status'] = row['original_status']
                self.updateAddRemoveBtnState()
            else:
                # we've inverted the management state
                self.AddRemoveBtn.setEnabled_(YES)
                if row['managed']:
                    # user checked this one
                    if row['original_status'] == NSLocalizedString(u"Not installed", None):
                        row['status'] = NSLocalizedString(u"Will be installed", None)
                    elif row['original_status'] == NSLocalizedString(u"Update available", None):
                        row['status'] = NSLocalizedString(u"Will be updated", None)
                    elif row['original_status'] == NSLocalizedString(u"Will be removed", None):
                        row['status'] = NSLocalizedString(u"Will not be removed", None)
                else:
                    # not row['managed']
                    if row['original_status'] == NSLocalizedString(u"Installed", None):
                        row['status'] = NSLocalizedString(u"Will be removed", None)
                    elif row['original_status'] == NSLocalizedString(u"Will be installed", None):
                        row['status'] = NSLocalizedString(u"Will not be installed", None)

                        
    def updateAddRemoveBtnState(self):
        userChanges = NO
        for row in self.array_controller.arrangedObjects():
            if row['managed'] != row['original_managed']:
                userChanges = YES
                break                      
        self.AddRemoveBtn.setEnabled_(userChanges)
    
    @IBAction
    def cancelBtnClicked_(self, sender):
        self.window_controller.theTabView.selectPreviousTabViewItem_(sender)
        if NSApp.delegate()._listofupdates == []:
            NSApp.delegate().noUpdatesAlert()
        
    @IBAction
    def AddRemoveBtnClicked_(self, sender):
        # process Adds and/or Removes
        self.window_controller.theTabView.selectPreviousTabViewItem_(sender)
        NSApp.delegate().addOrRemoveOptionalSoftware()
        
    def updateWebKitView_(self, description):
        if "</html>" in description or "</HTML>" in description:
            self.descriptionView.mainFrame().loadHTMLString_baseURL_(description, None)
        else:
            self.descriptionView.mainFrame().loadData_MIMEType_textEncodingName_baseURL_(
                                                  buffer(description),
                                                  u"text/plain", u"utf-8", None)
    def updateDescriptionView(self):
        #NSLog(u"MSUOptionalInstallsViewController.updateDescriptionView")
        if len(self.array_controller.selectedObjects()):
            row = self.array_controller.selectedObjects()[0]
            description = row.get("description", u"")
            self.updateRowStatus()
        else:
            description = u""
        self.performSelectorOnMainThread_withObject_waitUntilDone_(self.updateWebKitView_, description, NO)
            
    def tableViewSelectionDidChange_(self, sender):
        #NSLog(u"MSUOptionalInstallsViewController.tableViewSelectionDidChange_")
        #self.performSelectorOnMainThread_withObject_waitUntilDone_(self.updateDescriptionView, None, NO)
        self.updateDescriptionView()
