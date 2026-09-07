"""
N.A.S.H - Seleção do provedor de IA.

O provedor é escolhido pela variável de ambiente AI_PROVIDER:

    ollama  -> modelo local (padrão, gratuito, exige o Ollama rodando na máquina)
    openai  -> API da OpenAI  (exige OPENAI_API_KEY)
    gemini  -> API do Google  (exige GEMINI_API_KEY)

Os provedores são importados sob demanda, e não no topo do arquivo, porque
cada um traz sua própria dependência (`requests`, `openai`, `google-genai`).
Assim, quem usa apenas o Ollama não precisa instalar as bibliotecas dos outros.
"""
import os
import logging

logger = logging.getLogger("nash.ai.factory")

DEFAULT_PROVIDER = "ollama"
SUPPORTED_PROVIDERS = ("ollama", "openai", "gemini")


class UnknownProviderError(ValueError):
    """AI_PROVIDER foi preenchida com um valor que não existe."""
    pass


def get_provider_name() -> str:
    """Nome do provedor configurado, normalizado."""
    return (os.environ.get("AI_PROVIDER") or DEFAULT_PROVIDER).strip().lower()


def build_provider():
    """
    Instancia o provedor de IA configurado.

    Levanta UnknownProviderError se AI_PROVIDER tiver um valor inválido —
    é melhor o servidor recusar subir do que rodar em silêncio com um
    provedor diferente do que o operador pediu.
    """
    name = get_provider_name()

    if name not in SUPPORTED_PROVIDERS:
        raise UnknownProviderError(
            f"AI_PROVIDER='{name}' não é um provedor conhecido. "
            f"Use um de: {', '.join(SUPPORTED_PROVIDERS)}."
        )

    if name == "ollama":
        from backend.ai.ollama_provider import OllamaProvider
        provider = OllamaProvider()

    elif name == "openai":
        from backend.ai.openai_provider import OpenAIProvider
        provider = OpenAIProvider()

    else:  # gemini
        from backend.ai.gemini_provider import GeminiProvider
        provider = GeminiProvider()

    logger.info(
        "Provedor de IA: %s (modelo: %s, configurado: %s)",
        name, provider.model, provider.is_configured(),
    )
    return provider
