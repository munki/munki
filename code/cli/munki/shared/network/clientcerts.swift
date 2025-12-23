//
//  clientcerts.swift
//  munki
//
//  Created by Greg Neagle on 4/9/25.
//
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

import Foundation
import Security
import SwiftASN1
import X509

/// Takes a certificate ref, and attempts to construct the certificate chain.
/// Requires that any certificates in the chain are present in the Keychain.
func getCertChainRefs(_ certRef: SecCertificate) -> [SecCertificate]? {
    var trust: SecTrust?
    let status = SecTrustCreateWithCertificates(certRef, SecPolicyCreateBasicX509(), &trust)
    guard status == errSecSuccess, let trust else {
        return nil
    }

    var evalErr: CFError?
    _ = SecTrustEvaluateWithError(trust, &evalErr)
    if evalErr != nil {
        return nil
    }

    var certRefs = [SecCertificate]()
    if #available(macOS 12.0, *) {
        if let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate] {
            certRefs = chain
        }
    } else {
        for i in 0 ..< SecTrustGetCertificateCount(trust) {
            certRefs.append(SecTrustGetCertificateAtIndex(trust, i)!)
        }
    }
    return certRefs
}

/// Attempts to find an appropriate identity for the protectionSpace and return a credential
/// for client certificate authentication
func getClientCertCredential(
    protectionSpace: URLProtectionSpace,
    log: (String) -> Void
) -> URLCredential? {
    var expectedIssuers = [DistinguishedName]()
    if let distinguishedNames = protectionSpace.distinguishedNames {
        // distinguishedNames is an array of Data blobs
        // each blob is DER encoded
        for dnData in distinguishedNames {
            if let rootNode = try? ASN1Any(derEncoded: [UInt8](dnData)) {
                if let dn = try? DistinguishedName(asn1Any: rootNode) {
                    expectedIssuers.append(dn)
                    log("Accepted certificate-issuing authority: \(dn.description)")
                }
            }
        }
    }
    if expectedIssuers.isEmpty {
        log("The server didn't send the list of acceptable certificate-issuing authorities")
        return nil
    }
    // search for a matching identity (cert paired with private key)
    var identityRefs: CFTypeRef?
    let query = [
        kSecClass: kSecClassIdentity,
        kSecReturnRef: kCFBooleanTrue!,
        kSecMatchLimit: kSecMatchLimitAll,
    ] as CFDictionary
    let status = SecItemCopyMatching(query, &identityRefs)
    guard status == errSecSuccess, let identityRefs else {
        // couldn't find any identities in the keychain, so we can't authenticate
        log("Could not find keychain identities: \(status)")
        return nil
    }
    var certChainRefs: [SecCertificate]?
    // loop through results to find cert that matches issuer
    for identityRef in identityRefs as! [SecIdentity] {
        var certRef: SecCertificate?
        let status = SecIdentityCopyCertificate(identityRef, &certRef)
        guard status == errSecSuccess, let certRef else { continue }
        let certData = SecCertificateCopyData(certRef)
        guard let certificate = try? Certificate(derEncoded: [UInt8](certData as Data)) else { continue }
        var certSubjects = [certificate.issuer]
        certChainRefs = getCertChainRefs(certRef)
        if let certChainRefs {
            for c in certChainRefs {
                let certData = SecCertificateCopyData(c)
                if let certificate = try? Certificate(derEncoded: [UInt8](certData as Data)) {
                    certSubjects.append(certificate.subject)
                }
            }
        }
        for certSubject in certSubjects {
            if expectedIssuers.contains(certSubject) {
                log("Found matching identity")
                return URLCredential(
                    identity: identityRef,
                    certificates: certChainRefs,
                    persistence: .forSession
                )
            }
        }
    }
    // no matching identity found
    return nil
}
