The tools get their configuration from /Library/Preferences/ManagedInstalls.plist
If the file or any of the keys are missing, munki uses these defaults:


Where munki writes its install/remove metadata, caches install packages, and writes reports and logs:

    prefs['ManagedInstallDir'] = "/Library/Managed Installs"


This one is a convenience; if you set this one and do not set ManifestURL, CatalogURL or PackageURL, the other URLs will be built relative to the SoftwareRepoURL:

    prefs['SoftwareRepoURL'] = "http://munki/repo"


The next three are preferred to SoftwareRepoURL; They allow you to serve manifests and catalogs from one server and packages from another. If they exist in the plist, they take precedence over the URL implied by SoftwareRepoURL:

    prefs['ManifestURL'] = "http://munki/repo/manifests/"
    prefs['CatalogURL'] = "http://munki/repo/catalogs/"
    prefs['PackageURL'] = "http://munki/repo/pkgs/"


Use SSL client certificates to secure communication with the web server:

    prefs['UseClientCertificate'] = False
    prefs['ClientIdentifier'] = '' # (munki will use the FQDN, then short hostname, then look for site_default)


Location for logging and verbosity:

    prefs['LogFile'] = "/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log"
    prefs['LoggingLevel'] = 1


URL for an internal Apple Software Update Server. Delete the key or set it to an empty string to use Apple's SUS.:

    prefs['SoftwareUpdateServerURL'] = ''  #(use Apple's if this is empty)
    prefs['InstallAppleSoftwareUpdates'] = False


Number of days between user notifications from Managed Software Update:

    prefs['DaysBetweenNotifications'] = 1

The example ManagedInstalls.plist in this directory is not meant to be used as-is, but rather as a starting point.
You will need to modify it to match your needs.
