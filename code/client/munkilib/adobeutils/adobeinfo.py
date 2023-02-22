# encoding: utf-8
# Copyright 2009-2023 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
adobeutils.adobeinfo

Created by Greg Neagle on 2017-01-06.

Utilities to get info about Adobe installers/uninstallers

"""
from __future__ import absolute_import, print_function

import os
import json
import sqlite3

from glob import glob
from xml.dom import minidom

from .. import osutils
from .. import pkgutils


def find_install_app(dirpath):
    '''Searches dirpath and enclosed directories for Install.app.
    Returns the path to the actual executable.'''
    for (path, dummy_dirs, dummy_files) in os.walk(dirpath):
        if path.endswith("Install.app"):
            setup_path = os.path.join(path, "Contents", "MacOS", "Install")
            if os.path.exists(setup_path):
                return setup_path
    return ''


def find_setup_app(dirpath):
    '''Search dirpath and enclosed directories for Setup.app.
    Returns the path to the actual executable.'''
    for (path, dummy_dirs, dummy_files) in os.walk(dirpath):
        if path.endswith("Setup.app"):
            setup_path = os.path.join(path, "Contents", "MacOS", "Setup")
            if os.path.exists(setup_path):
                return setup_path
    return ''


def find_adobepatchinstaller_app(dirpath):
    '''Searches dirpath and enclosed directories for AdobePatchInstaller.app.
    Returns the path to the actual executable.'''
    for (path, dummy_dirs, dummy_files) in os.walk(dirpath):
        if path.endswith("AdobePatchInstaller.app"):
            setup_path = os.path.join(
                path, "Contents", "MacOS", "AdobePatchInstaller")
            if os.path.exists(setup_path):
                return setup_path
    return ''


def find_adobe_deployment_manager(dirpath):
    '''Searches dirpath and enclosed directories for AdobeDeploymentManager.
    Returns path to the executable.'''
    for (path, dummy_dirs, dummy_files) in os.walk(dirpath):
        if path.endswith("pkg/Contents/Resources"):
            dm_path = os.path.join(path, "AdobeDeploymentManager")
            if os.path.exists(dm_path):
                return dm_path
    return ''


def find_acrobat_patch_app(dirpath):
    '''Attempts to find an AcrobatPro patching application
    in dirpath. If found, returns the path to the bundled
    patching script.'''

    for (path, dummy_dirs, dummy_files) in os.walk(dirpath):
        if path.endswith(".app"):
            # look for Adobe's patching script
            patch_script_path = os.path.join(
                path, 'Contents', 'Resources', 'ApplyOperation.py')
            if os.path.exists(patch_script_path):
                return path
    return ''


def get_payload_info(dirpath):
    '''Parses Adobe payloads, pulling out info useful to munki.
    .proxy.xml files are used if available, or for CC-era updates
    which do not contain one, the Media_db.db file, which contains
    identical XML, is instead used.

    CS3/CS4:        contain only .proxy.xml
    CS5/CS5.5/CS6:  contain both
    CC:             contain only Media_db.db'''

    payloadinfo = {}
    # look for .proxy.xml file dir
    if os.path.isdir(dirpath):
        proxy_paths = glob(os.path.join(dirpath, '*.proxy.xml'))
        if proxy_paths:
            xmlpath = proxy_paths[0]
            dom = minidom.parse(xmlpath)
        # if there's no .proxy.xml we should hope there's a Media_db.db
        else:
            db_path = os.path.join(dirpath, 'Media_db.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute("SELECT value FROM PayloadData WHERE "
                            "PayloadData.key = 'PayloadInfo'")
                result = cur.fetchone()
                cur.close()
                if result:
                    info_xml = result[0].encode('UTF-8')
                    dom = minidom.parseString(info_xml)
            else:
                # no xml, no db, no payload info!
                return payloadinfo

        payload_info = dom.getElementsByTagName('PayloadInfo')
        if payload_info:
            installer_properties = payload_info[0].getElementsByTagName(
                'InstallerProperties')
            if installer_properties:
                properties = installer_properties[0].getElementsByTagName(
                    'Property')
                for prop in properties:
                    if 'name' in list(prop.attributes.keys()):
                        propname = prop.attributes['name'].value.encode('UTF-8')
                        propvalue = ''
                        for node in prop.childNodes:
                            propvalue += node.nodeValue
                        if propname == 'AdobeCode':
                            payloadinfo['AdobeCode'] = propvalue
                        if propname == 'ProductName':
                            payloadinfo['display_name'] = propvalue
                        if propname == 'ProductVersion':
                            payloadinfo['version'] = propvalue

            installmetadata = payload_info[0].getElementsByTagName(
                'InstallDestinationMetadata')
            if installmetadata:
                totalsizes = installmetadata[0].getElementsByTagName(
                    'TotalSize')
                if totalsizes:
                    installsize = ''
                    for node in totalsizes[0].childNodes:
                        installsize += node.nodeValue
                    payloadinfo['installed_size'] = int(int(installsize)/1024)

    return payloadinfo


def get_adobe_setup_info(installroot):
    '''Given the root of mounted Adobe DMG,
    look for info about the installer or updater'''

    info = {}
    payloads = []

    # look for all the payloads folders
    for (path, dummy_dirs, dummy_files) in os.walk(installroot):
        if path.endswith('/payloads'):
            driverfolder = ''
            media_signature = ''
            setupxml = os.path.join(path, 'setup.xml')
            if os.path.exists(setupxml):
                dom = minidom.parse(setupxml)
                drivers = dom.getElementsByTagName('Driver')
                if drivers:
                    driver = drivers[0]
                    if 'folder' in list(driver.attributes.keys()):
                        driverfolder = driver.attributes[
                            'folder'].value.encode('UTF-8')
                if driverfolder == '':
                    # look for mediaSignature (CS5 AAMEE install)
                    setup_elements = dom.getElementsByTagName('Setup')
                    if setup_elements:
                        media_signature_elements = setup_elements[
                            0].getElementsByTagName('mediaSignature')
                        if media_signature_elements:
                            element = media_signature_elements[0]
                            for node in element.childNodes:
                                media_signature += node.nodeValue

            for item in osutils.listdir(path):
                payloadpath = os.path.join(path, item)
                payloadinfo = get_payload_info(payloadpath)
                if payloadinfo:
                    payloads.append(payloadinfo)
                    if ((driverfolder and item == driverfolder) or
                            (media_signature and
                             payloadinfo['AdobeCode'] == media_signature)):
                        info['display_name'] = payloadinfo['display_name']
                        info['version'] = payloadinfo['version']
                        info['AdobeSetupType'] = 'ProductInstall'

    if not payloads:
        # look for an extensions folder; almost certainly this is an Updater
        for (path, dummy_dirs, dummy_files) in os.walk(installroot):
            if path.endswith("/extensions"):
                for item in osutils.listdir(path):
                    #skip LanguagePacks
                    if item.find("LanguagePack") == -1:
                        itempath = os.path.join(path, item)
                        payloadinfo = get_payload_info(itempath)
                        if payloadinfo:
                            payloads.append(payloadinfo)

                # we found an extensions dir,
                # so no need to keep walking the install root
                break

    if payloads:
        if len(payloads) == 1:
            info['display_name'] = payloads[0]['display_name']
            info['version'] = payloads[0]['version']
        else:
            if 'display_name' not in info:
                info['display_name'] = "ADMIN: choose from payloads"
            if 'version' not in info:
                info['version'] = "ADMIN please set me"
        info['payloads'] = payloads
        installed_size = 0
        for payload in payloads:
            installed_size = installed_size + payload.get('installed_size', 0)
        info['installed_size'] = installed_size
    return info


def get_adobe_package_info(installroot):
    '''Gets the package name from the AdobeUberInstaller.xml file;
    other info from the payloads folder'''

    info = get_adobe_setup_info(installroot)
    info['description'] = ""
    installerxml = os.path.join(installroot, "AdobeUberInstaller.xml")
    if os.path.exists(installerxml):
        description = ''
        dom = minidom.parse(installerxml)
        installinfo = dom.getElementsByTagName("InstallInfo")
        if installinfo:
            packagedescriptions = \
                installinfo[0].getElementsByTagName("PackageDescription")
            if packagedescriptions:
                prop = packagedescriptions[0]
                for node in prop.childNodes:
                    description += node.nodeValue

        if description:
            description_parts = description.split(' : ', 1)
            info['display_name'] = description_parts[0]
            if len(description_parts) > 1:
                info['description'] = description_parts[1]
            else:
                info['description'] = ""
            return info
        else:
            installerxml = os.path.join(installroot, "optionXML.xml")
            if os.path.exists(installerxml):
                dom = minidom.parse(installerxml)
                installinfo = dom.getElementsByTagName("InstallInfo")
                if installinfo:
                    pkgname_elems = installinfo[0].getElementsByTagName(
                        "PackageName")
                    if pkgname_elems:
                        prop = pkgname_elems[0]
                        pkgname = ""
                        for node in prop.childNodes:
                            pkgname += node.nodeValue
                        info['display_name'] = pkgname

    if not info.get('display_name'):
        info['display_name'] = os.path.basename(installroot)
    return info


def get_xml_text_element(dom_node, name):
    '''Returns the text value of the first item found with the given
    tagname'''
    value = None
    subelements = dom_node.getElementsByTagName(name)
    if subelements:
        value = ''
        for node in subelements[0].childNodes:
            value += node.nodeValue
    return value


def parse_option_xml(option_xml_file):
    '''Parses an optionXML.xml file and pulls the items of interest, returning
    them in a dictionary'''
    info = {}
    dom = minidom.parse(option_xml_file)
    installinfo = dom.getElementsByTagName('InstallInfo')
    if installinfo:
        if 'id' in list(installinfo[0].attributes.keys()):
            info['packager_id'] = installinfo[0].attributes['id'].value
        if 'version' in list(installinfo[0].attributes.keys()):
            info['packager_version'] = installinfo[
                0].attributes['version'].value
        info['package_name'] = get_xml_text_element(
            installinfo[0], 'PackageName')
        info['package_id'] = get_xml_text_element(installinfo[0], 'PackageID')
        info['products'] = []

        # CS5 to CC 2015.0-2015.2 releases use RIBS, and we retrieve a
        # display name, version and 'mediaSignature' for building installs
        # items. SAPCode is also stored so that we can later search by this
        # key across both RIBS and HyperDrive installer metadata.
        medias_elements = installinfo[0].getElementsByTagName('Medias')
        if medias_elements:
            media_elements = medias_elements[0].getElementsByTagName('Media')
            if media_elements:
                for media in media_elements:
                    product = {}
                    product['prodName'] = get_xml_text_element(
                        media, 'prodName')
                    product['prodVersion'] = get_xml_text_element(
                        media, 'prodVersion')
                    product['SAPCode'] = get_xml_text_element(media, 'SAPCode')
                    setup_elements = media.getElementsByTagName('Setup')
                    if setup_elements:
                        media_signature_elements = setup_elements[
                            0].getElementsByTagName('mediaSignature')
                        if media_signature_elements:
                            product['mediaSignature'] = ''
                            element = media_signature_elements[0]
                            for node in element.childNodes:
                                product['mediaSignature'] += node.nodeValue
                    info['products'].append(product)

        # HD (HyperDrive) media for new mid-June 2016 products. We need the
        # SAP codes, versions, and which ones are MediaType 'Product'. Support
        # payloads seem to all be 'STI', and are listed as STIDependencies under
        # the main product.
        hd_medias_elements = installinfo[0].getElementsByTagName('HDMedias')
        if hd_medias_elements:
            hd_media_elements = hd_medias_elements[0].getElementsByTagName(
                'HDMedia')
            if hd_media_elements:
                for hd_media in hd_media_elements:
                    product = {}
                    product['hd_installer'] = True
                    # productVersion is the 'full' version number
                    # prodVersion seems to be the "customer-facing" version for
                    # this update
                    # baseVersion is the first/base version for this standalone
                    # product/channel/LEID,
                    #   not really needed here so we don't copy it
                    for elem in [
                            'mediaLEID',
                            'prodVersion',
                            'productVersion',
                            'SAPCode',
                            'MediaType',
                            'TargetFolderName']:
                        product[elem] = get_xml_text_element(hd_media, elem)
                    info['products'].append(product)

    return info


def get_hd_installer_info(hd_payload_root, sap_code):
    '''Attempts to extract some information from a HyperDrive payload
    application.json file and return a reduced set in a dict'''
    hd_app_info = {}
    app_json_path = os.path.join(hd_payload_root, sap_code, 'Application.json')
    json_info = json.loads(open(app_json_path, 'r').read())

    # Copy some useful top-level keys, useful later for:
    # - Name: display_name pkginfo key
    # - ProductVersion: version pkginfo key and uninstall XML location
    # - SAPCode: an uninstallXml for an installs item if it's a 'core' Type
    # - BaseVersion and version: not currently used but may be useful once
    #   there are more HD installers in the future
    for key in ['BaseVersion', 'Name', 'ProductVersion', 'SAPCode', 'version']:
        hd_app_info[key] = json_info[key]
    hd_app_info['SAPCode'] = json_info['SAPCode']

    # Adobe puts an array of dicts in a dict with one key called 'Package'
    pkgs = [pkg for pkg in json_info['Packages']['Package']]
    hd_app_info['Packages'] = pkgs
    return hd_app_info


def get_cs5_media_signature(dirpath):
    '''Returns the CS5 mediaSignature for an AAMEE CS5 install.
    dirpath is typically the root of a mounted dmg'''

    payloads_dir = ""
    # look for a payloads folder
    for (path, dummy_dirs, dummy_files) in os.walk(dirpath):
        if path.endswith('/payloads'):
            payloads_dir = path

    # return empty-handed if we didn't find a payloads folder
    if not payloads_dir:
        return ''

    # now look for setup.xml
    setupxml = os.path.join(payloads_dir, 'Setup.xml')
    if os.path.exists(setupxml) and os.path.isfile(setupxml):
        # parse the XML
        dom = minidom.parse(setupxml)
        setup_elements = dom.getElementsByTagName('Setup')
        if setup_elements:
            media_signature_elements = (
                setup_elements[0].getElementsByTagName('mediaSignature'))
            if media_signature_elements:
                element = media_signature_elements[0]
                elementvalue = ''
                for node in element.childNodes:
                    elementvalue += node.nodeValue
                return elementvalue

    return ""


def get_cs5_uninstall_xml(option_xml_file):
    '''Gets the uninstall deployment data from a CS5 installer'''
    xml = ''
    dom = minidom.parse(option_xml_file)
    deployment_info = dom.getElementsByTagName('DeploymentInfo')
    if deployment_info:
        for info_item in deployment_info:
            deployment_uninstall = info_item.getElementsByTagName(
                'DeploymentUninstall')
            if deployment_uninstall:
                deployment_data = deployment_uninstall[0].getElementsByTagName(
                    'Deployment')
                if deployment_data:
                    deployment = deployment_data[0]
                    xml += deployment.toxml('UTF-8')
    return xml


def count_payloads(dirpath):
    '''Attempts to count the payloads in the Adobe installation item.
       Used for rough percent-done progress feedback.'''
    count = 0
    for (path, dummy_dirs, files) in os.walk(dirpath):
        if path.endswith("/payloads"):
            # RIBS-style installers
            for subitem in osutils.listdir(path):
                subitempath = os.path.join(path, subitem)
                if os.path.isdir(subitempath):
                    count = count + 1
        elif "/HD/" in path and "Application.json" in files:
            # we're inside an HD installer directory. The payloads/packages
            # are .zip files
            zip_file_count = len(
                [item for item in files if item.endswith(".zip")])
            count = count + zip_file_count
    return count


def get_adobe_install_info(installdir):
    '''Encapsulates info used by the Adobe Setup/Install app.'''
    adobe_install_info = {}
    if installdir:
        adobe_install_info['media_signature'] = get_cs5_media_signature(
            installdir)
        adobe_install_info['payload_count'] = count_payloads(installdir)
        option_xml_file = os.path.join(installdir, "optionXML.xml")
        if os.path.exists(option_xml_file):
            adobe_install_info['uninstallxml'] = get_cs5_uninstall_xml(
                option_xml_file)

    return adobe_install_info


# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=invalid-name
def getAdobeCatalogInfo(mountpoint, pkgname=""):
    '''Used by makepkginfo to build pkginfo data for Adobe
    installers/updaters'''

    # look for AdobeDeploymentManager (AAMEE installer)
    deploymentmanager = find_adobe_deployment_manager(mountpoint)
    if deploymentmanager:
        dirpath = os.path.dirname(deploymentmanager)
        option_xml_file = os.path.join(dirpath, 'optionXML.xml')
        option_xml_info = {}
        if os.path.exists(option_xml_file):
            option_xml_info = parse_option_xml(option_xml_file)
        cataloginfo = get_adobe_package_info(dirpath)
        if cataloginfo:
            # add some more data
            if option_xml_info.get('packager_id') == u'CloudPackager':
                # CCP package
                cataloginfo['display_name'] = option_xml_info.get(
                    'package_name', 'unknown')
                cataloginfo['name'] = cataloginfo['display_name'].replace(
                    ' ', '')
                cataloginfo['uninstallable'] = True
                cataloginfo['uninstall_method'] = "AdobeCCPUninstaller"
                cataloginfo['installer_type'] = "AdobeCCPInstaller"
                cataloginfo['minimum_os_version'] = "10.6.8"
                mediasignatures = [
                    item['mediaSignature']
                    for item in option_xml_info.get('products', [])
                    if 'mediaSignature' in item]
            else:
                # AAMEE package
                cataloginfo['name'] = cataloginfo['display_name'].replace(
                    ' ', '')
                cataloginfo['uninstallable'] = True
                cataloginfo['uninstall_method'] = "AdobeCS5AAMEEPackage"
                cataloginfo['installer_type'] = "AdobeCS5AAMEEPackage"
                cataloginfo['minimum_os_version'] = "10.5.0"
                cataloginfo['adobe_install_info'] = get_adobe_install_info(
                    installdir=dirpath)
                mediasignature = cataloginfo['adobe_install_info'].get(
                    "media_signature")
                mediasignatures = [mediasignature]

            # Determine whether we have HD media as well in this installer
            hd_metadata_dirs = [
                product['TargetFolderName']
                for product in option_xml_info['products']
                if product.get('hd_installer')]

            hd_app_infos = []
            for sap_code in hd_metadata_dirs:
                hd_app_info = get_hd_installer_info(
                    os.path.join(dirpath, 'HD'), sap_code)
                hd_app_infos.append(hd_app_info)

            # 'installs' array will be populated if we have either RIBS
            # or HD installers, which may be mixed together in one
            # CCP package.
            # Acrobat Pro DC doesn't currently generate any useful installs
            # info if it's part of a CCP package.
            installs = []

            # media signatures are used for RIBS (CS5 to CC mid-2015)
            if mediasignatures:
                # make a default <key>installs</key> array
                uninstalldir = "/Library/Application Support/Adobe/Uninstall"
                for mediasignature in mediasignatures:
                    signaturefile = mediasignature + ".db"
                    filepath = os.path.join(uninstalldir, signaturefile)
                    installitem = {}
                    installitem['path'] = filepath
                    installitem['type'] = 'file'
                    installs.append(installitem)

            # Custom installs items for HD installers seem to need only HDMedias
            # from optionXML.xml with a MediaType of 'Product' and their
            # 'core' packages (e.g. language packs are 'non-core')
            if hd_app_infos:
                if 'payloads' not in cataloginfo:
                    cataloginfo['payloads'] = []
                cataloginfo['payloads'].extend(hd_app_infos)

                # Calculate installed_size by counting packages in payloads
                # in these indexed HD medias. installed_size may exist already
                # if this package contained RIBS payloads, so try reading it
                # and default to 0. This will typically include several very
                # small packages (language or regional recommended settings)
                # which would not actually get installed. These seem to be
                # no larger than a few MB, so in practice it increases the
                # 'installed_size' value by only ~1%.
                installed_size = cataloginfo.get('installed_size', 0)
                for hd_payload in hd_app_infos:
                    for package in hd_payload['Packages']:
                        # Generally, all app installs will include 1-3 'core'
                        # packages and then additional language/settings/color
                        # packages which are regional or language-specific.
                        # If we filter this by including both unconditional
                        # installs and those which are language/region specific,
                        # we get a rough approximation of the total size of
                        # supplemental packages, as their equivalents for other
                        # languages are very close to the same size. We also
                        # get one included language package which would be the
                        # case for any install.
                        #
                        # Because InDesign CC 2017 is not like any other package
                        # and contains a 'Condition' key but as an empty
                        # string, we explicitly test this case as well.
                        if ('Condition' not in list(package.keys()) or
                                package.get('Condition') == '' or
                                '[installLanguage]==en_US' in
                                package.get('Condition', '')):
                            installed_size += int(package.get(
                                'ExtractSize', 0) / 1024)
                            # We get much closer to Adobe's "HDSetup" calculated
                            # install space requirement if we include both the
                            # DownloadSize and ExtractSize data
                            # (DownloadSize is just the zip file size)
                            installed_size += int(package.get(
                                'DownloadSize', 0) / 1024)
                # Add another 300MB for the CC app and plumbing in case they've
                # never been installed on the system
                installed_size += 307200
                cataloginfo['installed_size'] = installed_size

                uninstalldir = (
                    '/Library/Application Support/Adobe/Installers/uninstallXml'
                )
                product_saps = [
                    prod['SAPCode'] for
                    prod in option_xml_info['products']
                    if prod.get('MediaType') == 'Product'
                ]

                product_app_infos = [app for app in hd_app_infos
                                     if app['SAPCode'] in product_saps]
                # if we had only a single HD and no legacy apps, set a sane
                # version and display_name derived from the app's metadata
                if (len(product_app_infos) == 1) and not mediasignatures:
                    cataloginfo.update({
                        'display_name': product_app_infos[0]['Name'],
                        'version': product_app_infos[0]['ProductVersion'],
                    })

                for app_info in product_app_infos:
                    for pkg in app_info['Packages']:
                        # Don't assume 'Type' key always exists. At least the
                        #'AdobeIllustrator20-Settings'
                        # package doesn't have this key set.
                        if pkg.get('Type') == 'core':
                            # We can't use 'ProductVersion' from
                            # Application.json for the part following the
                            # SAPCode, because it's usually too specific and
                            # won't match the "short" product version.
                            # We can take 'prodVersion' from the optionXML.xml
                            # instead.
                            # We filter out any non-HD installers to avoid
                            # matching up the wrong versions for packages that
                            # may contain multiple different major versions of
                            # a given SAPCode
                            pkg_prod_vers = [
                                prod['prodVersion']
                                for prod in option_xml_info['products']
                                if prod.get('hd_installer') and
                                prod['SAPCode'] == app_info['SAPCode']][0]
                            uninstall_file_name = '_'.join([
                                app_info['SAPCode'],
                                pkg_prod_vers.replace('.', '_'),
                                pkg['PackageName'],
                                pkg['PackageVersion']]) + '.pimx'
                            filepath = os.path.join(
                                uninstalldir, uninstall_file_name)
                            installitem = {}
                            installitem['path'] = filepath
                            installitem['type'] = 'file'
                            installs.append(installitem)

            if installs:
                cataloginfo['installs'] = installs

            return cataloginfo

    # Look for Install.app (Bare metal CS5 install)
    # we don't handle this type, but we'll report it
    # back so makepkginfo can provide an error message
    installapp = find_install_app(mountpoint)
    if installapp:
        cataloginfo = {}
        cataloginfo['installer_type'] = "AdobeCS5Installer"
        return cataloginfo

    # Look for AdobePatchInstaller.app (CS5 updater)
    installapp = find_adobepatchinstaller_app(mountpoint)
    if os.path.exists(installapp):
        # this is a CS5 updater disk image
        cataloginfo = get_adobe_package_info(mountpoint)
        if cataloginfo:
            # add some more data
            cataloginfo['name'] = cataloginfo['display_name'].replace(' ', '')
            cataloginfo['uninstallable'] = False
            cataloginfo['installer_type'] = "AdobeCS5PatchInstaller"
            if pkgname:
                cataloginfo['package_path'] = pkgname

            # make some (hopefully functional) installs items from the payloads
            installs = []
            uninstalldir = "/Library/Application Support/Adobe/Uninstall"
            # first look for a payload with a display_name matching the
            # overall display_name
            for payload in cataloginfo.get('payloads', []):
                if (payload.get('display_name', '') ==
                        cataloginfo['display_name']):
                    if 'AdobeCode' in payload:
                        dbfile = payload['AdobeCode'] + ".db"
                        filepath = os.path.join(uninstalldir, dbfile)
                        installitem = {}
                        installitem['path'] = filepath
                        installitem['type'] = 'file'
                        installs.append(installitem)
                        break

            if installs == []:
                # didn't find a payload with matching name
                # just add all of the non-LangPack payloads
                # to the installs list.
                for payload in cataloginfo.get('payloads', []):
                    if 'AdobeCode' in payload:
                        if ("LangPack" in payload.get("display_name") or
                                "Language Files" in payload.get(
                                    "display_name")):
                            # skip Language Packs
                            continue
                        dbfile = payload['AdobeCode'] + ".db"
                        filepath = os.path.join(uninstalldir, dbfile)
                        installitem = {}
                        installitem['path'] = filepath
                        installitem['type'] = 'file'
                        installs.append(installitem)

            cataloginfo['installs'] = installs
            return cataloginfo

    # Look for AdobeUberInstaller items (CS4 install)
    pkgroot = os.path.join(mountpoint, pkgname)
    adobeinstallxml = os.path.join(pkgroot, "AdobeUberInstaller.xml")
    if os.path.exists(adobeinstallxml):
        # this is a CS4 Enterprise Deployment package
        cataloginfo = get_adobe_package_info(pkgroot)
        if cataloginfo:
            # add some more data
            cataloginfo['name'] = cataloginfo['display_name'].replace(' ', '')
            cataloginfo['uninstallable'] = True
            cataloginfo['uninstall_method'] = "AdobeUberUninstaller"
            cataloginfo['installer_type'] = "AdobeUberInstaller"
            if pkgname:
                cataloginfo['package_path'] = pkgname
            return cataloginfo

    # maybe this is an Adobe update DMG or CS3 installer
    # look for Adobe Setup.app
    setuppath = find_setup_app(mountpoint)
    if setuppath:
        cataloginfo = get_adobe_setup_info(mountpoint)
        if cataloginfo:
            # add some more data
            cataloginfo['name'] = cataloginfo['display_name'].replace(' ', '')
            cataloginfo['installer_type'] = "AdobeSetup"
            if cataloginfo.get('AdobeSetupType') == "ProductInstall":
                cataloginfo['uninstallable'] = True
                cataloginfo['uninstall_method'] = "AdobeSetup"
            else:
                cataloginfo['description'] = "Adobe updater"
                cataloginfo['uninstallable'] = False
                cataloginfo['update_for'] = ["PleaseEditMe-1.0.0.0.0"]
            return cataloginfo

    # maybe this is an Adobe Acrobat 9 Pro patcher?
    acrobatpatcherapp = find_acrobat_patch_app(mountpoint)
    if acrobatpatcherapp:
        cataloginfo = {}
        cataloginfo['installer_type'] = "AdobeAcrobatUpdater"
        cataloginfo['uninstallable'] = False
        plist = pkgutils.getBundleInfo(acrobatpatcherapp)
        cataloginfo['version'] = pkgutils.getVersionString(plist)
        cataloginfo['name'] = "AcrobatPro9Update"
        cataloginfo['display_name'] = "Adobe Acrobat Pro Update"
        cataloginfo['update_for'] = ["AcrobatPro9"]
        cataloginfo['RestartAction'] = 'RequireLogout'
        cataloginfo['requires'] = []
        cataloginfo['installs'] = [
            {'CFBundleIdentifier': 'com.adobe.Acrobat.Pro',
             'CFBundleName': 'Acrobat',
             'CFBundleShortVersionString': cataloginfo['version'],
             'path': '/Applications/Adobe Acrobat 9 Pro/Adobe Acrobat Pro.app',
             'type': 'application'}
        ]
        return cataloginfo

    # didn't find any Adobe installers/updaters we understand
    return None
# pylint: enable=invalid-name


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
