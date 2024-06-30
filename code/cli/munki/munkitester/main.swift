//
//  main.swift
//  munkitester
//
//  Created by Greg Neagle on 6/25/24.
//

// this is a temporary target to use to test things

import Foundation

/*
 do {
     let repo = try FileRepo("file:///Users/Shared/munki_repo")
     let pkgsinfo = try repo.itemlist("pkgsinfo")
     print(pkgsinfo)
     let data = try repo.get("manifests/site_default")
     if let plist = NSString(data: data, encoding: NSUTF8StringEncoding) {
         print(plist)
     }
     try repo.get("manifests/site_default", toFile: "/tmp/sitr_default")
 } catch {
     print(error)
 }
 */

/*
 do {
     let repo = try FileRepo("file:///Users/Shared/munki_repo")
     print(repo.baseurl)
     print(repo.root)
     let catalogsmaker = try CatalogsMaker(repo: repo)
     let errors = catalogsmaker.makecatalogs()
     if !errors.isEmpty {
         print(catalogsmaker.errors)
     }
 } catch {
     print(error)
 }
 */

/*
 let options = MakeCatalogOptions(
     skip_payload_check: true,
     force: false,
     verbose: true
 )

 do {
     let repo = try repoConnect(url: "file:///Users/Shared/munki_repo")
     var catalogsmaker = try CatalogsMaker(repo: repo, options: options)
     let errors = catalogsmaker.makecatalogs()
     if !errors.isEmpty {
         for error in errors {
             printStderr(error)
         }
         exit(-1)
     }
 } catch RepoError.error(let description) {
     printStderr("Repo error: \(description)")
     exit(-1)
 } catch MakeCatalogsError.PkginfoAccessError(let description) {
     printStderr("Pkginfo read error: \(description)")
     exit(-1)
 } catch MakeCatalogsError.CatalogWriteError(let description) {
     printStderr("Catalog write error: \(description)")
     exit(-1)
 } catch {
     printStderr("Unexpected error: \(error)")
     exit(-1)
 }
 */

do {
    let repo = try repoConnect(
        url: "file:///Users/Shared/munki_repo",
        plugin: "GitFileRepo"
    )
    let localFilePath = "/Users/Shared/munki_repo/manifests/site_default"
    let identifier = "manifests/foo"
    try repo.put(identifier, content: Data())
    try repo.put(identifier, fromFile: localFilePath)
    try repo.delete(identifier)
} catch {
    print(error)
}
