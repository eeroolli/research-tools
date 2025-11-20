"""
CPU monitoring utilities for throttling OCR processing.
"""
import psutil
import time
import logging
from typing import Optional


class CPUMonitor:
    """Monitor CPU usage and provide throttling functionality."""
    
    def __init__(self, threshold: float = 80.0, check_interval: float = 2.0):
        """
        Initialize CPU monitor.
        
        Args:
            threshold: CPU usage threshold (0-100) above which to throttle
            check_interval: How often to check CPU usage (seconds)
        """
        self.threshold = threshold
        self.check_interval = check_interval
        self.logger = logging.getLogger(__name__)
        self.last_check = 0
        self.last_cpu_usage = 0.0
    
    def get_cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        try:
            return psutil.cpu_percent(interval=0.1)
        except Exception as e:
            self.logger.warning(f"Error getting CPU usage: {e}")
            return 0.0
    
    def should_throttle(self) -> bool:
        """
        Check if processing should be throttled based on CPU usage.
        
        Returns:
            True if CPU usage is above threshold
        """
        current_time = time.time()
        
        # Only check if enough time has passed since last check
        if current_time - self.last_check < self.check_interval:
            return self.last_cpu_usage > self.threshold
        
        self.last_cpu_usage = self.get_cpu_usage()
        self.last_check = current_time
        
        if self.last_cpu_usage > self.threshold:
            self.logger.debug(f"CPU usage {self.last_cpu_usage:.1f}% exceeds threshold {self.threshold}%")
            return True
        
        return False
    
    def throttle_if_needed(self, delay: float = 1.0) -> None:
        """
        Throttle processing if CPU usage is too high.
        
        Args:
            delay: How long to sleep if throttling is needed
        """
        if self.should_throttle():
            self.logger.info(f"Throttling processing - CPU usage: {self.last_cpu_usage:.1f}%")
            time.sleep(delay)
    
    def get_system_info(self) -> dict:
        """Get current system resource information."""
        try:
            return {
                'cpu_percent': psutil.cpu_percent(interval=0.1),
                'memory_percent': psutil.virtual_memory().percent,
                'load_average': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
            }
        except Exception as e:
            self.logger.warning(f"Error getting system info: {e}")
            return {'cpu_percent': 0.0, 'memory_percent': 0.0, 'load_average': None}
