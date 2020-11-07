//
//  MSCWebViewController.swift
//  Managed Software Center
//
//  Created by Jim Zajkowski on 11/7/20.
//  Copyright © 2020 The Munki Project. All rights reserved.
//

import Cocoa
import WebKit

class MSCWebViewController: NSViewController {
    
    var webView: WKWebView!
    
    @IBOutlet weak var mainWindowController: MainWindowController!
        
    override func viewDidLoad() {
        super.viewDidLoad()
        
        // our view's size
        let width = view.frame.size.width
        let height = view.frame.size.height
        
        webView = MSCWebView(frame: NSMakeRect(0, 0, width, height), configuration: webViewConfiguration())

        webView.allowsBackForwardNavigationGestures = false
        webView.setValue(false, forKey: "drawsBackground")
        webView.navigationDelegate = mainWindowController

        webView.autoresizingMask = [.width, .height]
        self.view.addSubview(webView)

        mainWindowController.webView = webView
    }
    
    func webViewConfiguration() -> WKWebViewConfiguration {
        let webConfiguration = WKWebViewConfiguration()

        webConfiguration.userContentController = contentController()

        webConfiguration.preferences.javaScriptEnabled = true
        webConfiguration.preferences.javaEnabled = false
        if UserDefaults.standard.bool(forKey: "developerExtrasEnabled") {
            webConfiguration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        }
        
        return webConfiguration
    }
    
    func contentController() -> WKUserContentController {
        let wkContentController = WKUserContentController()

        wkContentController.add(mainWindowController, name: "openExternalLink")
        wkContentController.add(mainWindowController, name: "installButtonClicked")
        wkContentController.add(mainWindowController, name: "myItemsButtonClicked")
        wkContentController.add(mainWindowController, name: "actionButtonClicked")
        wkContentController.add(mainWindowController, name: "changeSelectedCategory")
        wkContentController.add(mainWindowController, name: "updateOptionalInstallButtonClicked")
        wkContentController.add(mainWindowController, name: "updateOptionalInstallButtonFinishAction")

        return wkContentController
    }
}
