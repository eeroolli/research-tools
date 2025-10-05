"""
Global thread pool manager for limiting concurrent tesseract processes.
"""
import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from .cpu_monitor import CPUMonitor


class ThreadPoolManager:
    """Manages global thread pool with CPU throttling."""
    
    _instance: Optional['ThreadPoolManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.logger = logging.getLogger(__name__)
        self.executor: Optional[ThreadPoolExecutor] = None
        self.cpu_monitor: Optional[CPUMonitor] = None
        self.max_workers = None
        self.throttle_delay = None
        
    def initialize(self, max_workers: int, cpu_threshold: float, 
                   throttle_delay: float, check_interval: float):
        """
        Initialize the thread pool manager.
        
        Args:
            max_workers: Maximum number of concurrent threads
            cpu_threshold: CPU usage threshold for throttling
            throttle_delay: Delay when throttling is needed
            check_interval: CPU check interval
        """
        self.max_workers = max_workers
        self.throttle_delay = throttle_delay
        self.cpu_monitor = CPUMonitor(cpu_threshold, check_interval)
        
        if self.executor is None or self.executor._max_workers != max_workers:
            if self.executor:
                self.executor.shutdown(wait=True)
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
            self.logger.info(f"Initialized thread pool with {max_workers} workers")
    
    def submit(self, fn, *args, **kwargs):
        """
        Submit a task to the thread pool with CPU throttling.
        
        Args:
            fn: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Future object
        """
        if self.executor is None:
            raise RuntimeError("ThreadPoolManager not initialized. Call initialize() first.")
        
        # Throttle if CPU usage is too high
        if self.cpu_monitor and self.throttle_delay:
            self.cpu_monitor.throttle_if_needed(self.throttle_delay)
        
        return self.executor.submit(fn, *args, **kwargs)
    
    def shutdown(self, wait: bool = True):
        """Shutdown the thread pool."""
        if self.executor:
            self.executor.shutdown(wait=wait)
            self.executor = None
            self.logger.info("Thread pool shutdown")
    
    def get_status(self) -> dict:
        """Get current thread pool status."""
        if not self.executor:
            return {'active_threads': 0, 'max_workers': 0, 'cpu_usage': 0.0}
        
        cpu_usage = self.cpu_monitor.get_cpu_usage() if self.cpu_monitor else 0.0
        
        return {
            'active_threads': len(self.executor._threads) if hasattr(self.executor, '_threads') else 0,
            'max_workers': self.max_workers or 0,
            'cpu_usage': cpu_usage
        }


# Global instance
thread_pool_manager = ThreadPoolManager()
