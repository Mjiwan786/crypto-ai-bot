# clean_repo.ps1 - Safe repository cleanup script for crypto-ai-bot
# This script removes development artifacts and caches without affecting source code

param(
    [switch]$Force,
    [switch]$DryRun
)

Write-Host "🧹 Crypto AI Bot Repository Cleanup Script" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "🔍 DRY RUN MODE - No files will be deleted" -ForegroundColor Yellow
}

# Define cleanup targets (safe to remove)
$cleanupTargets = @(
    "**/__pycache__",
    ".pytest_cache",
    ".ruff_cache", 
    ".benchmarks",
    "logs",
    "data/tmp",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.pyd",
    "**/*.so",
    "**/*.egg-info",
    ".coverage",
    "htmlcov",
    "*.egg-info",
    "dist",
    "build"
)

$totalSize = 0
$fileCount = 0

foreach ($pattern in $cleanupTargets) {
    $files = Get-ChildItem -Path . -Recurse -Force -Include $pattern -ErrorAction SilentlyContinue
    
    foreach ($file in $files) {
        if ($file.Exists) {
            $fileCount++
            $size = if ($file.PSIsContainer) {
                (Get-ChildItem -Path $file.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
            } else {
                $file.Length
            }
            $totalSize += $size
            
            $sizeFormatted = if ($size -gt 1MB) { "{0:N2} MB" -f ($size / 1MB) }
                           elseif ($size -gt 1KB) { "{0:N2} KB" -f ($size / 1KB) }
                           else { "{0} bytes" -f $size }
            
            if ($DryRun) {
                Write-Host "Would remove: $($file.FullName) ($sizeFormatted)" -ForegroundColor Yellow
            } else {
                Write-Host "Removing: $($file.FullName) ($sizeFormatted)" -ForegroundColor Red
                try {
                    if ($file.PSIsContainer) {
                        Remove-Item -Path $file.FullName -Recurse -Force
                    } else {
                        Remove-Item -Path $file.FullName -Force
                    }
                } catch {
                    Write-Warning "Failed to remove $($file.FullName): $($_.Exception.Message)"
                }
            }
        }
    }
}

# Summary
$totalSizeFormatted = if ($totalSize -gt 1MB) { "{0:N2} MB" -f ($totalSize / 1MB) }
                     elseif ($totalSize -gt 1KB) { "{0:N2} KB" -f ($totalSize / 1KB) }
                     else { "{0} bytes" -f $totalSize }

Write-Host "`n📊 Cleanup Summary:" -ForegroundColor Green
Write-Host "Files processed: $fileCount" -ForegroundColor White
Write-Host "Total size: $totalSizeFormatted" -ForegroundColor White

if ($DryRun) {
    Write-Host "`n💡 To actually perform cleanup, run: .\scripts\clean_repo.ps1" -ForegroundColor Cyan
} else {
    Write-Host "`n✅ Cleanup completed!" -ForegroundColor Green
}

# Conda environment check
Write-Host "`n🐍 Conda Environment Check:" -ForegroundColor Cyan
try {
    $condaInfo = conda info --envs 2>$null | Select-String "crypto-bot"
    if ($condaInfo) {
        Write-Host "✅ Found conda environment: crypto-bot" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Conda environment 'crypto-bot' not found" -ForegroundColor Yellow
        Write-Host "   Create it with: conda create -n crypto-bot python=3.11" -ForegroundColor Cyan
    }
} catch {
    Write-Host "⚠️  Conda not available or not in PATH" -ForegroundColor Yellow
}

# Redis connection check
Write-Host "`n🔴 Redis Connection Check:" -ForegroundColor Cyan
Write-Host "Redis Cloud URL: redis://default:***@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" -ForegroundColor White
Write-Host "Note: Use --tls --cacert <path_to_ca_certfile> for secure connection" -ForegroundColor Cyan

Write-Host "`n🎯 Next steps:" -ForegroundColor Cyan
Write-Host "1. Activate conda environment: conda activate crypto-bot" -ForegroundColor White
Write-Host "2. Install dependencies: pip install -r requirements.txt" -ForegroundColor White
Write-Host "3. Test Redis connection: scripts/check_redis_tls.py" -ForegroundColor White

