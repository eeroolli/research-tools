# Distributed Processing Optimization Plan
## Multi-Computer Scanning Workflow Analysis

**Date:** 2025-01-XX  
**Context:** Optimizing paper scanning workflow across p1 (ThinkPad P1) and blacktower (network scanner host)

---

## Current Architecture Analysis

### Hardware Configuration

**p1 (ThinkPad P1):**
- CPU: Intel i7 10th generation (8 cores, 16 threads)
- GPU: NVIDIA T1000 (4GB VRAM, CUDA support) + Intel UHD 640
- RAM: 32GB
- OS: Windows with WSL2
- Storage: Local SSD (fast I/O)

**blacktower (Lenovo M720t):**
- CPU: Intel i7 9th generation (6-8 cores, 12-16 threads)
- GPU: Intel UHD 640 (integrated graphics only)
- RAM: 32GB
- Network scanner host
- Scanner saves PDFs to `I:\FraScanner\papers\` (local drive on blacktower)
- Network share: F: drive mapped to p1 (from conversation summary)

**Hardware Comparison:**
- **CPU**: p1 has ~10-15% advantage (10th gen vs 9th gen, newer architecture)
- **GPU**: p1 has **significant advantage** (T1000 dedicated GPU vs UHD 640 only)
- **RAM**: Equal (32GB both)
- **Storage I/O**: p1 SSD vs blacktower (likely HDD or slower SSD) - **major advantage**

### Current Processing Flow

```
Scanner (blacktower) → I:\FraScanner\papers\ (network drive)
                           ↓
                    Daemon watches directory
                           ↓
                    GROBID (Docker, CPU) ~2-5s
                           ↓
                    User review (interactive)
                           ↓
                    Zotero integration
                           ↓
                    File copy to G:\My Drive\publications\
```

### Current Bottlenecks

1. **File I/O**: Network drive access (blacktower `I:\` → p1) - **PRIMARY BOTTLENECK**
2. **GROBID**: CPU-bound Docker container (~2-5s per paper) - Moderate bottleneck
3. **Sequential processing**: One PDF at a time - Moderate bottleneck
4. **Ollama**: CPU-bound LLM fallback (~30-60s per paper) - Rarely used (GROBID usually works)
5. **OCR**: Epson Document Capture Pro (CPU-only) - Usually done during scan, not a bottleneck
6. **GPU underutilization**: T1000 GPU not used for processing - **OPPORTUNITY**

---

## Optimization Strategies

### Strategy 1: Local File Copy + p1 Processing (RECOMMENDED)

**Architecture:**
```
Scanner (blacktower) → I:\FraScanner\papers\ (network)
                           ↓
                    Daemon on p1 watches network drive
                           ↓
                    Copy PDF to local temp directory (p1 SSD)
                           ↓
                    Process locally (GROBID, Ollama on p1)
                           ↓
                    Copy result to G:\My Drive\publications\
```

**Implementation:**
- Daemon runs on p1
- Watch network drive `I:\FraScanner\papers\`
- On file creation: Copy to local temp (`/tmp/paper_processing/` or `C:\temp\`)
- Process from local copy (faster I/O)
- Move original to `done/` on network drive after processing

**Pros:**
- ✅ **Fast local SSD I/O** (10-100x faster than network) - **PRIMARY BENEFIT**
- ✅ Uses p1's slightly faster CPU for GROBID/Ollama (minor benefit)
- ✅ Minimal changes to existing code
- ✅ Network drive only used for initial detection
- ✅ Can process multiple PDFs in parallel (local copies)
- ✅ Reduces network load on blacktower

**Cons:**
- ⚠️ Requires local temp storage (SSD space - minimal, ~10-50MB per PDF)
- ⚠️ Network copy adds ~1-2s per PDF (acceptable tradeoff for 10-20x faster processing)
- ⚠️ Two file copies (network → local, local → publications)

**Performance Gain:**
- **File I/O**: 10-50x faster (SSD vs network) - **MAJOR BENEFIT**
- **GROBID**: 1.1-1.2x faster (slightly better CPU on p1) - **MINOR BENEFIT**
- **Overall**: 2-3x faster per paper (primarily from I/O improvement)

**Code Changes:**
- Modify `PaperFileHandler.on_created()` to copy to local temp first
- Process from local copy
- Clean up local temp after processing

---

### Strategy 2: Distributed Processing (Daemon on p1, Heavy Work on blacktower)

**Architecture:**
```
Scanner (blacktower) → I:\FraScanner\papers\ (local to blacktower)
                           ↓
                    Daemon on p1 (lightweight watcher)
                           ↓
                    Remote processing request to blacktower
                           ↓
                    GROBID/Ollama on blacktower (via SSH/API)
                           ↓
                    Results sent back to p1
                           ↓
                    User review on p1
                           ↓
                    Zotero integration on p1
