//
//  MUconvert.swift
//  manifestutil
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
import MunkiShared

/// Convert manifest files between YAML and plist formats
extension ManifestUtil {
    struct Convert: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Convert manifest files between YAML and plist formats.",
            discussion: """
            Converts manifest files from plist to YAML or from YAML to plist.
            
            If converting a single file, specify both input and output paths.
            If converting a directory, specify the directory path and use --to-yaml or --to-plist.
            
            Examples:
              # Convert single manifest from plist to YAML
              manifestutil convert site_default.plist site_default.yaml
              
              # Convert single manifest from YAML to plist
              manifestutil convert site_default.yaml site_default.plist
              
              # Convert all manifests in repo to YAML
              manifestutil convert --to-yaml --backup
              
              # Convert all manifests in repo to plist (for compatibility)
              manifestutil convert --to-plist --backup
              
              # Dry run to see what would be converted
              manifestutil convert --to-yaml --dry-run
            """
        )
        
        @Argument(help: "Source file or directory (optional if using repo connection)")
        var source: String?
        
        @Argument(help: "Destination file (required when converting single file)")
        var destination: String?
        
        @Flag(name: .long, help: "Convert all manifests in repo to YAML format")
        var toYaml = false
        
        @Flag(name: .long, help: "Convert all manifests in repo to plist format")
        var toPlist = false
        
        @Flag(name: .long, help: "Create backup copies of original files")
        var backup = false
        
        @Flag(name: .long, help: "Show what would be done without making changes")
        var dryRun = false
        
        @Flag(name: .shortAndLong, help: "Verbose output")
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
        
        func run() async throws {
            if let src = source, let dest = destination {
                // Single file conversion
                try convertSingleFile(from: src, to: dest)
            } else if toYaml || toPlist {
                // Batch conversion using repo connection
                try await convertRepoManifests(toYaml: toYaml)
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
                let manifest = try readData(sourceData, preferYaml: isSourceYaml, filepath: source)
                
                guard let manifestDict = manifest as? PlistDict else {
                    throw ValidationError("Could not parse manifest from \(source)")
                }
                
                // Determine output format based on destination extension
                let isDestYaml = isYamlFile(destination)
                
                // Convert to destination format
                let destData: Data
                if isDestYaml {
                    destData = try yamlToData(manifestDict)
                } else {
                    destData = try plistToData(manifestDict)
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
        
        private func convertRepoManifests(toYaml: Bool) async throws {
            guard let repo = RepoConnection.shared.repo else {
                throw ValidationError("No repo connection. Run 'manifestutil config' first.")
            }
            
            let targetFormat = toYaml ? "YAML" : "plist"
            
            if verbose {
                print("Converting all manifests to \(targetFormat) format...")
                print("Backup: \(backup ? "enabled" : "disabled")")
                print("Dry run: \(dryRun ? "enabled" : "disabled")")
            }
            
            var stats = ConversionStats()
            
            // Get list of all manifests from repo using getManifestNames function
            guard let manifestNames = await getManifestNames(repo: repo) else {
                throw ValidationError("Could not retrieve manifest list from repo")
            }
            
            for manifestName in manifestNames {
                try await convertRepoManifest(
                    manifestName,
                    repo: repo,
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
        
        private func convertRepoManifest(
            _ manifestName: String,
            repo: Repo,
            toYaml: Bool,
            stats: inout ConversionStats
        ) async throws {
            // Determine the new extension based on conversion direction
            let fileExtension = toYaml ? ".yaml" : ""
            
            // Check if manifest is already in the target format
            let identifier = "manifests/\(manifestName)"
            let hasYamlExt = manifestName.hasSuffix(".yaml") || manifestName.hasSuffix(".yml")
            
            // Skip if already in target format
            if toYaml && hasYamlExt {
                if verbose {
                    print("Skipping (already YAML): \(manifestName)")
                }
                stats.skipped += 1
                return
            }
            if !toYaml && !hasYamlExt {
                if verbose {
                    print("Skipping (already plist): \(manifestName)")
                }
                stats.skipped += 1
                return
            }
            
            if verbose {
                let targetFormat = toYaml ? "YAML" : "plist"
                print("Converting \(manifestName) to \(targetFormat)...")
            }
            
            if dryRun {
                stats.converted += 1
                return
            }
            
            do {
                // Read the manifest using getManifest helper function
                guard let manifest = await getManifest(repo: repo, name: manifestName) else {
                    if verbose {
                        print("Error: Could not read manifest: \(manifestName)")
                    }
                    stats.errors += 1
                    return
                }
                
                // Create backup if requested
                if backup {
                    let backupName = "\(manifestName).backup"
                    let originalData = try await repo.get(identifier)
                    try await repo.put("manifests/\(backupName)", content: originalData)
                    if verbose {
                        print("Created backup: \(backupName)")
                    }
                }
                
                // Determine new manifest name (strip .yaml/.yml extension or add .yaml)
                let baseName: String
                if hasYamlExt {
                    baseName = (manifestName as NSString).deletingPathExtension
                } else {
                    baseName = manifestName
                }
                let newName = "\(baseName)\(fileExtension)"
                
                // Save manifest in new format using saveManifest helper
                if await saveManifest(repo: repo, manifest: manifest, name: newName, overwrite: true, yamlOutput: toYaml) {
                    // Delete old file if name changed
                    if manifestName != newName {
                        do {
                            try await repo.delete(identifier)
                            if verbose {
                                print("Deleted original: \(manifestName)")
                            }
                        } catch {
                            if verbose {
                                print("Warning: Could not delete original \(manifestName): \(error)")
                            }
                        }
                    }
                    stats.converted += 1
                } else {
                    if verbose {
                        print("Error: Could not save converted manifest: \(newName)")
                    }
                    stats.errors += 1
                }
            } catch {
                if verbose {
                    print("Error converting \(manifestName): \(error)")
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
