#!/usr/bin/env python3
"""
Stop the paper processor daemon cleanly.

Sends SIGTERM for graceful shutdown with timeout fallback to SIGKILL.

Usage:
    python stop_paper_processor.py
"""

import sys
import signal
import configparser
import psutil
from pathlib import Path


def main():
    """Stop daemon."""
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
    
    if not pid_file.exists():
        print("Daemon not running (no PID file)")
        sys.exit(1)
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        # Try to get the process
        try:
            proc = psutil.Process(pid)
            # Verify it's actually running
            if not proc.is_running():
                raise ValueError("Process not running")
        except Exception:
            print("Daemon not running (stale PID file)")
            pid_file.unlink()
            sys.exit(1)
        
        print(f"Stopping daemon (PID: {pid})...")
        proc.send_signal(signal.SIGTERM)
        
        # Wait for shutdown
        try:
            proc.wait(timeout=10)
            print("Daemon stopped successfully")
        except Exception:
            print("Daemon did not stop gracefully, killing...")
            try:
                proc.kill()
                print("Daemon killed")
            except:
                pass
        
    except (ValueError, IOError) as e:
        print(f"Error reading PID file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error stopping daemon: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

