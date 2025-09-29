#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import git
from git import Repo, InvalidGitRepositoryError, GitCommandError

try:
    import tomllib
except ImportError:
    import tomli as tomllib


def is_git_repo(path):
    """Check if a directory is a git repository."""
    try:
        Repo(path)
        return True
    except InvalidGitRepositoryError:
        return False


def clone_repo(url, branch, dest_dir, timeout=300, verbose=True):
    """Clone a git repository to the specified directory."""
    try:
        if verbose:
            print(f"Cloning {url} (branch: {branch}) to {dest_dir}...")
        
        # Set timeout for git operations
        os.environ['GIT_TERMINAL_PROMPT'] = '0'
        
        repo = Repo.clone_from(url, dest_dir, branch=branch)
        if verbose:
            print(f"✓ Successfully cloned {url}")
        return True, f"Successfully cloned {url}"
    except GitCommandError as e:
        error_msg = f"Failed to clone {url}: {e}"
        if verbose:
            print(f"✗ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error cloning {url}: {e}"
        if verbose:
            print(f"✗ {error_msg}")
        return False, error_msg


def sync_repo(dest_dir, branch, timeout=300, verbose=True):
    """Sync an existing git repository to the specified branch."""
    try:
        repo = Repo(dest_dir)
        
        # Fetch latest changes
        if verbose:
            print(f"Fetching updates for {dest_dir}...")
        repo.remotes.origin.fetch()
        
        # Switch to the desired branch if not already on it
        if repo.active_branch.name != branch:
            if verbose:
                print(f"Switching to branch {branch}...")
            repo.git.checkout(branch)
        
        # Pull latest changes
        if verbose:
            print(f"Pulling latest changes for {dest_dir}...")
        repo.remotes.origin.pull()
        
        if verbose:
            print(f"✓ Successfully synced {dest_dir}")
        return True, f"Successfully synced {dest_dir}"
    except GitCommandError as e:
        error_msg = f"Failed to sync {dest_dir}: {e}"
        if verbose:
            print(f"✗ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error syncing {dest_dir}: {e}"
        if verbose:
            print(f"✗ {error_msg}")
        return False, error_msg


def check_rsync_available():
    """Check if rsync is available on the system."""
    return shutil.which('rsync') is not None


def rsync_files(repo_config, settings, copy_base_dir=None, verbose=True):
    """Copy specified files using rsync."""
    if not copy_base_dir:
        return True, "No files to copy"
    
    # Check if rsync is available
    if not check_rsync_available():
        error_msg = "rsync is not available on this system"
        if verbose:
            print(f"✗ {error_msg}")
        return False, error_msg
    
    copy_files = repo_config.get('copy_files', [])
    repo_path = Path(repo_config['dest_dir'])
    
    # If no copy_files specified, copy everything but avoid directory duplication
    copy_everything = not copy_files
    if copy_everything:
        copy_files = ["./"]
    
    # Create destination path: base_dir/repo_name
    dest_path = Path(copy_base_dir) / repo_config['name']
    
    # Get rsync args (repo-specific or global default)
    rsync_args = repo_config.get('rsync_args', settings.get('rsync_args', ['-av']))
    
    # Get rsync excludes (repo-specific or global default)
    rsync_excludes = repo_config.get('rsync_excludes', settings.get('rsync_excludes', []))
    
    # Add exclude patterns to rsync args
    exclude_args = []
    for exclude_pattern in rsync_excludes:
        exclude_args.extend(['--exclude', exclude_pattern])
    
    # Validate and prepare sources
    valid_sources = []
    missing_sources = []
    
    for file_path in copy_files:
        source = repo_path / file_path
        if source.exists():
            if copy_everything:
                # For full copy, use trailing slash to copy contents, not the directory itself
                valid_sources.append(str(source) + "/")
            else:
                valid_sources.append(str(source))
        else:
            missing_sources.append(str(source))
    
    if missing_sources:
        if verbose:
            for missing in missing_sources:
                print(f"✗ Source path does not exist: {missing}")
    
    if not valid_sources:
        return False, f"No valid source paths found"
    
    # Create destination directory if it doesn't exist
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # Build single rsync command with all valid sources and excludes
    cmd = ['rsync'] + rsync_args + exclude_args + valid_sources + [str(dest_path)]
    
    try:
        if verbose:
            print(f"Copying {len(valid_sources)} items from {repo_config['name']} to {dest_path}...")
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        success_msg = f"Successfully copied {len(valid_sources)} items"
        if missing_sources:
            success_msg += f" ({len(missing_sources)} items were missing)"
        
        if verbose:
            print(f"✓ {success_msg}")
        
        return not bool(missing_sources), success_msg
        
    except subprocess.CalledProcessError as e:
        error_msg = f"rsync failed: {e.stderr.strip()}"
        if verbose:
            print(f"✗ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error during rsync: {e}"
        if verbose:
            print(f"✗ {error_msg}")
        return False, error_msg


def process_repo(repo_config, settings, copy_base_dir=None, operation='sync'):
    """Process a single repository from the TOML configuration."""
    # Extract and cache values to avoid repeated dict lookups
    name = repo_config.get('name', 'unknown')
    enabled = repo_config.get('enabled', True)
    
    if not enabled:
        return True, f"Skipped {name} (disabled)"
    
    # Cache commonly used values
    url = repo_config['url']
    branch = repo_config['branch']
    dest_dir = repo_config['dest_dir']
    timeout = settings.get('timeout_seconds', 300)
    verbose = settings.get('verbose', True)
    
    # Convert to Path once and reuse
    dest_path = Path(dest_dir)
    
    # Handle git operations if needed
    git_success = True
    git_message = ""
    
    if operation in ['sync', 'both']:
        if dest_path.exists():
            if is_git_repo(dest_path):
                git_success, git_message = sync_repo(dest_path, branch, timeout, verbose)
            else:
                git_message = f"Directory {dest_dir} exists but is not a git repository"
                if verbose:
                    print(f"✗ {git_message}")
                return False, git_message
        else:
            # Create parent directories if they don't exist
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            git_success, git_message = clone_repo(url, branch, dest_dir, timeout, verbose)
        
        if not git_success:
            return False, git_message
    
    # Handle file copying if needed
    rsync_success = True
    rsync_message = "No files to copy"
    
    if operation in ['copy', 'both']:
        if operation == 'copy' and not dest_path.exists():
            error_msg = f"Repository directory {dest_dir} does not exist (cannot copy without sync first)"
            if verbose:
                print(f"✗ {error_msg}")
            return False, error_msg
        
        rsync_success, rsync_message = rsync_files(repo_config, settings, copy_base_dir, verbose)
    
    # Combine results
    if git_success and rsync_success:
        if operation == 'sync':
            return True, git_message
        elif operation == 'copy':
            return True, rsync_message
        else:  # both
            combined_message = f"{git_message}; {rsync_message}" if rsync_message != "No files to copy" else git_message
            return True, combined_message
    else:
        if operation == 'sync':
            return False, git_message
        elif operation == 'copy':
            return False, rsync_message
        else:  # both
            combined_message = f"{git_message}; {rsync_message}"
            return False, combined_message


def load_config(config_file="repos.toml"):
    """Load configuration from TOML file."""
    try:
        with open(config_file, 'rb') as f:
            return tomllib.load(f)
    except FileNotFoundError:
        print(f"Error: {config_file} not found in current directory")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading configuration: {e}")
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Synchronize git repositories based on TOML configuration",
        epilog="Examples:\n"
               "  %(prog)s                    # Sync all repositories\n"
               "  %(prog)s uber-flipper       # Sync only uber-flipper\n"
               "  %(prog)s uber-flipper badusb bruce  # Sync multiple repos\n"
               "  %(prog)s --list             # List all repository names\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        'repositories',
        nargs='*',
        help='Repository names to sync (if not specified, all enabled repositories will be synced)'
    )
    
    parser.add_argument(
        '--config', '-c',
        default='repos.toml',
        help='Configuration file to use (default: repos.toml)'
    )
    
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List all repository names from the configuration and exit'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output (overrides config setting)'
    )
    
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Disable verbose output (overrides config setting)'
    )
    
    parser.add_argument(
        '--jobs', '-j',
        type=int,
        help='Number of parallel jobs (overrides config setting)'
    )
    
    parser.add_argument(
        '--copy-to',
        help='Base directory to copy files to (files will be copied to subdirectories named after each repository)'
    )
    
    parser.add_argument(
        '--operation', '-o',
        choices=['sync', 'copy', 'both'],
        default='sync',
        help='Operation to perform: sync (git only), copy (rsync only), both (git + rsync). Default: sync'
    )
    
    return parser.parse_args()


