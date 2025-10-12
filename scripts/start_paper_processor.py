#!/usr/bin/env python3
"""
Smart launcher for paper processor daemon.

Can be triggered by Epson scanner or run manually.
Only starts daemon if not already running (idempotent).

Features:
- Fast exit if daemon already running (< 1 second)
- PID file validation with process checking
- Stale PID file cleanup
- Works across platforms (WSL, Linux, Windows)

Usage:
    python start_paper_processor.py

Scanner Setup:
    Configure Epson scanner to trigger this script after saving PDFs
"""

import sys
import configparser
import psutil
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def is_daemon_running(pid_file: Path) -> bool:
    """Check if daemon is already running.
    
    Args:
        pid_file: Path to PID file
        
    Returns:
        True if daemon is running, False otherwise
    """
    if not pid_file.exists():
        return False
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        # Check if process with this PID exists
        try:
            proc = psutil.Process(pid)
            # Verify it's actually running and is our daemon
            if proc.is_running():
                cmdline = ' '.join(proc.cmdline())
                if 'paper_processor_daemon' in cmdline:
                    return True
        except Exception:
            pass
        
        # Stale PID file - clean it up
        pid_file.unlink()
        return False
        
    except (ValueError, IOError):
        # Corrupted PID file - clean it up
        if pid_file.exists():
            pid_file.unlink()
        return False


def start_daemon():
    """Start the daemon process."""
    import subprocess
    import platform
    
    daemon_script = Path(__file__).parent / "paper_processor_daemon.py"
    
    # Platform-specific daemon start
    if platform.system() == "Windows":
        # Windows: use pythonw.exe for background (future)
        # For now, use regular python to see output
        subprocess.Popen([sys.executable, str(daemon_script)])
    else:
        # Linux/WSL: standard python
        subprocess.Popen([sys.executable, str(daemon_script)])


def main():
    """Main entry point."""
    # Load configuration to get scanner directory
    config = configparser.ConfigParser()
    root_dir = Path(__file__).parent.parent
    config.read([
        root_dir / 'config.conf',
        root_dir / 'config.personal.conf'
    ])
    
    scanner_dir = Path(config.get('PATHS', 'scanner_papers_dir', 
                                   fallback='/mnt/i/FraScanner/papers'))
    pid_file = scanner_dir / ".daemon.pid"
    
    # Check if daemon already running
    if is_daemon_running(pid_file):
        # Already running - exit silently
        # This is the fast path when scanner triggers multiple times
        sys.exit(0)
    
    # Not running - start daemon
    print("="*60)
    print("Starting paper processor daemon...")
    print("="*60)
    start_daemon()
    print("")
    print("Daemon started successfully")
    print("")
    print("Terminal will show processing activity")
    print("Press Ctrl+C to stop daemon")
    print("")


if __name__ == "__main__":
    main()

