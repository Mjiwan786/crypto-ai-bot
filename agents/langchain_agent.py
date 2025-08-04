import os
from dotenv import load_dotenv

from langchain_community.chat_models import ChatOpenAI
from langchain.agents import Tool, AgentType, initialize_agent
from langchain.memory import ConversationBufferMemory

# Import internal agents
from agents.core.signal_analyst import SignalAnalyst
from agents.core.sentiment_agent import SentimentAgent

# Load environment variables (e.g., OPENAI_API_KEY)
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Validate key
if not OPENAI_API_KEY:
    raise ValueError("Missing OpenAI API Key. Please set OPENAI_API_KEY in your .env file")

# Initialize internal agents
signal_agent = SignalAnalyst()
sentiment_agent = SentimentAgent()

# Define LangChain-compatible tools
tools = [
    Tool(
        name="TechnicalSignalTool",
        func=lambda symbol: signal_agent.get_signal(symbol),
        description="Provides Buy/Sell/Hold recommendation based on technical indicators"
    ),
    Tool(
        name="SentimentAnalyzerTool",
        func=lambda symbol: sentiment_agent.analyze(symbol),
        description="Analyzes sentiment for a given crypto symbol (Twitter, Reddit, News)"
    )
]

# Create LangChain LLM agent
llm = ChatOpenAI(
    model="gpt-4",
    temperature=0,
    openai_api_key=OPENAI_API_KEY
)

memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    memory=memory,
    verbose=True
)

def analyze_and_decide(symbol: str):
    """
    Master function that coordinates signal + sentiment
    and returns a strategy decision.
    """
    print(f"\n🧠 Asking LangChain agent to analyze {symbol}...\n")
    prompt = (
        f"Analyze the current state of {symbol} using technical indicators "
        f"and sentiment signals. Based on the analysis, suggest a trading strategy "
        f"(buy, sell, hold, or avoid) with a reason."
    )
    return agent.run(prompt)

# Example CLI usage
if __name__ == "__main__":
    coin = input("Enter symbol (e.g., BTC/USDT): ").strip().upper()
    result = analyze_and_decide(coin)
    print(f"\n📈 Agent Decision: {result}")
