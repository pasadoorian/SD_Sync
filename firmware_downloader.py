#!/usr/bin/env python3

import argparse
import fnmatch
import json
import os
import re
import requests
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import tomllib
except ImportError:
    import tomli as tomllib


class FirmwareDownloader:
    def __init__(self, config_file="firmware.toml", verbose=True):
        self.config_file = config_file
        self.verbose = verbose
        self.api_url = "https://raw.githubusercontent.com/bmorcelli/M5Stack-json-fw/main/script/all_device_firmware.json"
        self.firmware_base_url = "https://m5burner-cdn.m5stack.com/firmware/"
        self.firmware_data = None
        self.config = self.load_config()
    
    def load_config(self):
        """Load firmware configuration from TOML file."""
        try:
            with open(self.config_file, 'rb') as f:
                return tomllib.load(f)
        except FileNotFoundError:
            print(f"Error: {self.config_file} not found")
            sys.exit(1)
        except Exception as e:
            print(f"Error loading configuration: {e}")
            sys.exit(1)
    
    def fetch_firmware_data(self):
        """Fetch firmware data from the API."""
        if self.firmware_data is not None:
            return self.firmware_data
        
        try:
            if self.verbose:
                print("Fetching firmware data from API...")
            
            response = requests.get(self.api_url, timeout=30)
            response.raise_for_status()
            self.firmware_data = response.json()
            
            if self.verbose:
                print(f"✓ Found {len(self.firmware_data)} firmware entries")
            
            return self.firmware_data
        except requests.RequestException as e:
            print(f"Error fetching firmware data: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error parsing firmware data: {e}")
            sys.exit(1)
    
    def get_available_devices(self):
        """Get list of available devices from firmware data."""
        data = self.fetch_firmware_data()
        devices = set()
        
        for firmware in data:
            category = firmware.get('category', '')
            if category:
                devices.add(category.lower())
        
        return sorted(devices)
    
    def get_firmware_for_device(self, device):
        """Get all firmware available for a specific device."""
        data = self.fetch_firmware_data()
        device_firmware = []
        
        for firmware in data:
            category = firmware.get('category', '').lower()
            if category == device.lower():
                device_firmware.append(firmware)
        
        return device_firmware
    
    def find_firmware_by_name(self, device, name):
        """Find specific firmware by device and name."""
        device_firmware = self.get_firmware_for_device(device)
        
        for firmware in device_firmware:
            fw_name = firmware.get('name', '').lower()
            if name.lower() in fw_name or fw_name in name.lower():
                return firmware
        
        return None
    
    def resolve_version(self, firmware, requested_version):
        """Resolve version (latest, stable, all, or specific) to actual version data."""
        versions = firmware.get('versions', [])
        if not versions:
            return None
        
        if requested_version == "latest":
            return versions[0]  # First version is typically latest
        elif requested_version == "stable":
            # Look for stable version, fallback to latest
            for version in versions:
                version_str = version.get('version', '').lower()
                if 'stable' in version_str or not any(x in version_str for x in ['beta', 'alpha', 'rc', 'dev']):
                    return version
            return versions[0]  # Fallback to latest
        elif requested_version == "all":
            return versions  # Return all versions
        else:
            # Look for specific version
            for version in versions:
                if requested_version in version.get('version', ''):
                    return version
            return None
    
    def clean_filename(self, name, version, device):
        """Create a clean filename for the firmware."""
        # Clean name (remove special characters)
        clean_name = re.sub(r'[^\w\-_]', '', name.replace(' ', '_'))
        
        # Clean version (remove 'v' prefix if present)
        clean_version = version.replace('v', '').replace('V', '')
        clean_version = re.sub(r'[^\w\-_\.]', '', clean_version)
        
        # Clean device name
        clean_device = re.sub(r'[^\w\-_]', '', device.replace(' ', '_'))
        
        return f"{clean_device}_{clean_name}_{clean_version}.bin"
    
    def download_single_version(self, firmware, version_data, device, device_key, settings):
        """Download a single version of firmware."""
        name = firmware['name']
        download_file = version_data.get('file', '')
        actual_version = version_data.get('version', 'unknown')
        
        if not download_file:
            if self.verbose:
                print(f"✗ No download file specified for {name} {actual_version}")
            return False
        
        # Create device directory
        base_dir = settings.get('output_base_dir', 'firmware')
        target_dir = Path(base_dir) / device_key
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Create filename
        filename = self.clean_filename(name, actual_version, device)
        target_file = target_dir / filename
        
        # Check if file exists
        if target_file.exists() and not settings.get('overwrite_existing', False):
            if self.verbose:
                print(f"✓ File already exists: {target_file}")
            return True
        
        # Download
        download_url = self.firmware_base_url + download_file
        
        try:
            if self.verbose:
                print(f"Downloading {name} {actual_version}...")
                print(f"  URL: {download_url}")
                print(f"  Target: {target_file}")
            
            timeout = settings.get('download_timeout', 300)
            response = requests.get(download_url, timeout=timeout, stream=True)
            response.raise_for_status()
            
            with open(target_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            if self.verbose:
                file_size = target_file.stat().st_size
                print(f"✓ Downloaded {filename} ({file_size:,} bytes)")
            
            return True
            
        except requests.RequestException as e:
            if self.verbose:
                print(f"✗ Download failed: {e}")
            if target_file.exists():
                target_file.unlink()  # Clean up partial download
            return False
        except Exception as e:
            if self.verbose:
                print(f"✗ Error saving file: {e}")
            if target_file.exists():
                target_file.unlink()  # Clean up partial download
            return False

    def download_firmware(self, firmware_config):
        """Download firmware based on configuration."""
        device = firmware_config['device']
        name = firmware_config['name']
        version = firmware_config.get('version', 'latest')
        device_key = firmware_config['device_key']
        
        if self.verbose:
            print(f"\nProcessing: {name} for {device}")
        
        # Find firmware
        firmware = self.find_firmware_by_name(device, name)
        if not firmware:
            print(f"✗ Firmware '{name}' not found for device '{device}'")
            return False
        
        # Resolve version
        version_data = self.resolve_version(firmware, version)
        if not version_data:
            print(f"✗ Version '{version}' not found for firmware '{name}'")
            return False
        
        settings = self.config.get('settings', {})
        
        # Handle "all" versions
        if version == "all" and isinstance(version_data, list):
            if self.verbose:
                print(f"Downloading all {len(version_data)} versions of {name}...")
            
            success_count = 0
            for version_item in version_data:
                if self.download_single_version(firmware, version_item, device, device_key, settings):
                    success_count += 1
            
            if self.verbose:
                print(f"✓ Downloaded {success_count}/{len(version_data)} versions of {name}")
            
            return success_count > 0
        else:
            # Handle single version (latest, stable, specific)
            return self.download_single_version(firmware, version_data, device, device_key, settings)
    
    def list_devices(self):
        """List all available devices."""
        devices = self.get_available_devices()
        print("Available devices:")
        for device in devices:
            print(f"  {device}")
    
    def list_firmware(self, device):
        """List all firmware for a specific device."""
        firmware_list = self.get_firmware_for_device(device)
        if not firmware_list:
            print(f"No firmware found for device: {device}")
            return
        
        print(f"Available firmware for {device}:")
        for firmware in firmware_list:
            name = firmware.get('name', 'Unknown')
            author = firmware.get('author', 'Unknown')
            versions = firmware.get('versions', [])
            version_count = len(versions)
            latest_version = versions[0].get('version', 'Unknown') if versions else 'None'
            print(f"  {name} by {author} ({version_count} versions, latest: {latest_version})")
    
    def get_firmware_configs(self):
        """Extract firmware configurations from device-organized config."""
        firmware_configs = []
        devices = self.config.get('devices', {})
        
        for device_key, device_config in devices.items():
            device_name = device_config.get('device_name', device_key)
            firmware_list = device_config.get('firmware', [])
            
            for firmware in firmware_list:
                config = {
                    'device': device_name,
                    'name': firmware['name'],
                    'version': firmware.get('version', 'latest'),
                    'device_key': device_key  # Use device key for directory
                }
                firmware_configs.append(config)
        
        return firmware_configs
    
    def download_all(self):
        """Download all firmware defined in configuration."""
        firmware_configs = self.get_firmware_configs()
        if not firmware_configs:
            print("No firmware configurations found")
            return [], []
        
        successful = []
        failed = []
        
        for firmware_config in firmware_configs:
            name = firmware_config['name']
            device = firmware_config['device']
            if self.download_firmware(firmware_config):
                successful.append(f"{name} ({device})")
            else:
                failed.append(f"{name} ({device})")
        
        if self.verbose:
            print(f"\nM5Stack firmware summary:")
            print(f"Successful: {len(successful)}")
            print(f"Failed: {len(failed)}")
            print(f"Total: {len(successful) + len(failed)}")
        
        return successful, failed
    
    def parse_github_releases_url(self, releases_url):
        """Parse GitHub releases URL to get API endpoint."""
        # Convert https://github.com/owner/repo/releases/ to API format
        if 'github.com' not in releases_url:
            return None
        
        # Extract owner and repo from URL
        parts = releases_url.rstrip('/').split('/')
        if len(parts) < 5:
            return None
        
        try:
            owner = parts[-3]
            repo = parts[-2]
            return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        except IndexError:
            return None
    
    def download_github_release_assets(self, github_config):
        """Download .bin files from GitHub releases."""
        name = github_config['name']
        releases_url = github_config['releases_url']
        file_pattern = github_config.get('file_pattern', '*.bin')
        
        if self.verbose:
            print(f"\nProcessing GitHub release: {name}")
        
        # Parse GitHub URL to API endpoint
        api_url = self.parse_github_releases_url(releases_url)
        if not api_url:
            print(f"✗ Invalid GitHub releases URL: {releases_url}")
            return False
        
        try:
            # Get latest release info from GitHub API
            if self.verbose:
                print(f"Fetching latest release info from GitHub...")
            
            headers = {'Accept': 'application/vnd.github.v3+json'}
            response = requests.get(api_url, headers=headers, timeout=30)
            response.raise_for_status()
            release_data = response.json()
            
            release_name = release_data.get('name', release_data.get('tag_name', 'unknown'))
            assets = release_data.get('assets', [])
            
            if not assets:
                print(f"✗ No assets found in latest release of {name}")
                return False
            
            # Filter assets by file pattern
            matching_assets = []
            for asset in assets:
                asset_name = asset.get('name', '')
                if fnmatch.fnmatch(asset_name, file_pattern):
                    matching_assets.append(asset)
            
            if not matching_assets:
                print(f"✗ No assets matching pattern '{file_pattern}' found in {name}")
                return False
            
            if self.verbose:
                print(f"Found {len(matching_assets)} matching assets in release {release_name}")
            
            # Create directory for this firmware distribution
            settings = self.config.get('settings', {})
            base_dir = settings.get('output_base_dir', 'firmware')
            target_dir = Path(base_dir) / name
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # Download each matching asset
            success_count = 0
            for asset in matching_assets:
                asset_name = asset.get('name', '')
                download_url = asset.get('browser_download_url', '')
                
                if not download_url:
                    if self.verbose:
                        print(f"✗ No download URL for asset: {asset_name}")
                    continue
                
                target_file = target_dir / asset_name
                
                # Check if file exists
                if target_file.exists() and not settings.get('overwrite_existing', False):
                    if self.verbose:
                        print(f"✓ File already exists: {asset_name}")
                    success_count += 1
                    continue
                
                try:
                    if self.verbose:
                        print(f"Downloading {asset_name}...")
                        print(f"  URL: {download_url}")
                        print(f"  Target: {target_file}")
                    
                    timeout = settings.get('download_timeout', 300)
                    response = requests.get(download_url, timeout=timeout, stream=True)
                    response.raise_for_status()
                    
                    with open(target_file, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    if self.verbose:
                        file_size = target_file.stat().st_size
                        print(f"✓ Downloaded {asset_name} ({file_size:,} bytes)")
                    
                    success_count += 1
                    
                except requests.RequestException as e:
                    if self.verbose:
                        print(f"✗ Download failed for {asset_name}: {e}")
                    if target_file.exists():
                        target_file.unlink()  # Clean up partial download
                except Exception as e:
                    if self.verbose:
                        print(f"✗ Error downloading {asset_name}: {e}")
                    if target_file.exists():
                        target_file.unlink()  # Clean up partial download
            
            if self.verbose:
                print(f"✓ Downloaded {success_count}/{len(matching_assets)} assets for {name}")
            
            return success_count > 0
            
        except requests.RequestException as e:
            print(f"✗ Failed to fetch GitHub release info: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"✗ Failed to parse GitHub API response: {e}")
            return False
        except Exception as e:
            print(f"✗ Unexpected error processing GitHub release: {e}")
            return False
    
    def download_all_github_releases(self):
        """Download all GitHub releases defined in configuration."""
        github_configs = self.config.get('github_releases', [])
        if not github_configs:
            if self.verbose:
                print("No GitHub releases configurations found")
            return [], []
        
        successful = []
        failed = []
        
        for github_config in github_configs:
            name = github_config['name']
            if self.download_github_release_assets(github_config):
                successful.append(name)
            else:
                failed.append(name)
        
        if self.verbose:
            print(f"\nGitHub releases summary:")
            print(f"Successful: {len(successful)}")
            print(f"Failed: {len(failed)}")
            print(f"Total: {len(successful) + len(failed)}")
        
        return successful, failed


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download ESP32 firmware from M5Stack repository",
        epilog="Examples:\n"
               "  %(prog)s                           # Download all configured firmware\n"
               "  %(prog)s --list-devices            # List available devices\n"
               "  %(prog)s --list-firmware cardputer # List firmware for cardputer\n"
               "  %(prog)s --device cardputer        # Download only cardputer firmware\n"
               "  %(prog)s --config my-firmware.toml # Use custom config\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--config', '-c',
        default='firmware.toml',
        help='Configuration file to use (default: firmware.toml)'
    )
    
    parser.add_argument(
        '--list-devices',
        action='store_true',
        help='List all available devices and exit'
    )
    
    parser.add_argument(
        '--list-firmware',
        metavar='DEVICE',
        help='List all firmware for the specified device and exit'
    )
    
    parser.add_argument(
        '--device',
        help='Download firmware only for the specified device'
    )
    
    parser.add_argument(
        '--firmware',
        help='Download only the specified firmware name (requires --device)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be downloaded without actually downloading'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite existing files'
    )
    
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress verbose output'
    )
    
    parser.add_argument(
        '--github-only',
        action='store_true',
        help='Download only GitHub releases (skip M5Stack firmware)'
    )
    
    parser.add_argument(
        '--skip-github',
        action='store_true',
        help='Skip GitHub releases (download only M5Stack firmware)'
    )
    
    return parser.parse_args()


def main():
    """Main function."""
    args = parse_args()
    
    verbose = not args.quiet
    downloader = FirmwareDownloader(args.config, verbose)
    
    # Override settings with command line args
    if args.force:
        downloader.config.setdefault('settings', {})['overwrite_existing'] = True
    
    # Handle list operations
    if args.list_devices:
        downloader.list_devices()
        return
    
    if args.list_firmware:
        downloader.list_firmware(args.list_firmware)
        return
    
    # Handle dry run
    if args.dry_run:
        print("DRY RUN - No files will be downloaded")
        downloader.verbose = True  # Force verbose for dry run
    
    # Get firmware configurations from device-organized structure
    firmware_configs = downloader.get_firmware_configs()
    
    if args.device:
        firmware_configs = [fw for fw in firmware_configs if fw['device'] == args.device]
        if not firmware_configs:
            print(f"No firmware configurations found for device: {args.device}")
            return
    
    if args.firmware:
        if not args.device:
            print("Error: --firmware requires --device to be specified")
            sys.exit(1)
        firmware_configs = [fw for fw in firmware_configs if args.firmware.lower() in fw['name'].lower()]
        if not firmware_configs:
            print(f"No firmware configurations found for: {args.firmware}")
            return
    
    # Process M5Stack firmware downloads
    m5_successful = []
    m5_failed = []
    
    if not args.github_only and firmware_configs:
        if args.dry_run:
            for firmware_config in firmware_configs:
                device = firmware_config['device']
                name = firmware_config['name']
                device_key = firmware_config['device_key']
                print(f"Would download: {name} for {device} to firmware/{device_key}/")
                m5_successful.append(f"{name} ({device})")
        else:
            for firmware_config in firmware_configs:
                name = firmware_config['name']
                device = firmware_config['device']
                if downloader.download_firmware(firmware_config):
                    m5_successful.append(f"{name} ({device})")
                else:
                    m5_failed.append(f"{name} ({device})")
    
    # Process GitHub releases downloads
    github_successful = []
    github_failed = []
    
    if not args.skip_github:
        github_configs = downloader.config.get('github_releases', [])
        
        if github_configs:
            if args.dry_run:
                for github_config in github_configs:
                    name = github_config['name']
                    print(f"Would download GitHub release: {name} to firmware/{name}/")
                    github_successful.append(name)
            else:
                for github_config in github_configs:
                    name = github_config['name']
                    if downloader.download_github_release_assets(github_config):
                        github_successful.append(name)
                    else:
                        github_failed.append(name)
    
    # Detailed Summary
    total_successful_count = len(m5_successful) + len(github_successful)
    total_failed_count = len(m5_failed) + len(github_failed)
    
    if verbose:
        print("\n" + "=" * 60)
        print("FINAL DOWNLOAD REPORT")
        print("=" * 60)
        
        if not args.github_only and (m5_successful or m5_failed):
            print(f"\nM5Stack Firmware:")
            print(f"  Successful ({len(m5_successful)}): {', '.join(m5_successful) if m5_successful else 'None'}")
            if m5_failed:
                print(f"  Failed ({len(m5_failed)}): {', '.join(m5_failed)}")
        
        if not args.skip_github and (github_successful or github_failed):
            print(f"\nGitHub Releases:")
            print(f"  Successful ({len(github_successful)}): {', '.join(github_successful) if github_successful else 'None'}")
            if github_failed:
                print(f"  Failed ({len(github_failed)}): {', '.join(github_failed)}")
        
        print(f"\nOverall Summary:")
        print(f"  Total Successful: {total_successful_count}")
        print(f"  Total Failed: {total_failed_count}")
        print(f"  Total Processed: {total_successful_count + total_failed_count}")
        
        if total_failed_count > 0:
            print(f"\nFailed Downloads:")
            all_failed = m5_failed + github_failed
            for i, failed_item in enumerate(all_failed, 1):
                print(f"  {i}. {failed_item}")
            print(f"\nCheck the output above for specific error details.")
        
        print("=" * 60)
    
    if total_failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()