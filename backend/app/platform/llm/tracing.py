"""Trace synchronous text model calls without changing provider results or signatures."""
import logging
from contextvars import ContextVar
from functools import wraps

from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory
from app.platform.observability.port import Observation, current_turn

logger = logging.getLogger(__name__)
_GENERATION: ContextVar[Observation | None] = ContextVar("text_agent_generation", default=None)


def observe_generation(method):
    with_tools = method.__name__ == "generate_with_tools"

    @wraps(method)
    def observed(provider, *args, **kwargs):
        turn = current_turn()
        if turn is None:
            return method(provider, *args, **kwargs)
        with turn.span("generation", method.__name__, model=provider.model_name) as span:
            if span is None:
                return method(provider, *args, **kwargs)
            token = _GENERATION.set(span)
            try:
                if span.capture_content:
                    try:
                        if with_tools:
                            messages = args[0] if args else kwargs.get("messages", ())
                            span.input = [message["content"] for message in messages
                                          if isinstance(message.get("content"), str)]
                        else:
                            prompt = args[0] if args else kwargs.get("prompt")
                            span.input = [part for part in (kwargs.get("system_prompt"), prompt)
                                          if isinstance(part, str)]
                    except Exception:
                        logger.warning("Model trace input could not be prepared")
                result = method(provider, *args, **kwargs)
                if span.capture_content:
                    try:
                        span.output = result.text if with_tools else result.model_dump_json()
                    except Exception:
                        logger.warning("Model trace output could not be prepared")
                return result
            except Exception as exc:
                span.failure_category = (exc.category.value if isinstance(exc, LLMProviderError)
                                         else LLMProviderFailureCategory.TRANSPORT.value)
                raise
            finally:
                _GENERATION.reset(token)

    return observed


def trace_usage(prompt: int, completion: int, reasoning: int, estimated_cost_usd: float) -> None:
    span = _GENERATION.get()
    if span is not None:
        span.usage = {"input": prompt, "output": completion, "total": prompt + completion,
                      "reasoning": reasoning}
        span.estimated_cost_usd = estimated_cost_usd
