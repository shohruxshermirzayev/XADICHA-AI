from __future__ import annotations

from ..config import Config
from .base import LLMProvider, ProviderError
from .rule_based import RuleBasedProvider


def make_provider(cfg: Config) -> LLMProvider:
    if cfg.provider == "gemini":
        return _make_gemini(cfg)
    if cfg.provider == "claude":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg.anthropic_api_key, cfg.claude_model)
    if cfg.provider == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(cfg.ollama_url, cfg.ollama_model)
    return RuleBasedProvider()


def _make_gemini(cfg: Config) -> LLMProvider:
    """Gemini (asosiy) + Ollama (zaxira). Kalit yo'q / SDK yo'q bo'lsa — zaxira ishlaydi, sabab statusda ko'rinadi."""
    from .gemini_provider import GeminiProvider

    primary: LLMProvider | None = None
    error = ""
    try:
        primary = GeminiProvider(cfg.gemini_api_key, cfg.gemini_model, cfg.gemini_timeout_s, cfg.gemini_thinking,
                                 fallback_models=cfg.gemini_fallback_models)
    except ProviderError as e:
        if cfg.fallback != "ollama":
            raise
        error = str(e)
    if cfg.fallback != "ollama":
        return primary   # type: ignore[return-value]
    from .fallback import FallbackProvider
    from .ollama_provider import OllamaProvider

    return FallbackProvider(primary, OllamaProvider(cfg.ollama_url, cfg.ollama_model),
                            primary_name="gemini", primary_model=cfg.gemini_model, primary_error=error)


__all__ = ["LLMProvider", "ProviderError", "RuleBasedProvider", "make_provider"]
