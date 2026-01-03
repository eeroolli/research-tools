#!/usr/bin/env python3
"""
Example demonstrating Unicode sanitization.

This shows what text needs to be sanitized and why.
"""

# Example 1: Normal text (works fine)
normal_text = 'Hushåll och Arbetsløshet - Postenkät om det sosiala nätverkets betydning'
print("=" * 70)
print("EXAMPLE 1: Normal text with special characters")
print("=" * 70)
print(f"Text: {normal_text}")
try:
    normal_text.encode('utf-8')
    print("✅ Encodes to UTF-8 successfully - NO sanitization needed")
except UnicodeEncodeError as e:
    print(f"❌ Encoding error: {e}")

print()

# Example 2: Text with invalid surrogate (what causes the error)
# This simulates what happens when text contains UTF-16 surrogates
# In real scenarios, this can happen from:
# - Copy/paste from certain Windows applications
# - Incorrect encoding conversions
# - Corrupted clipboard data

print("=" * 70)
print("EXAMPLE 2: Text with invalid Unicode surrogate")
print("=" * 70)

# Create a string with a surrogate character
# Surrogates are in range U+D800 to U+DFFF
# The error message showed '\udcc3' which is U+DCC3

# We can't directly create surrogates in Python string literals,
# but they can appear when text is incorrectly decoded
try:
    # Simulate: bytes that would decode to a surrogate if mishandled
    # In practice, this might come from:
    # - Copying text from a Windows application that uses UTF-16
    # - Incorrect encoding conversion
    # - Corrupted data
    
    # Create a string that would fail encoding
    # Using surrogatepass to allow surrogates (for demonstration)
    problematic_bytes = b'Text with \xed\xb0\x83 surrogate character'
    bad_text = problematic_bytes.decode('utf-8', errors='surrogatepass')
    
    print(f"Problematic text (contains surrogate): {repr(bad_text)}")
    print("Trying to encode to UTF-8 for JSON/API...")
    bad_text.encode('utf-8')
    print("✅ Encoded (unexpected - this shouldn't happen)")
except UnicodeEncodeError as e:
    print(f"❌ Encoding error: {e}")
    print("   This is EXACTLY what caused your Zotero API error!")
    print()
    print("The error was:")
    print("   'utf-8' codec can't encode character '\\udcc3' in position 54")
    print()
    print("This happens when:")
    print("  - Text contains UTF-16 surrogate characters")
    print("  - Python tries to encode to UTF-8 for JSON")
    print("  - UTF-8 cannot represent surrogates")
    
    # Show how sanitization fixes it
    print()
    print("=" * 70)
    print("EXAMPLE 3: How sanitization fixes it")
    print("=" * 70)
    
    # Sanitize the text
    sanitized = bad_text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
    print(f"Original (problematic): {repr(bad_text)}")
    print(f"Sanitized (fixed):      {repr(sanitized)}")
    print()
    
    try:
        sanitized.encode('utf-8')
        print("✅ Sanitized text encodes successfully!")
        print("   The surrogate was replaced with the replacement character ()")
        print("   Now it's safe to send to Zotero API")
    except Exception as e2:
        print(f"❌ Still has error: {e2}")

except Exception as e:
    print(f"Unexpected error: {e}")

print()
print("=" * 70)
print("REAL-WORLD EXAMPLE")
print("=" * 70)
print("In your case, the title was:")
print("  'Hushåll och Arbetsløshet - Postenkät om det sosiala nätverkets betydning'")
print()
print("At position 54, there was likely a corrupted character (surrogate)")
print("that came from:")
print("  - Copy/paste from a document")
print("  - Scanner OCR output")
print("  - Encoding conversion issue")
print()
print("The sanitization function now:")
print("  1. Detects these problematic characters")
print("  2. Replaces them with safe characters")
print("  3. Ensures all text can be encoded to UTF-8")
print("  4. Prevents the Zotero API error")

