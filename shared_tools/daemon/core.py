#!/usr/bin/env python3
"""
Core daemon module for paper processor daemon.

Provides file watching, lifecycle management, and event handling.
This module contains the core daemon functionality extracted from the main daemon script.
"""

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional, Callable

from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from shared_tools.daemon.exceptions import DaemonError
from shared_tools.daemon.constants import DaemonConstants


class PaperProcessorEventHandler(FileSystemEventHandler):
    """Event handler for file system events in the watch directory."""
    
    def __init__(self, processor_callback: Callable[[Path], None], logger: Optional[logging.Logger] = None):
        """Initialize event handler.
        
        Args:
            processor_callback: Callback function to process PDF files
            logger: Optional logger instance
        """
        self.processor_callback = processor_callback
        self.logger = logger or logging.getLogger(__name__)
        super().__init__()
    
    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events.
        
        Args:
            event: File system event
        """
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        
        # Only process PDF files
        if file_path.suffix.lower() == DaemonConstants.PDF_EXTENSION:
            self.logger.info(f"New PDF detected: {file_path.name}")
            self.processor_callback(file_path)


class PaperProcessorCore:
    """Core daemon class for file watching and lifecycle management."""
    
    def __init__(
        self,
        watch_dir: Path,
        processor_callback: Callable[[Path], None],
        logger: Optional[logging.Logger] = None
    ):
        """Initialize core daemon.
        
        Args:
            watch_dir: Directory to watch for new PDFs
            processor_callback: Callback function to process PDF files
            logger: Optional logger instance
        """
        self.watch_dir = Path(watch_dir)
        self.processor_callback = processor_callback
        self.logger = logger or logging.getLogger(__name__)
        
        # File watcher components
        self.observer: Optional[Observer] = None
        self.event_handler: Optional[PaperProcessorEventHandler] = None
        
        # State
        self.running = False
        self._shutdown_requested = False
    
    def start(self):
        """Start the daemon file watcher.
        
        Raises:
            DaemonError: If daemon fails to start
        """
        if self.running:
            self.logger.warning("Daemon is already running")
            return
        
        try:
            # Ensure watch directory exists
            self.watch_dir.mkdir(parents=True, exist_ok=True)
            
            # Create event handler
            self.event_handler = PaperProcessorEventHandler(
                processor_callback=self.processor_callback,
                logger=self.logger
            )
            
            # Create and start observer
            self.observer = Observer()
            self.observer.schedule(self.event_handler, str(self.watch_dir), recursive=False)
            self.observer.start()
            
            self.running = True
            self.logger.info(f"Daemon started watching: {self.watch_dir}")
            
        except Exception as e:
            raise DaemonError(f"Failed to start daemon: {e}") from e
    
    def stop(self):
        """Stop the daemon file watcher."""
        if not self.running:
            return
        
        self._shutdown_requested = True
        self.running = False
        
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=5)
                self.logger.info("Daemon file watcher stopped")
            except Exception as e:
                self.logger.error(f"Error stopping observer: {e}")
            finally:
                self.observer = None
                self.event_handler = None
    
    def is_running(self) -> bool:
        """Check if daemon is running.
        
        Returns:
            True if daemon is running
        """
        return self.running and self.observer is not None and self.observer.is_alive()
    
    def wait_for_shutdown(self):
        """Wait for shutdown signal or interrupt."""
        try:
            while self.is_running() and not self._shutdown_requested:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Shutdown requested via KeyboardInterrupt")
            self.stop()


class DaemonLifecycleManager:
    """Manages daemon lifecycle with signal handling and PID file management."""
    
    def __init__(
        self,
        core_daemon: PaperProcessorCore,
        pid_file: Path,
        logger: Optional[logging.Logger] = None
    ):
        """Initialize lifecycle manager.
        
        Args:
            core_daemon: Core daemon instance
            pid_file: Path to PID file
            logger: Optional logger instance
        """
        self.core_daemon = core_daemon
        self.pid_file = Path(pid_file)
        self.logger = logger or logging.getLogger(__name__)
        self._shutdown_handlers: List[Callable[[], None]] = []
    
    def register_shutdown_handler(self, handler: Callable[[], None]):
        """Register a handler to be called during shutdown.
        
        Args:
            handler: Function to call during shutdown
        """
        self._shutdown_handlers.append(handler)
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, shutting down...")
            self.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def write_pid_file(self):
        """Write PID file."""
        try:
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.pid_file, 'w') as f:
                f.write(str(os.getpid()))
            self.logger.debug(f"PID file written: {self.pid_file}")
        except Exception as e:
            self.logger.warning(f"Failed to write PID file: {e}")
    
    def remove_pid_file(self):
        """Remove PID file."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
                self.logger.debug(f"PID file removed: {self.pid_file}")
        except Exception as e:
            self.logger.warning(f"Failed to remove PID file: {e}")
    
    def shutdown(self):
        """Perform graceful shutdown."""
        self.logger.info("Shutting down daemon...")
        
        # Call registered shutdown handlers
        for handler in self._shutdown_handlers:
            try:
                handler()
            except Exception as e:
                self.logger.error(f"Error in shutdown handler: {e}")
        
        # Stop core daemon
        self.core_daemon.stop()
        
        # Remove PID file
        self.remove_pid_file()
        
        self.logger.info("Daemon shutdown complete")
    
    def run(self):
        """Run the daemon (start, setup signals, wait for shutdown).
        
        Raises:
            DaemonError: If daemon fails to start
        """
        # Setup signal handlers
        self.setup_signal_handlers()
        
        # Write PID file
        self.write_pid_file()
        
        try:
            # Start core daemon
            self.core_daemon.start()
            
            # Wait for shutdown
            self.core_daemon.wait_for_shutdown()
            
        except Exception as e:
            self.logger.error(f"Error in daemon run loop: {e}")
            raise DaemonError(f"Daemon run failed: {e}") from e
        finally:
            self.shutdown()

