# B1 — Environment Prep & Sanity Check
# PowerShell script for crypto-ai-bot environment setup and validation

Write-Host "=== B1 Environment Prep & Sanity Check ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Activate Conda environment and check Python version
Write-Host "[1/5] Activating Conda environment 'crypto-bot'..." -ForegroundColor Yellow
conda activate crypto-bot
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to activate conda environment 'crypto-bot'" -ForegroundColor Red
    exit 1
}

Write-Host "Python version:" -ForegroundColor Green
python -V

# Verify Python 3.10
$pythonVersion = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($pythonVersion -ne "3.10") {
    Write-Host "WARNING: Expected Python 3.10, got $pythonVersion" -ForegroundColor Yellow
}

Write-Host ""

# Step 2: Install requirements without upgrades
Write-Host "[2/5] Installing requirements.txt (no upgrades)..." -ForegroundColor Yellow
python -m pip install --no-upgrade -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: Some packages failed to install" -ForegroundColor Yellow
}

Write-Host ""

# Step 3: Verify core packages
Write-Host "[3/5] Verifying core package availability..." -ForegroundColor Yellow

$packages = @(
    @{name="ccxt"; import="ccxt"},
    @{name="pandas"; import="pandas"},
    @{name="numpy"; import="numpy"},
    @{name="ta"; import="ta"}
)

$allOk = $true

foreach ($pkg in $packages) {
    $result = python -c @"
try:
    import $($pkg.import)
    print(f'✓ $($pkg.name): {$($pkg.import).__version__}')
except ImportError:
    print('✗ $($pkg.name): NOT INSTALLED')
    exit(1)
except AttributeError:
    import $($pkg.import)
    print('✓ $($pkg.name): installed (version unknown)')
"@ 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host $result -ForegroundColor Green
    } else {
        Write-Host $result -ForegroundColor Red
        $allOk = $false
    }
}

# Check TA-Lib (optional)
Write-Host ""
Write-Host "Checking TA-Lib availability..." -ForegroundColor Cyan
$talibResult = python -c @"
try:
    import talib
    print(f'✓ TA-Lib: {talib.__version__}')
except ImportError:
    print('⚠ TA-Lib: NOT AVAILABLE (will fall back to pure-python indicators)')
except AttributeError:
    import talib
    print('✓ TA-Lib: installed (version unknown)')
"@ 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host $talibResult -ForegroundColor Green
} else {
    Write-Host $talibResult -ForegroundColor Yellow
}

Write-Host ""

# Step 4: Verify Redis connection
Write-Host "[4/5] Testing Redis Cloud connection..." -ForegroundColor Yellow
$redisTest = python -c @"
import redis
try:
    r = redis.from_url(
        'rediss://default:Salam78614**%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818',
        ssl_cert_reqs='required',
        decode_responses=True
    )
    r.ping()
    print('✓ Redis Cloud: CONNECTED')
except Exception as e:
    print(f'✗ Redis Cloud: FAILED - {e}')
    exit(1)
"@ 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host $redisTest -ForegroundColor Green
} else {
    Write-Host $redisTest -ForegroundColor Red
    $allOk = $false
}

Write-Host ""

# Step 5: Create reports directory
Write-Host "[5/5] Creating /reports directory..." -ForegroundColor Yellow
$reportsDir = "reports"
if (-not (Test-Path $reportsDir)) {
    New-Item -ItemType Directory -Path $reportsDir | Out-Null
    Write-Host "✓ Created $reportsDir directory" -ForegroundColor Green
} else {
    Write-Host "✓ $reportsDir directory already exists" -ForegroundColor Green
}

$gitkeepPath = "$reportsDir\.gitkeep"
if (-not (Test-Path $gitkeepPath)) {
    New-Item -ItemType File -Path $gitkeepPath | Out-Null
    Write-Host "✓ Created $gitkeepPath" -ForegroundColor Green
} else {
    Write-Host "✓ $gitkeepPath already exists" -ForegroundColor Green
}

Write-Host ""

# Summary
Write-Host "=== Environment Prep Complete ===" -ForegroundColor Cyan
if ($allOk) {
    Write-Host "✓ All checks passed! Ready for backtesting." -ForegroundColor Green
    exit 0
} else {
    Write-Host "⚠ Some checks failed. Review output above." -ForegroundColor Yellow
    exit 1
}
