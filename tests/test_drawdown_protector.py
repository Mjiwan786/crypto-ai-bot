import math


from agents.risk.drawdown_protector import (
    DrawdownBands,
    DrawdownProtector,
    DrawdownState,
    FillEvent,
    GateDecision,
    SnapshotEvent,
)


# ---------- Helpers ----------

class Clock:
    def __init__(self, t0: int) -> None:
        self.t = t0

    def now(self) -> int:
        return self.t

    def step(self, dt: int) -> int:
        self.t += dt
        return self.t


def mk_policy() -> DrawdownBands:
    # Easy math: daily stop -10%; hard at -15%.
    # Rolling: 1h -5%, 4h -8%.
    # Scale bands: warn at -2%, then -5%, -10%.
    return DrawdownBands(
        daily_stop_pct=-0.10,
        rolling_windows_pct=[(3600, -0.05), (4 * 3600, -0.08)],
        cooldown_after_soft_s=600,
        cooldown_after_hard_s=1800,
        max_consecutive_losses=2,
        scale_bands=[(-0.02, 0.8), (-0.05, 0.5), (-0.10, 0.25)],
        enable_per_strategy=True,
        enable_per_symbol=True,
    )


def init_protector(clock: Clock) -> DrawdownProtector:
    prot = DrawdownProtector(mk_policy(), now_s_provider=clock.now)
    prot.reset(equity_start_of_day_usd=1000.0, ts_s=clock.now())
    return prot


# ---------- Tests ----------

def test_happy_path_normal_allows_open_multiplier_1():
    clock = Clock(1_728_000_000)  # fixed epoch
    p = init_protector(clock)
    # Seed windows
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=1000.0))
    d = p.assess_can_open("stratA", "BTC/USD")
    assert d.allow_new_positions and not d.reduce_only and not d.halt_all
    assert math.isclose(d.size_multiplier, 1.0)
    assert d.reason is None


def test_warn_band_threshold_causes_warn_and_scaling():
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    # Drop equity 2% (warn threshold -2%)
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=980.0))
    d = p.assess_can_open("stratA", "BTC/USD")
    assert d.allow_new_positions and d.size_multiplier == 0.8
    assert d.reason == "warn-band-hit"


def test_daily_stop_triggers_soft_stop_and_cooldown():
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    # Hit -10% daily
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=900.0))
    d = p.assess_can_open("s", "sym")
    assert not d.allow_new_positions and d.reduce_only and not d.halt_all
    assert d.reason == "daily-stop-hit"
    # Cooldown active pinning
    d2 = p.assess_can_open("s", "sym")
    assert d2.reason in ("daily-stop-hit", "cooldown-soft-active")


def test_rolling_breach_pairs_per_window_not_min_vs_any():
    """
    Repro bug: windows must be checked pairwise (dd <= its own limit), not min(dds) <= any(limit).
    Simulate mild drawdown that should NOT breach configured rolling limits.
    """
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    sod = 1000.0

    # Seed + peak
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=sod, equity_current_usd=sod))
    clock.step(1800)  # +30m
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=sod, equity_current_usd=1006.0))
    # Fall ~ -1.39% from peak (less severe than 1h:-5% and 4h:-8% limits)
    clock.step(1800)  # +60m
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=sod, equity_current_usd=992.0))

    d = p.assess_can_open("A", "X")
    # Should NOT be soft stop due to rolling
    assert d.allow_new_positions
    assert d.reason in (None, "warn-band-hit")


def test_hard_halt_via_severity():
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    # Hard threshold -15% (1.5 * daily_stop -10%)
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=850.0))
    d = p.assess_can_open("s", "sym")
    assert not d.allow_new_positions and d.halt_all
    assert d.reason in ("daily-stop-hit", "hard-halt-triggered", "cooldown-hard-active")


def test_loss_streak_soft_then_hard_same_day():
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    # First streak breach → soft
    p.ingest_fill(FillEvent(ts_s=clock.now(), pnl_after_fees=-10.0, strategy="S", symbol="X", won=False))
    p.ingest_fill(FillEvent(ts_s=clock.now(), pnl_after_fees=-10.0, strategy="S", symbol="X", won=False))
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=995.0))
    d1 = p.assess_can_open("S", "X")
    assert not d1.allow_new_positions and d1.reduce_only
    assert d1.reason in ("loss-streak-soft", "cooldown-soft-active", "soft-stop-triggered")

    # Reset streak with a win, then breach again same day → hard
    p.ingest_fill(FillEvent(ts_s=clock.now(), pnl_after_fees=5.0, strategy="S", symbol="X", won=True))
    p.ingest_fill(FillEvent(ts_s=clock.now(), pnl_after_fees=-5.0, strategy="S", symbol="X", won=False))
    p.ingest_fill(FillEvent(ts_s=clock.now(), pnl_after_fees=-5.0, strategy="S", symbol="X", won=False))
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=990.0))
    d2 = p.assess_can_open("S", "X")
    assert d2.halt_all
    assert d2.reason in ("loss-streak-hard", "cooldown-hard-active", "hard-halt-triggered")


