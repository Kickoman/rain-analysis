#!/usr/bin/env python3
"""
fetch_yandex_archive.py — Download and extract Yandex Weather archive.
=======================================================================

Downloads the hourly Yandex Weather snapshot archive from the local server
and extracts it to a specified directory for use in rain analysis.

Usage:
  python fetch_yandex_archive.py --output data/yandex_archive/

Author: Karasik (AI assistant for Kickoman/rain-analysis)
"""

import argparse
import sys
import os
import tarfile
import shutil
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError


DEFAULT_URL = "http://10.8.0.4:7005/weather.tgz"


def download_archive(url: str, dest: str) -> str:
    """Download weather archive to a temporary file."""
    print(f"Downloading {url}...", end=" ", flush=True)
    try:
        local_file, _ = urlretrieve(url, dest)
        print("✓")
        return local_file
    except URLError as e:
        print(f"✗\n[ERROR] Failed to download: {e}", file=sys.stderr)
        sys.exit(1)


def extract_archive(archive_path: str, output_dir: str, strip_components: int = 2):
    """Extract weather archive, optionally stripping leading path components."""
    print(f"Extracting to {output_dir}...", end=" ", flush=True)
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            # Get all members
            members = tar.getmembers()
            
            # Strip leading path components if requested
            if strip_components > 0:
                for member in members:
                    parts = member.name.split("/")
                    if len(parts) > strip_components:
                        member.name = "/".join(parts[strip_components:])
                    else:
                        continue  # Skip this member
            
            # Extract
            tar.extractall(output_dir, members=members)
        
        print("✓")
        return len(members)
    except Exception as e:
        print(f"✗\n[ERROR] Failed to extract: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Download and extract Yandex Weather archive"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Archive URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory for extracted JSON snapshots",
    )
    parser.add_argument(
        "--keep-archive",
        action="store_true",
        help="Keep the downloaded .tgz file after extraction",
    )
    parser.add_argument(
        "--strip-components",
        type=int,
        default=2,
        help="Strip N leading path components from archive (default: 2)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress messages",
    )

    args = parser.parse_args()

    # Download
    temp_archive = "/tmp/yandex_weather.tgz"
    if not args.quiet:
        download_archive(args.url, temp_archive)
    else:
        try:
            urlretrieve(args.url, temp_archive)
        except URLError as e:
            print(f"[ERROR] Download failed: {e}", file=sys.stderr)
            return 1

    # Extract
    if not args.quiet:
        num_files = extract_archive(temp_archive, args.output, args.strip_components)
        print(f"\n✓ Extracted {num_files} files to {args.output}")
    else:
        extract_archive(temp_archive, args.output, args.strip_components)

    # Cleanup
    if not args.keep_archive and os.path.exists(temp_archive):
        os.remove(temp_archive)

    return 0


if __name__ == "__main__":
    sys.exit(main())
