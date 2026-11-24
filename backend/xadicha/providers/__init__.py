from __future__ import annotations

from ..config import Config
from .base import LLMProvider, ProviderError
from .rule_based import RuleBasedProvider


def make_provider(cfg: Config) -> LLMProvider:
    if cfg.provider == "claude":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg.anthropic_api_key, cfg.claude_model)
    if cfg.provider == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(cfg.ollama_url, cfg.ollama_model)
    return RuleBasedProvider()


__all__ = ["LLMProvider", "ProviderError", "RuleBasedProvider", "make_provider"]