def filter_repositories(repositories, requested_names):
    """Filter repositories by requested names."""
    if not requested_names:
        return repositories
    
    # Create a mapping of repository names to configs
    repo_map = {repo['name']: repo for repo in repositories}
    
    # Find requested repositories
    filtered_repos = []
    missing_repos = []
    
    for name in requested_names:
        if name in repo_map:
            filtered_repos.append(repo_map[name])
        else:
            missing_repos.append(name)
    
    if missing_repos:
        print(f"Error: Repository(ies) not found: {', '.join(missing_repos)}")
        print(f"Available repositories: {', '.join(repo_map.keys())}")
        sys.exit(1)
    
    return filtered_repos


def main():
    """Main function to process the repos.toml file."""
    args = parse_args()
    
    config = load_config(args.config)
    settings = config.get('settings', {})
    repositories = config.get('repositories', [])
    
    if not repositories:
        print("No repositories found in configuration")
        return
    
    # Handle --list option
    if args.list:
        print("Available repositories:")
        for repo in repositories:
            status = "enabled" if repo.get('enabled', True) else "disabled"
            print(f"  {repo['name']} ({status}) - {repo['url']}")
        return
    
    # Filter repositories by command line arguments
    repositories = filter_repositories(repositories, args.repositories)
    
    # Override settings with command line arguments
    parallel_jobs = args.jobs if args.jobs is not None else settings.get('parallel_jobs', 1)
    copy_base_dir = args.copy_to
    operation = args.operation
    
    # Early validation to prevent unnecessary work
    if operation in ['copy', 'both'] and not copy_base_dir:
        print("Error: --copy-to is required when using 'copy' or 'both' operations")
        sys.exit(1)
    
    # Check rsync availability early if needed
    if operation in ['copy', 'both'] and not check_rsync_available():
        print("Error: rsync is not available on this system")
        sys.exit(1)
    
    # Filter out disabled repositories early
    repositories = [repo for repo in repositories if repo.get('enabled', True)]
    
    if not repositories:
        print("No enabled repositories to process")
        return
    
    # Handle verbose/quiet flags
    if args.verbose:
        verbose = True
    elif args.quiet:
        verbose = False
    else:
        verbose = settings.get('verbose', True)
    
    if verbose:
        operation_desc = {
            'sync': 'repository synchronization',
            'copy': 'file copying',
            'both': 'repository synchronization and file copying'
        }
        print(f"Starting {operation_desc[operation]}...\n")
        print(f"Configuration: {len(repositories)} repositories, {parallel_jobs} parallel jobs\n")
    
    successful = 0
    failed = 0
    results = []
    
    # Add firmware directory to copy operations if configured
    firmware_dir = settings.get('firmware_dir')
    if firmware_dir and copy_base_dir and operation in ['copy', 'both']:
        firmware_path = Path(firmware_dir)
        if firmware_path.exists():
            if verbose:
                print(f"Including firmware directory: {firmware_dir}")
        else:
            if verbose:
                print(f"Firmware directory does not exist: {firmware_dir}")
    
    if parallel_jobs > 1:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=parallel_jobs) as executor:
            future_to_repo = {
                executor.submit(process_repo, repo, settings, copy_base_dir, operation): repo 
                for repo in repositories
            }
            
            for future in as_completed(future_to_repo):
                repo = future_to_repo[future]
                try:
                    success, message = future.result()
                    results.append((repo['name'], success, message))
                    if success:
                        successful += 1
                    else:
                        failed += 1
                except Exception as e:
                    error_msg = f"Exception processing {repo['name']}: {e}"
                    results.append((repo['name'], False, error_msg))
                    failed += 1
    else:
        # Sequential processing
        for repo in repositories:
            if verbose:
                print(f"Processing: {repo['name']} ({repo['url']}) -> {repo['dest_dir']}")
            
            try:
                success, message = process_repo(repo, settings, copy_base_dir, operation)
                results.append((repo['name'], success, message))
                if success:
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                error_msg = f"Exception processing {repo['name']}: {e}"
                results.append((repo['name'], False, error_msg))
                if verbose:
                    print(f"✗ {error_msg}")
                failed += 1
            
            if verbose:
                print()  # Empty line for readability
    
    # Handle firmware directory sync if configured
    if firmware_dir and copy_base_dir and operation in ['copy', 'both']:
        firmware_path = Path(firmware_dir)
        if firmware_path.exists():
            try:
                if verbose:
                    print(f"Syncing firmware directory: {firmware_dir} -> {copy_base_dir}/firmware")
                
                dest_firmware = Path(copy_base_dir) / "firmware"
                dest_firmware.mkdir(parents=True, exist_ok=True)
                
                # Use rsync to copy firmware directory contents
                rsync_args = settings.get('rsync_args', ['-av'])
                cmd = ['rsync'] + rsync_args + [str(firmware_path) + "/", str(dest_firmware)]
                
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                
                if verbose:
                    print(f"✓ Successfully synced firmware directory")
                
            except subprocess.CalledProcessError as e:
                if verbose:
                    print(f"✗ Failed to sync firmware directory: {e.stderr.strip()}")
                failed += 1
            except Exception as e:
                if verbose:
                    print(f"✗ Error syncing firmware directory: {e}")
                failed += 1
    
    # Summary
    if verbose:
        print("=" * 50)
        print(f"Synchronization complete!")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total: {successful + failed}")
        
        if failed > 0:
            print("\nFailed repositories:")
            for name, success, message in results:
                if not success:
                    print(f"  ✗ {name}: {message}")
    
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()