// PM2 Ecosystem Configuration for 24/7 Live Trading System
// Manages all 3 repos: crypto_ai_bot, signals-api, signals-site

module.exports = {
  apps: [
    // ============================================
    // CRYPTO AI BOT (Trading Core)
    // ============================================
    {
      name: 'bot-kraken-ingestor',
      script: 'python',
      args: '-m agents.infrastructure.kraken_ingestor',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\crypto-bot\\python.exe',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      watch: false,
      env: {
        REDIS_URL: process.env.REDIS_URL || '',
        REDIS_CA_CERT: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot\\config\\certs\\redis_ca.pem',
        MODE: 'PAPER',
        LOG_LEVEL: 'INFO'
      }
    },
    {
      name: 'bot-signal-processor',
      script: 'python',
      args: '-m agents.core.signal_processor',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\crypto-bot\\python.exe',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      watch: false,
      max_memory_restart: '800M',
      env: {
        REDIS_URL: process.env.REDIS_URL || '',
        REDIS_CA_CERT: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot\\config\\certs\\redis_ca.pem',
        CONFIG_FILE: 'config/turbo_mode.yaml',
        LOG_LEVEL: 'INFO'
      }
    },
    {
      name: 'bot-execution-agent',
      script: 'python',
      args: '-m agents.core.execution_agent --mode paper',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\crypto-bot\\python.exe',
      autorestart: true,
      max_restarts: 5,  // Lower for safety - don't auto-restart too many times
      min_uptime: '30s',
      restart_delay: 10000,
      watch: false,
      env: {
        REDIS_URL: process.env.REDIS_URL || '',
        REDIS_CA_CERT: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot\\config\\certs\\redis_ca.pem',
        MODE: 'PAPER',
        KRAKEN_API_KEY: process.env.KRAKEN_API_KEY || '',
        KRAKEN_API_SECRET: process.env.KRAKEN_API_SECRET || '',
        LOG_LEVEL: 'INFO'
      }
    },
    {
      name: 'bot-pnl-aggregator',
      script: 'python',
      args: 'monitoring/pnl_aggregator.py',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\crypto-bot\\python.exe',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      watch: false,
      env: {
        REDIS_URL: process.env.REDIS_URL || '',
        REDIS_CA_CERT: 'C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot\\config\\certs\\redis_ca.pem',
        START_EQUITY: '10000.0',
        USE_PANDAS: 'true',
        PNL_METRICS_PORT: '9100',
        LOG_LEVEL: 'INFO'
      }
    },

    // ============================================
    // SIGNALS API (Gateway)
    // ============================================
    {
      name: 'signals-api',
      script: 'uvicorn',
      args: 'app.main:app --host 0.0.0.0 --port 8000',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\signals_api',
      interpreter: 'C:\\Users\\Maith\\.conda\\envs\\signals-api\\python.exe',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      watch: false,
      max_memory_restart: '500M',
      env: {
        APP_ENV: 'prod',
        APP_HOST: '0.0.0.0',
        APP_PORT: '8000',
        REDIS_URL: process.env.REDIS_URL || '',
        REDIS_SSL: 'true',
        SIGNALS_STREAM_ACTIVE: 'signals:paper',
        CORS_ALLOW_ORIGINS: 'https://aipredictedsignals.cloud,https://www.aipredictedsignals.cloud,http://localhost:3000',
        PROMETHEUS_ENABLED: 'true',
        LOG_LEVEL: 'INFO'
      }
    },

    // ============================================
    // SIGNALS SITE (Frontend)
    // ============================================
    {
      name: 'signals-site',
      script: 'npm',
      args: 'start',
      cwd: 'C:\\Users\\Maith\\OneDrive\\Desktop\\signals-site\\web',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      watch: false,
      env: {
        NODE_ENV: 'production',
        PORT: '3000',
        NEXT_PUBLIC_API_URL: 'http://localhost:8000',
        REDIS_URL: process.env.REDIS_URL || ''
      }
    }
  ]
}
