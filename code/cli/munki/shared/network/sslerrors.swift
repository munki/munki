//
//  sslerrors.swift
//  munki
//
//  Created by Greg Neagle on 8/10/24.
//
//  Copyright 2024-2026 The Munki Project. All rights reserved.
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

let SSL_ERROR_CODES = [
    -9800: "SSL protocol error",
    -9801: "Cipher Suite negotiation failure",
    -9802: "Fatal alert",
    -9803: "I/O would block (not fatal)",
    -9804: "Attempt to restore an unknown session",
    -9805: "Connection closed gracefully",
    -9806: "Connection closed via error",
    -9807: "Invalid certificate chain",
    -9808: "Bad certificate format",
    -9809: "Underlying cryptographic error",
    -9810: "Internal error",
    -9811: "Module attach failure",
    -9812: "Valid cert chain, untrusted root",
    -9813: "Cert chain not verified by root",
    -9814: "Chain had an expired cert",
    -9815: "Chain had a cert not yet valid",
    -9816: "Server closed session with no notification",
    -9817: "Insufficient buffer provided",
    -9818: "Bad SSLCipherSuite",
    -9819: "Unexpected message received",
    -9820: "Bad MAC",
    -9821: "Decryption failed",
    -9822: "Record overflow",
    -9823: "Decompression failure",
    -9824: "Handshake failure",
    -9825: "Misc. bad certificate",
    -9826: "Bad unsupported cert format",
    -9827: "Certificate revoked",
    -9828: "Certificate expired",
    -9829: "Unknown certificate",
    -9830: "Illegal parameter",
    -9831: "Unknown Cert Authority",
    -9832: "Access denied",
    -9833: "Decoding error",
    -9834: "Decryption error",
    -9835: "Export restriction",
    -9836: "Bad protocol version",
    -9837: "Insufficient security",
    -9838: "Internal error",
    -9839: "User canceled",
    -9840: "No renegotiation allowed",
    -9841: "Peer cert is valid, or was ignored if verification disabled",
    -9842: "Server has requested a client cert",
    -9843: "Peer host name mismatch",
    -9844: "Peer dropped connection before responding",
    -9845: "Decryption failure",
    -9846: "Bad MAC",
    -9847: "Record overflow",
    -9848: "Configuration error",
    -9849: "Unexpected (skipped) record in DTLS",
]

func sslErrorForCode(_ code: Int) -> String {
    return SSL_ERROR_CODES[code] ?? "Unknown SSL error"
}
