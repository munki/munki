#!/bin/sh

arch=$(/usr/bin/arch)

if [ "$arch" == "arm64" ]; then
    /usr/sbin/softwareupdate --install-rosetta --agree-to-license
fi
