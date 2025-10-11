<#  validate_env.ps1
    Production validator for crypto-ai-bot .env
    Usage examples:
      powershell -ExecutionPolicy Bypass -File .\validate_env.ps1 -DotEnvPath .\.env -CheckOnline
      .\validate_env.ps1 -DotEnvPath ..\..\crypto_ai_bot\.env -Quiet
#>

param(
  [string]$DotEnvPath = ".\.env",
  [switch]$CheckOnline,          # hit external APIs (OpenAI/Twitter/Reddit/CryptoPanic)
  [switch]$Quiet                 # minimal output
)

# ---------- Helpers ----------
$ErrorActionPreference = "Stop"

function Write-Info($msg)  { if(-not $Quiet){ Write-Host "[i] $msg" -ForegroundColor Cyan } }
function Write-Ok($msg)    { if(-not $Quiet){ Write-Host "[OK] $msg" -ForegroundColor Green } }
function Write-Warn($msg)  { if(-not $Quiet){ Write-Host "[WARN] $msg" -ForegroundColor Yellow } }
function Write-Err($msg)   { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Exit-OnError($msg, [int]$code=1) { Write-Err $msg; exit $code }

function Assert-File([string]$path){
  if(-not (Test-Path -LiteralPath $path)){ Exit-OnError "File not found: $path" 2 }
}

function Import-DotEnv([string]$path){
  # Simple .env parser (ignores comments, preserves quoted values)
  Get-Content -LiteralPath $path | ForEach-Object {
    $line = $_.Trim()
    if($line -eq "" -or $line.StartsWith("#")){ return }
    $eq = $line.IndexOf("=")
    if($eq -lt 1){ return }
    $k = $line.Substring(0,$eq).Trim()
    $v = $line.Substring($eq+1).Trim()
    # Strip surrounding quotes if present
    if(($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))){
      $v = $v.Substring(1, $v.Length-2)
    }
    [Environment]::SetEnvironmentVariable($k, $v, "Process") | Out-Null
  }
}

function Test-Vars([string[]]$names){
  $missing = @()
  foreach($n in $names){
    if([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($n))){
      $missing += $n
    }
  }
  if($missing.Count -gt 0){
    Exit-OnError "Missing required env vars: $($missing -join ', ')" 10
  }
  Write-Ok "Required variables present: $($names -join ', ')"
}

function Test-Command($name){ $null -ne (Get-Command $name -ErrorAction SilentlyContinue) }

function Test-Redis(){
  $url = $env:REDIS_URL
  if([string]::IsNullOrWhiteSpace($url)){ Exit-OnError "REDIS_URL is empty" 11 }

  Write-Info "Testing Redis via redis-cli (if available)..."
  if(Test-Command "redis-cli"){
    # Build TLS flags if scheme = rediss
    $useTls = $url.StartsWith("rediss://")
    $tlsArgs = @()
    if($useTls){
      $tlsArgs += "--tls"
      if($env:REDIS_CA_CERT_PATH){ $tlsArgs += @("--cacert", $env:REDIS_CA_CERT_PATH) }
    }
    try{
      $ping = & redis-cli -u $url @tlsArgs ping 2>$null
      if($ping -and $ping.Trim().ToUpper() -in @("PONG","OK","TRUE")){
        Write-Ok "Redis PING succeeded ($ping)"
      } else {
        Write-Warn "redis-cli returned: '$ping' (continuing)"
      }
    } catch {
      Write-Warn "redis-cli failed: $($_.Exception.Message)"
    }
  } else {
    Write-Warn "redis-cli not found; skipping active PING. (Optional)"
  }
}

function Test-HTTP([string]$url, [hashtable]$headers){
  try{
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $url -Headers $headers -Method GET -TimeoutSec 15
    return $resp.StatusCode
  } catch {
    return -1
  }
}

# ---------- Start ----------
Write-Info "validate_env.ps1 starting..."
Assert-File -path $DotEnvPath
Write-Info "Loading .env from: $DotEnvPath"
Import-DotEnv -path $DotEnvPath
Write-Ok "Loaded .env into process env"

# ---- Core presence checks ----
$requiredCore = @(
  "ENVIRONMENT","TIMEZONE","LOG_LEVEL",
  "PAPER_TRADING_ENABLED","LIVE_TRADING_CONFIRMATION"
)
Test-Vars $requiredCore

# ---- Redis checks ----
$requiredRedis = @("REDIS_URL")
Test-Vars $requiredRedis
Test-Redis

# Optional Redis TLS hints
if($env:REDIS_URL -like "rediss://*"){
  if([string]::IsNullOrWhiteSpace($env:REDIS_CA_CERT_PATH) -and $env:REDIS_CA_CERT_USE_CERTIFI -ne "true"){
    Write-Warn "TLS enabled but no CA path and certifi not requested; verification may fail on some hosts."
  }
}

