# SPDX-License-Identifier: AGPL-3.0-only
"""Create/verify Sparkle artifacts using its official tools and a Keychain reference."""
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

try:
    from tools import sparkle
except ModuleNotFoundError:
    import sparkle

SPARKLE_NS = 'http://www.andymatuschak.org/xml-namespaces/sparkle'


def run(tool, *args):
    try:
        result = subprocess.run([str(tool), *map(str, args)], capture_output=True, text=True, check=False, timeout=600)
    except subprocess.TimeoutExpired:
        raise ValueError('Sparkle signing or verification timed out; no update may be published') from None
    if result.returncode:
        raise ValueError('Sparkle signing or verification failed; no update may be published')
    return result.stdout.strip()


def validate_feed(path, archive, info, url):
    root = ET.parse(path).getroot()
    items = root.findall('./channel/item')
    if len(items) != 1:
        raise ValueError('Expected one explicitly versioned update item')
    item = items[0]
    field = lambda name: item.findtext('{' + SPARKLE_NS + '}' + name)
    enclosure = item.find('enclosure')
    # Official Sparkle omits arm64 on macOS 27+, which itself excludes Intel.
    minimum_major = int(info['LSMinimumSystemVersion'].split('.')[0])
    hardware = field('hardwareRequirements')
    valid_hardware = hardware == 'arm64' or (minimum_major >= 27 and hardware is None)
    if (field('version') != info['CFBundleVersion'] or
            field('shortVersionString') != info['CFBundleShortVersionString'] or
            field('minimumSystemVersion') != info['LSMinimumSystemVersion'] or
            not valid_hardware or enclosure is None or
            enclosure.get('url') != url or enclosure.get('length') != str(archive.stat().st_size) or
            not re.fullmatch(r'[A-Za-z0-9+/]{86}==', enclosure.get('{' + SPARKLE_NS + '}edSignature', ''))):
        raise ValueError('Generated update feed does not match the signed app and archive')
    return enclosure.get('{' + SPARKLE_NS + '}edSignature')


def prepare(app, destination, stem, info, *, account, release_tag):
    if not account or not re.fullmatch(r'[A-Za-z0-9._-]+', release_tag or ''):
        raise ValueError('Update packaging requires a Keychain account reference and immutable release tag')
    sparkle.validate_configuration(info)
    tools = sparkle.distribution() / 'bin'
    public = run(tools / 'generate_keys', '--account', account, '-p')
    if public != info['SUPublicEDKey']:
        raise ValueError('The update signing account does not match the app public key')
    folder = destination / 'sparkle-update'
    folder.mkdir()
    archive = folder / (stem + '-update.zip')
    run('/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, archive)
    prefix = 'https://github.com/moey823/decrumb/releases/download/' + release_tag + '/'
    run(tools / 'generate_appcast', '--account', account, '--download-url-prefix', prefix,
        '--maximum-deltas', '0', '--maximum-versions', '1', '--link', 'https://mkships.app/decrumb/', folder)
    feed = folder / 'appcast.xml'
    signature = validate_feed(feed, archive, info, prefix + archive.name)
    run(tools / 'sign_update', '--account', account, '--verify', archive, signature)
    run(tools / 'sign_update', '--account', account, '--verify', feed)
    final_archive = destination / archive.name
    final_feed = destination / (stem + '-appcast.xml')
    shutil.move(archive, final_archive)
    shutil.move(feed, final_feed)
    return final_archive, final_feed
