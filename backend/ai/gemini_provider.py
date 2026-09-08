import os
import json
import logging

from google import genai
from google.genai import types

from backend.ai.provider import (
    AIProvider,
    AIResponse,
    ToolCall,
    MissingAPIKeyError,
    AIServiceUnavailableError,
)

logger = logging.getLogger("nash.ai.gemini")


class GeminiProvider(AIProvider):
    def __init__(self, model: str | None = None):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = model or (os.environ.get("GEMINI_MODEL") or "").strip() or "gemini-3.6-flash"
        self._client = None

        # Guarda a resposta ORIGINAL do Gemini.
        # Isso é importante porque ela contém a thought_signature.
        self._last_gemini_content = None

        # Relaciona IDs das tool calls do N.A.S.H com os nomes
        # das funções usadas pelo Gemini.
        self._tool_call_names = {}

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if not self.is_configured():
            raise MissingAPIKeyError(
                "GEMINI_API_KEY não configurada. "
                "Defina a variável no arquivo .env."
            )

        if self._client is None:
            try:
                self._client = genai.Client(api_key=self.api_key)
            except Exception as exc:
                raise AIServiceUnavailableError(
                    "Não foi possível inicializar o cliente Gemini."
                ) from exc

        return self._client

    def _convert_tools(self, tools):
        if not tools:
            return None

        declarations = []

        for tool in tools:
            function = tool.get("function", {})

            declarations.append(
                types.FunctionDeclaration(
                    name=function.get("name"),
                    description=function.get("description", ""),
                    parameters=function.get(
                        "parameters",
                        {
                            "type": "object",
                            "properties": {},
                        },
                    ),
                )
            )

        return [
            types.Tool(
                function_declarations=declarations
            )
        ]

    def _convert_messages(self, messages):
        system_instruction = ""
        contents = []

        for index, message in enumerate(messages):
            role = message.get("role")
            content = message.get("content")

            # ---------------------------------------------------------
            # SYSTEM
            # ---------------------------------------------------------
            if role == "system":
                system_instruction += (
                    str(content or "") + "\n"
                )
                continue

            # ---------------------------------------------------------
            # USER
            # ---------------------------------------------------------
            if role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                text=str(content or "")
                            )
                        ],
                    )
                )
                continue

            # ---------------------------------------------------------
            # ASSISTANT
            # ---------------------------------------------------------
            if role == "assistant":

                # Se esta é a resposta anterior que continha
                # function calls, reutilizamos o Content ORIGINAL
                # retornado pelo Gemini.
                #
                # Isso preserva a thought_signature.
                if (
                    self._last_gemini_content is not None
                    and message.get("tool_calls")
                ):
                    contents.append(
                        self._last_gemini_content
                    )
                    continue

                parts = []

                if content:
                    parts.append(
                        types.Part(
                            text=str(content)
                        )
                    )

                if parts:
                    contents.append(
                        types.Content(
                            role="model",
                            parts=parts,
                        )
                    )

                continue

            # ---------------------------------------------------------
            # TOOL
            # ---------------------------------------------------------
            if role == "tool":

                try:
                    result = json.loads(
                        content or "{}"
                    )
                except json.JSONDecodeError:
                    result = {
                        "result": content or ""
                    }

                tool_call_id = message.get(
                    "tool_call_id"
                )

                function_name = (
                    self._tool_call_names.get(
                        tool_call_id,
                        "tool",
                    )
                )

                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=function_name,
                                response=result,
                            )
                        ],
                    )
                )

        return (
            system_instruction.strip(),
            contents,
        )

    def chat(
        self,
        messages,
        tools=None,
    ) -> AIResponse:

        client = self._get_client()

        (
            system_instruction,
            contents,
        ) = self._convert_messages(messages)

        config = types.GenerateContentConfig(
            system_instruction=(
                system_instruction
                if system_instruction
                else None
            ),
            temperature=0.6,
            tools=self._convert_tools(tools),
        )

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

        except Exception as exc:
            logger.error(
                "Falha ao chamar a API do Gemini: %s",
                exc,
            )

            message = str(exc)

            if (
                "api key" in message.lower()
                or "authentication" in message.lower()
                or "401" in message
                or "403" in message
            ):
                raise MissingAPIKeyError(
                    "A chave do Gemini foi rejeitada. "
                    "Verifique GEMINI_API_KEY."
                ) from exc

            raise AIServiceUnavailableError(
                "Não foi possível contatar o provedor "
                "Gemini no momento."
            ) from exc

        # -------------------------------------------------------------
        # GUARDA O CONTENT ORIGINAL
        # -------------------------------------------------------------
        #
        # Aqui fica a thought_signature.
        #
        if response.candidates:
            self._last_gemini_content = (
                response.candidates[0].content
            )
        else:
            self._last_gemini_content = None

        text = getattr(
            response,
            "text",
            None,
        )

        tool_calls = []

        if getattr(
            response,
            "function_calls",
            None,
        ):
            for index, function_call in enumerate(
                response.function_calls
            ):

                tool_call_id = (
                    f"gemini_call_{index}"
                )

                function_name = (
                    function_call.name
                )

                self._tool_call_names[
                    tool_call_id
                ] = function_name

                tool_calls.append(
                    ToolCall(
                        id=tool_call_id,
                        name=function_name,
                        arguments=dict(
                            function_call.args
                            or {}
                        ),
                    )
                )

        return AIResponse(
            text=text,
            tool_calls=tool_calls,
            raw={
                "gemini_content": (
                    self._last_gemini_content
                ),
            },
        )