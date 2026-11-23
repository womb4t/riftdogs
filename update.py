#!/usr/bin/env python3
"""Update Riftdogs to the latest release without touching the saved game.

Installs made from a Git checkout update that checkout to the newest signed release tag; others download
the release archive and check it against MANIFEST.sha256, signed with the Riftdogs release key."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

OFFICIAL = 'https://github.com/womb4t/riftdogs'
REPOS = ('womb4t/riftdogs',)
# GitHub names a release archive's top folder after the repository: riftdogs-X.
ARCHIVE_PREFIXES = ('riftdogs-',)
# A git checkout installs updates only from the public repository.
OFFICIAL_REMOTES = {form.format(name) for name in ('riftdogs',)
                    for form in ('https://github.com/womb4t/{}', 'git@github.com:womb4t/{}')}

# The Riftdogs release key, in ssh allowed-signers format. Only releases signed with it install.
NAMESPACE = 'riftdogs-release'
PLACEHOLDER_SIGNERS = 'riftdogs-release ssh-ed25519 REPLACE_WITH_THE_RELEASE_KEY'
RELEASE_SIGNERS = 'riftdogs-release ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFE/vQKgQKZwFQ2jOA6i/VZlae8XZTFmuzcCgGDf1UQG'   # the Riftdogs release key (public half)
MANIFEST = 'MANIFEST.sha256'
UNSIGNED = "This update isn't signed by Riftdogs. Nothing was installed."
NO_KEY = 'This build has no release key yet. Nothing was installed.'
NOT_NEWER = 'This update is not newer than your game. Nothing was installed.'
MISMATCH = "This update's version doesn't match its signature. Nothing was installed."
UNKNOWN_VERSION = "Can't read this game's version. Nothing was installed."
HEADER = '# riftdogs-release '   # first manifest line: the signed release version
SSH_SIGNATURE = b'-----BEGIN SSH SIGNATURE-----\n'
DOWNLOAD_LIMIT = 64*1024*1024
VERSION_LINE = re.compile(r"^VERSION = '([0-9]+(?:\.[0-9]+)*)'$", re.M)   # ASCII digits only (\d takes any script's)
NO_SSH_KEYGEN = "ssh-keygen (part of OpenSSH) wasn't found, so this update can't be checked. Nothing was installed."


def output(repo, *args):
    return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()


def is_checkout(path):
    """A .git name alone is insufficient (it can be an empty placeholder)."""
    try:
        result = subprocess.run(['git','-C',str(path),'rev-parse','--show-toplevel'],
                                capture_output=True,text=True,check=False)
        return result.returncode == 0 and Path(result.stdout.strip()).resolve() == path.resolve()
    except OSError:
        return False


def resolve_checkout(here):
    if is_checkout(here): return here
    metadata = here/'install-info.json'
    if metadata.is_file():
        data = json.loads(metadata.read_text())
        source = data.get('source')
        if not isinstance(source,str) or not source.strip(): raise ValueError('Invalid source checkout in install-info.json.')
        if source == 'release': raise ValueError('Installed from a release download.')
        repo = Path(source).expanduser().resolve()
        if is_checkout(repo): return repo
        raise ValueError(f'The recorded source checkout is not a valid Git repository: {repo}')
    raise ValueError('No valid checkout or installation metadata found. Run the installer from the official checkout.')


def installer_name():
    return 'install-mac.sh' if sys.platform == 'darwin' else 'install.sh'


def official_remote(url):
    url = url.rstrip('/')
    return url.removesuffix('.git') in OFFICIAL_REMOTES


def require_release_key():
    if RELEASE_SIGNERS == PLACEHOLDER_SIGNERS or 'REPLACE_WITH' in RELEASE_SIGNERS: raise ValueError(NO_KEY)


def signers_file(folder):
    path = Path(folder)/'allowed_signers'
    path.write_text(RELEASE_SIGNERS.strip()+'\n')
    return path


def safe_path(path):
    """A manifest path: relative, POSIX, no '..', '.', empty parts or backslashes."""
    parts = path.split('/')
    return bool(path) and not path.startswith('/') and '\\' not in path and all(part not in ('', '.', '..') for part in parts)


def tree_files(root):
    """Every file under root as {posix relative path: Path}, skipping only the top-level .git. Refuses links and odd files."""
    root, found = Path(root), {}
    def walk(folder, prefix):
        with os.scandir(folder) as entries: entries = list(entries)
        for entry in entries:
            rel = prefix+entry.name
            if rel == '.git': continue
            if entry.is_symlink(): raise ValueError(f'Links are not allowed in a release: {rel}')
            if entry.is_dir(follow_symlinks=False): walk(entry.path, rel+'/')
            elif entry.is_file(follow_symlinks=False): found[rel] = Path(entry.path)
            else: raise ValueError(f'Unexpected file in release: {rel}')
    walk(root, '')
    return found


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''): digest.update(block)
    return digest.hexdigest()


def tree_version(root):
    """VERSION from a tree's riftdogs.py, read as text (never imported or run); None when absent."""
    try: text = (Path(root)/'riftdogs.py').read_text(encoding='utf-8')
    except (OSError,UnicodeDecodeError): return None
    found = VERSION_LINE.search(text)
    return found.group(1) if found else None


