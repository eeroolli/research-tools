# Bayesian Document Classification with User-Specific Knowledge Base

**Concept:** Use analysis of existing Zotero collection to create personalized Bayesian classifier

**Date:** October 9, 2025  
**Status:** 💭 Concept Evaluation - Not Yet Implemented

---

## The Idea

### **Core Concept:**
1. **Initial Setup Script** - Analyzes user's Zotero collection, creates knowledge base
2. **Bayesian Probabilities** - Calculate P(type|features) from historical data
3. **User Overrides** - Config file allows temporary overrides for batch processing
4. **Portable** - Each user's Zotero creates their personalized classifier

### **Example Workflow:**

```bash
# First time setup
python scripts/analysis/build_knowledge_base.py
# Output: data/classification/user_knowledge_base.yaml

# Processing with learned probabilities
python scripts/process_scanned_papers.py
# Uses Bayesian probabilities from knowledge base

# Override for specific batch
# In config.personal.conf:
[CLASSIFICATION_OVERRIDE]
assume_type = newspaper_article
confidence_boost = 0.3
# "I'm scanning newspaper clippings today"
```

---

## Bayesian Classification Logic

### **Prior Probabilities (from Zotero analysis):**

From your 9,834 documents (excluding notes):
```
P(journal_article) = 1600/9834 = 16.3%
P(book) = 3653/9834 = 37.1%
P(book_chapter) = 1052/9834 = 10.7%
P(report) = 838/9834 = 8.5%
P(newspaper) = 42/9834 = 0.4%
```

### **Feature Likelihoods (from analysis):**

```
P(has_DOI | journal_article) = 32.3%
P(has_DOI | book_chapter) = 0%
P(has_DOI | newspaper) = 0%

P(has_URL | newspaper) = 50%
P(has_URL | journal_article) = 13.8%
P(has_URL | book_chapter) = 2.3%

P(pages_8-30 | book_chapter) = ~70% (estimated from pages field data)
P(pages_8-30 | newspaper) = ~90% (short articles)
```

### **Bayesian Update:**

```python
# Given: 15-page document, has URL, no DOI
# Calculate: P(type | features)

P(newspaper | URL, 15_pages, no_DOI) = 
    P(URL | newspaper) × P(15_pages | newspaper) × P(no_DOI | newspaper) × P(newspaper)
    ────────────────────────────────────────────────────────────────────────
    Σ [same calculation for all types]

Result:
  newspaper: 65%
  book_chapter: 25%
  report: 10%

→ Pass to Ollama: "Likely NEWSPAPER (65% confidence based on your collection)"
```

---

## Advantages

### ✅ **Personalized to User**
- Learns from YOUR collection patterns
- If you have 40% political science papers, classifier knows this
- Better than generic rules

### ✅ **Mathematically Sound**
- Bayesian inference is proven methodology
- Quantifies uncertainty
- Updates with new evidence

### ✅ **User Override for Batch Processing**
```ini
# config.personal.conf
[CLASSIFICATION_OVERRIDE]
# "I'm scanning 50 newspaper clippings today"
assume_type = newspaper_article
confidence_boost = 0.4
```
Smart! User knows context we don't.

### ✅ **Portable Across Users**
- Each user runs initial analysis
- Creates personalized knowledge base
- Commercial product benefit!

### ✅ **Improves Over Time**
- Re-run analysis monthly → Updates probabilities
- As library grows, classification improves
- Self-learning system

---

## Disadvantages

### ⚠️ **Complexity**
- Bayesian math adds complexity
- More code to maintain
- Users need to run initial setup

### ⚠️ **Overfitting Risk**
- If user has 90% political science, might mis-classify economics papers
- Needs sufficient diversity in collection
- Minimum collection size needed (500+ items?)

### ⚠️ **Maintenance Overhead**
- Knowledge base gets stale
- User must remember to re-run analysis
- What if they change research field?

### ⚠️ **Configuration Complexity**
- Override syntax needs to be user-friendly
- Need good documentation
- Risk of user confusion

---

## Alternative Approaches

### **Option 1: Simple Rules + Universal Signals (Current)**
```python
# Universal rules that work for everyone
if pages <= 8 and has_url:
    type = "newspaper"  # Works for ALL users
```
**Pro:** Simple, portable, no setup  
**Con:** Not personalized

### **Option 2: Bayesian Without User Override (Simpler)**
- Use Bayesian probabilities
- Skip override complexity
- Re-run analysis automatically when Zotero changes