```

**Implementation:**
- Lightweight daemon on p1 watches network drive
- On file creation: Send processing request to blacktower
- blacktower runs GROBID/Ollama locally (faster network I/O)
- Results returned to p1 for user interaction
- p1 handles Zotero and file management

**Pros:**
- ✅ Leverages both machines
- ✅ blacktower processes files from local drive (fast I/O)
- ✅ p1 handles interactive UI (better for user experience)
- ✅ Can scale to multiple processing nodes

**Cons:**
- ❌ Complex architecture (network RPC/SSH)
- ❌ Network latency for results
- ❌ Requires blacktower to run processing services
- ❌ Error handling more complex
- ❌ Debugging harder (distributed system)

**Performance Gain:**
- **File I/O**: Fast (blacktower local drive)
- **Processing**: Depends on blacktower CPU (may be slower)
- **Overall**: Potentially slower due to network overhead

**Code Changes:**
- Major refactoring required
- Add remote processing client/server
- Add network communication layer
- Error handling for network failures

---

### Strategy 3: GPU-Accelerated OCR on p1 (T1000)

**Architecture:**
```
Scanner (blacktower) → I:\FraScanner\papers\ (network)
                           ↓
                    Daemon on p1
                           ↓
                    Copy to local temp
                           ↓
                    GPU OCR (T1000) instead of Epson CPU OCR
                           ↓
                    GROBID/Ollama on p1 CPU
                           ↓
                    User review
```

**Implementation:**
- Replace Epson Document Capture Pro OCR with GPU-accelerated OCR
- Use NVIDIA T1000 for OCR processing
- Options:
  - **EasyOCR** with CUDA (good accuracy, moderate speed)
  - **PaddleOCR** with CUDA (better GPU utilization)
  - **Tesseract with GPU wrapper** (if available)
  - **Custom OpenVINO** (Intel UHD 640, but T1000 better)

**Pros:**
- ✅ **GPU acceleration for OCR** (5-10x faster than CPU) - **SIGNIFICANT p1 ADVANTAGE**
- ✅ **T1000 has 4GB VRAM** (good for batch processing) - **p1 ONLY** (blacktower has no dedicated GPU)
- ✅ Frees CPU for GROBID/Ollama
- ✅ Can process multiple pages in parallel on GPU
- ✅ **Major advantage over blacktower** (which only has UHD 640, no CUDA support)

**Cons:**
- ⚠️ Requires CUDA setup and GPU drivers on p1
- ⚠️ Additional dependencies (PyTorch/CUDA libraries)
- ⚠️ May need model training/fine-tuning
- ⚠️ Epson scanner already does OCR (may be redundant)
- ⚠️ **Only works on p1** (blacktower can't use this - no T1000)

**Performance Gain:**
- **OCR**: 5-10x faster (if replacing Epson OCR) - **p1 ONLY** (T1000 advantage)
- **CPU availability**: More free for GROBID/Ollama
- **Overall**: 2-3x faster if OCR is bottleneck
- **Strategic advantage**: This optimization **only works on p1** (blacktower has no dedicated GPU)

**Code Changes:**
- Add GPU OCR module
- Configure CUDA environment
- Integrate with existing pipeline
- Fallback to CPU if GPU unavailable

**Note:** Epson Document Capture Pro already does OCR during scanning. This optimization only helps if:
1. You disable Epson OCR and do it yourself
2. You need additional OCR for already-scanned PDFs
3. You want better OCR quality than Epson provides

---

### Strategy 4: Parallel Processing (Multiple PDFs Simultaneously)

**Architecture:**
```
Scanner → Multiple PDFs in queue
              ↓
         Daemon processes queue
              ↓
    ┌─────────┼─────────┐
    ↓         ↓         ↓
GROBID-1  GROBID-2  GROBID-3  (parallel)
    ↓         ↓         ↓
