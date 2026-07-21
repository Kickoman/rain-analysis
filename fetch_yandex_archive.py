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
import tempfile
from pathlib import Path
from urllib.error import URLError

try:
    import requests
except ImportError:
    print("[ERROR] requests library not found. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


DEFAULT_URL = "http://10.8.0.4:7005/weather.tgz"
DOWNLOAD_TIMEOUT = 30  # seconds


def download_archive(url: str, dest: str) -> str:
    """Download weather archive to a temporary file with timeout."""
    print(f"Downloading {url}...", end=" ", flush=True)
    try:
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)
        response.raise_for_status()
        
        with open(dest, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print("✓")
        return dest
    except requests.exceptions.Timeout:
        print(f"✗\n[ERROR] Download timed out after {DOWNLOAD_TIMEOUT}s", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"✗\n[ERROR] Failed to download: {e}", file=sys.stderr)
        sys.exit(1)


def extract_archive(archive_path: str, output_dir: str, strip_components: int = 2):
    """Extract weather archive, optionally stripping leading path components."""
    print(f"Extracting to {output_dir}...", end=" ", flush=True)
    
    # Clean output directory before extraction
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            # Get all members
            members = tar.getmembers()
            
            # Strip leading path components if requested
            if strip_components > 0:
                filtered_members = []
                for member in members:
                    parts = member.name.split("/")
                    if len(parts) > strip_components:
                        member.name = "/".join(parts[strip_components:])
                        filtered_members.append(member)
                    # Members without enough depth are now excluded from extraction
                members = filtered_members
            
            # Extract with security filter (Python 3.12+)
            # 'data' filter rejects absolute paths, '..' components, symlinks, and device files
            tar.extractall(output_dir, members=members, filter="data")
        
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
        help="Suppress progress output (errors still printed)",
    )

    args = parser.parse_args()

    # Use secure temp file instead of predictable /tmp/weather.tgz
    temp_archive = tempfile.NamedTemporaryFile(delete=False, suffix=".tgz")
    temp_archive_path = temp_archive.name
    temp_archive.close()

    try:
        # Download
        download_archive(args.url, temp_archive_path)
        
        # Extract
        extracted_count = extract_archive(
            temp_archive_path,
            args.output,
            strip_components=args.strip_components,
        )
        
        if not args.quiet:
            print(f"[SUCCESS] Extracted {extracted_count} files to {args.output}")
        
        # Clean up archive unless --keep-archive
        if not args.keep_archive:
            os.unlink(temp_archive_path)
    except Exception:
        # Clean up on error
        if os.path.exists(temp_archive_path):
            os.unlink(temp_archive_path)
        raise


if __name__ == "__main__":
    main()
