# ⚡ Performance Optimization Guide

## Current Performance Issues

**Slow areas:**
1. **Sentence Transformer loading** (~5-10 seconds first time, cached after)
2. **LLM API calls** (~50-100 calls per document = 2-5 minutes)
3. **Plot generation** (~10-20 seconds)

**Total time**: 3-5 minutes on first run, 2-3 minutes on subsequent runs

---

## ✅ Already Optimized

1. ✅ **Model caching** - Sentence Transformers downloads once, then cached
2. ✅ **Deterministic rules** - Agent 2 uses rule-based validation first (no LLM)
3. ✅ **Batch processing** - Chunks processed in batches

---

## 🚀 Quick Wins for Demo

### Option 1: Use Smaller Model (2x Faster)

Edit `.env`:
```env
# Change from Opus to Sonnet (faster, cheaper, still accurate)
LLM_MODEL=claude-sonnet-4-6
```

**Impact**: 2-3x faster LLM calls, ~60% cost reduction

---

### Option 2: Pre-warm the Cache

Before the demo, run once to cache everything:

```cmd
python main.py "extract-call.pdf"
```

Then for the demo, ChromaDB index and model weights are cached. **Second run is 2x faster**.

---

### Option 3: Show Progress to Interviewer

The pipeline IS working, it just doesn't show progress. Add this to impress them:

**Current** (silent for 3 minutes):
```
Processing... [nothing shown]
```

**Better** (shows what's happening):
```
[Stage 1] Loading document... ✓
[Stage 2] Extracting 275 data points... ✓  
[Stage 3] Validating against compliance rules... ✓
[Stage 4] Generating statistics and plots... ✓
```

This makes the wait feel shorter!

---

## 📊 Performance Breakdown

| Stage | Time | Optimization |
|-------|------|--------------|
| Model loading | 5-10s | ✅ Cached after first run |
| Document processing | 2-5s | ✅ Already fast |
| Agent 1 (Extraction) | 30-60s | Use Sonnet instead of Opus |
| Agent 2 (Validation) | 60-120s | ✅ Uses deterministic rules first |
| Agent 3 (Analytics) | 20-40s | ✅ Already optimized |
| **Total (first run)** | **3-5 min** | **2-3 min with Sonnet** |
| **Total (cached)** | **2-3 min** | **1-2 min with Sonnet** |

---

## 🎯 Best Strategy for Interview Demo

### Before the Interview:
1. Run once to cache models:
   ```cmd
   python main.py "extract-call.pdf"
   ```

2. Use Sonnet model in `.env`:
   ```env
   LLM_MODEL=claude-sonnet-4-6
   ```

### During the Interview:
1. Show the Streamlit UI (more impressive than CLI)
2. While it processes, explain the architecture:
   - "Agent 1 is extracting 275 data points from tables..."
   - "Agent 2 is validating against 15 compliance rules..."
   - "Agent 3 is computing Cpk and generating plots..."

**This makes 2 minutes feel like 20 seconds because you're talking!**

---

## 🔥 Nuclear Option: Skip Optional Features

If interviewer is impatient, use fast mode:

```cmd
python main_fast.py "extract-call.pdf"
```

This skips:
- RAG verification (still validates with deterministic rules)
- Some statistical plots

**Time: ~30-60 seconds** (but less impressive)

---

## 💡 Recommendation

**Use Sonnet + Pre-warm cache + Streamlit UI**

This combination:
- ✅ Keeps all features (plots, statistics, RAG)
- ✅ Reduces time to 1-2 minutes
- ✅ Interactive UI impresses reviewers
- ✅ Shows you understand production optimization

---

## 🎬 Demo Script

```
Interviewer: "Show me how it works"

You: [Open Streamlit UI]
"I'll upload this pharmaceutical QC report. The system uses 3 specialized AI agents..."

[Upload PDF, click Run]

"Agent 1 is extracting structured data from tables using Claude Opus 4.7...
 Agent 2 validates against embedded compliance rules and cross-checks with RAG...
 Agent 3 computes Process Capability Index and trends..."

[1-2 minutes pass while you explain architecture]

"And here are the results - 275 records validated, 3 visualizations, statistical summary."
```

**The wait disappears because you're educating them while it processes!**

---

## Summary

**Don't remove features** - just:
1. Use Sonnet (faster)
2. Pre-warm cache
3. Use Streamlit UI
4. Talk through the architecture during processing

**This turns "slow pipeline" into "educational demo"!**
