# Gutter Detection Improvements - Suggestion for Planning Agent

## Problem Summary

PDF splitting incorrectly identifies column edges as gutters, especially for printouts. The current algorithm finds the minimum content density position but doesn't distinguish between:
- **Real gutters**: Gradual valley (low content across a wider region)
- **Column edges**: Sharp drop (sudden transition from text to white space)

## Runtime Evidence Collected

### Shape Analysis Data (from debug logs)

For printout PDFs (no real gutters), the shape analysis shows:
- **Average gradient**: 1000-1800 (relatively high - suggests sharp transitions)
- **Max gradient**: 8000-15000 (very high - indicates sharp drops)
- **Valley width ratio**: 0.51-0.69 (moderate width, but may be misleading)
- **Second derivative**: 800-1600 avg, 8000-14000 max (high curvature - sharp transitions)

### Current Behavior
- Detected positions are in middle region (0.43-0.44 ratio of content width)
- All 3 pages contribute positions, but they're likely column edges, not gutters
- Fix already implemented: returns None if printout_ratio >= 0.5 or gutter_positions < 2

## Suggested Improvement: Content Projection Shape Analysis

### Concept
Analyze the **shape** of the content projection around the detected minimum position to distinguish:
1. **Real gutters**: Gradual valley (low gradient, wide valley, smooth transition)
2. **Column edges**: Sharp drop (high gradient, narrow valley, sudden transition)

### Implementation Approach

#### 1. Gradient Analysis (First Derivative)
- Calculate rate of change around the minimum position
- **Real gutter**: Low average gradient (< 500) - gradual transition
- **Column edge**: High average gradient (> 1000) - sharp transition

#### 2. Curvature Analysis (Second Derivative)
- Calculate how sharp the transition is
- **Real gutter**: Low second derivative (< 500) - smooth curve
- **Column edge**: High second derivative (> 1000) - sharp corner

#### 3. Valley Width Analysis
- Measure how wide the low-content region is
- **Real gutter**: Wide valley (valley_width_ratio > 0.6) - extended low-content area
- **Column edge**: Narrow valley (valley_width_ratio < 0.4) - tight transition zone

### Decision Logic

Reject detected position as a column edge (not a gutter) if:
- `avg_gradient > 1000` AND `valley_width_ratio < 0.5` (sharp, narrow transition)
- OR `max_gradient > 5000` AND `avg_second_deriv > 1000` (very sharp corner)

Accept as real gutter if:
- `avg_gradient < 500` AND `valley_width_ratio > 0.6` (gradual, wide valley)
- AND `avg_second_deriv < 500` (smooth transition)

### Integration Points

1. **Location**: `scripts/paper_processor_daemon.py`, `_find_gutter_position()` method
2. **After**: Shape analysis is already calculated (lines ~5124-5200)
3. **Before**: Adding position to `gutter_positions` list (line ~5292)
4. **Action**: Add validation check using shape analysis metrics before appending to `gutter_positions`

### Expected Outcome

- Printouts with column edges: Rejected (use 50/50 split)
- Physical book scans with real gutters: Accepted (use detected position)
- Printed articles with real gutters: Accepted (use detected position)

## Current Instrumentation

Shape analysis data is already being logged in debug logs with keys:
- `shape_analysis.avg_gradient`
- `shape_analysis.max_gradient`
- `shape_analysis.avg_second_deriv`
- `shape_analysis.max_second_deriv`
- `shape_analysis.valley_width_ratio`

## Next Steps

1. Collect more runtime evidence from PDFs with actual gutters (physical book scans)
2. Compare shape analysis metrics between:
   - Real gutters (from book scans)
   - Column edges (from printouts)
3. Refine threshold values based on evidence
4. Implement validation logic using shape analysis