### **Option 3: Hybrid Approach (Recommended)**
```python
# Universal rules as baseline
base_classification = simple_rules(pages, url, keywords)

# Bayesian adjustment if knowledge base exists
if knowledge_base_exists():
    adjusted = bayesian_update(base_classification, user_priors)
else:
    adjusted = base_classification

# Simple override
if config.get('force_type'):
    final = config.get('force_type')
else:
    final = adjusted
```

**Pro:** Graceful degradation, works without setup, better with setup  
**Con:** Still complex

---

## Recommendation

### **Phase 1 (Next Session): Simple Rules**
Implement universal rules based on page count + URL + keywords:
```python
if pages <= 8 and has_url and detect_newspaper(text):
    return "newspaper_article"
```

**Why:** 
- Works immediately, no setup
- Covers 80-90% of cases correctly
- Can ship to other users

### **Phase 2 (Future): Add Bayesian Layer**
Once simple rules work well:
```python
base = simple_rules()
if has_knowledge_base:
    final = bayesian_adjust(base, user_collection)
```

**Why:**
- Incremental improvement
- Optional enhancement
- Doesn't break if missing

### **Phase 3 (Future): User Override**
Simple config option:
```ini
[PROCESSING]
force_document_type = newspaper_article  # For batch processing
```

---

## Evaluation Summary

**Verdict:** 
- ✅ **Brilliant idea** for commercial product
- ⚠️ **Too complex for initial implementation**
- ✅ **Perfect as Phase 2 enhancement**

**Recommendation:**
1. **Now:** Build simple universal rules (works for everyone)
2. **Next:** Add optional Bayesian layer (better for power users)
3. **Later:** Add override for batch processing

**Priority:** Finish simple preprocessing first, validate it works, THEN add sophistication.

---

## Implementation Notes for Future

If implementing Bayesian approach:

1. **Knowledge Base Format:**
```yaml
# user_classification_priors.yaml
collection_stats:
  total_documents: 9834
  analyzed_date: "2025-10-09"
  
priors:
  journal_article: 0.163
  book: 0.371
  book_chapter: 0.107
  newspaper: 0.004
  
likelihoods:
  has_doi:
    journal_article: 0.323
    book_chapter: 0.0
  has_url:
    newspaper: 0.50
    journal_article: 0.138
  pages_8_to_30:
    book_chapter: 0.70
    newspaper: 0.90
```

2. **Update Script:**
```bash
# Re-run monthly
python scripts/analysis/update_knowledge_base.py
```

3. **Fallback:**
```python
if not knowledge_base_exists():
    use_universal_rules()  # Always works
```

---

---

## Interactive Learning & Adaptive System

### **User Correction Feedback Loop**

**Problem:** System guesses wrong, user knows better

**Solution:** Interactive correction during processing (like `add_or_remove_books_zotero.py`)

### **Implementation:**

**1. Interactive Override During Processing:**
```
Processing: Smith_2024_Title.pdf
  Detected type: journal_article (65% confidence)
  
  Options:
  1. Accept (journal_article)
  2. Override → book_chapter
  3. Override → newspaper_article
  4. Override → report
  5. Skip (manual later)
  
Your choice: 2

✅ Corrected to: book_chapter
💾 Correction logged for learning
```

**2. Pattern Detection:**
```python
# Track user corrections in session
corrections = [
    {'guessed': 'journal_article', 'actual': 'book_chapter'},
    {'guessed': 'journal_article', 'actual': 'book_chapter'},
    {'guessed': 'journal_article', 'actual': 'book_chapter'},  # 3x same correction!
]

# Detect systematic overriding
if count_same_correction(corrections) >= 3:
    suggest_override_update()
```

**3. Smart Suggestion:**
```
⚠️  NOTICE: You've corrected 'journal_article' → 'book_chapter' 5 times.

This suggests your current batch is mostly book chapters.
Would you like to:

  1. Add temporary override to config:
     [CLASSIFICATION_OVERRIDE]
     assume_type = book_chapter
     confidence_boost = 0.4
     
  2. Continue manual corrections
  3. Show me your current override settings

Your choice: 1

✅ Temporary override added to config.personal.conf
   (Remember to remove when done with this batch!)
```

