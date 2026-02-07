from plain.runtime import Secret

# The default provider to use when none is specified on the agent.
# Options: "anthropic", "openai"
AI_DEFAULT_PROVIDER: str = "anthropic"

# The default model to use when none is specified on the agent.
# If empty, each provider uses its own default.
AI_DEFAULT_MODEL: str = ""

# API keys - loaded from environment variables by default.
AI_ANTHROPIC_API_KEY: Secret[str] = ""  # type: ignore[assignment]
AI_OPENAI_API_KEY: Secret[str] = ""  # type: ignore[assignment]
