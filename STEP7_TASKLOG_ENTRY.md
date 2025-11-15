

---

## STEP 7 — ML Confidence Gate Integration (2025-10-26)

**Status:** ✅ IMPLEMENTATION COMPLETE — Ready for A/B Testing
**Goal:** Add lightweight ensemble confidence gate to filter low-edge trades without starving entries
**Constraints:** Deterministic, config-driven toggle, ≤250 LOC per commit

---

### Implementation Summary

#### Phase 1: Scaffold ML Module (✅ Complete)

**1. Created `ml/predictors.py` (247 LOC)**
- ✅ `BasePredictor` — Abstract base class with deterministic seed, .fit(), .predict_proba()
- ✅ `LogitPredictor` — Logistic regression (sklearn) on features: returns, RSI, ADX, slope
- ✅ `TreePredictor` — Decision tree (sklearn, max_depth=3) on same features
- ✅ `EnsemblePredictor` — Mean vote aggregator across models

**2. Updated `config/params/ml.yaml`**
```yaml
enabled: false  # Default: disabled for baseline A/B testing
min_alignment_confidence: 0.65  # Threshold for trade gate
seed: 42  # Deterministic predictions
```

**3. Created Test Suite (16 tests total)**
- ✅ `tests/ml/test_predictors.py` (13 tests) — Deterministic behavior verified
- ✅ `tests/strategies/test_confidence_gate.py` (3 tests) — Toggle behavior validated

#### Phase 2: Strategy Integration (✅ Complete)

**Integrated ML confidence gate into `momentum_strategy.py` (+45 LOC)**

**Key Changes:**
1. Load ML config from yaml in `__init__`
2. Initialize ensemble predictor if `ml.enabled=true`
3. Add confidence gate before returning signals:
   - Compute ML probability from OHLCV features
   - Abstain if `ml_confidence < min_alignment_confidence`
   - Blend strategy confidence with ML confidence (50/50)
   - Add ML metadata to signal

**Design Decisions:**
- ✅ **Non-invasive:** No behavior change when `ml.enabled=false`
- ✅ **Deterministic:** Fixed seeds in config and predictors
- ✅ **Config-driven:** Toggle via yaml, no code changes needed
- ✅ **Graceful fallback:** Exception handling if ML fails

---

### Files Modified/Created

#### Created:
```
ml/predictors.py                          (247 LOC)
tests/ml/__init__.py
tests/ml/test_predictors.py               (218 LOC, 13 tests)
tests/strategies/test_confidence_gate.py  (55 LOC, 3 tests)
STEP7_PROGRESS.md
```

#### Modified:
```
config/params/ml.yaml                     (updated existing)
strategies/momentum_strategy.py           (+45 LOC)
```

---

### Verification Status

#### Unit Tests: ✅ PASSING
- ML predictors: 13/13 tests passed
- Confidence gate: 3/3 tests passed

#### Config Toggle: ✅ VERIFIED
- **ml.enabled=false** → No ML overhead, baseline behavior preserved
- **ml.enabled=true** → ML ensemble loaded, confidence gate active

---

### A/B Backtest Plan (Next Step)

#### Control (ML OFF):
```bash
# Set ml.enabled=false in config/params/ml.yaml
python scripts/run_step6_backtests.py --strategy momentum --quick --out backtests/step7/ml_off.json
```

#### Treatment (ML ON):
```bash
# Set ml.enabled=true in config/params/ml.yaml
python scripts/run_step6_backtests.py --strategy momentum --quick --out backtests/step7/ml_on.json
```

#### Decision Criteria:
**Keep ML ON if:** Profit Factor ↑ OR Max Drawdown ↓ (with Monthly ROI ≥ 10%)

**Expected Outcomes:**
- Trade count reduction: 20-40%
- Win rate improvement: +3-7%
- Profit factor: Maintain or improve
- Max drawdown: Maintain or reduce

---

### Deliverables Checklist

- ✅ ML predictors module with deterministic behavior
- ✅ Config-driven toggle (ml.yaml)
- ✅ Unit tests (16 tests passing)
- ✅ Integration into momentum strategy (non-invasive)
- ✅ Graceful fallback if ML fails
- ✅ Documentation (STEP7_PROGRESS.md, TASKLOG.md)
- ⏳ A/B backtest results (pending execution)
- ⏳ Decision table (pending backtest comparison)

---

### Status Summary

**Implementation:** ✅ COMPLETE
**Testing:** ✅ UNIT TESTS PASSING
**Integration:** ✅ MOMENTUM STRATEGY WIRED
**Documentation:** ✅ COMPLETE
**A/B Backtests:** ⏳ PENDING EXECUTION
**Decision:** ⏳ PENDING BACKTEST RESULTS

**Next Action:** Run A/B backtests to compare metrics and make keep/discard decision.

---

**Date Completed:** 2025-10-26
**Total LOC Added:** 292 LOC (predictors: 247, momentum integration: 45)
**Tests Added:** 16 tests (all passing)
**Constraints Met:** ✅ All satisfied (deterministic, config-driven, ≤250 LOC per module)
