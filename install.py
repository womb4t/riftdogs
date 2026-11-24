#!/usr/bin/env python3
"""Install Riftdogs into the current user's XDG data directory."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def install_mac_app(target):
    # A minimal app bundle in ~/Applications, so Riftdogs opens from Launchpad, Spotlight or the Dock.
    bundle = Path(os.environ.get('RIFTDOGS_APP') or Path.home()/'Applications'/'Riftdogs.app')
    app = bundle/'Contents'
    (app/'MacOS').mkdir(parents=True, exist_ok=True)
    (app/'Info.plist').write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        '<key>CFBundleName</key><string>Riftdogs</string>\n'
        '<key>CFBundleIdentifier</key><string>io.github.womb4t.riftdogs</string>\n'
        '<key>CFBundleExecutable</key><string>riftdogs</string>\n'
        '<key>CFBundlePackageType</key><string>APPL</string>\n'
        '<key>CFBundleIconFile</key><string>Riftdogs</string>\n'
        '<key>NSHighResolutionCapable</key><true/>\n'
        '<key>LSMinimumSystemVersion</key><string>10.13</string>\n'
        '</dict></plist>\n', encoding='utf-8')
    def quote(value): return "'" + str(value).replace("'", "'\\''") + "'"
    game = quote(target/'riftdogs.py')
    private = app/'Resources'/'python'/'bin'/'python3'
    interpreter = app/'MacOS'/'Riftdogs'
    if private.exists():
        # The Dock names an app after the bundle holding the running binary, so run a copy of the
        # app's private (statically linked) Python from Contents/MacOS, pointed at its own library.
        shutil.copy2(private.resolve(), interpreter)
        script = ('#!/bin/sh\n'
                  'contents="$(cd "$(dirname "$0")/.." && pwd)"\n'
                  'export PYTHONHOME="$contents/Resources/python"\n'
                  'export SSL_CERT_FILE="$contents/Resources/cacert.pem"\n'
                  'export RIFTDOGS_FRAMEWORKS="$contents/Frameworks"\n'
                  f'[ -x "$contents/MacOS/Riftdogs" ] && exec "$contents/MacOS/Riftdogs" {game} "$@"\n'
                  f'exec "$PYTHONHOME/bin/python3" {game} "$@"\n')
    else:
        interpreter.unlink(missing_ok=True)
        script = f'#!/bin/sh\nexec {quote(sys.executable)} {game} "$@"\n'
    launcher = app/'MacOS'/'riftdogs'
    launcher.write_text(script, encoding='utf-8')
    launcher.chmod(0o755)
    icon = Path(__file__).resolve().parent/'assets'/'Riftdogs.icns'
    if icon.is_file():
        (app/'Resources').mkdir(exist_ok=True)
        shutil.copy2(icon, app/'Resources'/'Riftdogs.icns')
    print('Installed! Open Riftdogs from Launchpad, Spotlight, or ~/Applications.')
    print('Your saved game is preserved when reinstalling. When a new release is out, the start screen offers to install it.')


# Everything the installed game runs from. test_deploy checks every module the game imports is listed here.
GAME_FILES = ('riftdogs.py', 'startup.py', 'presence.py', 'market.py', 'economy.py', 'council.py', 'tally.py',
              'save_sync.py', 'seal.py', 'update.py', 'payments.py', 'comms.py', 'LICENSE', 'README.md', 'PRIVACY.md', 'TERMS.md')


def recorded_source(source):
    """Where updates come from: the checkout, or 'release' when installed from a release download (its folder is temporary)."""
    return 'release' if os.environ.get('RIFTDOGS_FROM_RELEASE') == '1' else str(source)


def install():
    source = Path(__file__).resolve().parent
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share').expanduser().resolve()
    target = data / 'riftdogs'
    target.mkdir(parents=True, exist_ok=True)
    for name in GAME_FILES:
        destination = target / name
        if (source / name).resolve() != destination.resolve():
            shutil.copy2(source / name, destination)
    assets = target/'assets'
    assets.mkdir(exist_ok=True)
    splash = source/'assets/riftdogs-splash.bmp.gz'
    if splash.resolve() != (assets/splash.name).resolve():
        shutil.copy2(splash,assets/splash.name)
    icon = source/'assets/riftdogs-icon.png'
    if icon.resolve() != (assets/icon.name).resolve():
        shutil.copy2(icon,assets/icon.name)
    from riftdogs import VERSION
    (target/'install-info.json').write_text(json.dumps(dict(source=recorded_source(source),version=VERSION)),encoding='utf-8')
    if sys.platform == 'darwin':
        install_mac_app(target)
        return
    apps = data / 'applications'
    apps.mkdir(parents=True, exist_ok=True)
    # Desktop Entry Exec quoting: escape reserved characters, and literal %.
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    launcher = apps / 'riftdogs.desktop'
    launcher.write_text('[Desktop Entry]\nType=Application\nName=Riftdogs\n'
                        'Comment=Trade, haul and fight across a living galaxy\n'
                        f'Exec={quote(sys.executable)} {quote(target / "riftdogs.py")}\n'
                        f'Icon={assets / icon.name}\nTerminal=false\nCategories=Game;Simulation;\n'
                        'StartupWMClass=riftdogs\n', encoding='utf-8')
    refresh = shutil.which('update-desktop-database')
    if refresh:
        subprocess.run([refresh, str(apps)], check=False)
    print('Installed! Open the Omarchy app launcher and search for Riftdogs.')
    print(f'Or run: python3 "{target / "riftdogs.py"}"')
    print('Your saved game is preserved when reinstalling.')
    print(f'For future updates: python3 "{target / "update.py"}"')


if __name__ == '__main__':
    install()
