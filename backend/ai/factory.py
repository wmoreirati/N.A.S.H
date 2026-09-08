"""
N.A.S.H - Seleção do provedor de IA.

O provedor é escolhido pela variável de ambiente AI_PROVIDER:

    ollama      -> modelo local (padrão, gratuito, exige o Ollama na máquina)
    openai      -> API da OpenAI          (exige OPENAI_API_KEY)
    openrouter  -> catálogo do OpenRouter (exige OPENROUTER_API_KEY)
    gemini      -> API do Google          (exige GEMINI_API_KEY)

Os provedores são importados sob demanda, e não no topo do arquivo, porque
cada um traz sua própria dependência (`requests`, `openai`, `google-genai`).
Assim, quem usa apenas o Ollama não precisa instalar as bibliotecas dos outros.
"""
import os
import logging

logger = logging.getLogger("nash.ai.factory")

DEFAULT_PROVIDER = "ollama"
SUPPORTED_PROVIDERS = ("ollama", "openai", "openrouter", "gemini")


class UnknownProviderError(ValueError):
    """AI_PROVIDER foi preenchida com um valor que não existe."""
    pass


class UnavailableProvider:
    """
    Substituto usado quando o provedor configurado não pôde ser carregado —
    biblioteca ausente, incompatível, ou erro na construção.

    Existe para que uma falha do provedor de IA não derrube a aplicação
    inteira. Sem isso, um erro de importação em produção vira um crash na
    subida do processo, e o usuário perde tarefas, projetos e interface por
    causa do chat. Com isso, o site continua de pé e o motivo real aparece
    em /api/health e na mensagem do chat.
    """

    def __init__(self, nome: str, motivo: str):
        self.nome = nome
        self.motivo = motivo
        self.model = None

    def is_configured(self) -> bool:
        return False

    def chat(self, messages, tools=None):
        from backend.ai.provider import AIServiceUnavailableError
        raise AIServiceUnavailableError(
            f"O provedor de IA '{self.nome}' não pôde ser carregado neste servidor: {self.motivo}"
        )


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

    try:
        if name == "ollama":
            from backend.ai.ollama_provider import OllamaProvider
            provider = OllamaProvider()

        elif name == "openai":
            from backend.ai.openai_provider import OpenAIProvider
            provider = OpenAIProvider()

        elif name == "openrouter":
            from backend.ai.openrouter_provider import OpenRouterProvider
            provider = OpenRouterProvider()

        else:  # gemini
            from backend.ai.gemini_provider import GeminiProvider
            provider = GeminiProvider()

    except Exception as exc:  # noqa: BLE001
        # Nunca deixar o chat derrubar o resto da aplicação: sem isso, uma
        # biblioteca ausente ou incompatível impede o processo de subir.
        logger.exception("Falha ao carregar o provedor de IA '%s'", name)
        return UnavailableProvider(name, f"{type(exc).__name__}: {exc}")

    logger.info(
        "Provedor de IA: %s (modelo: %s, configurado: %s)",
        name, provider.model, provider.is_configured(),
    )
    return provider
