#!/usr/bin/env python3
"""Install the pinned Android SDK under ignored work/, without touching hardware."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = "15859902"
SHA256 = "4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"
URL = f"https://dl.google.com/android/repository/commandlinetools-linux-{BUILD}_latest.zip"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Accept SDK licenses and install pinned SDK packages")
    args = parser.parse_args()
    sdk = ROOT / "work/android-sdk"
    manager = sdk / "cmdline-tools/19.0/bin/sdkmanager"
    if not manager.exists():
        downloads = ROOT / "work/android-downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        archive = downloads / f"commandlinetools-linux-{BUILD}_latest.zip"
        if not archive.exists():
            urllib.request.urlretrieve(URL, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise SystemExit("Android command-line tools checksum mismatch")
        target = sdk / "cmdline-tools/19.0"
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                path = Path(info.filename)
                if path.is_absolute() or ".." in path.parts or path.parts[0] != "cmdline-tools":
                    raise SystemExit("Unsafe SDK archive")
                relative = Path(*path.parts[1:])
                output = target / relative
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(bundle.read(info))
                    output.chmod(0o755 if relative.parts[0] == "bin" else 0o644)
    if args.install:
        subprocess.run([str(manager), f"--sdk_root={sdk}", "--licenses"], input="y\n" * 100, text=True, check=True)
        subprocess.run([str(manager), f"--sdk_root={sdk}", "platforms;android-37.0", "build-tools;36.0.0"], check=True)
    subprocess.run([str(manager), f"--sdk_root={sdk}", "--list_installed"], check=True)
    print(f"SDK: {sdk}")
    print(f"GRADLE_USER_HOME: {ROOT / 'work/android-gradle-cache'}")


if __name__ == "__main__":
    main()
