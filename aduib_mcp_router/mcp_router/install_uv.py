#!/usr/bin/env python3
"""
UV binary installer for Cherry Studio
Converts the Node.js install-uv.js logic to Python
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

# Base URL for downloading uv binaries
UV_RELEASE_BASE_URL = 'https://gitcode.com/CherryHQ/uv/releases/download'
DEFAULT_UV_VERSION = '0.7.13'

# Mapping of platform+arch to binary package name
UV_PACKAGES = {
    'darwin-arm64': 'uv-aarch64-apple-darwin.zip',
    'darwin-x64': 'uv-x86_64-apple-darwin.zip',
    'win32-arm64': 'uv-aarch64-pc-windows-msvc.zip',
    'win32-ia32': 'uv-i686-pc-windows-msvc.zip',
    'win32-x64': 'uv-x86_64-pc-windows-msvc.zip',
    'linux-arm64': 'uv-aarch64-unknown-linux-gnu.zip',
    'linux-ia32': 'uv-i686-unknown-linux-gnu.zip',
    'linux-ppc64': 'uv-powerpc64-unknown-linux-gnu.zip',
    'linux-ppc64le': 'uv-powerpc64le-unknown-linux-gnu.zip',
    'linux-s390x': 'uv-s390x-unknown-linux-gnu.zip',
    'linux-x64': 'uv-x86_64-unknown-linux-gnu.zip',
    'linux-armv7l': 'uv-armv7-unknown-linux-gnueabihf.zip',
    # MUSL variants
    'linux-musl-arm64': 'uv-aarch64-unknown-linux-musl.zip',
    'linux-musl-ia32': 'uv-i686-unknown-linux-musl.zip',
    'linux-musl-x64': 'uv-x86_64-unknown-linux-musl.zip',
    'linux-musl-armv6l': 'uv-arm-unknown-linux-musleabihf.zip',
    'linux-musl-armv7l': 'uv-armv7-unknown-linux-musleabihf.zip'
}


def download_with_redirects(url: str, filename: str) -> None:
    """
    Download a file from URL with redirect support
    """
    try:
        print(f"Downloading from: {url}")
        request = Request(url, headers={
            'User-Agent': 'Cherry Studio UV Installer/1.0'
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


def download_uv_binary(platform_name: str, arch: str, version: str = DEFAULT_UV_VERSION, is_musl: bool = False) -> int:
    """
    Downloads and extracts the uv binary for the specified platform and architecture

    Args:
        platform_name: Platform to download for (e.g., 'darwin', 'win32', 'linux')
        arch: Architecture to download for (e.g., 'x64', 'arm64')
        version: Version of uv to download
        is_musl: Whether to use MUSL variant for Linux

    Returns:
        int: Exit code (0 for success, non-zero for error)
    """
    platform_key = f"{platform_name}-musl-{arch}" if is_musl else f"{platform_name}-{arch}"
    package_name = UV_PACKAGES.get(platform_key)

    if not package_name:
        print(f"Error: No binary available for {platform_key}", file=sys.stderr)
        return 101

    # Create output directory structure
    bin_dir = Path(os.path.join(config.ROUTER_HOME, "bin"))
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Download URL for the specific binary
    download_url = f"{UV_RELEASE_BASE_URL}/{version}/{package_name}"

    # Create temporary file for download
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
        temp_filename = temp_file.name

    try:
        print(f"Downloading uv {version} for {platform_key}...")
        print(f"URL: {download_url}")

        download_with_redirects(download_url, temp_filename)

        print(f"Extracting {package_name} to {bin_dir}...")

        with zipfile.ZipFile(temp_filename, 'r') as zip_file:
            # Extract files directly to binDir, flattening the directory structure
            for entry in zip_file.infolist():
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
                            print(f"Warning: Failed to set executable permissions on {filename}: {chmod_error}",
                                  file=sys.stderr)
                            return 102

                    print(f"Extracted {entry.filename} -> {output_path}")

        # Clean up temporary file
        os.unlink(temp_filename)
        print(f"Successfully installed uv {version} for {platform_name} in {bin_dir}")
        return 0

    except Exception as error:
        ret_code = 103

        print(f"Error installing uv for {platform_key}: {error}", file=sys.stderr)

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


def detect_platform_and_arch() -> tuple[str, str, bool]:
    """
    Detects current platform and architecture

    Returns:
        tuple: (platform, arch, is_musl)
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
    elif machine == 'armv7l':
        arch = 'armv7l'
    elif machine == 'armv6l':
        arch = 'armv6l'
    elif machine in ('ppc64', 'powerpc64'):
        arch = 'ppc64'
    elif machine == 'ppc64le':
        arch = 'ppc64le'
    elif machine == 's390x':
        arch = 's390x'
    else:
        # Default to x64 for unknown architectures
        arch = 'x64'
        print(f"Warning: Unknown architecture {machine}, defaulting to x64", file=sys.stderr)

    # Detect MUSL
    is_musl = platform_name == 'linux' and detect_is_musl()

    return platform_name, arch, is_musl


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


def install_uv() -> int:
    """
    Main function to install uv

    Returns:
        int: Exit code (0 for success, non-zero for error)
    """
    version = DEFAULT_UV_VERSION
    print(f"Using uv version: {version}")

    try:
        platform_name, arch, is_musl = detect_platform_and_arch()

        musl_str = ' (MUSL)' if is_musl else ''
        print(f"Installing uv {version} for {platform_name}-{arch}{musl_str}...")

        return download_uv_binary(platform_name, arch, version, is_musl)

    except Exception as error:
        print(f"Error during installation: {error}", file=sys.stderr)
        return 100


def run_install_uv():
    """Main entry point"""
    try:
        ret_code = install_uv()
        if ret_code == 0:
            print("Installation successful")
        else:
            print("Installation failed", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nInstallation cancelled by user", file=sys.stderr)
    except Exception as error:
        print(f"Installation failed: {error}", file=sys.stderr)
