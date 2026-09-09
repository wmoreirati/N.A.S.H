"""
N.A.S.H - Interface abstrata de provedor de IA.

Permite trocar de provedor (OpenAI, outro futuramente) sem alterar o
restante do sistema. Todo provedor concreto deve implementar `chat()`.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class AIProviderError(Exception):
    """Erro genérico de provedor de IA (chave ausente, API offline, resposta inválida...)."""
    pass


class MissingAPIKeyError(AIProviderError):
    """A variável de ambiente com a chave da API não está configurada."""
    pass


class AIServiceUnavailableError(AIProviderError):
    """A API do provedor está offline, com timeout, ou retornou erro de servidor."""
    pass


class ModelWantedToolError(AIProviderError):
    """
    O modelo tentou chamar uma ferramenta numa requisição que não ofereceu
    nenhuma, e o provedor recusou a resposta inteira.

    Acontece porque o agente só manda o catálogo de ferramentas quando a
    mensagem parece pedir ação — economia que existe para caber no teto de
    tokens por minuto da camada gratuita. Quando o modelo discorda dessa
    aposta, o pedido morre com 400 em vez de virar uma resposta.

    É um erro RECUPERÁVEL: basta repetir a chamada oferecendo as ferramentas.
    Por isso tem tipo próprio -- quem chama precisa distinguir isto de uma
    falha real do provedor.
    """
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AIResponse:
    """Resposta normalizada do modelo, independente do provedor."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict | None = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class AIProvider(ABC):
    """Todo provedor de IA concreto (OpenAI, etc.) deve implementar esta interface."""

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> AIResponse:
        """
        Envia o histórico de mensagens (formato OpenAI: [{role, content}, ...])
        e a lista de ferramentas disponíveis (JSON schema), retornando uma
        AIResponse normalizada (texto e/ou chamadas de ferramenta).
        """
        raise NotImplementedError

    @abstractmethod
    def is_configured(self) -> bool:
        """Retorna True se o provedor possui as credenciais necessárias configuradas."""
        raise NotImplementedError
