#
#  MSUWebViewPolicyDelegate.py
#  ManagedSoftwareUpdate
#
#  Created by Greg Neagle on 2/10/10.
#  Copyright 2009-2011 Greg Neagle.
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


from Foundation import *
from WebKit import *

class MSUWebViewPolicyDelegate(NSObject):
    # needed to intercept clicks on weblinks in descriptions
    # and pass them onto the user's default web browser.
    # without this the link will load inside the webview in our app.
    def webView_decidePolicyForNavigationAction_request_frame_decisionListener_(self, webView, actionInformation, request, frame, listener):
        if actionInformation.objectForKey_(u"WebActionNavigationTypeKey").intValue() == WebNavigationTypeLinkClicked:
            listener.ignore()
            NSWorkspace.sharedWorkspace().openURL_(request.URL())
        else:
            listener.use()
        
