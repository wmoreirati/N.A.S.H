"""
N.A.S.H - Provedor de IA: OpenAI.

A chave da API é lida EXCLUSIVAMENTE da variável de ambiente OPENAI_API_KEY
(carregada via .env no servidor). Ela nunca é enviada ao frontend, nunca
aparece em templates HTML e nunca é logada.
"""
import os
import json
import logging

from backend.ai.provider import (
    AIProvider,
    AIResponse,
    ToolCall,
    MissingAPIKeyError,
    AIServiceUnavailableError,
    ModelWantedToolError,
)

logger = logging.getLogger("nash.ai.openai")


class OpenAIProvider(AIProvider):
    """
    Provedor para a API da OpenAI e para qualquer serviço compatível com ela.

    Os atributos de classe abaixo existem para que um serviço compatível
    (como o OpenRouter) seja uma subclasse de quatro linhas, em vez de uma
    cópia inteira desta implementação.
    """

    NOME = "OpenAI"
    VAR_CHAVE = "OPENAI_API_KEY"
    VAR_MODELO = "OPENAI_MODEL"
    MODELO_PADRAO = "gpt-4o-mini"
    BASE_URL = None          # None = endpoint padrão da OpenAI
    CABECALHOS = None

    def __init__(self, model: str | None = None):
        self.api_key = os.environ.get(self.VAR_CHAVE, "").strip()
        self.model = (
            model
            or (os.environ.get(self.VAR_MODELO) or "").strip()
            or self.MODELO_PADRAO
        )
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if not self.is_configured():
            raise MissingAPIKeyError(
                f"{self.VAR_CHAVE} não configurada. Defina a variável de ambiente no arquivo .env."
            )
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise AIServiceUnavailableError(
                    "Biblioteca 'openai' não instalada. Rode: pip install -r requirements.txt"
                ) from exc
            kwargs = {"api_key": self.api_key}
            if self.BASE_URL:
                kwargs["base_url"] = self.BASE_URL
            if self.CABECALHOS:
                kwargs["default_headers"] = self.CABECALHOS
            self._client = OpenAI(**kwargs)
        return self._client

    def _erro_amigavel(self, mensagem: str, codigo=None, origem: Exception | None = None):
        """
        Converte a falha do provedor em algo acionável para quem está usando.

        Sem isto, "sem créditos", "modelo sobrecarregado" e "chave errada"
        chegavam todos como "não foi possível contatar o provedor" — e a
        pessoa não tinha como saber onde mexer. Sempre levanta exceção.
        """
        m = (mensagem or "").lower()
        try:
            codigo = int(codigo) if codigo is not None else None
        except (TypeError, ValueError):
            codigo = None

        # O modelo quis usar ferramenta numa chamada que nao ofereceu nenhuma.
        # Nao e falha do provedor nem da chave: e uma aposta errada do agente,
        # e da para refazer. Precisa vir antes das demais regras porque tambem
        # e 400 e cairia numa mensagem generica.
        if "tool_use_failed" in m or "tool choice is none" in m:
            raise ModelWantedToolError(
                "O modelo tentou usar uma ferramenta que não foi oferecida nesta chamada."
            ) from origem

        if codigo in (401, 403) or "api key" in m or "authentic" in m or "user not found" in m:
            raise MissingAPIKeyError(
                f"A chave da API foi rejeitada pelo provedor {self.NOME}. "
                f"Verifique se {self.VAR_CHAVE} está correta."
            ) from origem

        if codigo == 402 or "insufficient credit" in m or "purchase" in m:
            raise AIServiceUnavailableError(
                f"A conta do {self.NOME} está sem créditos para o modelo '{self.model}'. "
                "Adicione crédito no painel do provedor ou troque para um modelo gratuito."
            ) from origem

        if codigo == 429 or "rate-limited" in m or "rate limit" in m or "quota" in m:
            raise AIServiceUnavailableError(
                f"O modelo '{self.model}' está sem capacidade no momento (limite de uso). "
                "Tente de novo em instantes ou escolha outro modelo."
            ) from origem

        if codigo in (502, 503) or "overloaded" in m or "upstream" in m:
            raise AIServiceUnavailableError(
                f"O modelo '{self.model}' está sobrecarregado do lado do fornecedor. "
                "Tente de novo em instantes ou escolha outro modelo."
            ) from origem

        raise AIServiceUnavailableError(
            f"Não foi possível obter resposta de {self.NOME} no momento"
            + (f": {mensagem}" if mensagem else ".")
        ) from origem

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> AIResponse:
        client = self._get_client()

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.6,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - normalizamos qualquer falha de rede/API
            logger.error("Falha ao chamar a API de %s: %s", self.NOME, exc)
            self._erro_amigavel(str(exc), getattr(exc, "status_code", None), origem=exc)

        # Serviços compatíveis nem sempre usam o código HTTP para sinalizar
        # falha: o OpenRouter devolve 200 com o erro no corpo e `choices` nulo
        # (modelo sobrecarregado, por exemplo). Indexar direto viraria um
        # TypeError incompreensível na cara de quem só fez uma pergunta.
        if not getattr(completion, "choices", None):
            erro = getattr(completion, "error", None)
            erro = erro if isinstance(erro, dict) else {}
            logger.error("%s respondeu sem choices: %s", self.NOME, erro or completion)
            self._erro_amigavel(str(erro.get("message") or ""), erro.get("code"))

        choice = completion.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return AIResponse(
            text=msg.content,
            tool_calls=tool_calls,
            raw=completion.model_dump() if hasattr(completion, "model_dump") else None,
        )
