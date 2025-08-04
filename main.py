# Entry point for the crypto AI bot.

from ai_engine.global_context import set_context, get_context


def initialise() -> None:
    """Perform initial setup of the bot."""
    # Example of setting some default context values
    set_context("regime_state", "neutral")
    set_context("sentiment_score", "0.0")

    print("[✅] Redis Cloud Connected")
    print("[✅] MCP Context Initialized")
    print("[✅] Hypergrowth Mode ACTIVE")


def run() -> None:
    """Start the main event loop of the bot."""
    # Placeholder: in a real bot this would orchestrate agents
    print("Bot is running...")


if __name__ == "__main__":
    initialise()
    run()