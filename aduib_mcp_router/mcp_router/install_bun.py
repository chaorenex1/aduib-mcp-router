#!/usr/bin/env python3
"""
Bun binary installer for Cherry Studio
Converts the Node.js install-bun.js logic to Python
"""

import os
import platform
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import urlopen, Request

from aduib_mcp_router.configs import config

# Base URL for downloading bun binaries
BUN_RELEASE_BASE_URL = 'https://gitcode.com/CherryHQ/bun/releases/download'
DEFAULT_BUN_VERSION = '1.2.17'  # Default fallback version

# Mapping of platform+arch to binary package name
BUN_PACKAGES = {
    'darwin-arm64': 'bun-darwin-aarch64.zip',
    'darwin-x64': 'bun-darwin-x64.zip',
    'win32-x64': 'bun-windows-x64.zip',
    'win32-x64-baseline': 'bun-windows-x64-baseline.zip',
    'win32-arm64': 'bun-windows-x64.zip',
    'win32-arm64-baseline': 'bun-windows-x64-baseline.zip',
    'linux-x64': 'bun-linux-x64.zip',
    'linux-x64-baseline': 'bun-linux-x64-baseline.zip',
    'linux-arm64': 'bun-linux-aarch64.zip',
    # MUSL variants
    'linux-musl-x64': 'bun-linux-x64-musl.zip',
    'linux-musl-x64-baseline': 'bun-linux-x64-musl-baseline.zip',
    'linux-musl-arm64': 'bun-linux-aarch64-musl.zip'
}


def download_with_redirects(url: str, filename: str) -> None:
    """
    Download a file from URL with redirect support
    """
    try:
        print(f"Downloading from: {url}")
        request = Request(url, headers={
            'User-Agent': 'Cherry Studio Bun Installer/1.0'
        })

        with urlopen(request) as response:
            if response.status != 200:
                raise HTTPError(url, response.status, f"HTTP {response.status}", response.headers, None)

            with open(filename, 'wb') as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)

        print(f"Downloaded to: {filename}")
    except (URLError, HTTPError) as e:
        raise Exception(f"Failed to download {url}: {e}")


def download_bun_binary(platform_name: str, arch: str, version: str = DEFAULT_BUN_VERSION,
                       is_musl: bool = False, is_baseline: bool = False) -> int:
    """
    Downloads and extracts the bun binary for the specified platform and architecture

    Args:
        platform_name: Platform to download for (e.g., 'darwin', 'win32', 'linux')
        arch: Architecture to download for (e.g., 'x64', 'arm64')
        version: Version of bun to download
        is_musl: Whether to use MUSL variant for Linux
        is_baseline: Whether to use baseline variant

    Returns:
        int: Exit code (0 for success, non-zero for error)
    """
    platform_key = f"{platform_name}-musl-{arch}" if is_musl else f"{platform_name}-{arch}"
    if is_baseline:
        platform_key += '-baseline'

    package_name = BUN_PACKAGES.get(platform_key)

    if not package_name:
        print(f"Error: No binary available for {platform_key}", file=sys.stderr)
        return 101

    # Create output directory structure
    bin_dir = Path(os.path.join(config.ROUTER_HOME, "bin"))
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Download URL for the specific binary
    download_url = f"{BUN_RELEASE_BASE_URL}/bun-v{version}/{package_name}"

    # Create temporary file for download
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
        temp_filename = temp_file.name

    try:
        print(f"Downloading bun {version} for {platform_key}...")
        print(f"URL: {download_url}")

        download_with_redirects(download_url, temp_filename)

        print(f"Extracting {package_name} to {bin_dir}...")

        with zipfile.ZipFile(temp_filename, 'r') as zip_file:
            # Get all entries in the zip file
            entries = zip_file.infolist()

            # Extract files directly to binDir, flattening the directory structure
            for entry in entries:
                if not entry.is_dir():
                    # Get just the filename without path
                    filename = os.path.basename(entry.filename)
                    output_path = bin_dir / filename

                    print(f"Extracting {entry.filename} -> {filename}")

                    # Extract file content
                    with zip_file.open(entry) as source:
                        with open(output_path, 'wb') as target:
                            target.write(source.read())

                    # Make executable files executable on Unix-like systems
                    if platform_name != 'win32':
                        try:
                            os.chmod(output_path, 0o755)
                        except OSError as chmod_error:
                            print(f"Warning: Failed to set executable permissions on {filename}", file=sys.stderr)
                            return 102

                    print(f"Extracted {entry.filename} -> {output_path}")

        # Clean up temporary file
        os.unlink(temp_filename)
        print(f"Successfully installed bun {version} for {platform_key} in {bin_dir}")
        return 0

    except Exception as error:
        ret_code = 103

        print(f"Error installing bun for {platform_key}: {error}", file=sys.stderr)

        # Clean up temporary file if it exists
        if os.path.exists(temp_filename):
            try:
                os.unlink(temp_filename)
            except OSError:
                pass

        # Check if binDir is empty and remove it if so
        try:
            if bin_dir.exists() and not any(bin_dir.iterdir()):
                bin_dir.rmdir()
                print(f"Removed empty directory: {bin_dir}")
        except OSError as cleanup_error:
            print(f"Warning: Failed to clean up directory: {cleanup_error}", file=sys.stderr)
            ret_code = 104

        return ret_code


