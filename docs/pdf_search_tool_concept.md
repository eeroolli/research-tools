## PDF Retrieval Assistant Concept

### Problem Statement
- Need a fallback when physical scans are unusable.
- Input is structured bibliography data (authors, year, journal), often includes DOI or alternate identifiers.
- Output should be actionable download links plus provenance and access type.

### Success Criteria
- Prioritize legality: only surface openly accessible or institutionally sanctioned copies.
- Minimize false positives by matching on DOI/ISSN and high-confidence metadata.
- Provide transparent status reporting when no open copy exists.

### Candidate Data Sources
- **Crossref API** for DOI lookup and expanded metadata.
- **Unpaywall** to identify open-access versions and classify access status.
- **OpenAlex** for alternate IDs, institutional repository URLs, and rich metadata.
- **Internet Archive / HathiTrust** for older or public-domain content.
- **Institutional repositories** (DSpace/OAI-PMH endpoints) configurable per user.
- **General search brokers** (Google Scholar, Bing) reserved for manual follow-up; capture query templates rather than automated scraping to stay compliant.

### Proposed Architecture
- Standalone CLI (`scripts/pdf_search_tool.py`) powered by a shared config (`config.conf`) to centralize API keys, rate limits, and repository endpoints.
- Modular provider classes in `shared_tools/pdf_sources/` implementing a common interface:
  - `prepare_query(metadata)`
  - `fetch_candidates()`
  - `score_candidates()`
- Incremental result cache (e.g., SQLite or CSV) keyed by normalized DOI/metadata hash to avoid redundant queries.
- Logging:
  - Human-readable summary per run.
  - Detailed CSV log capturing query params, providers contacted, response timing, discovered URLs, and status.
- Configurable retry/backoff strategy, respecting provider rate limits and ToS.
- Pluggable scoring that combines:
  - Identifier exact match (DOI, PMID, ISBN).
  - Metadata similarity (title, authors, year).
  - Provider reliability weighting.

### Prototype Workflow
1. Normalize user-supplied metadata (strip punctuation, canonicalize author names, enforce lower-case DOIs).
2. Query Crossref/OpenAlex to fill missing identifiers.
3. Query Unpaywall and institutional sources for OA links.
4. Query archival repositories (Internet Archive, HathiTrust) with fuzzy matching if DOI unavailable.
5. Aggregate candidates, compute scores, and output ranked results with access notes (`open`, `restricted`, `unknown`).
6. Write summary/log entries and update cache.

### Risks and Mitigations
- **Incomplete metadata**: add fuzzy matching with configurable thresholds and manual review flags.
- **Rate limits**: throttle requests; cache responses.
- **Legal constraints**: only use APIs or sources that permit automated discovery; prompt user before following links that require credentials.
- **Ambiguous records**: provide multiple candidates with confidence scores instead of auto-selection.

### Expected Effectiveness
- High success for articles with DOIs and OA versions (`Unpaywall` coverage >50% of recent literature).
- Moderate success for older or niche publications when institutional repositories participate.
- Lower success for proprietary or obscure works lacking digital distribution; highlight these for manual escalation.

### Next Steps
- Validate API credentials and quotas for Crossref, Unpaywall, OpenAlex.
- Draft data models and provider interface in a sandbox module.
- Design unit tests covering metadata normalization, provider integration mocks, and scoring.
- Revisit integration with existing workflows once prototype reliability is established.

