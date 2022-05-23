#!/bin/sh

rm -rf /Users/admin/code
cp -r /Users/admin/Documents/Development/Munki/code /Users/admin/

/Users/admin/code/tools/make_munki_mpkg.sh -S "Developer ID Application: Emily Carr University of Art and Design (7TF6CSP83S)" -s "Developer ID Installer: Emily Carr University of Art and Design (7TF6CSP83S)"

rm -rf /Users/admin/code