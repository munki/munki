//
//  MainWindowController+WKNavigationDelegate.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/28/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
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
            if scheme == "mailto" {
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
    
    /// Returns index of a sidebar item that has the given page. -1 if none
    func sidebarHasItemWithURL(_ url: URL) -> Int {
        for (index, item) in sidebar_items.enumerated() {
            if item.page == url.absoluteString {
                return index
            }
            let munkiURL = munkiURL(from: url.absoluteString)
            if item.page == munkiURL {
                return index
            }
        }
        return -1
    }
    
    func webView(_ webView: WKWebView,
                 didStartProvisionalNavigation navigation: WKNavigation!) {
        // Animate progress spinner while we load a page and highlight the
        // proper toolbar button
        pageLoadProgress?.startAnimation(self)
        guard let main_url = webView.url else { return }
        let pagename = main_url.lastPathComponent
        if main_url.scheme == "file" {
            msc_debug_log("Requested pagename is \(pagename)")
        } else {
            msc_debug_log("Requested URL is \(main_url)")
        }
        // first try to find a matching sidebar item to highlight
        let itemIndex = sidebarHasItemWithURL(main_url)
        if itemIndex != -1 {
            highlightSidebarItemByIndex(itemIndex)
            return
        }
        // otherwise, attempt to figure out something relevant
        if (pagename == "category-all.html" ||
            pagename.hasPrefix("detail-") ||
            pagename.hasPrefix("filter-") ||
            pagename.hasPrefix("developer-")) {
            highlightSidebarItemByPage(MunkiURL.software.rawValue)
        } else if pagename == "categories.html" || pagename.hasPrefix("category-") {
            highlightSidebarItemByPage(MunkiURL.categories.rawValue)
        } else if pagename == "myitems.html" {
            highlightSidebarItemByPage(MunkiURL.myItems.rawValue)
        } else if pagename == "updates.html" || pagename.hasPrefix("updatedetail-") {
            highlightSidebarItemByPage(MunkiURL.updates.rawValue)
        } else {
            // no idea what type of item it is, highlight nothing
            highlightSidebarItemByPage("")
        }
    }
    
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // react to end of displaying a new page
        pageLoadProgress?.stopAnimation(self)
        clearCache()
        let allowNavigateBack = webView.canGoBack
        let page_url = webView.url
        let onSidebarPage = page_url != nil ? sidebarHasItemWithURL(page_url!) != -1 : false
        navigateBackMenuItem.isEnabled = (allowNavigateBack && !onSidebarPage)
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
