//
//  yaml_migrate.swift
//  yaml_migrate
//
//  Created for Munki v7 YAML migration support
//  Copyright 2024-2025 Greg Neagle.
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//       https://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.

import ArgumentParser
import Foundation
import Yams

@main
struct YamlMigrate: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "yaml_migrate",
        abstract: "Migrate Munki repository files from plist to YAML format",
        discussion: """
        This tool converts manifests and pkginfo files in a Munki repository from plist format to YAML format.
        
        It will recursively scan the specified directories and convert all .plist files to .yaml files.
        The original files can be backed up or replaced based on the options provided.
        
        Examples:
          # Migrate all manifests and pkginfo files, keeping backups
          yaml_migrate /path/to/munki/repo --backup
          
          # Migrate only manifests, replacing originals
          yaml_migrate /path/to/munki/repo --manifests-only --no-backup
          
          # Dry run to see what would be converted
          yaml_migrate /path/to/munki/repo --dry-run
        """
    )
    
    @Argument(help: "Path to the Munki repository root")
    var repoPath: String
    
    @Flag(name: .long, help: "Only migrate manifest files")
    var manifestsOnly = false
    
    @Flag(name: .long, help: "Only migrate pkginfo files")
    var pkginfoOnly = false
    
    @Flag(name: .long, help: "Create backup copies of original files")
    var backup = false
    
    @Flag(name: .long, help: "Don't create backup copies of original files")
    var noBackup = false
    
    @Flag(name: .long, help: "Show what would be done without making changes")
    var dryRun = false
    
    @Flag(name: .short, help: "Verbose output")
    var verbose = false
    
    @Flag(name: .long, help: "Force overwrite existing YAML files")
    var force = false
    
    mutating func run() throws {
        // Handle backup flag logic - default to true unless explicitly disabled
        let shouldBackup = !noBackup && (backup || (!backup && !noBackup))
        
        let repoURL = URL(fileURLWithPath: repoPath)
        
        // Validate repository path
        guard FileManager.default.fileExists(atPath: repoPath) else {
            throw ValidationError("Repository path does not exist: \(repoPath)")
        }
        
        var stats = MigrationStats()
        
        // Determine which directories to process
        let directories = getDirectoriesToProcess()
        
        if verbose {
            print("Starting YAML migration...")
            print("Repository: \(repoPath)")
            print("Backup: \(shouldBackup ? "enabled" : "disabled")")
            print("Dry run: \(dryRun ? "enabled" : "disabled")")
            print("Directories to process: \(directories.joined(separator: ", "))")
        }
        
        for directory in directories {
            let dirURL = repoURL.appendingPathComponent(directory)
            if FileManager.default.fileExists(atPath: dirURL.path) {
                try processDirectory(dirURL, stats: &stats, backup: shouldBackup)
            } else if verbose {
                print("Directory not found, skipping: \(dirURL.path)")
            }
        }
        
        // Print summary
        printSummary(stats)
    }
    
    /// Recursively converts NSMutableDictionary and NSMutableArray objects to native Swift types
    private static func convertToNativeSwiftTypes(_ object: Any) -> Any {
        if let dict = object as? NSDictionary {
            var result: [String: Any] = [:]
            for (key, value) in dict {
                if let stringKey = key as? String {
                    result[stringKey] = convertToNativeSwiftTypes(value)
                }
            }
            return result
        } else if let array = object as? NSArray {
            return array.map { convertToNativeSwiftTypes($0) }
        } else if let string = object as? NSString {
            return String(string)
        } else if let number = object as? NSNumber {
            // Check if it's a boolean
            if CFGetTypeID(number) == CFBooleanGetTypeID() {
                return number.boolValue
            }
            // Check if it's an integer
            if number === number.intValue as NSNumber {
                return number.intValue
            }
            // Otherwise treat as double
            return number.doubleValue
        } else {
            return object
        }
    }
    
    private func getDirectoriesToProcess() -> [String] {
        if manifestsOnly {
            return ["manifests"]
        } else if pkginfoOnly {
            return ["pkgsinfo"]
        } else {
            return ["manifests", "pkgsinfo"]
        }
    }
    
    private func processDirectory(_ directoryURL: URL, stats: inout MigrationStats, backup: Bool) throws {
        if verbose {
            print("Processing directory: \(directoryURL.path)")
        }
        
        let fileManager = FileManager.default
        let enumerator = fileManager.enumerator(
            at: directoryURL,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        )
        
        guard let fileEnumerator = enumerator else {
            throw YamlMigrateError.directoryError("Could not enumerate directory: \(directoryURL.path)")
        }
        
        for case let fileURL as URL in fileEnumerator {
            do {
                let resourceValues = try fileURL.resourceValues(forKeys: [.isRegularFileKey])
                if resourceValues.isRegularFile == true && fileURL.pathExtension.lowercased() == "plist" {
                    try processFile(fileURL, stats: &stats, backup: backup)
                }
            } catch {
                if verbose {
                    print("Error processing \(fileURL.path): \(error)")
                }
                stats.errors += 1
            }
        }
    }
    
    private func processFile(_ fileURL: URL, stats: inout MigrationStats, backup: Bool) throws {
        let yamlURL = fileURL.deletingPathExtension().appendingPathExtension("yaml")
        
        // Check if YAML file already exists
        if FileManager.default.fileExists(atPath: yamlURL.path) && !force {
            if verbose {
                print("YAML file already exists, skipping: \(yamlURL.path)")
            }
            stats.skipped += 1
            return
        }
        
        if verbose {
            print("Converting: \(fileURL.path) -> \(yamlURL.path)")
        }
        
        if dryRun {
            stats.processed += 1
            return
        }
        
        do {
            // Read the plist file
            let data = try Data(contentsOf: fileURL)
            let plistObject = try PropertyListSerialization.propertyList(
                from: data,
                options: .mutableContainers,
                format: nil
            )
            
            // Convert NSMutableDictionary/NSMutableArray to native Swift types
            let swiftObject = YamlMigrate.convertToNativeSwiftTypes(plistObject)
            
            // Convert to YAML
            let yamlString = try Yams.dump(object: swiftObject, 
                                         indent: 2,
                                         width: -1, 
                                         allowUnicode: true)
            
            // Write YAML file
            try yamlString.write(to: yamlURL, atomically: true, encoding: String.Encoding.utf8)
            
            // Create backup if requested
            if backup {
                let backupURL = fileURL.appendingPathExtension("backup")
                if !FileManager.default.fileExists(atPath: backupURL.path) {
                    try FileManager.default.copyItem(at: fileURL, to: backupURL)
                    if verbose {
                        print("Created backup: \(backupURL.path)")
                    }
                }
            }
            
            // Remove original plist file
            try FileManager.default.removeItem(at: fileURL)
            
            stats.processed += 1
            
        } catch {
            if verbose {
                print("Error converting \(fileURL.path): \(error)")
            }
            stats.errors += 1
            throw YamlMigrateError.conversionError("Failed to convert \(fileURL.path): \(error)")
        }
    }
    
    private func printSummary(_ stats: MigrationStats) {
        print("\nMigration Summary:")
        print("Files processed: \(stats.processed)")
        print("Files skipped: \(stats.skipped)")
        print("Errors: \(stats.errors)")
        
        if dryRun {
            print("\n(This was a dry run - no files were actually modified)")
        }
    }
}

struct MigrationStats {
    var processed = 0
    var skipped = 0
    var errors = 0
}

enum YamlMigrateError: Error, LocalizedError {
    case directoryError(String)
    case conversionError(String)
    
    var errorDescription: String? {
        switch self {
        case .directoryError(let message):
            return "Directory error: \(message)"
        case .conversionError(let message):
            return "Conversion error: \(message)"
        }
    }
}