**4. Reminder System:**
```python
# Check if override is stale
if config.has_override():
    override_date = config.get_override_date()
    days_old = (today - override_date).days
    
    if days_old > 30:
        print("\n⚠️  REMINDER: You have classification override from 45 days ago:")
        print(f"    assume_type = {config.get_override_type()}")
        print(f"    Is this still relevant? (y/n): ", end='')
```

**5. Learning from Corrections:**
```python
# Save corrections to learning database
corrections_db = {
    'user_corrections': [
        {
            'date': '2025-10-09',
            'features': {'pages': 15, 'has_url': False, 'keywords': ['Chapter']},
            'guessed': 'journal_article',
            'user_corrected_to': 'book_chapter',
            'confidence_was': 0.65
        }
    ]
}

# Use for knowledge base updates
python scripts/analysis/update_knowledge_base.py --include-corrections
# Updates Bayesian priors with user feedback
```

---

## Advantages of Interactive Learning

### ✅ **System Improves Over Time**
- User corrections = training data
- Knowledge base evolves with usage
- No manual tuning needed

### ✅ **Detects Batch Context**
- "User corrected 5/5 as newspaper" → Suggests override
- Adapts to temporary workflows
- Reminds about stale overrides

### ✅ **Transparent & Controllable**
- User sees why system guessed wrong
- Can fix systematic issues
- Learns user's preferences

### ✅ **Portable Across Users**
- Each user builds their own patterns
- Commercial product benefit
- Privacy preserved (local learning)

---

## Implementation Considerations

### **Storage:**
```
data/classification/
├── user_knowledge_base.yaml        # Bayesian priors from Zotero
├── user_corrections.csv            # User feedback log
└── override_history.csv            # Track when overrides were active
```

### **Config Integration:**
```ini
# config.personal.conf
[CLASSIFICATION]
# Updated automatically by analysis script
last_analysis_date = 2025-10-09
knowledge_base_version = 1

[CLASSIFICATION_OVERRIDE]
# Temporary override for batch processing
# Remove when done!
assume_type = newspaper_article
confidence_boost = 0.3
override_date = 2025-10-09
```

### **Learning Update Frequency:**
```bash
# Triggered by:
1. Manual: python scripts/analysis/update_knowledge_base.py
2. Automatic: After processing 100 documents
3. Prompted: "You've corrected 20 items, update knowledge base? (y/n)"
```

---

## Evaluation: Should We Implement This?

### **For Your Personal Use:**
**Priority: Medium**
- Nice to have, not essential
- Simple rules might be good enough
- Your collection is already well-organized

### **For Commercial Product:**
**Priority: High**
- Differentiating feature
- Learns user patterns
- Professional polish

### **Development Effort:**
- **Phase 1 (Simple rules):** 1 session
- **Phase 2 (Bayesian):** 2-3 sessions
- **Phase 3 (Interactive learning):** 2-3 sessions
- **Total:** 5-7 sessions

### **Recommended Approach:**

**Immediate (Next 1-2 Sessions):**
1. ✅ Simple universal rules (pages + URL + newspaper names)
2. ✅ Basic override in config
3. ✅ Test and validate

**Short Term (3-4 Sessions):**
1. Build knowledge base from Zotero analysis
2. Implement Bayesian classification
3. Test accuracy improvement

**Medium Term (5-7 Sessions):**
1. Add interactive correction UI
2. Implement pattern detection
3. Build learning feedback loop
4. Add override suggestions

---

## Decision Matrix

| Feature | Complexity | User Value | Commercial Value | Priority |
|---------|------------|------------|------------------|----------|
| Simple rules | Low | High | Medium | **Do Now** |
| Basic override | Low | Medium | Medium | **Do Now** |
| Bayesian priors | Medium | Medium | High | Phase 2 |
| Interactive learning | High | High | Very High | Phase 3 |
| Pattern detection | Medium | High | High | Phase 3 |
| Override suggestions | Medium | Medium | High | Phase 3 |

---

## Conclusion

**The Idea:** ⭐⭐⭐⭐⭐ Excellent! Shows sophisticated thinking.

**Timing:** Implement in phases
1. **Now:** Simple + basic override (1-2 sessions)
2. **Soon:** Bayesian (2-3 sessions)  
3. **Later:** Interactive learning (2-3 sessions)

**Commercial Potential:** Very High - personalized AI that learns is marketable

**Recommendation:** Document now, implement Phase 1 next session, Phases 2-3 when basic system is validated.

---

**This evaluation saved for future reference and product roadmap planning.**
