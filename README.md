# SD_Sync

Tools for syncing Git repositories, downloading ESP32 firmware, and syncing to an SD card. There are many different ESP32 firmware distrobutions for a wide variety of ESP32 hardware. The Launcher firmware allows you to switch between them at boot time (amoung many other amazing features). I found I was copying firmware, config files, and defition files to SD cards. This became a tedious process. These scripts will help you get all of the files you need to an SD card and keep it in sync easily. You could also use this for your FlipperZero SD card as well. While many firmware ditrobutions come with some definitions for IR, SubGHz, etc... there are many more on the Internet. These scripts will help you load up an SD card so you can control all the things, on all the firmware, and on all the hardware. Use at your own risk and do not break the law. You've been warned!

**NOTE: This was 99% vibe coded using Claude. Say what you will, but I was actually impressed (which is rare as I get older). I continue to review the code to flush out any bugs and/or vulnerabilities. Pull requests welcome.** 

## Overview

SD_Sync consists of two main scripts:
- **sync_repos.py**: Syncs Git repositories and copies files to SD card structure
- **firmware_downloader.py**: Downloads ESP32 firmware from M5Stack and GitHub releases

## Quick Start

1. Create a Python Virtual Environment and install dependencies:
```bash
python -m venv venv
pip install -r requirements.txt
source ./venv/bin/activate
chmod +x firmware_downloader.py sync_repos.py
```

2. Configure repositories in `repos.toml` (I include several by default)
3. Configure firmware in `firmware.toml` (I included a bunch by default here too)
4. Download firmware and run sync:
```bash
./firmware_downloader.py
./sync_repos.py --operation both --copy-to /mnt/sdcard
```

## Repository Sync (sync_repos.py)

Syncs Git repositories and organizes files for SD card deployment.

### Configuration (repos.toml)

Note: I store all of the Git repos and firmware in a subdirectory called "data" to keep things neat. 

```toml
[settings]
parallel_jobs = 4
firmware_dir = "data/firmware"
rsync_excludes = [".*", ".*/"]

[[repositories]]
name = "uber-flipper"
url = "https://github.com/UberGuidoZ/Flipper.git"
branch = "main"
dest_dir = "uber-flipper"
copy_files = ["BadUSB/", "Infrared/", "Sub-GHz/"]
```

### Usage

```bash
# Sync all repos
./sync_repos.py --operation sync

# Copy files to SD card
./sync_repos.py --operation both --copy-to /mnt/sdcard

# Sync specific repos
./sync_repos.py uber-flipper bruce --operation both --copy-to /mnt/sdcard
```

### Operations
- `sync`: Git clone/pull only
- `copy`: Copy files only (requires existing repos)
- `both`: Git sync + file copy

## Firmware Download (firmware_downloader.py)

Downloads ESP32 firmware from multiple sources.

### Configuration (firmware.toml)

```toml
[settings]
output_base_dir = "data/firmware"

# M5Stack firmware by device
[devices.cardputer]
device_name = "cardputer"

[[devices.cardputer.firmware]]
name = "Bruce"
version = "latest"  # latest, stable, all, or specific version

# GitHub releases by distribution
[[github_releases]]
name = "Bruce"
releases_url = "https://github.com/pr3y/Bruce/releases/"
file_pattern = "*.bin"
```

### Usage

```bash
# Download all firmware
./firmware_downloader.py

# List available options
./firmware_downloader.py --list-devices
./firmware_downloader.py --list-firmware cardputer

# Download specific sources
./firmware_downloader.py --github-only
./firmware_downloader.py --device cardputer
```

### Version Options
- `latest`: Most recent version
- `stable`: Stable release (fallback to latest)
- `all`: All available versions
- `v1.2.3`: Specific version

## Directory Structure

```
project/
├── repos.csv              # Legacy CSV format (deprecated)
├── repos.toml             # Repository configuration  
├── firmware.toml          # Firmware configuration
├── sync_repos.py          # Repository sync script
├── firmware_downloader.py # Firmware download script
├── requirements.txt       # Python dependencies
└── firmware/              # Downloaded firmware
    ├── cardputer/         # M5Stack firmware by device
    └── Bruce/             # GitHub releases by distribution
```

## Integration

Use both tools together:

```bash
# 1. Download firmware
./firmware_downloader.py

# 2. Sync everything to SD card
./sync_repos.py --operation both --copy-to /mnt/sdcard
```

Result: Complete SD card with organized repository files and firmware.

## Command Reference

### sync_repos.py
- `--operation/-o`: sync, copy, both (default: sync)
- `--copy-to`: Destination directory for file copying
- `--config/-c`: Custom config file
- `--list/-l`: List repository names
- `--verbose/-v`, `--quiet/-q`: Output control
- `--jobs/-j`: Parallel jobs

### firmware_downloader.py  
- `--github-only`: Download only GitHub releases
- `--skip-github`: Skip GitHub releases
- `--device`: Filter by device
- `--firmware`: Filter by firmware name (requires --device)
- `--dry-run`: Show what would be downloaded
- `--force`: Overwrite existing files
- `--quiet/-q`: Suppress output
