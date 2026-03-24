#!/usr/bin/env python3
"""
User interaction module for daemon operations.

Provides menu display, navigation, prompts, and input handling with timeout support.
"""

import logging
import signal
from pathlib import Path
from typing import Optional, Callable, Any, List

from shared_tools.daemon.exceptions import DaemonError
from shared_tools.daemon.constants import DaemonConstants


class TimeoutError(DaemonError):
    """Exception raised when user input times out."""
    pass


class UserInteraction:
    """Handles user interaction (menus, prompts, input)."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize user interaction handler.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.prompt_timeout = DaemonConstants.PROMPT_TIMEOUT
    
    def prompt_with_timeout(
        self,
        prompt: str,
        timeout: Optional[int] = None,
        default: Optional[str] = None
    ) -> Optional[str]:
        """Prompt user for input with timeout.
        
        Args:
            prompt: Prompt text to display
            timeout: Timeout in seconds (uses default if None)
            default: Default value to return on timeout
            
        Returns:
            User input string, default value on timeout, or None if cancelled
            
        Raises:
            TimeoutError: If timeout occurs and no default provided
        """
        timeout = timeout or self.prompt_timeout
        
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Input timeout after {timeout} seconds")
        
        # Set up signal handler for timeout (Unix only)
        try:
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)
        except (AttributeError, OSError):
            # Windows doesn't support SIGALRM
            # For Windows, we'll just use regular input (no timeout)
            pass
        
        try:
            try:
                response = input(prompt).strip()
                return response if response else default
            except (KeyboardInterrupt, EOFError):
                return None
        except TimeoutError:
            if default is not None:
                return default
            raise
        finally:
            # Restore signal handler and cancel alarm
            try:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
            except (AttributeError, OSError):
                pass
    
    def prompt_yes_no(
        self,
        prompt: str,
        default: Optional[bool] = None,
        timeout: Optional[int] = None
    ) -> Optional[bool]:
        """Prompt user for yes/no answer.
        
        Args:
            prompt: Prompt text to display
            default: Default value (True/False) or None for no default
            timeout: Timeout in seconds
            
        Returns:
            True for yes, False for no, None if cancelled or timeout with no default
        """
        default_str = " [Y/n]" if default is True else (" [y/N]" if default is False else " [y/n]")
        full_prompt = f"{prompt}{default_str}: "
        
        try:
            response = self.prompt_with_timeout(full_prompt, timeout=timeout, default="")
            if not response:
                return default
            
            response_lower = response.lower().strip()
            if response_lower in ('y', 'yes'):
                return True
            elif response_lower in ('n', 'no'):
                return False
            else:
                # Invalid input, return default or ask again
                return default
        except TimeoutError:
            return default
    
    def display_menu(self, title: str, options: List[str], prompt: str = "Choice: ") -> Optional[str]:
        """Display a menu and get user choice.
        
        Args:
            title: Menu title
            options: List of option strings
            prompt: Prompt text for input
            
        Returns:
            User's choice string, or None if cancelled
        """
        print(f"\n{title}")
        print("-" * len(title))
        for i, option in enumerate(options, 1):
            print(f"{i}. {option}")
        print()
        
        try:
            choice = input(prompt).strip()
            return choice
        except (KeyboardInterrupt, EOFError):
            return None
    
    def prompt_for_page_offset(
        self,
        pdf_path: Path,
        timeout: Optional[int] = None
    ) -> Optional[int]:
        """Prompt user for page offset.
        
        Args:
            pdf_path: Path to PDF file
            timeout: Timeout in seconds (uses page offset timeout if None)
            
        Returns:
            Page offset (0-indexed), or None if cancelled/timeout
        """
        timeout = timeout or DaemonConstants.PAGE_OFFSET_TIMEOUT
        
        prompt = f"Enter page number to start from (1 = first page, or Enter to skip): "
        
        try:
            response = self.prompt_with_timeout(prompt, timeout=timeout, default="")
            if not response:
                return None
            
            try:
                page_num = int(response)
                if page_num < 1:
                    self.logger.warning(f"Invalid page number: {page_num}")
                    return None
                # Convert to 0-indexed offset
                return page_num - 1
            except ValueError:
                self.logger.warning(f"Invalid input: {response}")
                return None
        except TimeoutError:
            self.logger.info("Page offset prompt timed out")
            return None