# ---- Kraken presence + public status ----
$requiredKraken = @("KRAKEN_API_URL")
Test-Vars $requiredKraken
Write-Info "Checking Kraken public system status..."
try{
  $status = Invoke-RestMethod -Uri "$($env:KRAKEN_API_URL)/0/public/SystemStatus" -Method GET -TimeoutSec 15
  if($status -and $status.status -eq "ok"){
    Write-Ok "Kraken public endpoint reachable"
  } else {
    Write-Warn "Kraken public endpoint responded but not 'ok' (info only)"
  }
} catch {
  Write-Warn "Kraken public status check failed: $($_.Exception.Message)"
}
# Keys presence (don't call private endpoints here)
if([string]::IsNullOrWhiteSpace($env:KRAKEN_API_KEY) -or [string]::IsNullOrWhiteSpace($env:KRAKEN_API_SECRET)){
  Write-Warn "KRAKEN_API_KEY/SECRET not set (paper/dev ok)."
} else {
  Write-Ok "Kraken API key/secret present."
}

# ---- MCP/AI presence ----
$requiredMcp = @("MCP_ENABLED","MCP_ROLE")
Test-Vars $requiredMcp

$requiredOpenAI = @("OPENAI_API_KEY","OPENAI_MODEL")
Test-Vars $requiredOpenAI

# ---- Sentiment inputs presence (soft) ----
$anySentiment = @(
  $env:TWITTER_BEARER_TOKEN,
  $env:REDDIT_CLIENT_ID,
  $env:CRYPTOPANIC_API_KEY
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

if($anySentiment.Count -eq 0){
  Write-Warn "No sentiment API creds provided yet (Twitter/Reddit/CryptoPanic)."
} else {
  Write-Ok "At least one sentiment source has credentials."
}

# ---- Optional Online checks ----
if($CheckOnline){
  Write-Info "Running online checks (safe, read-only)..."

  # OpenAI: list models (harmless)
  if(-not [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)){
    try{
      $headers = @{ "Authorization" = "Bearer $($env:OPENAI_API_KEY)" }
      $code = Test-HTTP -url "https://api.openai.com/v1/models" -headers $headers
      if($code -eq 200){ Write-Ok "OpenAI reachable (models endpoint 200)" }
      elseif($code -eq 401){ Write-Err "OpenAI key rejected (401). Check OPENAI_API_KEY." }
      else { Write-Warn "OpenAI HTTP status: $code" }
    } catch { Write-Warn "OpenAI check error: $($_.Exception.Message)" }
  }

  # Twitter (X): recent search w/ bearer (safe)
  if(-not [string]::IsNullOrWhiteSpace($env:TWITTER_BEARER_TOKEN)){
    $headers = @{ "Authorization" = "Bearer $($env:TWITTER_BEARER_TOKEN)" }
    $q = [System.Web.HttpUtility]::UrlEncode("bitcoin")
    $twitterUrl = "https://api.twitter.com/2/tweets/search/recent?query=$q" + [char]38 + "max_results=10"
    $code = Test-HTTP -url $twitterUrl -headers $headers
    if($code -eq 200){ Write-Ok "Twitter API reachable" }
    elseif($code -eq 401){ Write-Err "Twitter bearer rejected (401)." }
    else { Write-Warn "Twitter HTTP status: $code" }
  }

  # Reddit: public subreddit about (no auth required)
  try{
    $userAgent = if (![string]::IsNullOrWhiteSpace($env:REDDIT_USER_AGENT)) { $env:REDDIT_USER_AGENT } else { "crypto-ai-bot/1.0" }
    $headers = @{ "User-Agent" = $userAgent }
    $code = Test-HTTP -url "https://www.reddit.com/r/cryptocurrency/about.json" -headers $headers
    if($code -eq 200){ Write-Ok "Reddit public reachable" }
    else { Write-Warn "Reddit HTTP status: $code" }
  } catch { Write-Warn "Reddit check error: $($_.Exception.Message)" }

  # CryptoPanic (requires token)
  if(-not [string]::IsNullOrWhiteSpace($env:CRYPTOPANIC_API_KEY)){
    $cryptoPanicUrl = "https://cryptopanic.com/api/v1/posts/?auth_token=$($env:CRYPTOPANIC_API_KEY)" + [char]38 + "kind=news"
    $code = Test-HTTP -url $cryptoPanicUrl -headers @{}
    if($code -eq 200){ Write-Ok "CryptoPanic reachable" }
    elseif($code -eq 401){ Write-Err "CryptoPanic token rejected (401)." }
    else { Write-Warn "CryptoPanic HTTP status: $code" }
  }
}

Write-Ok "Environment validation completed."
exit 0