User-1    User-2    User-3  (sequential review)
```

**Implementation:**
- Maintain processing queue
- Process multiple PDFs with GROBID in parallel (thread pool)
- User review remains sequential (one at a time)
- GROBID can handle multiple requests (Docker container)

**Pros:**
- ✅ Faster batch processing
- ✅ Better CPU utilization
- ✅ GROBID container can handle concurrent requests
- ✅ User review doesn't block processing

**Cons:**
- ⚠️ More complex queue management
- ⚠️ Memory usage increases (multiple PDFs in memory)
- ⚠️ User review still sequential (bottleneck)
- ⚠️ Error handling more complex

**Performance Gain:**
- **Batch processing**: 2-4x faster (depending on CPU cores)
- **User review**: No change (still sequential)
- **Overall**: 1.5-2x faster for batch scanning

**Code Changes:**
- Add processing queue
- Thread pool for GROBID requests
- Queue management for user review
- Memory management for parallel processing

---

### Strategy 5: Hybrid Approach (Combined Optimizations)

**Architecture:**
```
Scanner (blacktower) → I:\FraScanner\papers\ (network)
                           ↓
                    Daemon on p1 watches network drive
                           ↓
                    Copy to local temp (p1 SSD) - FAST I/O
                           ↓
                    Parallel processing queue
                    ┌──────┼──────┐
                    ↓      ↓      ↓
              GROBID-1  GROBID-2  GROBID-3  (parallel, p1 CPU)
                    ↓      ↓      ↓
              Results queue
                    ↓
              Sequential user review (p1)
                    ↓
              Zotero integration (p1)
                    ↓
              Copy to G:\My Drive\publications\
```

**Implementation:**
- Combine Strategy 1 (local copy) + Strategy 4 (parallel processing)
- Optional: Strategy 3 (GPU OCR) if needed
- Best of all worlds

**Pros:**
- ✅ Fast local I/O (SSD)
- ✅ Parallel GROBID processing
- ✅ Better CPU utilization
- ✅ Uses p1's faster hardware
- ✅ Scalable architecture

**Cons:**
- ⚠️ More complex implementation
- ⚠️ Requires local temp storage
- ⚠️ More memory usage

**Performance Gain:**
- **File I/O**: 10-50x faster
- **GROBID**: 2-4x faster (parallel + better CPU)
- **Overall**: 3-5x faster per paper

**Code Changes:**
- Strategy 1 changes (local copy)
- Strategy 4 changes (parallel processing)
- Optional: Strategy 3 changes (GPU OCR)

---

## Recommended Implementation Plan

### Phase 1: Quick Win - Local File Copy (Strategy 1)

**Priority: HIGH**  
**Effort: LOW**  
**Impact: MEDIUM-HIGH**

**Changes:**
1. Modify `PaperFileHandler.on_created()` to copy PDF to local temp directory
2. Process from local copy
3. Clean up local temp after processing
4. Keep original on network drive until processing complete

**Expected Performance:**
- 2-3x faster file I/O
- Better responsiveness during processing

**Code Location:**
- `scripts/paper_processor_daemon.py` - `PaperFileHandler.on_created()`
- Add `_copy_to_local_temp()` method
- Add `_cleanup_local_temp()` method

**Configuration:**
```ini
[PROCESSING]
# Local temp directory for fast processing
local_temp_dir = /tmp/paper_processing
# Or on Windows: C:\temp\paper_processing
```

---

### Phase 2: Parallel Processing (Strategy 4)

**Priority: MEDIUM**  
**Effort: MEDIUM**  
**Impact: MEDIUM-HIGH**

**Changes:**
1. Add processing queue
2. Thread pool for GROBID requests (2-4 workers)
3. Sequential user review (one at a time)
4. Queue management

**Expected Performance:**
- 1.5-2x faster for batch processing
- Better CPU utilization

**Code Location:**
- `scripts/paper_processor_daemon.py` - Add queue management
- `shared_tools/metadata/paper_processor.py` - Make GROBID calls thread-safe

**Configuration:**
```ini
[PROCESSING]
# Number of parallel GROBID workers
parallel_grobid_workers = 2
# Maximum queue size
max_queue_size = 10
```

---

### Phase 3: GPU OCR (Strategy 3) - OPTIONAL

**Priority: LOW**  
**Effort: HIGH**  
**Impact: MEDIUM** (only if OCR is bottleneck)

**Changes:**
1. Install CUDA and PyTorch
2. Add GPU OCR module
3. Integrate with pipeline
4. Fallback to CPU if GPU unavailable

**Expected Performance:**
- 5-10x faster OCR (if replacing Epson OCR)
- More CPU available for GROBID/Ollama

**Note:** Only implement if Epson OCR is insufficient or you want to disable it.

---

## Performance Comparison

### Current System (Baseline)
- **File I/O**: Network drive (~50-100 MB/s) - **BOTTLENECK**
- **GROBID**: ~2-5s per paper (CPU-bound on blacktower or p1)
- **User review**: ~10-30s (manual)
- **Total per paper**: ~15-40s (excluding user review)
- **Hardware**: Processing on either machine (similar CPU performance)

### Strategy 1 (Local Copy)
- **File I/O**: Local SSD (~500-2000 MB/s) - **10-20x faster** ⭐ **MAJOR**
- **GROBID**: ~2-4s per paper (slightly better CPU) - **1.1-1.2x faster** ⚠️ **MINOR**
- **User review**: ~10-30s (unchanged)
- **Total per paper**: ~12-35s - **~20% faster** (primarily from I/O)

### Strategy 1 + 4 (Local Copy + Parallel)
- **File I/O**: Local SSD - **10-20x faster** ⭐ **MAJOR**
- **GROBID**: ~1-2s per paper (parallel processing) - **2-4x faster** ⭐ **MAJOR**
- **User review**: ~10-30s (unchanged)
- **Total per paper**: ~11-33s - **~30% faster**
- **Batch processing**: **2-4x faster** (multiple papers in parallel) ⭐ **MAJOR**

### Strategy 1 + 4 + 3 (Full Hybrid)
- **File I/O**: Local SSD - **10-20x faster** ⭐ **MAJOR**
- **OCR**: GPU-accelerated (T1000, if replacing Epson) - **5-10x faster** ⭐ **MAJOR** (p1 advantage)
- **GROBID**: ~1-2s per paper (parallel processing) - **2-4x faster** ⭐ **MAJOR**
- **User review**: ~10-30s (unchanged)
- **Total per paper**: ~10-32s - **~35% faster**

---

## Implementation Details

### Local Temp Directory Structure

```
/tmp/paper_processing/          # or C:\temp\paper_processing\
├── active/                     # PDFs currently being processed
│   ├── scan_20250101_120000.pdf
│   └── scan_20250101_120100.pdf
├── done/                       # Successfully processed (cleaned up)
└── failed/                     # Failed processing (for debugging)
```

### Processing Queue

```python
class ProcessingQueue:
    """Manages parallel PDF processing."""
    
    def __init__(self, max_workers=2):
        self.queue = queue.Queue()
        self.workers = ThreadPoolExecutor(max_workers=max_workers)
        self.results = {}
    
    def add_pdf(self, pdf_path: Path):
        """Add PDF to processing queue."""
        future = self.workers.submit(self._process_pdf, pdf_path)
        self.results[pdf_path] = future
    
    def _process_pdf(self, pdf_path: Path):
        """Process single PDF with GROBID."""
        # Copy to local temp
        local_copy = self._copy_to_local_temp(pdf_path)
        # Process with GROBID
        metadata = self.grobid_client.extract(local_copy)
        # Clean up
        self._cleanup_local_temp(local_copy)
        return metadata
