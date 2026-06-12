"""Model registry for nakama_kun AI integrations."""

SUPPORTED_MODELS: dict[str, str] = {
    "gpt-5": "openai/gpt-5",
    "gpt-5-mini": "openai/gpt-5-mini",
    "claude-opus": "anthropic/claude-opus-4.1",
    "claude-sonnet": "anthropic/claude-sonnet-4",
    "gemini-pro": "google/gemini-2.5-pro",
    "deepseek-r1": "deepseek/deepseek-r1",
    "deepseek-chat": "deepseek/deepseek-chat",
    "llama-maverick": "meta-llama/llama-4-maverick",
    
    # user specified short keys
    "gpt5": "openai/gpt-5",
    "claude": "anthropic/claude-sonnet-4",
    "opus": "anthropic/claude-opus-4.1",
    "gemini": "google/gemini-2.5-pro",
    "r1": "deepseek/deepseek-r1",
}


def get_model_identifier(model_name: str) -> str:
    """
    Resolve a model name or friendly key to the full OpenRouter model identifier.

    If the name is not in the registry, it is returned as-is, allowing direct usage
    of any OpenRouter model identifier.
    """
    return SUPPORTED_MODELS.get(model_name.lower(), model_name)
