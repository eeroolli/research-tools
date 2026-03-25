#!/usr/bin/env python3
"""
Unit tests for ServiceManager module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import configparser

from shared_tools.daemon.service_manager import ServiceManager


class TestServiceManager(unittest.TestCase):
    """Test cases for ServiceManager."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = configparser.ConfigParser()
        self.config.add_section('GROBID')
        self.config.add_section('OLLAMA')
        self.config.add_section('SERVICE_RESILIENCE')
        
        # Default config values
        self.config.set('GROBID', 'host', 'localhost')
        self.config.set('GROBID', 'port', '8070')
        self.config.set('GROBID', 'auto_start', 'true')
        self.config.set('OLLAMA', 'host', 'localhost')
        self.config.set('OLLAMA', 'port', '11434')
        self.config.set('OLLAMA', 'auto_start', 'true')
        self.config.set('SERVICE_RESILIENCE', 'health_check_timeout', '5')
        self.config.set('SERVICE_RESILIENCE', 'health_check_retries', '3')
    
    def test_init_localhost(self):
        """Test ServiceManager initialization with localhost."""
        manager = ServiceManager(self.config)
        self.assertTrue(manager.is_local_grobid)
        self.assertTrue(manager.is_local_ollama)
    
    def test_init_remote(self):
        """Test ServiceManager initialization with remote host."""
        self.config.set('GROBID', 'host', '192.168.1.100')
        manager = ServiceManager(self.config)
        self.assertFalse(manager.is_local_grobid)
        self.assertTrue(manager.is_local_ollama)  # Ollama still localhost
    
    @patch('shared_tools.daemon.service_manager.GrobidClient')
    @patch('shared_tools.daemon.service_manager.socket.create_connection')
    @patch('shared_tools.daemon.service_manager.requests.get')
    def test_initialize_grobid_success(self, mock_get, mock_conn, mock_grobid_client):
        """Test successful GROBID initialization."""
        mock_grobid_client.return_value = Mock()
        mock_conn.return_value = MagicMock(close=Mock())
        mock_get.return_value = MagicMock(status_code=200, text='true')
        
        manager = ServiceManager(self.config)
        result = manager.initialize_grobid()
        
        self.assertTrue(result)
        self.assertTrue(manager.grobid_ready)
        self.assertIsNotNone(manager.grobid_client)
    
    @patch('shared_tools.daemon.service_manager.OllamaClient')
    @patch('shared_tools.daemon.service_manager.requests')
    def test_initialize_ollama_success(self, mock_requests, mock_ollama_client):
        """Test successful Ollama initialization."""
        # Mock Ollama health check
        mock_requests.get.return_value.status_code = 200
        
        mock_client_instance = Mock()
        mock_ollama_client.return_value = mock_client_instance
        
        manager = ServiceManager(self.config)
        result = manager.initialize_ollama()
        
        self.assertTrue(result)
        self.assertTrue(manager.ollama_ready)
        self.assertIsNotNone(manager.ollama_client)
    
    @patch('shared_tools.daemon.service_manager.GrobidClient')
    @patch('shared_tools.daemon.service_manager.socket.create_connection')
    @patch('shared_tools.daemon.service_manager.requests.get')
    def test_initialize_grobid_failure(self, mock_get, mock_conn, mock_grobid_client):
        """Test GROBID initialization failure."""
        mock_grobid_client.return_value = Mock()
        # TCP connect fails quickly; should not try HTTP at all
        mock_conn.side_effect = OSError("No route to host")
        
        manager = ServiceManager(self.config)
        result = manager.initialize_grobid()
        
        self.assertFalse(result)
        self.assertFalse(manager.grobid_ready)
        mock_get.assert_not_called()

    @patch('shared_tools.daemon.service_manager.subprocess.run')
    @patch('shared_tools.daemon.service_manager.requests.get')
    @patch('shared_tools.daemon.service_manager.socket.create_connection')
    @patch('shared_tools.daemon.service_manager.GrobidClient')
    def test_initialize_grobid_remote_autostart_runs_ssh(self, mock_grobid_client, mock_conn, mock_get, mock_run):
        """Remote auto-start should run SSH command once before health checks."""
        self.config.set('GROBID', 'host', '192.168.1.100')
        self.config.set('GROBID', 'auto_start', 'true')
        self.config.set('GROBID', 'remote_auto_start', 'true')
        self.config.set('GROBID', 'remote_ssh_host', 'p1')
        self.config.set('GROBID', 'remote_ssh_user', '')
        self.config.set('GROBID', 'remote_start_command', 'docker start grobid')

        # SSH command succeeds
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        # TCP connect succeeds
        mock_conn.return_value = MagicMock(close=Mock())
        # Health check succeeds
        mock_get.return_value = MagicMock(status_code=200, text='true')
        mock_grobid_client.return_value = Mock()

        manager = ServiceManager(self.config)
        result = manager.initialize_grobid()
        self.assertTrue(result)

        mock_run.assert_called()
        called_args = mock_run.call_args[0][0]
        self.assertEqual(called_args[0], 'ssh')
        self.assertIn('BatchMode=yes', called_args)
        self.assertIn('ConnectTimeout=10', called_args)
        self.assertIn('p1', called_args)
        self.assertIn('docker start grobid', called_args)

    @patch('shared_tools.daemon.service_manager.socket.create_connection')
    @patch('shared_tools.daemon.service_manager.requests.get')
    @patch('shared_tools.daemon.service_manager.GrobidClient')
    def test_check_grobid_health_tcp_failure_reports_tcp(self, mock_grobid_client, mock_get, mock_conn):
        """TCP precheck failure should be reported as TCP connect failure."""
        mock_grobid_client.return_value = Mock()
        mock_conn.side_effect = OSError("No route to host")
        manager = ServiceManager(self.config)
        manager.grobid_client = Mock()
        ok, err = manager.check_grobid_health()
        self.assertFalse(ok)
        self.assertIn("TCP connect failed", err)
        mock_get.assert_not_called()


if __name__ == '__main__':
    unittest.main()