def version_key(version):
    return tuple(int(part) for part in version.split('.'))


def running_version():
    return tree_version(Path(__file__).resolve().parent)


def build_manifest(root):
    """MANIFEST.sha256 for a release tree: a `# riftdogs-release <version>` line, then sorted `sha256  relative/path` lines."""
    files = tree_files(root)
    version = tree_version(root)
    if not version: raise ValueError(f'No VERSION line found in {Path(root)/"riftdogs.py"}')
    return (HEADER+version+'\n'+''.join(f'{sha256(files[rel])}  {rel}\n' for rel in sorted(files))).encode()


def manifest_version(manifest):
    first = manifest.split(b'\n',1)[0].decode('utf-8','replace')
    version = first.removeprefix(HEADER)
    if not first.startswith(HEADER) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*',version): raise ValueError(UNSIGNED)
    return version


def parse_manifest(manifest):
    files = {}
    manifest_version(manifest)
    try: text = manifest.decode('utf-8')
    except UnicodeDecodeError: raise ValueError(UNSIGNED) from None
    for line in text.splitlines()[1:]:
        digest, sep, path = line.partition('  ')
        if not sep or len(digest) != 64 or digest.strip('0123456789abcdef') or not safe_path(path) or path in files:
            raise ValueError(UNSIGNED)
        files[path] = digest
    if not files: raise ValueError(UNSIGNED)
    return files


def ssh_verify(data, signature, namespace):
    """ssh-keygen -Y verify against RELEASE_SIGNERS as principal riftdogs-release; raises unless it succeeds."""
    require_release_key()
    if not shutil.which('ssh-keygen'): raise ValueError(NO_SSH_KEYGEN)
    with tempfile.TemporaryDirectory(prefix='riftdogs-verify-') as folder:
        sig = Path(folder)/'signature.sig'
        sig.write_bytes(signature)
        try:
            result = subprocess.run(['ssh-keygen','-Y','verify','-f',str(signers_file(folder)),'-I',NAMESPACE,'-n',namespace,'-s',str(sig)],
                                    input=data,capture_output=True,timeout=60,check=False)
        except FileNotFoundError: raise ValueError(NO_SSH_KEYGEN) from None
        except (OSError,subprocess.TimeoutExpired): raise ValueError(UNSIGNED) from None
    if result.returncode != 0: raise ValueError(UNSIGNED)


def verify_manifest(manifest, signature):
    """Check the release key signed this manifest; returns {path: sha256}."""
    ssh_verify(manifest,signature,NAMESPACE)
    return parse_manifest(manifest)