def detect_platform_and_arch() -> tuple[str, str, bool, bool]:
    """
    Detects current platform and architecture

    Returns:
        tuple: (platform, arch, is_musl, is_baseline)
    """
    # Get platform
    system = platform.system().lower()
    if system == 'darwin':
        platform_name = 'darwin'
    elif system == 'windows':
        platform_name = 'win32'
    elif system == 'linux':
        platform_name = 'linux'
    else:
        raise Exception(f"Unsupported platform: {system}")

    # Get architecture
    machine = platform.machine().lower()
    if machine in ('x86_64', 'amd64'):
        arch = 'x64'
    elif machine in ('arm64', 'aarch64'):
        arch = 'arm64'
    elif machine in ('i386', 'i686'):
        arch = 'ia32'
    else:
        # Default to x64 for unknown architectures
        arch = 'x64'
        print(f"Warning: Unknown architecture {machine}, defaulting to x64", file=sys.stderr)

    # Detect MUSL and baseline
    is_musl = platform_name == 'linux' and detect_is_musl()
    is_baseline = platform_name == 'win32'  # Windows uses baseline by default

    return platform_name, arch, is_musl, is_baseline


def detect_is_musl() -> bool:
    """
    Attempts to detect if running on MUSL libc

    Returns:
        bool: True if MUSL is detected, False otherwise
    """
    try:
        # Simple check for Alpine Linux which uses MUSL
        with open('/etc/os-release', 'r') as f:
            content = f.read().lower()
            return 'alpine' in content
    except (FileNotFoundError, OSError):
        return False


def install_bun() -> int:
    """
    Main function to install bun

    Returns:
        int: Exit code (0 for success, non-zero for error)
    """
    version = DEFAULT_BUN_VERSION
    print(f"Using bun version: {version}")

    try:
        platform_name, arch, is_musl, is_baseline = detect_platform_and_arch()

        musl_str = ' (MUSL)' if is_musl else ''
        baseline_str = ' (baseline)' if is_baseline else ''
        print(f"Installing bun {version} for {platform_name}-{arch}{musl_str}{baseline_str}...")

        return download_bun_binary(platform_name, arch, version, is_musl, is_baseline)

    except Exception as error:
        print(f"Error during installation: {error}", file=sys.stderr)
        return 100


def run_install_bun():
    """Main entry point"""
    try:
        ret_code = install_bun()
        if ret_code == 0:
            print("Installation successful")
        else:
            print("Installation failed", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nInstallation cancelled by user", file=sys.stderr)
    except Exception as error:
        print(f"Installation failed: {error}", file=sys.stderr)
