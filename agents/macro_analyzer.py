"""
Macro Analyzer (agents/ interface).

Re-exports from ai_engine.regime_detector.macro_analyzer for backward
compatibility. The real implementation lives there.
"""
from __future__ import annotations

from ai_engine.regime_detector.macro_analyzer import MacroAnalyzer, analyse_macro

__all__ = ["MacroAnalyzer", "analyse_macro"]
