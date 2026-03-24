# Future small PDF fixtures for tests

This note documents planned future work to add small, deterministic PDF-based
tests without depending on personal paths or always-on services.

- **Scope**
  - GROBID extraction (basic metadata from a tiny 1–2 page PDF).
  - Rotation handling (a single rotated page where the expected rotation is known).
  - Gutter detection (a synthetic two-column page with a clear gutter).
  - Year extraction (a crafted cover page with a single unambiguous publication year).
  - Handwritten detection (a minimal synthetic sample that reliably exercises the
    handwritten‑vs‑printed heuristic).

- **Constraints**
  - PDFs stored under `tests/fixtures/` with small file sizes and neutral content.
  - Tests should:
    - Skip cleanly when heavy services (e.g. GROBID) are unavailable.
    - Avoid hard‑coded personal paths such as `I:\FraScanner\...` or `G:\My Drive\...`.
    - Be runnable on Windows without requiring local GROBID or OCR services by default.

This file serves as the anchor for the `future-fixture-tests` task in the
`windows-daemon-tests-alignment` plan; the concrete pytest tests will be added
in a later session.

