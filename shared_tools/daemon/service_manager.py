#!/usr/bin/env python3
"""
Service Manager for Paper Processor Daemon.

Manages service lifecycle for GROBID and Ollama services,
with robust network resilience for distributed setups (blacktower ↔ P1).
"""

import configparser
import logging
import time
import subprocess
import socket
import shlex
from typing import Optional, Tuple, Callable, List
from pathlib import Path
import requests

# Import service clients
from shared_tools.api.grobid_client import GrobidClient
from shared_tools.ai.ollama_client import OllamaClient

# Import shared exceptions
from shared_tools.daemon.exceptions import ServiceError

# Import constants
from shared_tools.daemon.constants import DaemonConstants


class ServiceManager:
    """Manages service lifecycle for GROBID and Ollama (local or remote)."""
    
    def __init__(self, config: configparser.ConfigParser, logger: Optional[logging.Logger] = None):
        """Initialize service manager.
        
        Args:
            config: Configuration parser with service settings
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # GROBID configuration
        self.grobid_host = config.get('GROBID', 'host', fallback='localhost').strip()
        self.grobid_port = config.getint('GROBID', 'port', fallback=8070)
        self.grobid_auto_start = config.getboolean('GROBID', 'auto_start', fallback=True)
        self.grobid_auto_stop = config.getboolean('GROBID', 'auto_stop', fallback=True)
        self.grobid_container_name = config.get('GROBID', 'container_name', fallback='grobid')
        
        # Ollama configuration
        self.ollama_host = config.get('OLLAMA', 'host', fallback='localhost').strip()
        self.ollama_port = config.getint('OLLAMA', 'port', fallback=11434)
        self.ollama_auto_start = config.getboolean('OLLAMA', 'auto_start', fallback=True)
        self.ollama_startup_timeout = config.getint('OLLAMA', 'startup_timeout', fallback=DaemonConstants.SERVICE_STARTUP_TIMEOUT)
        self.ollama_shutdown_timeout = config.getint('OLLAMA', 'shutdown_timeout', fallback=10)
        
        # Health check configuration (with fallback defaults)
        self.health_check_timeout = config.getint(
            'SERVICE_RESILIENCE', 'health_check_timeout', fallback=5
        )
        self.health_check_retries = config.getint(
            'SERVICE_RESILIENCE', 'health_check_retries', fallback=3
        )
        self.health_check_backoff_multiplier = config.getint(
            'SERVICE_RESILIENCE', 'health_check_backoff_multiplier', fallback=2
        )
        
        # Service state
        self.grobid_ready = False
        self.ollama_ready = False
        self.grobid_client: Optional[GrobidClient] = None
        self.ollama_client: Optional[OllamaClient] = None
        self.ollama_process: Optional[subprocess.Popen] = None
        
        # Detect if services are local
        self.is_local_grobid = self._is_localhost(self.grobid_host)
        self.is_local_ollama = self._is_localhost(self.ollama_host)
    
    @staticmethod
    def _is_localhost(host: str) -> bool:
        """Check if host is localhost.
        
        Args:
            host: Hostname or IP address
            
        Returns:
            True if host is localhost
        """
        return host.lower() in ('localhost', '127.0.0.1', '::1', '0.0.0.0')
    
    def initialize_grobid(self) -> bool:
        """Initialize GROBID service.
        
        Returns:
            True if GROBID is available, False otherwise
        """
        self.logger.info("Initializing GROBID service...")
        
        # Create GROBID config
        grobid_config = {
            'handle_rotation': self.config.getboolean('GROBID', 'handle_rotation', fallback=True),
            'rotation_check_pages': self.config.getint('GROBID', 'rotation_check_pages', fallback=2),
            'tesseract_path': self.config.get('PROCESSING', 'tesseract_path', fallback=None)
        }
        
        # Create GROBID client
        grobid_url = f"http://{self.grobid_host}:{self.grobid_port}"
        self.grobid_client = GrobidClient(grobid_url, config=grobid_config)
        
        # Check if available
        is_available, error_msg = self.check_grobid_health()
        
        if is_available:
            self.grobid_ready = True
            location = "Local" if self.is_local_grobid else f"Remote ({self.grobid_host})"
            self.logger.info(f"GROBID initialized successfully ({location})")
            return True
        else:
            # Try to start if local
            if self.is_local_grobid and self.grobid_auto_start:
                self.logger.info("Attempting to start local GROBID container...")
                if self._start_local_grobid():
                    self.grobid_ready = True
                    return True
            
            self.grobid_ready = False
            location = "local" if self.is_local_grobid else f"remote ({self.grobid_host})"
            self.logger.warning(f"GROBID not available ({location}): {error_msg}")
            return False
    
    def initialize_ollama(self) -> bool:
        """Initialize Ollama service (lazy initialization - only check availability).
        
        Returns:
            True if Ollama is available, False otherwise
        """
        self.logger.info("Checking Ollama availability...")
        
        # Create Ollama client (it loads config internally)
        self.ollama_client = OllamaClient()
        
        # Just check availability, don't start yet
        is_available, error_msg = self.check_ollama_health()
        
        if is_available:
            self.ollama_ready = True
            location = "Local" if self.is_local_ollama else f"Remote ({self.ollama_host})"
            self.logger.info(f"Ollama available ({location})")
            return True
        else:
            self.ollama_ready = False
            location = "local" if self.is_local_ollama else f"remote ({self.ollama_host})"
            self.logger.debug(f"Ollama not available ({location}): {error_msg}")
            return False
    
    def ensure_grobid_ready(self) -> bool:
        """Ensure GROBID is ready (check health with retries).
        
        Returns:
            True if GROBID is ready
        """
        if self.grobid_ready:
            is_available, _ = self.check_grobid_health()
            if is_available:
                return True
            else:
                # Service was ready but now unavailable
                self.grobid_ready = False
                self.logger.warning("GROBID was ready but is now unavailable")
        
        # Re-check with retries
        is_available, error_msg = self.check_grobid_health()
        if is_available:
            self.grobid_ready = True
            return True
        else:
            self.logger.debug(f"GROBID not ready: {error_msg}")
            return False
    
    def ensure_ollama_ready(self) -> bool:
        """Ensure Ollama is ready (start if local and needed).
        
        Returns:
            True if Ollama is ready
        """
        if self.ollama_ready:
            is_available, _ = self.check_ollama_health()
            if is_available:
                return True
            else:
                self.ollama_ready = False
        
        # Check health
        is_available, error_msg = self.check_ollama_health()
        if is_available:
            self.ollama_ready = True
            return True
        
        # Try to start if local
        if self.is_local_ollama and self.ollama_auto_start:
            self.logger.info("Starting local Ollama service...")
            if self._start_local_ollama():
                self.ollama_ready = True
                return True
        
        self.logger.warning(f"Ollama not ready: {error_msg}")
        return False
    
    def check_grobid_health(self) -> Tuple[bool, Optional[str]]:
        """Check GROBID health with retries and exponential backoff.
        
        Returns:
            Tuple of (is_healthy, error_message)
        """
        if not self.grobid_client:
            return False, "GROBID client not initialized"
        
        health_url = f"http://{self.grobid_host}:{self.grobid_port}/api/isalive"
        
        return self._check_service_health(
            service_name="GROBID",
            health_url=health_url,
            health_check_fn=lambda: self.grobid_client.is_available(verbose=False)
        )
    
    def check_ollama_health(self) -> Tuple[bool, Optional[str]]:
        """Check Ollama health with retries and exponential backoff.
        
        Returns:
            Tuple of (is_healthy, error_message)
        """
        if not self.ollama_client:
            return False, "Ollama client not initialized"
        
        health_url = f"http://{self.ollama_host}:{self.ollama_port}/api/tags"
        
        def check_ollama() -> bool:
            try:
                response = requests.get(health_url, timeout=self.health_check_timeout)
                return response.status_code == 200
            except Exception:
                return False
        
        return self._check_service_health(
            service_name="Ollama",
            health_url=health_url,
            health_check_fn=check_ollama
        )
    
    def _check_service_health(
        self,
        service_name: str,
        health_url: str,
        health_check_fn: Callable[[], bool]
    ) -> Tuple[bool, Optional[str]]:
        """Check service health with exponential backoff.
        
        Args:
            service_name: Name of service (for logging)
            health_url: URL for health check
            health_check_fn: Function to check service health
            
        Returns:
            Tuple of (is_healthy, error_message)
        """
        last_error = None
        
        for attempt in range(self.health_check_retries):
            try:
                if health_check_fn():
                    return True, None
                else:
                    last_error = f"{service_name} health check returned False"
            except requests.ConnectionError as e:
                last_error = f"Connection error: {e}"
            except requests.Timeout:
                last_error = f"Timeout after {self.health_check_timeout}s"
            except requests.RequestException as e:
                last_error = f"Request error: {e}"
            except Exception as e:
                # Catch-all for unexpected errors (e.g., from health_check_fn)
                last_error = f"Unexpected error: {e}"
            
            # Exponential backoff (except on last attempt)
            if attempt < self.health_check_retries - 1:
                wait_time = self.health_check_backoff_multiplier ** attempt
                time.sleep(wait_time)
                self.logger.debug(
                    f"{service_name} health check failed (attempt {attempt + 1}/{self.health_check_retries}), "
                    f"retrying in {wait_time}s..."
                )
        
        error_msg = f"{service_name} health check failed after {self.health_check_retries} attempts: {last_error}"
        return False, error_msg
    
    def _start_local_grobid(self) -> bool:
        """Start local GROBID Docker container.
        
        Returns:
            True if started successfully
        """
        if not self.is_local_grobid:
            self.logger.warning("Cannot start GROBID: not configured as local service")
            return False
        
        try:
            if not self._ensure_grobid_container_exists():
                return False
            
            if not self._wait_for_grobid_ready():
                return False
            
            return True
            
        except FileNotFoundError:
            self.logger.error("Docker not found. Please install Docker first.")
            return False
        except Exception as e:
            self.logger.error(f"Failed to start GROBID container: {e}")
            return False
    
    def _ensure_grobid_container_exists(self) -> bool:
        """Ensure GROBID container exists and is running.
        
        Returns:
            True if container exists and is started, False otherwise
        """
        # Check if container exists
        result = subprocess.run(
            ['docker', 'ps', '-a', '--filter', f'name={self.grobid_container_name}', '--format', '{{.Names}}'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if self.grobid_container_name in result.stdout:
            # Start existing container
            return self._start_existing_grobid_container()
        else:
            # Create new container
            return self._create_new_grobid_container()
    
    def _start_existing_grobid_container(self) -> bool:
        """Start an existing GROBID container.
        
        Returns:
            True if started successfully, False otherwise
        """
        self.logger.info(f"Starting existing GROBID container: {self.grobid_container_name}")
        # Safe: container name is from config, not user input
        result = subprocess.run(
            ['docker', 'start', self.grobid_container_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=30  # Add timeout for safety
        )
        if result.returncode != 0:
            self.logger.error(f"Failed to start container: {result.stderr}")
            return False
        return True
    
    def _create_new_grobid_container(self) -> bool:
        """Create a new GROBID Docker container.
        
        Returns:
            True if created successfully, False otherwise
        """
        self.logger.info(f"Creating new GROBID container: {self.grobid_container_name}")
        # Safe: all values are from config, not user input
        # Using list form (not shell=True) prevents injection
        result = subprocess.run([
            'docker', 'run', '-d',
            '--name', self.grobid_container_name,
            '-p', f'{self.grobid_port}:8070',
            'lfoppiano/grobid:0.8.2'
        ], capture_output=True, text=True, check=False, timeout=60)
        
        if result.returncode != 0:
            self.logger.error(f"Failed to create container: {result.stderr}")
            return False
        return True
    
    def _wait_for_grobid_ready(self) -> bool:
        """Wait for GROBID to become ready after starting.
        
        Returns:
            True if GROBID is ready, False if timeout
        """
        self.logger.info("Waiting for GROBID to initialize...")
        for attempt in range(DaemonConstants.GROBID_STARTUP_TIMEOUT):
            time.sleep(1)
            if self.grobid_client and self.grobid_client.is_available(verbose=False):
                self.logger.info(f"GROBID ready after {attempt + 1} seconds")
                return True
            if attempt % 10 == 9:
                self.logger.debug(f"Still waiting for GROBID... ({attempt + 1}s)")
        
        self.logger.error("GROBID container started but not responding after timeout")
        return False
    
    def _start_local_ollama(self) -> bool:
        """Start local Ollama service.
        
        Returns:
            True if started successfully
        """
        if not self.is_local_ollama:
            self.logger.warning("Cannot start Ollama: not configured as local service")
            return False
        
        try:
            self.logger.info("Starting Ollama server in background...")
            
            # Start Ollama server in background
            # Safe: fixed command, no user input
            self.ollama_process = subprocess.Popen(
                ['ollama', 'serve'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False  # Explicitly disable shell (default, but explicit for security)
            )
            
            # Wait for Ollama to be ready
            for attempt in range(self.ollama_startup_timeout):
                time.sleep(1)
                if self._is_ollama_running():
                    self.logger.info(f"Ollama ready after {attempt + 1} seconds")
                    return True
                if attempt % 5 == 4:
                    self.logger.debug(f"Still waiting for Ollama... ({attempt + 1}s)")
            
            self.logger.warning(f"Ollama failed to start within {self.ollama_startup_timeout} seconds")
            return False
            
        except FileNotFoundError:
            self.logger.error("Ollama not found. Please install Ollama first.")
            return False
        except Exception as e:
            self.logger.error(f"Failed to start Ollama: {e}")
            return False
    
    def _is_ollama_running(self) -> bool:
        """Check if Ollama server is running on the configured port.
        
        Returns:
            True if Ollama is responding, False otherwise
        """
        try:
            # Try to connect to Ollama's configured port with fast timeout
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)  # Fast 2 second timeout for detection
            result = sock.connect_ex((self.ollama_host, self.ollama_port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def shutdown(self):
        """Shutdown services (stop local services if auto_stop enabled)."""
        if self.is_local_grobid and self.grobid_auto_stop:
            self._stop_local_grobid()
        
        if self.is_local_ollama and self.ollama_process:
            self._stop_local_ollama()
    
    def _stop_local_grobid(self):
        """Stop local GROBID Docker container."""
        try:
            # Safe: container name is from config, not user input
            result = subprocess.run(
                ['docker', 'stop', self.grobid_container_name],
                capture_output=True,
                text=True,
                check=False,
                timeout=30  # Add timeout for safety
            )
            if result.returncode == 0:
                self.logger.info("GROBID container stopped")
            else:
                self.logger.warning(f"Failed to stop GROBID container: {result.stderr}")
        except Exception as e:
            self.logger.error(f"Error stopping GROBID container: {e}")
    
    def _stop_local_ollama(self):
        """Stop local Ollama service."""
        if self.ollama_process:
            try:
                self.ollama_process.terminate()
                self.ollama_process.wait(timeout=self.ollama_shutdown_timeout)
                self.logger.info("Ollama process stopped")
            except subprocess.TimeoutExpired:
                self.ollama_process.kill()
                self.logger.warning("Ollama process killed (did not terminate gracefully)")
            except Exception as e:
                self.logger.error(f"Error stopping Ollama: {e}")

