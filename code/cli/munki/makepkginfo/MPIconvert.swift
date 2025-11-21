//
//  MPIconvert.swift
//  makepkginfo
//
//  Created by Rod Christiansen on 10/5/25.
//
//  Copyright 2025 The Munki Project
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

extension MakePkgInfo {
    struct Convert: ParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Convert pkginfo files between YAML and plist formats.",
            discussion: """
            Converts pkginfo files from plist to YAML or from YAML to plist.
            
            If converting a single file, specify both input and output paths.
            If converting a directory, specify the directory path and use --to-yaml or --to-plist.
            
            Examples:
              # Convert single pkginfo from plist to YAML
              makepkginfo convert Firefox-123.0.plist Firefox-123.0.yaml
              
              # Convert single pkginfo from YAML to plist
              makepkginfo convert Firefox-123.0.yaml Firefox-123.0.plist
              
              # Convert all pkgsinfo files in a directory to YAML
              makepkginfo convert /path/to/pkgsinfo --to-yaml --backup
              
              # Convert all pkgsinfo files in a directory to plist
              makepkginfo convert /path/to/pkgsinfo --to-plist --backup
              
              # Dry run to see what would be converted
              makepkginfo convert /path/to/pkgsinfo --to-yaml --dry-run
            """
        )
        
        @Argument(help: "Source file or directory path")
        var source: String?
        
        @Argument(help: "Destination file path (required when converting single file)")
        var destination: String?
        
        @Flag(name: .long, help: "Convert all pkgsinfo files to YAML format")
        var toYaml = false
        
        @Flag(name: .long, help: "Convert all pkgsinfo files to plist format")
        var toPlist = false
        
        @Flag(name: .long, help: "Create backup copies of original files")
        var backup = false
        
        @Flag(name: .long, help: "Show what would be done without making changes")
        var dryRun = false
        
        @Flag(name: [.short, .long], help: "Verbose output")
        var verbose = false
        
        @Flag(name: .long, help: "Force overwrite existing files")
        var force = false
        
        mutating func validate() throws {
            // Single file conversion requires both source and destination
            if source != nil && !toYaml && !toPlist {
                if destination == nil {
                    throw ValidationError("Destination file required when converting a single file")
                }
            }
            
            // Batch conversion requires --to-yaml or --to-plist
            if toYaml && toPlist {
                throw ValidationError("Please specify only one of --to-yaml or --to-plist")
            }
            
            if (toYaml || toPlist) && destination != nil {
                throw ValidationError("Cannot specify destination file with --to-yaml or --to-plist")
            }
        }
        
        mutating func run() throws {
            if let src = source, let dest = destination {
                // Single file conversion
                try convertSingleFile(from: src, to: dest)
            } else if let src = source, (toYaml || toPlist) {
                // Batch directory conversion
                try convertDirectory(src, toYaml: toYaml)
            } else {
                throw ValidationError("Please specify either source/destination files or use --to-yaml/--to-plist for batch conversion")
            }
        }
        
        private func convertSingleFile(from source: String, to destination: String) throws {
            let sourceURL = URL(fileURLWithPath: source)
            let destURL = URL(fileURLWithPath: destination)
            
            guard FileManager.default.fileExists(atPath: source) else {
                throw ValidationError("Source file does not exist: \(source)")
            }
            
            if FileManager.default.fileExists(atPath: destination) && !force && !dryRun {
                throw ValidationError("Destination file already exists: \(destination). Use --force to overwrite.")
            }
            
            if verbose {
                print("Converting: \(source) -> \(destination)")
            }
            
            if dryRun {
                print("Would convert: \(source) -> \(destination)")
                return
            }
            
            do {
                // Read the source file data
                let sourceData = try Data(contentsOf: sourceURL)
                
                // Determine if source is YAML or plist
                let isSourceYaml = isYamlFile(source)
                
                // Parse the source file
                let pkginfo = try readData(sourceData, preferYaml: isSourceYaml, filepath: source)
                
                guard let pkginfoDict = pkginfo as? PlistDict else {
                    throw ValidationError("Could not parse pkginfo from \(source)")
                }
                
                // Determine output format based on destination extension
                let isDestYaml = isYamlFile(destination)
                
                // Convert to destination format
                let destData: Data
                if isDestYaml {
                    destData = try yamlToData(pkginfoDict)
                } else {
                    destData = try plistToData(pkginfoDict)
                }
                
                // Write to destination
                try destData.write(to: destURL)
                
                if verbose {
                    print("Successfully converted: \(destination)")
                }
            } catch {
                printStderr("Error converting \(source): \(error)")
                throw ExitCode.failure
            }
        }
        
        private func convertDirectory(_ directoryPath: String, toYaml: Bool) throws {
            let directoryURL = URL(fileURLWithPath: directoryPath)
            
            guard FileManager.default.fileExists(atPath: directoryPath) else {
                throw ValidationError("Directory does not exist: \(directoryPath)")
            }
            
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: directoryPath, isDirectory: &isDirectory),
                  isDirectory.boolValue else {
                throw ValidationError("Path is not a directory: \(directoryPath)")
            }
            
            let targetFormat = toYaml ? "YAML" : "plist"
            
            if verbose {
                print("Converting all pkginfo files in \(directoryPath) to \(targetFormat) format...")
                print("Backup: \(backup ? "enabled" : "disabled")")
                print("Dry run: \(dryRun ? "enabled" : "disabled")")
            }
            
            var stats = ConversionStats()
            
            // Get all files in directory (non-recursive for now)
            let fileManager = FileManager.default
            guard let enumerator = fileManager.enumerator(at: directoryURL,
                                                          includingPropertiesForKeys: [.isRegularFileKey],
                                                          options: [.skipsHiddenFiles]) else {
                throw ValidationError("Could not enumerate directory: \(directoryPath)")
            }
            
            for case let fileURL as URL in enumerator {
                let relativePath = fileURL.path.replacingOccurrences(of: directoryURL.path + "/", with: "")
                
                // Check if it's a regular file
                let resourceValues = try fileURL.resourceValues(forKeys: [.isRegularFileKey])
                guard resourceValues.isRegularFile == true else {
                    continue
                }
                
                // Check if it's a pkginfo file (plist or yaml)
                let filename = fileURL.lastPathComponent
                let isPlist = filename.hasSuffix(".plist")
                let isYaml = filename.hasSuffix(".yaml") || filename.hasSuffix(".yml")
                
                // Skip if not a pkginfo file
                guard isPlist || isYaml else {
                    continue
                }
                
                try convertDirectoryFile(
                    fileURL: fileURL,
                    relativePath: relativePath,
                    toYaml: toYaml,
                    stats: &stats
                )
            }
            
            // Print summary
            print("\nConversion Summary:")
            print("Files converted: \(stats.converted)")
            print("Files skipped: \(stats.skipped)")
            print("Errors: \(stats.errors)")
            
            if dryRun {
                print("\n(This was a dry run - no files were actually modified)")
            }
        }
        
        private func convertDirectoryFile(
            fileURL: URL,
            relativePath: String,
            toYaml: Bool,
            stats: inout ConversionStats
        ) throws {
            let filename = fileURL.lastPathComponent
            let hasYamlExt = filename.hasSuffix(".yaml") || filename.hasSuffix(".yml")
            
            // Skip if already in target format
            if toYaml && hasYamlExt {
                if verbose {
                    print("Skipping (already YAML): \(relativePath)")
                }
                stats.skipped += 1
                return
            }
            if !toYaml && !hasYamlExt {
                if verbose {
                    print("Skipping (already plist): \(relativePath)")
                }
                stats.skipped += 1
                return
            }
            
            if verbose {
                let targetFormat = toYaml ? "YAML" : "plist"
                print("Converting \(relativePath) to \(targetFormat)...")
            }
            
            if dryRun {
                stats.converted += 1
                return
            }
            
            do {
                // Read the pkginfo file
                let sourceData = try Data(contentsOf: fileURL)
                let pkginfo = try readData(sourceData, preferYaml: hasYamlExt, filepath: fileURL.path)
                
                guard let pkginfoDict = pkginfo as? PlistDict else {
                    if verbose {
                        print("Error: Could not parse pkginfo: \(relativePath)")
                    }
                    stats.errors += 1
                    return
                }
                
                // Create backup if requested
                if backup {
                    let backupURL = fileURL.appendingPathExtension("backup")
                    if !FileManager.default.fileExists(atPath: backupURL.path) {
                        try FileManager.default.copyItem(at: fileURL, to: backupURL)
                        if verbose {
                            print("Created backup: \(backupURL.lastPathComponent)")
                        }
                    }
                }
                
                // Determine new filename (strip .yaml/.yml extension or add .yaml)
                let baseName: String
                if hasYamlExt {
                    baseName = (filename as NSString).deletingPathExtension
                } else {
                    // Remove .plist extension if present
                    baseName = filename.hasSuffix(".plist") ? (filename as NSString).deletingPathExtension : filename
                }
                let fileExtension = toYaml ? ".yaml" : ".plist"
                let newFilename = "\(baseName)\(fileExtension)"
                let newURL = fileURL.deletingLastPathComponent().appendingPathComponent(newFilename)
                
                // Convert to destination format
                let destData: Data
                if toYaml {
                    destData = try yamlToData(pkginfoDict)
                } else {
                    destData = try plistToData(pkginfoDict)
                }
                
                // Write new file
                try destData.write(to: newURL)
                
                // Delete old file if name changed
                if filename != newFilename {
                    do {
                        try FileManager.default.removeItem(at: fileURL)
                        if verbose {
                            print("Deleted original: \(filename)")
                        }
                    } catch {
                        if verbose {
                            print("Warning: Could not delete original \(filename): \(error)")
                        }
                    }
                }
                
                stats.converted += 1
            } catch {
                if verbose {
                    print("Error converting \(relativePath): \(error)")
                }
                stats.errors += 1
            }
        }
    }
}

struct ConversionStats {
    var converted = 0
    var skipped = 0
    var errors = 0
}