def check_tree(root, manifest):
    """Every file in the tree (except .git) must be in the signed manifest with the same hash, and nothing missing."""
    try: files = tree_files(root)
    except (OSError,ValueError): raise ValueError(UNSIGNED) from None
    if set(files) != set(manifest): raise ValueError(UNSIGNED)
    for rel, path in files.items():
        if sha256(path) != manifest[rel]: raise ValueError(UNSIGNED)


def verify_tag(repo, tag):
    """Check the release key signed this tag and return the commit it names.

    git verify-tag's exit code is not trusted: git picks the verifier from the signature block, so a PGP
    signature from any key in the player's gpg keyring would pass. Only an SSH signature is accepted, checked
    here with ssh-keygen over exactly the signed part of the tag object."""
    require_release_key()
    try: raw = subprocess.check_output(['git','-C',str(repo),'cat-file','tag',f'refs/tags/{tag}'],stderr=subprocess.DEVNULL,timeout=60)
    except subprocess.CalledProcessError: raise ValueError(UNSIGNED) from None   # e.g. a lightweight tag: nothing signed
    start = raw.find(SSH_SIGNATURE)
    if start < 0 or raw.count(b'-----BEGIN ') != 1 or not raw.endswith(b'-----END SSH SIGNATURE-----\n'): raise ValueError(UNSIGNED)
    payload, signature = raw[:start], raw[start:]
    header = payload.split(b'\n\n',1)[0].decode('utf-8','replace').splitlines()
    if len(header) < 3 or not header[0].startswith('object ') or header[1] != 'type commit' or header[2] != f'tag {tag}':
        raise ValueError(UNSIGNED)
    commit = header[0].removeprefix('object ')
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',commit): raise ValueError(UNSIGNED)
    ssh_verify(payload,signature,'git')
    return commit


def latest_tag(repo):
    tags = output(repo,'tag','--list','v*','--merged','origin/main','--sort=-v:refname').splitlines()
    if not tags: raise ValueError('No release tag found on the official main branch. Nothing was installed.')
    return tags[0]


