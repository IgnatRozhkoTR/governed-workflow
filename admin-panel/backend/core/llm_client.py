"""Thin LLM client: OpenAI (preferred) or Anthropic, driven by env vars."""
import os


_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"


class LLMClientError(Exception):
    """Raised when the LLM call cannot be completed."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _model_from_env(default: str) -> str:
    return os.environ.get("GW_REFLECTION_MODEL") or default


def _call_openai(prompt: str, model: str, json_mode: bool) -> str:
    from openai import OpenAI  # type: ignore[import]

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def _call_anthropic(prompt: str, model: str) -> str:
    import anthropic  # type: ignore[import]

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""


def complete(prompt: str, model: str | None = None, json_mode: bool = False) -> str:
    """Call the configured LLM and return the text response.

    Prefers OPENAI_API_KEY over ANTHROPIC_API_KEY when both are set.
    Raises LLMClientError(code='unconfigured') when neither key is present.
    """
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not openai_key and not anthropic_key:
        raise LLMClientError(
            "No LLM API key configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY.",
            code="unconfigured",
        )

    try:
        if openai_key:
            resolved_model = model or _model_from_env(_DEFAULT_OPENAI_MODEL)
            return _call_openai(prompt, resolved_model, json_mode)

        resolved_model = model or _model_from_env(_DEFAULT_ANTHROPIC_MODEL)
        return _call_anthropic(prompt, resolved_model)
    except LLMClientError:
        raise
    except Exception as exc:
        raise LLMClientError(str(exc), code="api_error") from exc