```

### Configuration Updates

```ini
[PROCESSING]
# Local temp directory for fast processing
local_temp_dir = /tmp/paper_processing
# Number of parallel GROBID workers
parallel_grobid_workers = 2
# Maximum queue size
max_queue_size = 10
# Cleanup local temp after processing
cleanup_local_temp = true

[GPU_OCR]
# Enable GPU-accelerated OCR (optional)
enabled = false
# CUDA device (0 for T1000)
cuda_device = 0
# OCR engine (easyocr, paddleocr, tesseract)
ocr_engine = easyocr
```

---

## Risk Assessment

### Low Risk
- ✅ **Strategy 1 (Local Copy)**: Minimal code changes, easy to test, easy to rollback
- ✅ **Strategy 4 (Parallel)**: Moderate changes, well-understood pattern, easy to disable

### Medium Risk
- ⚠️ **Strategy 3 (GPU OCR)**: Requires CUDA setup, additional dependencies, may conflict with existing OCR

### High Risk
- ❌ **Strategy 2 (Distributed)**: Complex architecture, network dependencies, harder to debug

---

## Recommendations

### Immediate (Next Session) - **HIGHEST IMPACT**
1. **Implement Strategy 1 (Local Copy)**
   - Quick win with minimal risk
   - **20% performance improvement** (primarily from I/O)
   - Easy to test and verify
   - **Works regardless of which machine processes** (I/O benefit is universal)

### Short Term (1-2 Sessions) - **GOOD ROI**
2. **Implement Strategy 4 (Parallel Processing)**
   - Moderate effort, good performance gain
   - **30% overall improvement** (parallel GROBID)
   - Better CPU utilization
   - **Works on both machines** (CPU-based, no GPU needed)

### Long Term (Future) - **p1-SPECIFIC ADVANTAGE**
3. **Consider Strategy 3 (GPU OCR)** - Only if OCR becomes bottleneck
   - **Only works on p1** (T1000 GPU required)
   - **Major advantage over blacktower** (which can't do GPU OCR)
   - Requires CUDA setup
   - **Strategic**: Makes p1 the preferred processing machine

### Avoid
- ❌ **Strategy 2 (Distributed)**: Too complex for current needs, network overhead negates benefits
- ❌ **Processing on blacktower**: No GPU advantage, similar CPU, network I/O bottleneck

### Key Insight
Given the hardware comparison:
- **CPU difference is minor** (10th gen vs 9th gen i7) - not worth optimizing for
- **I/O difference is major** (SSD vs network) - Strategy 1 is critical
- **GPU difference is major** (T1000 vs none) - Strategy 3 is p1-specific advantage
- **Parallel processing works on both** - Strategy 4 is universal benefit

---

## Testing Plan

### Phase 1 Testing (Local Copy)
1. Test file copy from network drive to local temp
2. Verify processing from local copy works
3. Verify cleanup works correctly
4. Test with multiple PDFs
5. Measure performance improvement

### Phase 2 Testing (Parallel)
1. Test parallel GROBID processing
2. Verify queue management
3. Test error handling (one PDF fails, others continue)
4. Test with 2, 4, 8 parallel workers
5. Measure performance improvement

### Phase 3 Testing (GPU OCR) - If Implemented
1. Test CUDA setup and GPU detection
2. Test OCR accuracy vs Epson OCR
3. Test performance improvement
4. Test fallback to CPU if GPU unavailable

---

## Success Metrics

### Performance Targets
- **File I/O**: < 1s for local copy (vs 2-5s network access)
- **GROBID**: < 2s per paper (vs 2-5s current)
- **Batch processing**: 2-4x faster for multiple PDFs
- **Overall**: 30-50% faster per paper (excluding user review)

### Quality Targets
- ✅ No functionality lost
- ✅ Error handling maintained
- ✅ User experience unchanged (or improved)
- ✅ System stability maintained

---

## Conclusion

**Recommended Approach:**
1. **Start with Strategy 1 (Local Copy)** - Quick win, low risk, **highest impact**
2. **Add Strategy 4 (Parallel Processing)** - Good performance gain, universal benefit
3. **Consider Strategy 3 (GPU OCR)** - p1-specific advantage, only if needed

**⚠️ IMPORTANT UPDATE: OCR Bottleneck Analysis**

If **OCR is the primary bottleneck** (takes 30-60+ seconds), see `docs/OCR_OPTIMIZATION_ANALYSIS.md` for a revised strategy:

- **Option A (Recommended)**: Daemon on p1, OCR on p1 with GPU acceleration
  - Disable OCR in Epson (scan raw PDFs)
  - Add GPU-accelerated OCR step in daemon (EasyOCR/PaddleOCR with CUDA)
  - **5-10x faster OCR** (30-60s → 3-12s)
  - **3-5x faster overall** per paper processing

- **Key Insight**: If OCR takes 30-60s, file I/O optimization (10x faster) only saves 1-2s
- **Primary benefit**: GPU-accelerated OCR on p1's T1000 provides 5-10x speedup

**Expected Overall Improvement:**
- **30-50% faster** per paper processing
- **2-4x faster** batch processing
- **Better CPU utilization**
- **10-20x faster file I/O** (primary benefit)

**Hardware-Specific Insights:**
- **CPU difference is minor** (9th gen vs 10th gen i7) - not worth optimizing for
- **I/O difference is major** (SSD vs network) - Strategy 1 is critical
- **GPU difference is major** (T1000 vs none) - Strategy 3 makes p1 preferred
- **Both have 32GB RAM** - no memory constraints

**Implementation Priority:**
1. ✅ Strategy 1 (Local Copy) - **HIGHEST PRIORITY** - Works on both machines
2. ✅ Strategy 4 (Parallel Processing) - **HIGH PRIORITY** - Works on both machines
3. ⚠️ Strategy 3 (GPU OCR) - **MEDIUM PRIORITY** - p1-specific, strategic advantage
4. ❌ Strategy 2 (Distributed) - **NOT RECOMMENDED** - Too complex, minimal benefit

**Strategic Recommendation:**
- **Process everything on p1** (better I/O, GPU option, slightly better CPU)
- **Use blacktower only for scanning** (network scanner host)
- **Local copy strategy makes p1 processing optimal** (fast SSD I/O)

---

*This plan provides a clear path forward with measurable improvements and minimal risk. The hardware analysis shows that p1 is the optimal processing machine, with Strategy 1 (local copy) providing the highest impact improvement.*

