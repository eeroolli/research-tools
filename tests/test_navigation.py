"""Tests for page-based navigation system."""

import unittest
from pathlib import Path
from shared_tools.ui.navigation import (
    NavigationResult,
    Page,
    ItemSelectedContext,
    NavigationEngine
)


class TestNavigationResult(unittest.TestCase):
    """Test NavigationResult class."""
    
    def test_show_page(self):
        """Test show_page result."""
        result = NavigationResult.show_page('next_page')
        self.assertEqual(result.type, NavigationResult.Type.SHOW_PAGE)
        self.assertEqual(result.page_id, 'next_page')
    
    def test_return_to_caller(self):
        """Test return_to_caller result."""
        result = NavigationResult.return_to_caller()
        self.assertEqual(result.type, NavigationResult.Type.RETURN_TO_CALLER)
    
    def test_quit_scan(self):
        """Test quit_scan result."""
        result = NavigationResult.quit_scan(move_to_manual=True)
        self.assertEqual(result.type, NavigationResult.Type.QUIT_SCAN)
        self.assertTrue(result.move_to_manual)
    
    def test_process_pdf(self):
        """Test process_pdf result."""
        result = NavigationResult.process_pdf()
        self.assertEqual(result.type, NavigationResult.Type.PROCESS_PDF)
    
    def test_equality(self):
        """Test result equality."""
        r1 = NavigationResult.show_page('page1')
        r2 = NavigationResult.show_page('page1')
        r3 = NavigationResult.show_page('page2')
        self.assertEqual(r1, r2)
        self.assertNotEqual(r1, r3)


class TestItemSelectedContext(unittest.TestCase):
    """Test ItemSelectedContext class."""
    
    def test_to_dict(self):
        """Test context to dict conversion."""
        pdf_path = Path('/test/file.pdf')
        metadata = {'title': 'Test Paper'}
        selected_item = {'key': 'ABC123', 'title': 'Test', 'authors': ['Author1']}
        
        context = ItemSelectedContext(
            pdf_path=pdf_path,
            metadata=metadata,
            selected_item=selected_item,
            item_key='ABC123',
            target_filename='test.pdf'
        )
        
        ctx_dict = context.to_dict()
        self.assertEqual(ctx_dict['pdf_path'], pdf_path)
        self.assertEqual(ctx_dict['item_key'], 'ABC123')
        self.assertEqual(ctx_dict['target_filename'], 'test.pdf')
        self.assertEqual(ctx_dict['zotero_title'], 'Test')


class TestPage(unittest.TestCase):
    """Test Page dataclass."""
    
    def test_page_creation(self):
        """Test creating a page."""
        def content(ctx):
            return ["Line 1", "Line 2"]
        
        handlers = {
            'y': lambda ctx: NavigationResult.process_pdf(),
            'n': lambda ctx: NavigationResult.return_to_caller()
        }
        
        page = Page(
            page_id='test_page',
            title='TEST PAGE',
            content=content,
            prompt='Choose [y/n]: ',
            valid_inputs=['y', 'n'],
            handlers=handlers,
            default='y',
            back_page='previous_page'
        )
        
        self.assertEqual(page.page_id, 'test_page')
        self.assertEqual(page.default, 'y')
        self.assertEqual(page.back_page, 'previous_page')
        self.assertIn('z', page.valid_inputs)  # Should be auto-added
    
    def test_page_auto_adds_standard_commands(self):
        """Test that page auto-adds z and q to valid_inputs."""
        def quit_action(ctx):
            return NavigationResult.quit_scan()
        
        page = Page(
            page_id='test',
            title='Test',
            content=lambda ctx: [],
            prompt='> ',
            valid_inputs=['y'],
            handlers={},
            back_page='prev',
            quit_action=quit_action
        )
        
        self.assertIn('z', page.valid_inputs)
        self.assertIn('q', page.valid_inputs)


class TestNavigationEngine(unittest.TestCase):
    """Test NavigationEngine class."""
    
    def test_standardize_input(self):
        """Test input standardization."""
        page = Page(
            page_id='test',
            title='Test',
            content=lambda ctx: [],
            prompt='> ',
            valid_inputs=['y', 'n'],
            handlers={},
            default='y'
        )
        
        engine = NavigationEngine({})
        
        # Empty input should become default
        self.assertEqual(engine.standardize_input('', page), 'y')
        # Non-empty should pass through
        self.assertEqual(engine.standardize_input('n', page), 'n')
    
    def test_validate_input(self):
        """Test input validation."""
        page = Page(
            page_id='test',
            title='Test',
            content=lambda ctx: [],
            prompt='> ',
            valid_inputs=['y', 'n', 'z'],
            handlers={}
        )
        
        engine = NavigationEngine({})
        
        self.assertTrue(engine.validate_input('y', page))
        self.assertTrue(engine.validate_input('z', page))
        self.assertFalse(engine.validate_input('x', page))


if __name__ == '__main__':
    unittest.main()

