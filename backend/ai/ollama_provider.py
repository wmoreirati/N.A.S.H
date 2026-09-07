import os
import logging
import requests

from backend.ai.provider import (
    AIProvider,
    AIResponse,
    ToolCall,
    MissingAPIKeyError,
    AIServiceUnavailableError,
)

logger = logging.getLogger("nash.ai.ollama")


class OllamaProvider(AIProvider):
    """
    Provedor local do N.A.S.H usando Ollama.

    O modelo roda no próprio computador.
    Não precisa de API key.
    """

    def __init__(self, model: str | None = None):
        self.base_url = os.environ.get(
            "OLLAMA_BASE_URL",
            "http://127.0.0.1:11434",
        ).rstrip("/")

        self.model = model or os.environ.get(
            "OLLAMA_MODEL",
            "qwen3:1.7b",
        )

    def is_configured(self) -> bool:
        return bool(self.model)

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AIResponse:

        # ---------------------------------------------------------
        # PERSONALIDADE DO N.A.S.H
        # ---------------------------------------------------------

        nash_prompt = """
Você é N.A.S.H, um assistente pessoal de IA.

Você é o assistente pessoal, parceiro de estudos e centro de comando
do usuário.

PERSONALIDADE:
- Inteligente.
- Educado.
- Natural.
- Objetivo.
- Prestativo.
- Proativo quando isso realmente ajudar.
- Técnico quando necessário.
- Capaz de conversar casualmente.
- Nunca soe como um chatbot robótico.

IDIOMA:
- Responda em português do Brasil por padrão.
- Se o usuário pedir outro idioma, use o idioma solicitado.

ASSISTENTE PESSOAL:
Você deve ajudar o usuário a organizar, estudar, criar, pesquisar,
programar e resolver problemas.

Você pode ajudar especialmente com:
- Matemática.
- Física.
- Química.
- Biologia.
- Tecnologia.
- Programação.
- Engenharia.
- Astronomia.
- Eletrônica.
- Ciência em geral.

MODO ESPECIALISTA:
Quando resolver problemas de exatas, programação ou tecnologia,
explique de forma didática quando isso for útil.

Quando apropriado, organize a solução em:
1. O que o problema pede.
2. Dados fornecidos.
3. Conceitos necessários.
4. Fórmulas.
5. Explicação das variáveis.
6. Substituição dos valores.
7. Cálculo.
8. Verificação.
9. Resposta final.

Se o usuário pedir apenas a resposta, seja conciso.

Se o usuário pedir passo a passo, explique detalhadamente.

ENSINO:
Quando ensinar matemática, física, química, programação ou tecnologia,
use exemplos práticos.

Sempre que fizer sentido, proponha uma pequena experiência,
simulação, exercício ou exemplo interativo que o usuário possa testar.

PROGRAMAÇÃO:
Explique código para iniciantes quando necessário.
Não presuma que o usuário conhece programação.

ASSISTENTE:
Não invente ações que você não executou.

Não diga que criou, apagou, salvou ou modificou alguma coisa
se a ferramenta correspondente não tiver realmente sido executada.

SEGURANÇA:
Ferramentas que alteram, criam ou excluem dados devem respeitar
o sistema de confirmação do N.A.S.H.

Nunca tente contornar as confirmações.

MEMÓRIA:
Use a memória fornecida pelo sistema quando ela estiver disponível.
Não invente memórias.

OBJETIVO:
Seu objetivo é ser um assistente pessoal útil, inteligente,
didático e confiável para o usuário.
"""

        # ---------------------------------------------------------
        # PREPARAÇÃO DAS MENSAGENS
        # ---------------------------------------------------------

        ollama_messages = [
            {
                "role": "system",
                "content": nash_prompt,
            }
        ]

        # O system prompt original do N.A.S.H continua sendo enviado.
        # Isso preserva memória, conexões e regras do agent.py.
        for message in messages:

            role = message.get("role")
            content = message.get("content")

            if role in ("system", "user", "assistant"):

                if content:
                    ollama_messages.append(
                        {
                            "role": role,
                            "content": str(content),
                        }
                    )

        # ---------------------------------------------------------
        # CONFIGURAÇÃO DA REQUISIÇÃO
        # ---------------------------------------------------------

                # ---------------------------------------------------------
        # CONFIGURAÇÃO DA REQUISIÇÃO
        # ---------------------------------------------------------

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.7,
            },
        }

        if tools:
            payload["tools"] = tools

        print(
            f"[OLLAMA] modelo={self.model} "
            f"mensagens={len(ollama_messages)} "
            f"caracteres={sum(len(str(m.get('content', ''))) for m in ollama_messages)} "
            f"ferramentas={len(tools or [])}"
        )
        try:

            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=300,
            )

        except requests.exceptions.ConnectionError as exc:

            raise AIServiceUnavailableError(
                "Não foi possível conectar ao Ollama. "
                "Verifique se o Ollama está aberto e funcionando."
            ) from exc

        except requests.exceptions.Timeout as exc:

            raise AIServiceUnavailableError(
                "O Ollama demorou muito para responder."
            ) from exc

        except Exception as exc:

            logger.exception(
                "Erro ao comunicar com o Ollama"
            )

            raise AIServiceUnavailableError(
                f"Erro ao comunicar com o Ollama: {exc}"
            ) from exc

        # ---------------------------------------------------------
        # ERROS HTTP
        # ---------------------------------------------------------

        if response.status_code != 200:

            try:
                error_data = response.json()
            except Exception:
                error_data = response.text

            logger.error(
                "Ollama retornou erro %s: %s",
                response.status_code,
                error_data,
            )

            raise AIServiceUnavailableError(
                f"Ollama retornou erro HTTP "
                f"{response.status_code}: {error_data}"
            )

        # ---------------------------------------------------------
        # RESPOSTA
        # ---------------------------------------------------------

        try:
            data = response.json()
        except Exception as exc:

            raise AIServiceUnavailableError(
                "O Ollama retornou uma resposta inválida."
            ) from exc

        message = data.get("message", {})

        text = message.get("content")

        tool_calls = []

        for index, tool_call in enumerate(
            message.get("tool_calls", []) or []
        ):

            function = tool_call.get(
                "function",
                {},
            )

            name = function.get(
                "name"
            )

            arguments = function.get(
                "arguments",
                {},
            )

            tool_calls.append(
                ToolCall(
                    id=f"ollama_call_{index}",
                    name=name,
                    arguments=arguments or {},
                )
            )

        return AIResponse(
            text=text,
            tool_calls=tool_calls,
            raw=data,
        )