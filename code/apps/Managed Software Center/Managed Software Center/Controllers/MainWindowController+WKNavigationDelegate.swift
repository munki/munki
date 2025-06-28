//
//  MainWindowController+WKNavigationDelegate.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/28/25.
//  Copyright © 2025 The Munki Project. All rights reserved.
//

import Cocoa
import WebKit

extension MainWindowController: WKNavigationDelegate {
    
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url {
            msc_debug_log("Got load request for \(url)")
            if navigationAction.targetFrame == nil {
                // new window target
                // open link in default browser instead of in our app's WebView
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
                return
            }
        }
        if let url = navigationAction.request.url, let scheme = url.scheme {
            msc_debug_log("Got URL scheme: \(scheme)")
            if scheme == "munki" {
                handleMunkiURL(url)
                decisionHandler(.cancel)
                return
            }
            if scheme == "mailto" || scheme == "http" || scheme == "https" {
                // open link in default mail client since WKWebView doesn't
                // forward these links natively
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
                return
            }
            if url.scheme == "file" {
                // if this is a MSC page, generate it!
                if url.deletingLastPathComponent().path == htmlDir {
                    let filename = url.lastPathComponent
                    do {
                        try buildPage(filename)
                    } catch {
                        msc_debug_log(
                            "Could not build page for \(filename): \(error)")
                    }
                }
            }
        }
        decisionHandler(.allow)
    }
    
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if !(navigationResponse.canShowMIMEType) {
            if let url = navigationResponse.response.url {
                // open link in default browser instead of in our app's WebView
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
                return
            }
        }
        decisionHandler(.allow)
    }
    
    func webView(_ webView: WKWebView,
                 didStartProvisionalNavigation navigation: WKNavigation!) {
        // Animate progress spinner while we load a page and highlight the
        // proper toolbar button
        pageLoadProgress?.startAnimation(self)
        if let main_url = webView.url {
            let pagename = main_url.lastPathComponent
            msc_debug_log("Requested pagename is \(pagename)")
            if (pagename == "category-all.html" ||
                pagename.hasPrefix("detail-") ||
                pagename.hasPrefix("filter-") ||
                pagename.hasPrefix("developer-")) {
                highlightSidebarItem("Software")
            } else if pagename == "categories.html" || pagename.hasPrefix("category-") {
                highlightSidebarItem("Categories")
            } else if pagename == "myitems.html" {
                highlightSidebarItem("My Items")
            } else if pagename == "updates.html" || pagename.hasPrefix("updatedetail-") {
                highlightSidebarItem("Updates")
            } else {
                // no idea what type of item it is
                highlightSidebarItem("")
            }
        }
    }
    
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // react to end of displaying a new page
        pageLoadProgress?.stopAnimation(self)
        clearCache()
        let allowNavigateBack = webView.canGoBack
        let page_url = webView.url
        let filename = page_url?.lastPathComponent ?? ""
        let onMainPage = (
            ["category-all.html", "categories.html", "myitems.html", "updates.html"].contains(filename))
        navigateBackMenuItem.isEnabled = (allowNavigateBack && !onMainPage)
        if !navigateBackMenuItem.isEnabled {
            hideNavigationToolbarItem()
        } else {
            showNavigationToolbarItem()
        }
    }
    
    func webView(_ webView: WKWebView,
                 didFail navigation: WKNavigation!,
                 withError error: Error) {
        // Stop progress spinner and log error
        pageLoadProgress?.stopAnimation(self)
        msc_debug_log("Committed load error: \(error)")
    }
    
    func webView(_ webView: WKWebView,
                 didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        // Stop progress spinner and log
        pageLoadProgress?.stopAnimation(self)
        msc_debug_log("Provisional load error: \(error)")
        do {
            let files = try FileManager.default.contentsOfDirectory(atPath: htmlDir)
            msc_debug_log("Files in html_dir: \(files)")
        } catch {
            // ignore
        }
    }
}
