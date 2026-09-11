from __future__ import annotations

from typing import Any

from app.config import settings
from app.logging import get_logger

log = get_logger("acme.ap.llm")


def provider_name() -> str | None:
    if settings.xai_api_key:
        return "xai"
    if settings.openai_api_key:
        return "openai"
    if settings.anthropic_api_key:
        return "anthropic"
    if settings.google_api_key:
        return "google"
    return None


def get_chat_model() -> tuple[Any, str] | tuple[None, None]:
    """Return (model, provider). xAI is OpenAI-compatible; the brief's `from xai import Grok` is not a real SDK."""
    if settings.xai_api_key:
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            base_url="https://api.x.ai/v1",
            api_key=settings.xai_api_key,
            model=settings.xai_model,
            temperature=0,
        )
        return model, "xai"
    if settings.openai_api_key:
        from langchain_openai import ChatOpenAI

        return (
            ChatOpenAI(api_key=settings.openai_api_key, model=settings.openai_model, temperature=0),
            "openai",
        )
    if settings.anthropic_api_key:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            log.warning("ANTHROPIC_API_KEY set but langchain-anthropic is not installed")
            return None, None
        return (
            ChatAnthropic(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
                temperature=0,
            ),
            "anthropic",
        )
    if settings.google_api_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            log.warning("GOOGLE_API_KEY set but langchain-google-genai is not installed")
            return None, None
        return (
            ChatGoogleGenerativeAI(
                google_api_key=settings.google_api_key,
                model=settings.google_model,
                temperature=0,
            ),
            "google",
        )
    return None, None
