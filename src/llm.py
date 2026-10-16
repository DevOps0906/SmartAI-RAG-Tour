"""LLM 팩토리. 키가 없거나 provider=none 이면 LLMUnavailable 발생 -> 호출부에서 폴백."""
from langchain_core.language_models.chat_models import BaseChatModel

from src.config import get_settings


class LLMUnavailable(RuntimeError):
    pass


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    s = get_settings()
    if s.llm_provider == "anthropic" and s.anthropic_api_key:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=s.llm_model, temperature=temperature,
                             api_key=s.anthropic_api_key, timeout=30, max_retries=2)
    if s.llm_provider == "openai" and s.openai_api_key:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=s.llm_model, temperature=temperature,
                          api_key=s.openai_api_key, timeout=30, max_retries=2)
    # 메시지에 키 값은 넣지 않는다.
    raise LLMUnavailable(f"LLM 사용 불가 (provider={s.llm_provider}, 키 미설정 또는 none)")
