"""
N.A.S.H - Como a resposta sai quando vai ser OUVIDA, não lida.

Dois problemas relatados em uso real, no modo voz:

1. "10 x 10" não respondia "100": o assistente repetia a pergunta e ia
   desfiando etapas. O roteador rápido só entendia `*`, e ninguém FALA
   "asterisco" -- a conta caía no modelo, que aplicava a estrutura de 8 passos
   do modo especialista a uma multiplicação trivial.

2. A fala saía robotizada, lendo pontuação em voz alta (inclusive aspas).
"""
import os
import tempfile
import unittest

os.environ.setdefault("OPENAI_API_KEY", "")

from app import create_app  # noqa: E402
from backend.ai import agent  # noqa: E402
from backend.models import db  # noqa: E402


class MatematicaFaladaTestCase(unittest.TestCase):
    """O roteador rápido responde sem chamar o modelo — e sem enrolação."""

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

    def test_multiplicacao_como_se_fala(self):
        for frase in ("10 x 10", "10 X 10", "10 × 10", "10 vezes 10",
                      "quanto é 10 x 10", "quanto e 10 vezes 10",
                      "calcule 10 vezes 10"):
            with self.subTest(frase=frase):
                r = agent._fast_command(frase)
                self.assertIsNotNone(r, "deveria ser resolvido sem o modelo")
                self.assertIn("100", r["text"])

    def test_demais_operacoes_faladas(self):
        casos = {
            "100 dividido por 4": "25",
            "7 mais 3": "10",
            "9 menos 4": "5",
            "3 multiplicado por 3": "9",
        }
        for frase, esperado in casos.items():
            with self.subTest(frase=frase):
                r = agent._fast_command(frase)
                self.assertIsNotNone(r, frase)
                self.assertIn(esperado, r["text"])

    def test_frase_comum_com_palavra_de_operador_vai_para_o_modelo(self):
        """
        "mais", "menos" e "vezes" aparecem em conversa normal. Converter sempre
        transformaria "me fale mais sobre física" em "me fale + sobre física".
        A troca só vale se o resultado virar aritmética pura.
        """
        for frase in ("me fale mais sobre física",
                      "conte mais sobre você",
                      "quero saber mais",
                      "às vezes eu esqueço",
                      "estou de menos ânimo hoje"):
            with self.subTest(frase=frase):
                self.assertIsNone(
                    agent._fast_command(frase),
                    "não deveria ser tratado como conta",
                )

    def test_resposta_do_roteador_e_curta(self):
        """O ponto do conserto: caber numa frase falada."""
        r = agent._fast_command("10 x 10")
        self.assertLess(len(r["text"]), 60, r["text"])


class PromptDeVozTestCase(unittest.TestCase):
    """A instrução de voz entra só quando a resposta vai ser falada."""

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

    def test_texto_nao_recebe_instrucao_de_voz(self):
        self.assertNotIn("MODO VOZ", agent.build_system_prompt())

    def test_voz_recebe_instrucao_de_voz(self):
        prompt = agent.build_system_prompt(modo_voz=True)
        self.assertIn("MODO VOZ", prompt)
        self.assertIn("OUVIDA", prompt)

    def test_instrucao_de_voz_proibe_o_formato_de_documento(self):
        prompt = agent.build_system_prompt(modo_voz=True)
        for exigencia in ("listas", "estrutura numerada", "repetir a pergunta"):
            with self.subTest(exigencia=exigencia):
                self.assertIn(exigencia, prompt)

    def test_a_rota_repassa_o_modo_voz(self):
        """
        Marca de que veio da voz tem de chegar ao agente. Sem isso a instrução
        existe e nunca é aplicada -- o defeito silencioso mais provável aqui.
        """
        recebido = {}

        def espiao(provider, history, user_message, modo_voz=False):
            recebido["modo_voz"] = modo_voz
            return {"type": "message", "text": "ok"}

        # O e-mail precisa estar em ADMIN_EMAIL ANTES do cadastro: é no
        # cadastro que a conta nasce administradora e já com sessão. Fora
        # dessa ordem o cliente fica pendente e /api/chat responde 401 --
        # o espião nunca seria chamado e o teste "falharia" pelo motivo errado.
        admin_antes = os.environ.get("ADMIN_EMAIL")
        os.environ["ADMIN_EMAIL"] = "dono@teste.local"

        original = agent.run_chat_turn
        agent.run_chat_turn = espiao
        try:
            cliente = self.app.test_client()
            entrada = cliente.post(
                "/api/auth/registrar",
                json={"email": "dono@teste.local", "senha": "senha-de-teste-123"},
            )
            self.assertTrue(entrada.get_json().get("liberado"), entrada.get_json())

            resp = cliente.post("/api/chat", json={"message": "oi", "voz": True})
            self.assertEqual(resp.status_code, 200, resp.get_json())
            self.assertIs(recebido.get("modo_voz"), True)

            cliente.post("/api/chat", json={"message": "oi"})
            self.assertIs(recebido.get("modo_voz"), False)
        finally:
            agent.run_chat_turn = original
            if admin_antes is None:
                os.environ.pop("ADMIN_EMAIL", None)
            else:
                os.environ["ADMIN_EMAIL"] = admin_antes


if __name__ == "__main__":
    unittest.main()
