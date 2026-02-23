# Storage Optimization: Moving Scanner Folder to SSD

## Quick Answer

**Yes, moving the scanner folder from I: (HDD) to F: (SSD) will help, but the benefit is minor compared to OCR optimization.**

## Analysis

### Current Setup
- **I: drive**: HDD on blacktower (current scanner destination)
- **F: drive**: SSD on blacktower (network share, accessible from p1)
- **User observation**: HDD (I:) doesn't feel slow

### Why Moving to F: (SSD) Helps

**File I/O Performance:**
- **HDD (I:)**: ~100-200 MB/s sequential, ~1-2 MB/s random
- **SSD (F:)**: ~500-2000 MB/s sequential, ~50-100 MB/s random
- **Improvement**: 2-10x faster for file operations

**However:**
- If OCR takes 30-60s, file I/O improvements save only 1-2s
- **OCR is the bottleneck**, not file I/O
- User says HDD doesn't feel slow (confirms I/O isn't the problem)

### Benefits of Moving to F: (SSD)

1. **Faster file detection** (daemon watching directory)
2. **Faster file copying** (if copying to local temp)
3. **Better for parallel processing** (multiple PDFs)
4. **Future-proof** (SSD is better for all operations)

### Recommendation

**Move to F: (SSD) as part of Option A implementation:**

1. **Move scanner folder**: `I:\FraScanner\papers\` → `F:\FraScanner\papers\`
2. **Update Epson settings**: Save to F: (SSD)
3. **Update daemon config**: Watch F: (SSD)
4. **Benefit**: Minor I/O improvement, but **primary benefit is GPU OCR** (5-10x faster)

**Expected Impact:**
- **File I/O**: 2-10x faster (saves 1-2s per paper)
- **OCR**: Still bottleneck if done on CPU (30-60s)
- **Overall**: Minor improvement without GPU OCR, **major improvement with GPU OCR**

## Implementation Steps

### Step 1: Move Scanner Folder

**On blacktower:**
```powershell
# Create destination folder
New-Item -ItemType Directory -Path "F:\FraScanner\papers" -Force

# Move existing files (if any)
Move-Item -Path "I:\FraScanner\papers\*" -Destination "F:\FraScanner\papers\" -Force

# Verify
Get-ChildItem "F:\FraScanner\papers\"
```

### Step 2: Update Epson Capture Pro

1. Open Epson Capture Pro
2. Edit job/profile settings
3. Change save location: `I:\FraScanner\papers\` → `F:\FraScanner\papers\`
4. Save settings

### Step 3: Update Daemon Config

**Edit `config.personal.conf`:**
```ini
[PATHS]
# Change from:
scanner_papers_dir = /mnt/i/FraScanner/papers
# To:
scanner_papers_dir = /mnt/f/FraScanner/papers
```

### Step 4: Test

1. Scan a test document
2. Verify it saves to F: (SSD)
3. Verify daemon detects it
4. Check processing speed

## Performance Comparison

### Current (I: HDD)
- **File detection**: ~0.1-0.5s (acceptable)
- **File copy**: ~1-2s for 10MB PDF (acceptable)
- **OCR**: 30-60s (CPU) - **BOTTLENECK**

### With F: SSD
- **File detection**: ~0.05-0.2s (2x faster) - **MINOR**
- **File copy**: ~0.5-1s for 10MB PDF (2x faster) - **MINOR**
- **OCR**: 30-60s (CPU) - **STILL BOTTLENECK**

### With F: SSD + GPU OCR
- **File detection**: ~0.05-0.2s (2x faster) - **MINOR**
- **File copy**: ~0.5-1s for 10MB PDF (2x faster) - **MINOR**
- **OCR**: 3-12s (GPU) - **5-10x FASTER** ⭐ **MAJOR**

## Conclusion

**Move to F: (SSD) as part of the optimization, but don't expect major improvements without GPU OCR.**

**Priority:**
1. ✅ **Move to F: (SSD)** - Easy, minor benefit
2. ✅ **Add GPU OCR** - Hard, major benefit (5-10x faster)
3. ✅ **Combine both** - Best performance

**Expected Overall Improvement:**
- **F: SSD alone**: ~5-10% faster (saves 1-2s per paper)
- **GPU OCR alone**: ~300-500% faster (saves 25-50s per paper)
- **Both combined**: ~350-550% faster (saves 26-52s per paper)

---

*Move to F: (SSD) is a good optimization, but GPU OCR provides the real performance gain.*