def fetch(url):
    req = urllib.request.Request(url,headers={'User-Agent':'Riftdogs-updater','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=30) as response: data = response.read(DOWNLOAD_LIMIT+1)
    if len(data) > DOWNLOAD_LIMIT: raise ValueError(f'Download too large: {url}. Nothing was installed.')
    return data


def latest_release():
    """(github.com repository URL, tag) of the latest release."""
    for repo in REPOS:
        try: data = fetch(f'https://api.github.com/repos/{repo}/releases/latest')
        except urllib.error.HTTPError as error:
            if error.code == 404: continue
            raise
        tag = json.loads(data).get('tag_name')
        if not isinstance(tag,str) or not tag.startswith('v') or '/' in tag: break
        return f'https://github.com/{repo}', tag
    raise ValueError('Could not find the latest release.')


def extract_release(archive, dest):
    """Unpack a release archive into dest and return its one top folder (riftdogs-X)."""
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            name = Path(member.name)
            if name.is_absolute() or '..' in name.parts or member.issym() or member.islnk() or member.isdev():
                raise ValueError(f'Unexpected file in release archive: {member.name}')
        tar.extractall(dest,filter='data')
    folders = list(Path(dest).iterdir())
    if len(folders) != 1 or not folders[0].is_dir() or not folders[0].name.startswith(ARCHIVE_PREFIXES):
        raise ValueError('The release archive does not hold a Riftdogs release. Nothing was installed.')
    if os.path.lexists(folders[0]/'.git'): raise ValueError(UNSIGNED)   # check_tree skips .git, so a release may not carry one
    return folders[0]


def check_release(source, files, version):
    """The extracted tree matches the signed manifest, and its riftdogs.py VERSION is the signed version."""
    check_tree(source,files)
    if tree_version(source) != version: raise ValueError(MISMATCH)


def release_update(dry_run):
    require_release_key()
    current = running_version()
    # Without the running version the downgrade check can't run: an older signed release could replay. Fail closed.
    if current is None: raise ValueError(UNKNOWN_VERSION)
    base, tag = latest_release()
    print(f'Updating to release {tag}. Saved progress will be preserved.',flush=True)
    if dry_run:
        print(f'Dry run: would download {tag}, check its signature and rerun {installer_name()}.')
        return
    work = Path(tempfile.mkdtemp(prefix='riftdogs-update-'))
    try:
        try:
            manifest = fetch(f'{base}/releases/download/{tag}/{MANIFEST}')
            signature = fetch(f'{base}/releases/download/{tag}/{MANIFEST}.sig')
        except OSError: raise ValueError(UNSIGNED) from None
        files = verify_manifest(manifest,signature)
        version = manifest_version(manifest)
        if tag != f'v{version}': raise ValueError(MISMATCH)
        if version_key(version) <= version_key(current): raise ValueError(NOT_NEWER)
        archive = work/'release.tar.gz'
        archive.write_bytes(fetch(f'{base}/archive/refs/tags/{tag}.tar.gz'))
        tree = work/'tree'
        tree.mkdir()
        source = extract_release(archive,tree)
        check_release(source,files,version)
        subprocess.run(['bash',str(source/installer_name())],check=True,cwd=source,env={**os.environ,'RIFTDOGS_FROM_RELEASE':'1'})
    finally:
        shutil.rmtree(work,ignore_errors=True)
    print('Update complete. Restart Riftdogs to use the new version.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true',help='validate and show the update without changing files')
    parser.add_argument('--unsigned',action='store_true',help='Git checkouts only: pull main without checking a signed release tag')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    try:
        try: repo = resolve_checkout(here)
        except ValueError:
            if args.unsigned: raise ValueError('--unsigned only works in a Git checkout. Nothing was installed.') from None
            return release_update(args.dry_run)
        if not official_remote(output(repo,'remote','get-url','origin')):
            raise ValueError('This updater only fetches the official womb4t/riftdogs repository.')
        if output(repo,'branch','--show-current') != 'main':
            raise ValueError('Switch to main before updating. Your current branch has been left unchanged.')
        if output(repo,'status','--porcelain'):
            raise ValueError('Local edits or untracked files found. Commit or back up your changes before updating.')
        if not args.unsigned: require_release_key()
        print(f'Updating official checkout: {repo}',flush=True)
        print('Saved progress will be preserved. Dependency installation may ask for your password.',flush=True)
        if args.unsigned:
            print('Warning: --unsigned skips the release signature check and installs whatever is on main.',file=sys.stderr,flush=True)
        if args.dry_run:
            what = 'origin/main' if args.unsigned else 'the newest signed release tag'
            print(f'Dry run: would fetch origin, merge {what} --ff-only, then rerun the installer.')
            return
        if args.unsigned:
            subprocess.run(['git','-C',str(repo),'fetch','origin','main'],check=True,timeout=300)
            target = 'origin/main'
        else:
            subprocess.run(['git','-C',str(repo),'fetch','--tags','origin','main'],check=True,timeout=300)
            tag = latest_tag(repo)
            target = verify_tag(repo,tag)
            print(f'Release {tag} is signed by Riftdogs.',flush=True)
        subprocess.run(['git','-C',str(repo),'merge','--ff-only',target],check=True,timeout=120)
        subprocess.run(['bash',str(repo/installer_name())],check=True,cwd=repo)
        print('Update complete. Restart Riftdogs to use the new version.')
    except (OSError,ValueError,KeyError,StopIteration,tarfile.TarError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
        print(f'Update stopped: {error}',file=sys.stderr)
        print('You can reinstall at any time; saved progress is kept. See README.md for the install command.',file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
