"""
N.A.S.H - Provedor de IA: OpenRouter.

O OpenRouter expõe uma API compatível com a da OpenAI, mudando apenas o
endereço base e a chave. Por isso este arquivo é uma especialização de
`OpenAIProvider` em vez de uma segunda implementação: toda a lógica de
chamada, de leitura de tool calls e de tratamento de erro é a mesma, e
duplicá-la só criaria dois lugares para corrigir o mesmo defeito.

Vantagem para este projeto: um único cadastro dá acesso a centenas de
modelos de fornecedores diferentes, e trocar de modelo passa a ser mudar
uma variável de ambiente — sem nova conta, nova chave ou novo código.

Atenção ao escolher o modelo: o N.A.S.H depende de chamada de ferramentas
para criar tarefas, projetos e memórias. Nem todo modelo do catálogo
suporta isso. Confira em https://openrouter.ai/models que o modelo aceita
"tools" antes de apontar OPENROUTER_MODEL para ele.
"""
from backend.ai.openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    NOME = "OpenRouter"
    VAR_CHAVE = "OPENROUTER_API_KEY"
    VAR_MODELO = "OPENROUTER_MODEL"

    # Barato, da familia GPT-5 e com suporte a ferramentas. É um ponto de
    # partida razoável, não uma escolha definitiva — trocar custa uma linha
    # no .env.
    MODELO_PADRAO = "openai/gpt-5-nano"

    BASE_URL = "https://openrouter.ai/api/v1"

    # Cabeçalhos opcionais que o OpenRouter usa para identificar a aplicação
    # nos painéis de uso. Não afetam a resposta.
    CABECALHOS = {
        "X-Title": "N.A.S.H",
    }
