// swift-tools-version: 5.9
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "munki-cli",
    platforms: [
        .macOS(.v10_15)
    ],
    products: [
        .executable(name: "makepkginfo", targets: ["makepkginfo"]),
        .executable(name: "makecatalogs", targets: ["makecatalogs"]),
        .executable(name: "manifestutil", targets: ["manifestutil"]),
        .executable(name: "munkiimport", targets: ["munkiimport"]),
        .executable(name: "repoclean", targets: ["repoclean"]),
        .executable(name: "yaml_migrate", targets: ["yaml_migrate"]),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser", from: "1.2.0"),
        .package(url: "https://github.com/jpsim/Yams.git", from: "6.0.2"),
    ],
    targets: [
        .executableTarget(
            name: "makepkginfo",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                "Yams",
                "MunkiShared"
            ],
            path: "makepkginfo"
        ),
        .executableTarget(
            name: "makecatalogs",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                "Yams",
                "MunkiShared"
            ],
            path: "makecatalogs"
        ),
        .executableTarget(
            name: "manifestutil",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                "Yams",
                "MunkiShared"
            ],
            path: "manifestutil"
        ),
        .executableTarget(
            name: "munkiimport",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                "Yams",
                "MunkiShared"
            ],
            path: "munkiimport"
        ),
        .executableTarget(
            name: "repoclean",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                "Yams",
                "MunkiShared"
            ],
            path: "repoclean"
        ),
        .executableTarget(
            name: "yaml_migrate",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                "Yams",
            ],
            path: "yaml_migrate"
        ),
        .target(
            name: "MunkiShared",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                "Yams",
            ],
            path: "shared",
            exclude: [
                "Predicates.m", 
                "headers/", 
                "network/",
                "admin/readline.swift",
                "facts.swift",
                "updatecheck/",
                "installer/"
            ]
        ),
    ]
)
