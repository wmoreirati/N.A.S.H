"""
N.A.S.H - O agente aposta se a mensagem precisa de ferramentas.

Ele só manda o catálogo quando a mensagem casa com palavras de ação, para
caber no teto de tokens por minuto da camada gratuita. Quando o modelo
discorda dessa aposta e chama uma ferramenta assim mesmo, o provedor recusa a
resposta inteira com HTTP 400.

Isso apareceu em produção com a mensagem "Olá nash": o chat inteiro morria e o
erro cru da API ia para a tela. Estes testes fixam o comportamento correto --
refazer a chamada oferecendo as ferramentas -- para o caso não voltar.
"""
import os
import tempfile
import unittest

os.environ.setdefault("OPENAI_API_KEY", "")

from app import create_app  # noqa: E402
from backend.ai import agent  # noqa: E402
from backend.ai.provider import (  # noqa: E402
    AIResponse,
    AIServiceUnavailableError,
    ModelWantedToolError,
    ToolCall,
)
from backend.models import db  # noqa: E402


class ProvedorQueRecusaSemFerramentas:
    """
    Reproduz o Groq: se a chamada não oferece ferramentas e o modelo tenta
    usar uma, a requisição inteira falha com 400.
    """

    def __init__(self, resposta_final="Olá! Como posso ajudar?"):
        self.chamadas = []          # lista de len(tools) por chamada
        self.resposta_final = resposta_final

    def chat(self, messages, tools=None):
        self.chamadas.append(len(tools or []))
        if not tools:
            raise ModelWantedToolError(
                "O modelo tentou usar uma ferramenta que não foi oferecida nesta chamada."
            )
        return AIResponse(text=self.resposta_final)


class RecuperacaoTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_saudacao_nao_morre_quando_o_modelo_pede_ferramenta(self):
        """
        "Olá nash" não casa com nenhuma palavra de ação, então a primeira
        chamada vai sem ferramentas. O modelo pede uma, o provedor recusa, e o
        agente tem de refazer com o catálogo em vez de devolver erro.
        """
        provedor = ProvedorQueRecusaSemFerramentas()
        resultado = agent.run_chat_turn(provedor, [], "Olá nash")

        self.assertEqual(resultado["type"], "message", resultado)
        self.assertEqual(resultado["text"], "Olá! Como posso ajudar?")

        # Primeira chamada sem ferramenta nenhuma; a segunda, com o catálogo.
        self.assertEqual(len(provedor.chamadas), 2, provedor.chamadas)
        self.assertEqual(provedor.chamadas[0], 0)
        self.assertGreater(provedor.chamadas[1], 0)

    def test_nao_insiste_quando_ja_havia_ferramentas(self):
        """
        Se a chamada JÁ oferecia ferramentas e mesmo assim veio esse erro, o
        problema é outro. Repetir só gastaria tokens e chegaria no mesmo lugar.
        """
        class SempreRecusa(ProvedorQueRecusaSemFerramentas):
            def chat(self, messages, tools=None):
                self.chamadas.append(len(tools or []))
                raise ModelWantedToolError("recusa mesmo com ferramentas")

        provedor = SempreRecusa()
        # "tarefa" casa com as palavras de ação: já vai com o catálogo.
        resultado = agent.run_chat_turn(provedor, [], "liste minhas tarefas")

        self.assertEqual(resultado["type"], "error")
        self.assertEqual(len(provedor.chamadas), 1, "não pode repetir")
        self.assertGreater(provedor.chamadas[0], 0)

    def test_outros_erros_de_provedor_continuam_virando_erro(self):
        """A recuperação é só para este caso; falha real continua falha."""
        class ForaDoAr:
            def chat(self, messages, tools=None):
                raise AIServiceUnavailableError("provedor fora do ar")

        resultado = agent.run_chat_turn(ForaDoAr(), [], "Olá nash")
        self.assertEqual(resultado["type"], "error")
        self.assertIn("fora do ar", resultado["text"])

    def test_ferramenta_inventada_pelo_modelo_nao_derruba_o_turno(self):
        """
        No erro real o modelo chamou `tool_get_google_calendar`, que não
        existe (a nossa é `tool_get_calendar`). Nome desconhecido tem de virar
        resposta, não exceção.
        """
        class ChamaFerramentaInexistente:
            def __init__(self):
                self.vezes = 0

            def chat(self, messages, tools=None):
                self.vezes += 1
                if self.vezes == 1:
                    return AIResponse(tool_calls=[
                        ToolCall(id="1", name="tool_get_google_calendar", arguments={})
                    ])
                return AIResponse(text="Não tenho essa ferramenta, mas posso ajudar.")

        resultado = agent.run_chat_turn(
            ChamaFerramentaInexistente(), [], "liste minhas tarefas"
        )
        self.assertIn(resultado["type"], ("message", "error"))
        self.assertTrue(resultado.get("text"))


if __name__ == "__main__":
    unittest.main()
