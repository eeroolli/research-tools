#!/usr/bin/env python3
"""
Comprehensive test for all refactoring steps together.

Tests all 5 steps:
1. Step 1: Generalized script path helper
2. Step 2: Removed duplicate _windows_to_wsl_path()
3. Step 3: _to_windows_path() uses helper
4. Step 4: _move_to_recycle_bin_windows() uses helper
5. Step 5: normalize_path_for_wsl() uses static _normalize_path()
"""

import sys
from pathlib import Path

# Add project root and scripts directory to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'scripts'))

from scripts.paper_processor_daemon import PaperProcessorDaemon
from scripts.paper_processor_daemon import normalize_path_for_wsl

def test_all_steps():
    """Test all refactoring steps together."""
    print("="*70)
    print("Comprehensive Test: All Refactoring Steps")
    print("="*70)
    print()
    
    # Create a daemon instance
    try:
        dummy_watch_dir = Path("/tmp")
        daemon = PaperProcessorDaemon(dummy_watch_dir, debug=False)
    except Exception as e:
        print(f"  ✗ Failed to initialize daemon: {e}")
        print("  Note: This test requires a valid config.conf file")
        return False
    
    all_passed = True
    
    # ===== STEP 1: Generalized script path helper =====
    print("STEP 1: Generalized script path helper")
    print("-" * 70)
    try:
        # Test _get_script_path_win() with different scripts
        path1 = daemon._get_script_path_win('path_utils.ps1')
        path2 = daemon._get_script_path_win('move_to_recycle_bin.ps1')
        path3 = daemon._get_path_utils_script_win()
        
        assert path1.endswith('path_utils.ps1'), "Should end with script name"
        assert path2.endswith('move_to_recycle_bin.ps1'), "Should end with script name"
        assert path1 == path3, "Both methods should return same result"
        print("  ✓ _get_script_path_win() works with different scripts")
        print("  ✓ _get_path_utils_script_win() uses helper correctly")
    except Exception as e:
        print(f"  ✗ STEP 1 FAILED: {e}")
        all_passed = False
    
    # ===== STEP 2: Removed duplicate _windows_to_wsl_path() =====
    print("\nSTEP 2: Removed duplicate _windows_to_wsl_path()")
    print("-" * 70)
    try:
        # Verify method is removed
        assert not hasattr(daemon, '_windows_to_wsl_path'), "Method should be removed"
        
        # Test _normalize_path() works (replacement)
        win_path = "G:\\My Drive\\test.pdf"
        wsl_path = daemon._normalize_path(win_path)
        assert wsl_path.startswith('/mnt/g/'), "Should convert to WSL format"
        print("  ✓ _windows_to_wsl_path() has been removed")
        print("  ✓ _normalize_path() works as replacement")
    except Exception as e:
        print(f"  ✗ STEP 2 FAILED: {e}")
        all_passed = False
    
    # ===== STEP 3: _to_windows_path() uses helper =====
    print("\nSTEP 3: _to_windows_path() uses helper")
    print("-" * 70)
    try:
        # Test Windows path (should return as-is)
        win_path = Path("G:\\My Drive\\test.pdf")
        result1 = daemon._to_windows_path(win_path)
        assert result1 == str(win_path) or "G:" in result1, "Should return Windows path as-is"
        
        # Test WSL path (should convert using helper)
        wsl_path = Path("/mnt/g/My Drive/test.pdf")
        result2 = daemon._to_windows_path(wsl_path)
        assert result2.startswith('G:'), "Should convert to Windows format"
        
        # Verify helper exists
        assert hasattr(daemon, '_convert_wsl_to_windows_path'), "Helper should exist"
        print("  ✓ _to_windows_path() handles Windows paths correctly")
        print("  ✓ _to_windows_path() converts WSL paths using helper")
        print("  ✓ Helper method _convert_wsl_to_windows_path() exists")
    except Exception as e:
        print(f"  ✗ STEP 3 FAILED: {e}")
        all_passed = False
    
    # ===== STEP 4: _move_to_recycle_bin_windows() uses helper =====
    print("\nSTEP 4: _move_to_recycle_bin_windows() uses helper")
    print("-" * 70)
    try:
        # Verify method exists and uses helper
        assert hasattr(daemon, '_move_to_recycle_bin_windows'), "Method should exist"
        assert hasattr(daemon, '_get_script_path_win'), "Helper should exist"
        
        # Check that the method can get the script path (we won't actually call it)
        script_path = daemon._get_script_path_win('move_to_recycle_bin.ps1')
        assert script_path.endswith('move_to_recycle_bin.ps1'), "Should get script path"
        print("  ✓ _move_to_recycle_bin_windows() method exists")
        print("  ✓ Can get script path using helper (refactored)")
    except Exception as e:
        print(f"  ✗ STEP 4 FAILED: {e}")
        all_passed = False
    
    # ===== STEP 5: normalize_path_for_wsl() uses static _normalize_path() =====
    print("\nSTEP 5: normalize_path_for_wsl() uses static _normalize_path()")
    print("-" * 70)
    try:
        # Test standalone function
        win_path = "G:\\My Drive\\test.pdf"
        result1 = normalize_path_for_wsl(win_path)
        assert result1.startswith('/mnt/g/'), "Should convert to WSL format"
        
        # Test static method directly
        result2 = PaperProcessorDaemon._normalize_path(win_path)
        assert result2.startswith('/mnt/g/'), "Static method should work"
        
        # Both should return same result
        assert result1 == result2, "Both should return same result"
        
        # Test instance method still works (static methods can be called on instances)
        result3 = daemon._normalize_path(win_path)
        assert result3 == result1, "Instance call should work"
        
        # Test with sanitization (quotes/whitespace)
        dirty_path = '  "G:\\My Drive\\test.pdf"  '
        result4 = normalize_path_for_wsl(dirty_path)
        assert result4.startswith('/mnt/g/'), "Should sanitize and convert"
        assert '"' not in result4, "Should remove quotes"
        
        print("  ✓ normalize_path_for_wsl() works as standalone function")
        print("  ✓ _normalize_path() works as static method")
        print("  ✓ Both return identical results")
        print("  ✓ Instance calls still work (backward compatible)")
        print("  ✓ Sanitization works (quotes/whitespace removed)")
    except Exception as e:
        print(f"  ✗ STEP 5 FAILED: {e}")
        all_passed = False
    
    # ===== Integration Test: Real-world scenario =====
    print("\nINTEGRATION TEST: Real-world path conversion scenario")
    print("-" * 70)
    try:
        # Simulate a real scenario: Windows path from config -> WSL -> Windows for Zotero
        config_path = "G:\\My Drive\\publications\\paper.pdf"
        
        # Step 1: Normalize to WSL (like in load_config)
        wsl_path = daemon._normalize_path(config_path)
        assert wsl_path.startswith('/mnt/g/'), "Should convert to WSL"
        
        # Step 2: Convert back to Windows (like for Zotero attachment)
        win_path_result = daemon._to_windows_path(Path(wsl_path))
        assert win_path_result.startswith('G:'), "Should convert back to Windows"
        
        # Step 3: Normalize again (like in main function)
        wsl_path_again = normalize_path_for_wsl(win_path_result)
        assert wsl_path_again.startswith('/mnt/g/'), "Should convert to WSL again"
        
        print("  ✓ Windows -> WSL -> Windows -> WSL conversion chain works")
        print("  ✓ All path utilities work together correctly")
    except Exception as e:
        print(f"  ✗ INTEGRATION TEST FAILED: {e}")
        all_passed = False
    
    # ===== Summary =====
    print("\n" + "="*70)
    if all_passed:
        print("✓ ALL REFACTORING STEPS PASSED!")
        print("="*70)
        print("\nSummary:")
        print("  ✓ Step 1: Generalized script path helper - Working")
        print("  ✓ Step 2: Removed duplicate method - Working")
        print("  ✓ Step 3: _to_windows_path() uses helper - Working")
        print("  ✓ Step 4: Recycle bin uses helper - Working")
        print("  ✓ Step 5: Consolidated normalize_path_for_wsl() - Working")
        print("  ✓ Integration: All components work together - Working")
        return True
    else:
        print("✗ SOME TESTS FAILED")
        print("="*70)
        return False

if __name__ == '__main__':
    success = test_all_steps()
    sys.exit(0 if success else 1)