def test_cooldown_pins_state_and_expiry_recomputes():
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    # Enter soft stop via daily stop
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=900.0))
    d1 = p.assess_can_open("s", "sym")
    assert not d1.allow_new_positions
    # Improve equity but still within cooldown → decision pinned
    clock.step(60)
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=995.0))
    d2 = p.assess_can_open("s", "sym")
    assert not d2.allow_new_positions  # pinned by cooldown
    # Advance beyond cooldown and recompute → should relax
    clock.step(mk_policy().cooldown_after_soft_s + 1)
    d3 = p.assess_can_open("s", "sym")
    assert d3.allow_new_positions


def test_scope_precedence_and_portfolio_cap():
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    # Portfolio warn (-2%) → multiplier 0.8
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=980.0))
    # Symbol breaches daily stop → soft stop; portfolio multiplier should cap combined
    p.ingest_snapshot(SnapshotEvent(
        ts_s=clock.now(),
        equity_start_of_day_usd=1000.0,
        equity_current_usd=980.0,
        symbol_equity_usd={"BTC/USD": 850.0},
    ))
    d = p.assess_can_open("stratA", "BTC/USD")
    assert not d.allow_new_positions and d.reduce_only
    # multiplier should respect min of scopes (<= 0.8 here)
    assert d.size_multiplier <= 0.8


def test_day_rollover_resets_daily_only_and_rolling_persists():
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    # Build rolling history and daily dd
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=950.0))
    # Next UTC day
    clock.step(86_400)
    p.on_day_rollover(1000.0, ts_s=clock.now())
    # Daily dd must reset on next snapshot; rolling still based on window queue
    p.ingest_snapshot(SnapshotEvent(ts_s=clock.now(), equity_start_of_day_usd=1000.0, equity_current_usd=990.0))
    st = p.current_state()
    assert st.portfolio.loss_streak == 0
    assert isinstance(st, DrawdownState)


def test_determinism_same_inputs_same_outputs():
    t0 = 1_728_000_000
    c1, c2 = Clock(t0), Clock(t0)
    p1, p2 = init_protector(c1), init_protector(c2)
    seq = [
        lambda clk, prot: prot.ingest_snapshot(SnapshotEvent(ts_s=clk.now(), equity_start_of_day_usd=1000.0, equity_current_usd=980.0)),
        lambda clk, prot: prot.ingest_fill(FillEvent(ts_s=clk.now(), pnl_after_fees=-1.0, strategy="S", symbol="X", won=False)),
        lambda clk, prot: prot.ingest_snapshot(SnapshotEvent(ts_s=clk.now(), equity_start_of_day_usd=1000.0, equity_current_usd=970.0)),
        lambda clk, prot: prot.assess_can_open("S", "X"),
    ]
    out = []
    for step_fn in seq:
        out.append(step_fn(c1, p1))
        out.append(step_fn(c2, p2))
    d1: GateDecision = out[-2]
    d2: GateDecision = out[-1]
    assert (d1.allow_new_positions, d1.reduce_only, d1.halt_all, d1.size_multiplier, d1.reason) == \
           (d2.allow_new_positions, d2.reduce_only, d2.halt_all, d2.size_multiplier, d2.reason)


def test_no_empty_scope_leak_on_snapshot_updates():
    """Ensure we never create '' keys in per_strategy/per_symbol."""
    clock = Clock(1_728_000_000)
    p = init_protector(clock)
    p.ingest_snapshot(SnapshotEvent(
        ts_s=clock.now(),
        equity_start_of_day_usd=1000.0,
        equity_current_usd=1000.0,
        strategy_equity_usd={"S": 1000.0},
        symbol_equity_usd={"BTC/USD": 1000.0},
    ))
    st = p.current_state()
    assert "" not in st.per_strategy
    assert "" not in st.per_symbol
