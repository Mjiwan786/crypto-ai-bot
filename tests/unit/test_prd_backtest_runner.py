"""
Unit tests for PRD-001 Section 6.4 Backtest Runner

Tests coverage:
- PRDBacktestRunner initialization
- Backtest execution
- HTML report generation
- Acceptance criteria enforcement
- Results storage in out/backtests/

Author: Crypto AI Bot Team
"""

import pytest
import json
from pathlib import Path
from datetime import datetime

from backtesting.prd_backtest_runner import PRDBacktestRunner, BacktestResults


class TestPRDBacktestRunnerInit:
    """Test PRDBacktestRunner initialization."""

    def test_init_default(self):
        """Test initialization with default parameters."""
        runner = PRDBacktestRunner()

        assert runner.output_dir == Path("out/backtests")
        assert runner.reports_dir == Path("docs")
        assert runner.data_provider is not None
        assert runner.metrics_calculator is not None
        assert runner.acceptance_criteria is not None

    def test_init_custom_dirs(self):
        """Test initialization with custom directories."""
        output_dir = Path("custom/output")
        reports_dir = Path("custom/reports")

        runner = PRDBacktestRunner(
            output_dir=output_dir,
            reports_dir=reports_dir
        )

        assert runner.output_dir == output_dir
        assert runner.reports_dir == reports_dir

    def test_init_creates_directories(self):
        """Test that initialization creates output directories."""
        import tempfile
        import shutil

        temp_dir = Path(tempfile.mkdtemp())

        try:
            output_dir = temp_dir / "output"
            reports_dir = temp_dir / "reports"

            runner = PRDBacktestRunner(
                output_dir=output_dir,
                reports_dir=reports_dir
            )

            assert output_dir.exists()
            assert reports_dir.exists()

        finally:
            shutil.rmtree(temp_dir)


class TestBacktestExecution:
    """Test backtest execution."""

    def test_run_backtest_basic(self):
        """Test basic backtest execution."""
        runner = PRDBacktestRunner()

        results = runner.run_backtest(
            strategy="scalper",
            pair="BTC/USD",
            period_days=30,  # Short period for test
            timeframe="1h",
            initial_capital=10000.0,
            use_latest_data=False  # Use cached data
        )

        assert results is not None
        assert results.strategy == "scalper"
        assert results.pair == "BTC/USD"
        assert results.period_days == 30
        assert results.timeframe == "1h"
        assert results.initial_capital == 10000.0

        # Check metrics
        assert results.metrics is not None
        assert hasattr(results.metrics, 'total_return_pct')
        assert hasattr(results.metrics, 'sharpe_ratio')
        assert hasattr(results.metrics, 'max_drawdown_pct')

        # Check acceptance result
        assert results.acceptance_result is not None
        assert hasattr(results.acceptance_result, 'passed')

    def test_run_backtest_saves_results(self):
        """Test that backtest results are saved to JSON."""
        runner = PRDBacktestRunner()

        results = runner.run_backtest(
            strategy="test_strategy",
            pair="BTC/USD",
            period_days=7,
            use_latest_data=False
        )

        # Check that JSON file was created
        output_files = list(runner.output_dir.glob("test_strategy_BTC_USD_*.json"))
        assert len(output_files) > 0

        # Verify JSON content
        latest_file = output_files[-1]
        with open(latest_file, 'r') as f:
            data = json.load(f)

        assert data['strategy'] == "test_strategy"
        assert data['pair'] == "BTC/USD"
        assert 'metrics' in data
        assert 'acceptance_result' in data


class TestHTMLReportGeneration:
    """Test HTML report generation."""

    def test_generate_html_report(self):
        """Test HTML report generation."""
        runner = PRDBacktestRunner()

        # Run backtest
        results = runner.run_backtest(
            strategy="scalper",
            pair="BTC/USD",
            period_days=30,
            use_latest_data=False
        )

        # Generate HTML report
        html_path = runner.generate_html_report(
            results, "scalper", "BTC/USD"
        )

        assert html_path.exists()
        assert html_path.suffix == ".html"

        # Check HTML content
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        assert "scalper" in html_content.lower()
        assert "BTC/USD" in html_content
        assert "Equity Curve" in html_content
        assert "Total Return" in html_content
        assert "Sharpe Ratio" in html_content

    def test_html_report_contains_chart(self):
        """Test that HTML report contains Chart.js equity curve."""
        runner = PRDBacktestRunner()

        results = runner.run_backtest(
            strategy="momentum",
            pair="ETH/USD",
            period_days=30,
            use_latest_data=False
        )

        html_path = runner.generate_html_report(
            results, "momentum", "ETH/USD"
        )

        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Check for Chart.js
        assert "chart.js" in html_content.lower()
        assert "canvas" in html_content.lower()
        assert "equityChart" in html_content

    def test_html_report_shows_failures_when_failed(self):
        """Test that HTML report shows acceptance failures."""
        runner = PRDBacktestRunner()

        results = runner.run_backtest(
            strategy="test",
            pair="BTC/USD",
            period_days=7,  # Short period likely to fail
            use_latest_data=False
        )

        html_path = runner.generate_html_report(
            results, "test", "BTC/USD"
        )

        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # If acceptance failed, should show failures
        if not results.acceptance_result.passed:
            assert "Acceptance Criteria Failures" in html_content or "FAILED" in html_content


class TestAcceptanceCriteriaEnforcement:
    """Test acceptance criteria enforcement in CI mode."""

    def test_check_acceptance_criteria_and_exit_on_failure(self):
        """Test that check_acceptance_criteria_and_exit exits on failure."""
        runner = PRDBacktestRunner()

        results = runner.run_backtest(
            strategy="test",
            pair="BTC/USD",
            period_days=7,  # Likely to fail acceptance
            use_latest_data=False
        )

        # If criteria failed, should exit with code 1
        if not results.acceptance_result.passed:
            with pytest.raises(SystemExit) as exc_info:
                runner.check_acceptance_criteria_and_exit(results.metrics)

            assert exc_info.value.code == 1


class TestSingletonInstance:
    """Test singleton instance."""

    def test_get_backtest_runner_singleton(self):
        """Test that get_backtest_runner returns singleton."""
        from backtesting.prd_backtest_runner import get_backtest_runner

        runner1 = get_backtest_runner()
        runner2 = get_backtest_runner()

        assert runner1 is runner2
