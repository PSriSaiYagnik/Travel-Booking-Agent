from functools import lru_cache
from langchain_cerebras import ChatCerebras
from app.core.config import settings


@lru_cache(maxsize=1)
def get_llm(temperature: float = 0.2) -> ChatCerebras:
    """Return a cached ChatCerebras instance.

    Args:
        temperature: Sampling temperature. Default 0.2 keeps outputs
                     deterministic and factual — good for structured
                     extraction and routing. Raise to 0.7 if you want
                     more creative response generation.

    Returns:
        A LangChain-compatible ChatCerebras model instance.
    """
    return ChatCerebras(
        model=settings.CEREBRAS_MODEL,
        api_key=settings.CEREBRAS_API_KEY,
        temperature=temperature,
    )


# Convenience singleton — used by all agent nodes.
llm: ChatCerebras = get_llm()
