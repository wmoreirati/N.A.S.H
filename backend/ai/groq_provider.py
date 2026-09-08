"""
N.A.S.H - Provedor de IA: Groq.

O Groq expõe uma API compatível com a da OpenAI, então aqui vale a mesma
lógica do OpenRouter: especializar `OpenAIProvider` em vez de reimplementar
a chamada, a leitura de tool calls e o tratamento de erro.

Por que ele interessa a este projeto:

- Camada gratuita **sem cartão de crédito**, com limite generoso para uso
  pessoal (dezenas de milhares de requisições por dia).
- Suporte a chamada de ferramentas, que o N.A.S.H exige para criar tarefas,
  projetos e memórias.
- Inferência muito rápida — o problema oposto ao modelo gratuito que
  testamos no OpenRouter, que levou mais de dois minutos para responder.

A lista de modelos disponíveis muda com frequência. Consulte
https://console.groq.com/docs/models e ajuste GROQ_MODEL conforme o que
estiver ativo na sua conta.
"""
from backend.ai.openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    NOME = "Groq"
    VAR_CHAVE = "GROQ_API_KEY"
    VAR_MODELO = "GROQ_MODEL"
    MODELO_PADRAO = "llama-3.3-70b-versatile"
    BASE_URL = "https://api.groq.com/openai/v1"
