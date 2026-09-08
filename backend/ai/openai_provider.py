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
)

logger = logging.getLogger("nash.ai.openai")


class OpenAIProvider(AIProvider):
    def __init__(self, model: str | None = None):
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.model = model or (os.environ.get("OPENAI_MODEL") or "").strip() or "gpt-4o-mini"
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if not self.is_configured():
            raise MissingAPIKeyError(
                "OPENAI_API_KEY não configurada. Defina a variável de ambiente no arquivo .env."
            )
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise AIServiceUnavailableError(
                    "Biblioteca 'openai' não instalada. Rode: pip install -r requirements.txt"
                ) from exc
            self._client = OpenAI(api_key=self.api_key)
        return self._client

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
            logger.error("Falha ao chamar a API da OpenAI: %s", exc)
            message = str(exc)
            if "authentic" in message.lower() or "api key" in message.lower() or "401" in message:
                raise MissingAPIKeyError(
                    "A chave da API foi rejeitada pela OpenAI. Verifique se OPENAI_API_KEY está correta."
                ) from exc
            raise AIServiceUnavailableError(
                "Não foi possível contatar o provedor de IA no momento. Tente novamente em instantes."
            ) from exc

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
