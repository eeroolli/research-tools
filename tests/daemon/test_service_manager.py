#!/usr/bin/env python3
"""
Unit tests for ServiceManager module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import configparser
from pathlib import Path

from shared_tools.daemon.service_manager import ServiceManager
from shared_tools.daemon.exceptions import ServiceError


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
    @patch('shared_tools.daemon.service_manager.requests')
    def test_initialize_grobid_success(self, mock_requests, mock_grobid_client):
        """Test successful GROBID initialization."""
        # Mock GROBID client and health check
        mock_client_instance = Mock()
        mock_client_instance.is_available.return_value = True
        mock_grobid_client.return_value = mock_client_instance
        
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
    @patch('shared_tools.daemon.service_manager.requests')
    def test_initialize_grobid_failure(self, mock_requests, mock_grobid_client):
        """Test GROBID initialization failure."""
        # Mock GROBID client and health check failure
        mock_client_instance = Mock()
        mock_client_instance.is_available.return_value = False
        mock_grobid_client.return_value = mock_client_instance
        
        manager = ServiceManager(self.config)
        result = manager.initialize_grobid()
        
        self.assertFalse(result)
        self.assertFalse(manager.grobid_ready)


if __name__ == '__main__':
    unittest.main()

