"""Claude (Anthropic API) provayderi."""

from __future__ import annotations

from ..vision.screen import Screenshot
from .base import LLMProvider, ProviderError


class AnthropicProvider(LLMProvider):
    name = "claude"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY o'rnatilmagan.")
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, screen: Screenshot | None) -> str:
        import anthropic

        content: list[dict] = []
        if screen is not None:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": screen.media_type, "data": screen.png_base64}})
        content.append({"type": "text", "text": user})
        try:
            msg = self._client.messages.create(
                model=self.model, max_tokens=1024, system=system,
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIError as e:
            raise ProviderError(f"Claude API xatosi: {e.__class__.__name__}") from e
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
