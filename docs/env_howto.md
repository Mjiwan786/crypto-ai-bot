# Environment Configuration Guide

This guide explains how to set up your environment variables for the crypto AI bot.

## Quick Start

1. **Copy the template:**
   ```bash
   cp .env.example .env
   ```

2. **Fill in your values:**
   - Open `.env` in your preferred editor
   - Replace empty values with your actual credentials
   - Keep the template values that don't need changing

3. **Never commit secrets:**
   - The `.env` file is already in `.gitignore`
   - Only commit `.env.example` (the template)
   - Double-check before any git operations

## Configuration Sections

### App Settings
- `APP_ENV=prod` - Environment mode
- `TZ=UTC` - Timezone (keep UTC for consistency)
- `LOG_LEVEL=INFO` - Logging verbosity
- `PAPER_TRADING=true` - Enable paper trading (safe for testing)
- `RISK_HARD_KILL=true` - Enable hard risk limits
- `MAX_CONCURRENT_ORDERS=3` - Maximum simultaneous orders

### Kraken Exchange
- `KRAKEN_API_KEY` - Your Kraken API key
- `KRAKEN_API_SECRET` - Your Kraken API secret
- `KRAKEN_SANDBOX=false` - Use live trading (set to true for testing)

### Redis Cloud (TLS)
- `REDIS_URL` - Your Redis Cloud connection URL
- `REDIS_PASSWORD` - Redis password
- `REDIS_DB=0` - Database number
- `REDIS_SSL=true` - Enable TLS encryption
- `REDIS_SSL_CERT_REQS=required` - Require valid certificates
- `REDIS_CA_CERT_USE_CERTIFI=true` - Use certifi for CA certificates
- `REDIS_CA_CERT_PATH=config/certs/redis_ca.pem` - Path to CA certificate
- `REDIS_SSL_CHECK_HOSTNAME=true` - Verify hostname
- `REDIS_DECODE_RESPONSES=true` - Decode responses to strings

### Notifications (Optional)
- `DISCORD_BOT_TOKEN` - Discord bot token for notifications
- `DISCORD_GUILD_ID` - Discord server ID
- `DISCORD_CHANNEL_ID` - Discord channel ID
- `TELEGRAM_BOT_TOKEN` - Telegram bot token
- `TELEGRAM_CHAT_ID` - Telegram chat ID

## Windows-Specific Notes

- **No chmod needed:** Windows doesn't require file permission changes
- **File encoding:** The `.env` file uses UTF-8 encoding
- **Path separators:** Use forward slashes `/` in paths (works on Windows too)

## Security Best Practices

1. **Never share your `.env` file**
2. **Use strong, unique passwords**
3. **Rotate API keys regularly**
4. **Enable 2FA on all exchange accounts**
5. **Start with paper trading** (`PAPER_TRADING=true`)
6. **Test with small amounts** before going live

## Troubleshooting

- **Connection issues:** Check your Redis URL and credentials
- **API errors:** Verify your Kraken API key permissions
- **SSL errors:** Ensure your CA certificate is in the correct location
- **Paper trading:** Set `PAPER_TRADING=true` for safe testing

## Getting Help

If you encounter issues:
1. Check the logs for specific error messages
2. Verify all required environment variables are set
3. Test your Redis connection separately
4. Test your Kraken API connection separately
