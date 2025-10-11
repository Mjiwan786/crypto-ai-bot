#!/usr/bin/env python3
"""
Tests for the preflight hard checks system
"""

import pytest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestPreflightHardChecks:
    """Test the preflight hard checks functionality"""
    
    def test_preflight_script_exists(self):
        """Test that the preflight script exists and is executable"""
        script_path = Path("scripts/preflight_hard_checks.py")
        assert script_path.exists(), "Preflight script should exist"
        assert script_path.is_file(), "Preflight script should be a file"
    
    def test_preflight_script_help(self):
        """Test that the preflight script shows help when requested"""
        result = subprocess.run(
            [sys.executable, "scripts/preflight_hard_checks.py", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        assert result.returncode == 0, "Help should be shown successfully"
        assert "Crypto AI Bot Preflight Checks" in result.stdout
        assert "--verbose" in result.stdout
    
    def test_preflight_script_version_check(self):
        """Test that the preflight script checks Python version"""
        result = subprocess.run(
            [sys.executable, "scripts/preflight_hard_checks.py"],
            capture_output=True,
            text=True,
            timeout=30
        )
        # Should not fail due to version (we're running 3.10)
        assert "Python runtime" in result.stdout
        assert "3.10" in result.stdout
    
    def test_preflight_script_verbose_mode(self):
        """Test that verbose mode works"""
        result = subprocess.run(
            [sys.executable, "scripts/preflight_hard_checks.py", "--verbose"],
            capture_output=True,
            text=True,
            timeout=30
        )
        # Should show verbose output
        assert "[INFO]" in result.stdout or "[WARN]" in result.stdout
    
    def test_powershell_wrapper_exists(self):
        """Test that PowerShell wrapper exists"""
        ps1_path = Path("scripts/preflight_hard_checks.ps1")
        assert ps1_path.exists(), "PowerShell wrapper should exist"
        assert ps1_path.is_file(), "PowerShell wrapper should be a file"
    
    def test_bash_wrapper_exists(self):
        """Test that bash wrapper exists"""
        sh_path = Path("scripts/preflight_hard_checks.sh")
        assert sh_path.exists(), "Bash wrapper should exist"
        assert sh_path.is_file(), "Bash wrapper should be a file"
    
    def test_readme_exists(self):
        """Test that README exists"""
        readme_path = Path("scripts/README_PREFLIGHT.md")
        assert readme_path.exists(), "README should exist"
        assert readme_path.is_file(), "README should be a file"
        
        # Check that README contains key information
        readme_content = readme_path.read_text(encoding='utf-8')
        assert "Preflight Hard Checks" in readme_content
        assert "Windows" in readme_content
        assert "Linux" in readme_content
        assert "macOS" in readme_content
    
    @patch('subprocess.run')
    def test_host_specs_check(self, mock_run):
        """Test host specifications check"""
        # Mock psutil to return test values
        with patch('psutil.cpu_count', return_value=4), \
             patch('psutil.virtual_memory', return_value=MagicMock(total=8*1024**3)), \
             patch('psutil.disk_usage', return_value=MagicMock(free=100*1024**3)):
            
            from scripts.preflight_hard_checks import PreflightChecker
            checker = PreflightChecker()
            checker.check_host_specs()
            
            # Should pass with sufficient resources
            assert len(checker.failed_checks) == 0
    
    @patch('subprocess.run')
    def test_host_specs_check_insufficient_cpu(self, mock_run):
        """Test host specifications check with insufficient CPU"""
        # Mock psutil to return insufficient CPU
        with patch('psutil.cpu_count', return_value=1), \
             patch('psutil.virtual_memory', return_value=MagicMock(total=8*1024**3)), \
             patch('psutil.disk_usage', return_value=MagicMock(free=100*1024**3)):
            
            from scripts.preflight_hard_checks import PreflightChecker
            checker = PreflightChecker()
            checker.check_host_specs()
            
            # Should fail with insufficient CPU
            assert len(checker.failed_checks) > 0
            assert any("Insufficient CPU cores" in check for check in checker.failed_checks)
    
    def test_logs_path_check(self):
        """Test logs path check"""
        from scripts.preflight_hard_checks import PreflightChecker
        checker = PreflightChecker()
        checker.check_logs_path()
        
        # Should pass (logs directory should exist)
        assert len(checker.failed_checks) == 0
    
    def test_secrets_hygiene_check(self):
        """Test secrets hygiene check"""
        from scripts.preflight_hard_checks import PreflightChecker
        checker = PreflightChecker()
        checker.check_secrets_hygiene()
        
        # Should pass (no hardcoded secrets in our config)
        assert len(checker.failed_checks) == 0
    
    @patch('os.environ.get')
    def test_redis_connectivity_no_url(self, mock_env):
        """Test Redis connectivity check with no URL"""
        mock_env.return_value = None
        
        from scripts.preflight_hard_checks import PreflightChecker
        checker = PreflightChecker()
        checker.check_redis_connectivity()
        
        # Should fail without REDIS_URL
        assert len(checker.failed_checks) > 0
        assert any("REDIS_URL not set" in check for check in checker.failed_checks)
    
    def test_config_sanity_check(self):
        """Test configuration sanity check"""
        from scripts.preflight_hard_checks import PreflightChecker
        checker = PreflightChecker()
        checker.check_config_sanity()
        
        # Should pass (config files exist and are valid)
        assert len(checker.failed_checks) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
