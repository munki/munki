//
//  LogViewController.swift
//  MunkiStatus
//
//  Created by Greg Neagle on 5/20/18.
//  Copyright © 2018-2019 The Munki Project. All rights reserved.
//

import Cocoa

class LogViewDataSource: NSObject, NSTableViewDataSource {
    // Data source for an NSTableView that displays an array of text lines.
    // Line breaks are assumed to be LF, and partial lines from incremental
    // reading are handled.
    
    var logFileData: NSMutableArray = []
    var filteredData: NSArray = []
    
    var lastLineIsPartial = false
    var filterText = ""
    
    func tableView(_ tableView: NSTableView, writeRowsWith rowIndexes: IndexSet, to pboard: NSPasteboard) -> Bool {
        // Implements drag-n-drop of text rows to external apps
        var textToCopy = ""
        for i in rowIndexes {
            let line = filteredData.object(at: i)
            textToCopy.append("\(line)\n")
        }
        pboard.writeObjects([textToCopy as NSString])
        return true
    }
    
    func applyFilterToData() {
        // Filter our log data
        if !(filterText.isEmpty) {
            let filterPredicate = NSPredicate(format: "self CONTAINS[cd] %@", argumentArray: [filterText])
            filteredData = logFileData.filtered(using: filterPredicate) as NSArray
        } else {
            filteredData = logFileData as NSArray
        }
    }
    
    func addLine(_ line: String) {
        if lastLineIsPartial {
            let joinedLine = logFileData.lastObject as! String + line
            logFileData.removeLastObject()
            logFileData.add(joinedLine)
            lastLineIsPartial = false
        } else {
            logFileData.add(line)
        }
        applyFilterToData()
    }
    
    func removeAllLines() {
        // Remove all data from our datasource'''
        logFileData.removeAllObjects()
    }
    
    func numberOfRows(in tableView: NSTableView) -> Int {
        // Required datasource method
        return filteredData.count
    }
    
    func tableView(_ tableView: NSTableView, objectValueFor column: NSTableColumn?, row: Int) -> Any? {
        // Required datasource method -- returns the text data for the
        // given row and column
        if column!.identifier == NSUserInterfaceItemIdentifier("data") {
            return filteredData.object(at: row)
        } else {
            return ""
        }
    }
}

class LogViewController: NSViewController {

    @IBOutlet weak var searchField: NSSearchField!
    @IBOutlet weak var pathControl: NSPathControl!
    @IBOutlet weak var logView: NSTableView!
    
    var updateTimer: Timer? = nil
    var fileHandle: FileHandle? = nil
    var logFileData = LogViewDataSource()

    override func viewDidLoad() {
        if #available(OSX 10.10, *) {
            super.viewDidLoad()
        } else {
            // Fallback on earlier versions
        }
        // Do view setup here.
    }
    
    @objc func copy(_ sender: AnyObject?) {
        var textToCopy = ""
        let indexes = logView.selectedRowIndexes
        for i in indexes {
            let line = logFileData.filteredData.object(at: i)
            textToCopy.append("\(line)\n")
        }
        let pboard = NSPasteboard.general
        pboard.clearContents()
        pboard.writeObjects([textToCopy as NSString])
    }
    
    @IBAction func showLogWindow(_ sender: Any) {
        let logWindow = view.window!
        if logWindow.isVisible {
            logWindow.makeKeyAndOrderFront(self)
            return
        }
        if atLoginWindow() {
            logWindow.canBecomeVisibleWithoutLogin = true
            logWindow.level = statusWindowLevel
        }
        var windowRect = NSScreen.main!.frame
        windowRect.origin.x = 100.0
        windowRect.origin.y = 200.0
        windowRect.size.width -= 200.0
        windowRect.size.height -= 300.0
        let logFileURL = NSURL.fileURL(withPath: logFilePref())
        pathControl.url = logFileURL
        logWindow.title = logFileURL.lastPathComponent
        logWindow.setFrame(windowRect, display: false)
        logWindow.makeKeyAndOrderFront(self)
        watchLogFile(logFileURL)
        logView.setDraggingSourceOperationMask(.all, forLocal: false)
    }
    
    func watchLogFile(_ logFileURL: URL) {
        // Display and continuously update a log file in the main window.
        stopWatching()
        logFileData.removeAllLines()
        logView.dataSource = logFileData
        logView.reloadData()
        do {
            try fileHandle = FileHandle(forReadingFrom: logFileURL)
            refreshLog()
            // Kick off a timer that updates the log view periodically.
            updateTimer = Timer.scheduledTimer(timeInterval: 0.25,
                                               target: self,
                                               selector: #selector(LogViewController.refreshLog),
                                               userInfo: nil,
                                               repeats: true)
        } catch {
            print("Unexpected error: \(error)")
        }
    }
    
    func stopWatching() {
        // Release the file handle and stop the update timer.
        if fileHandle != nil {
            fileHandle!.closeFile()
            fileHandle = nil
        }
        if updateTimer != nil {
            updateTimer!.invalidate()
            updateTimer = nil
        }
    }
    
    @objc func refreshLog() {
        // Check for new available data, read it, and scroll to the bottom.
        if fileHandle != nil {
            let data = fileHandle!.availableData
            if !(data.isEmpty) {
                var lastLineIsPartial = false
                let uString = NSString(data: data, encoding: String.Encoding.utf8.rawValue)
                var lines = uString!.components(separatedBy: "\n")
                if lines.last!.isEmpty {
                    // means text data ended with a newline character and therefore we have a complete line
                    // at the end. Don't add the empty line to the data array.
                    lines.removeLast()
                } else {
                    // text data did not end with a newline character; our last line is partial.
                    lastLineIsPartial = true
                }
                for line in lines {
                    logFileData.addLine(line)
                }
                // if the data ends with a \n the last line is not partial
                logFileData.lastLineIsPartial = lastLineIsPartial
                logView.reloadData()
                let lineCount = logFileData.filteredData.count
                if lineCount > 0 {
                    logView.scrollRowToVisible(lineCount - 1)
                }
            }
        }
    }
    
    @IBAction func searchFilterChanged(_ sender: Any) {
        // User changed the search field
        let filterString = searchField.stringValue.lowercased()
        logFileData.filterText = filterString
        logFileData.applyFilterToData()
        logView.reloadData()
    }
}
