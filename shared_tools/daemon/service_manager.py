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
        # Remote GROBID auto-start (SSH to remote host and run a command, e.g. "docker start grobid")
        self.grobid_remote_auto_start = config.getboolean('GROBID', 'remote_auto_start', fallback=False)
        self.grobid_remote_ssh_host = config.get('GROBID', 'remote_ssh_host', fallback='').strip()
        self.grobid_remote_ssh_user = config.get('GROBID', 'remote_ssh_user', fallback='').strip()
        self.grobid_remote_start_command = config.get(
            'GROBID', 'remote_start_command', fallback=f'docker start {self.grobid_container_name}'
        ).strip()
        # TCP precheck: fast connectivity test before HTTP health check (seconds)
        self.grobid_tcp_precheck_timeout = float(
            config.get('GROBID', 'tcp_precheck_timeout', fallback='1.0')
        )
        # Optional fallback hosts for GROBID (comma-separated list)
        fallback_str = config.get('GROBID', 'fallback_hosts', fallback='').strip()
        self.grobid_fallback_hosts: List[str] = [
            h.strip() for h in fallback_str.split(',') if h.strip()
        ] if fallback_str else []
        
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
        
        # Try primary host first, then any configured fallback hosts
        hosts_to_try: List[str] = [self.grobid_host]
        for h in self.grobid_fallback_hosts:
            if h not in hosts_to_try:
                hosts_to_try.append(h)

        # Option A (start first): run one start step up-front if configured
        primary_host = hosts_to_try[0].strip() if hosts_to_try else self.grobid_host
        is_primary_local = self._is_localhost(primary_host)

        if is_primary_local and self.grobid_auto_start:
            # Ensure flags/host match the primary before starting local container
            self.grobid_host = primary_host
            self.is_local_grobid = True
            self.logger.info("Auto-start enabled for local GROBID; starting container before health checks...")
            self._start_local_grobid()
        elif (not is_primary_local) and self.grobid_remote_auto_start:
            ssh_host = (self.grobid_remote_ssh_host or primary_host).strip()
            self.logger.info(f"Auto-start enabled for remote GROBID; attempting remote start on {ssh_host}...")
            self._try_remote_grobid_start(ssh_host)
        
        last_error = None
        
        for host in hosts_to_try:
            # Update current host and locality flag
            self.grobid_host = host.strip()
            self.is_local_grobid = self._is_localhost(self.grobid_host)
            
            # Create GROBID client for this host
            grobid_url = f"http://{self.grobid_host}:{self.grobid_port}"
            self.grobid_client = GrobidClient(grobid_url, config=grobid_config)
            
            # Check if available
            is_available, error_msg = self.check_grobid_health()
            last_error = error_msg
            
            if is_available:
                self.grobid_ready = True
                location = "Local" if self.is_local_grobid else f"Remote ({self.grobid_host})"
                self.logger.info(f"GROBID initialized successfully ({location})")
                return True
            else:
                location = "local" if self.is_local_grobid else f"remote ({self.grobid_host})"
                self.logger.warning(f"GROBID not available on {location} host {self.grobid_host}: {error_msg}")
        
        self.grobid_ready = False
        location = "local" if self.is_local_grobid else f"remote ({self.grobid_host})"
        self.logger.warning(f"GROBID not available ({location}): {last_error}")
        return False

    def _try_remote_grobid_start(self, ssh_host: str) -> bool:
        """Attempt to start remote GROBID via SSH.

        Runs a configured command on a remote host (e.g. 'docker start grobid').
        This method does not validate GROBID readiness; it only executes the command.
        """
        if not ssh_host:
            self.logger.warning("Remote GROBID SSH host is empty; skipping remote start")
            return False

        ssh_target = (
            f"{self.grobid_remote_ssh_user}@{ssh_host}"
            if self.grobid_remote_ssh_user
            else ssh_host
        )

        try:
            result = subprocess.run(
                [
                    'ssh',
                    '-o', 'BatchMode=yes',
                    '-o', 'ConnectTimeout=10',
                    ssh_target,
                    self.grobid_remote_start_command,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if result.returncode == 0:
                self.logger.debug("Remote start command completed successfully")
                return True

            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            msg = stderr if stderr else stdout if stdout else f"exit code {result.returncode}"
            self.logger.warning(f"Remote start command failed: {msg}")
            return False
        except Exception as e:
            self.logger.warning(f"Remote start command failed: {e}")
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

        def check_grobid() -> Tuple[bool, Optional[str]]:
            tcp_ok, tcp_err = self._tcp_can_connect(
                host=self.grobid_host,
                port=self.grobid_port,
                timeout_s=self.grobid_tcp_precheck_timeout,
            )
            if not tcp_ok:
                return False, f"TCP connect failed: {tcp_err}"

            response = requests.get(health_url, timeout=self.health_check_timeout)
            body = (response.text or "").strip()
            if response.status_code == 200 and body == "true":
                return True, None

            preview = body[:200]
            return False, f"HTTP bad response: status={response.status_code} body={preview!r}"
        
        return self._check_service_health(
            service_name="GROBID",
            health_url=health_url,
            health_check_fn=check_grobid
        )
    
    def check_ollama_health(self) -> Tuple[bool, Optional[str]]:
        """Check Ollama health with retries and exponential backoff.
        
        Returns:
            Tuple of (is_healthy, error_message)
        """
        if not self.ollama_client:
            return False, "Ollama client not initialized"
        
        health_url = f"http://{self.ollama_host}:{self.ollama_port}/api/tags"
        
        def check_ollama() -> Tuple[bool, Optional[str]]:
            response = requests.get(health_url, timeout=self.health_check_timeout)
            if response.status_code == 200:
                return True, None
            return False, f"HTTP bad response: status={response.status_code}"
        
        return self._check_service_health(
            service_name="Ollama",
            health_url=health_url,
            health_check_fn=check_ollama
        )
    
    def _check_service_health(
        self,
        service_name: str,
        health_url: str,
        health_check_fn: Callable[[], Tuple[bool, Optional[str]]]
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
                ok, msg = health_check_fn()
                if ok:
                    return True, None
                last_error = msg or f"{service_name} health check returned False"
            except requests.ConnectionError as e:
                last_error = f"Connection error: {e}"
            except requests.Timeout:
                last_error = f"Timeout after {self.health_check_timeout}s"
            except requests.RequestException as e:
                last_error = f"Request error: {e}"
            
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

    @staticmethod
    def _tcp_can_connect(host: str, port: int, timeout_s: float) -> Tuple[bool, Optional[str]]:
        """Fast TCP connectivity probe to separate network vs HTTP/service failures."""
        try:
            conn = socket.create_connection((host, port), timeout=timeout_s)
            conn.close()
            return True, None
        except socket.gaierror as e:
            return False, f"DNS error: {e}"
        except TimeoutError:
            return False, f"timeout after {timeout_s}s"
        except OSError as e:
            return False, str(e)
    
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
        # FIX: Added JVM memory options (-Xmx2g -Xms2g -XX:+UseG1GC) to address intermittent availability
        # The G1GC garbage collector is better for handling native memory fragmentation from ML libraries
        result = subprocess.run([
            'docker', 'run', '-d',
            '--name', self.grobid_container_name,
            '-p', f'{self.grobid_port}:8070',
            '-e', 'GROBID_SERVICE_OPTS=-Xmx2g -Xms2g -XX:+UseG1GC -Djava.library.path=grobid-home/lib/lin-64:grobid-home/lib/lin-64/jep',
            '--memory', '4g',
            '--memory-swap', '4g',
            '--restart', 'unless-stopped',
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
