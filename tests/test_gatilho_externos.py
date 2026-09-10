"""
N.A.S.H - Testes do gatilho das acoes externas.

Nasceram de um defeito visto em producao: o usuario pediu "me mande a lista
de arquivos do drive", a resposta nao saiu naquele momento, e turnos depois o
modelo respondeu ao pedido antigo com uma lista de arquivos INVENTADA
("Planejamento Projeto X.xlsx", "Contrato-Cliente-ABC.docx"...), apresentada
como se viesse do Drive de verdade.

A causa: o catalogo externo so era oferecido quando a MENSAGEM DO TURNO citava
o servico -- mas o modelo le o historico inteiro. Ele tinha a intencao sem ter
a ferramenta, e preencheu o buraco.

Aqui se cobre a correcao pelos dois lados: a janela de historico (com o
orcamento de tokens que a torna segura) e a regra do system prompt, que e a
defesa que vale mesmo quando a palavra-chave escapa.
"""
import os
import tempfile
import unittest

from flask import session as flask_session

os.environ.setdefault("OPENAI_API_KEY", "")

EMAIL_ADMIN = "dona@nash.local"
SENHA_ADMIN = "senha-de-teste-123"
SENHA_COMUM = "senha-comum-123"
os.environ["ADMIN_EMAIL"] = EMAIL_ADMIN

from app import create_app  # noqa: E402
from backend.models import db  # noqa: E402
from backend.ai import agent  # noqa: E402
from backend.security import auth as auth_mod  # noqa: E402
from backend.tools import composio_tools  # noqa: E402
from backend.ai.provider import AIResponse  # noqa: E402


class ProvedorEspiao:
    """Provedor falso: nao responde nada util, so anota o que recebeu."""

    model = "espiao"

    def __init__(self):
        self.ferramentas = []

    def is_configured(self):
        return True

    def chat(self, messages, tools=None):
        self.ferramentas.append(list(tools or []))
        return AIResponse(text="ok")


# Historico do defeito real: o pedido do Drive ficou tres turnos para tras.
HISTORICO_DO_DEFEITO = [
    {"role": "user", "content": "Me informe sobre a agenda"},
    {"role": "assistant", "content": "Claro! Qual periodo?"},
    {"role": "user", "content": "Me mande a lista de arquivos do drive"},
    {"role": "user", "content": "ola"},
    {"role": "assistant", "content": "Ola!"},
    {"role": "user", "content": "ola"},
]


class GatilhoExternosTestCase(unittest.TestCase):
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

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------

    def _cliente_admin(self):
        """
        Cliente autenticado como administradora.

        Cadastra na primeira vez e ENTRA nas seguintes. Pular o cadastro e ir
        direto ao login deixa o cliente sem cookie quando a conta ainda nao
        existe -- e a falha aparece longe, como KeyError na resposta de outra
        rota.
        """
        cliente = self.app.test_client()
        resp = cliente.post(
            "/api/auth/registrar",
            json={"email": EMAIL_ADMIN, "senha": SENHA_ADMIN},
        )
        if resp.status_code != 200:
            cliente.post(
                "/api/auth/login",
                json={"email": EMAIL_ADMIN, "senha": SENHA_ADMIN},
            )
        return cliente

    def _sessao_admin(self):
        with self._cliente_admin().session_transaction() as sessao:
            return sessao[auth_mod.CHAVE_SESSAO]

    def _sessao_comum(self, email="comum@exemplo.com"):
        cliente = self.app.test_client()
        cliente.post(
            "/api/auth/registrar",
            json={"email": email, "senha": SENHA_COMUM},
        )
        adm = self._cliente_admin()
        alvo = next(
            u for u in adm.get("/api/admin/usuarios").get_json()["usuarios"]
            if u["email"] == email
        )
        adm.post(f"/api/admin/usuarios/{alvo['id']}/aprovar")
        cliente.post("/api/auth/login", json={"email": email, "senha": SENHA_COMUM})
        with cliente.session_transaction() as sessao:
            return sessao[auth_mod.CHAVE_SESSAO]

    def _exigir_catalogo(self):
        if not composio_tools.get_schemas():
            self.skipTest("Catalogo do Composio indisponivel (COMPOSIO_API_KEY ausente).")

    def _servicos_para(self, mensagem, historico=None, sessao=None):
        with self.app.test_request_context("/"):
            flask_session[auth_mod.CHAVE_SESSAO] = sessao or self._sessao_admin()
            return agent._servicos_dos_schemas(
                agent.schemas_externos_para(mensagem, historico)
            )

    # ------------------------------------------------------------------
    # A janela de historico
    # ------------------------------------------------------------------

    def test_pedido_de_turnos_atras_ainda_traz_a_ferramenta(self):
        """
        O defeito exato: "teste" nao cita servico nenhum, mas o Drive foi
        pedido antes e o modelo vai responder aquele pedido. Sem a ferramenta,
        ele inventa.
        """
        self._exigir_catalogo()
        servicos = self._servicos_para("teste", HISTORICO_DO_DEFEITO)
        self.assertIn("googledrive", servicos)

    def test_sem_a_janela_o_defeito_volta(self):
        """
        Controle negativo. Com a janela em zero o comportamento e o antigo --
        se este teste NAO falhar ao desligar a correcao, ele nao prova nada.
        """
        self._exigir_catalogo()
        original = agent.JANELA_GATILHO_HISTORICO
        agent.JANELA_GATILHO_HISTORICO = 0
        try:
            servicos = self._servicos_para("teste", HISTORICO_DO_DEFEITO)
        finally:
            agent.JANELA_GATILHO_HISTORICO = original
        self.assertNotIn("googledrive", servicos)

    def test_historico_vazio_se_comporta_como_antes(self):
        """A mudanca nao pode alterar o caminho de quem pede na hora."""
        self._exigir_catalogo()
        self.assertIn("googledrive", self._servicos_para("liste os arquivos do drive"))
        self.assertEqual(self._servicos_para("bom dia"), set())
        self.assertEqual(self._servicos_para("bom dia", []), set())

    def test_conversa_antiga_nao_gruda_para_sempre(self):
        """
        A janela e curta de proposito: um servico citado ha muitos turnos nao
        pode continuar custando tokens em toda pergunta seguinte.
        """
        self._exigir_catalogo()
        antigo = [{"role": "user", "content": "liste os arquivos do drive"}]
        antigo += [
            {"role": "user", "content": f"pergunta comum {i}"}
            for i in range(agent.JANELA_GATILHO_HISTORICO + 1)
        ]
        self.assertNotIn("googledrive", self._servicos_para("obrigado", antigo))

    # ------------------------------------------------------------------
    # O orcamento que torna a janela segura
    # ------------------------------------------------------------------

    def test_o_que_vem_do_historico_respeita_o_orcamento(self):
        """
        O catalogo inteiro custa ~5.800 tokens contra um teto de 6.000 por
        minuto na camada gratuita. A janela nao pode trocar resposta inventada
        por estouro de cota.
        """
        self._exigir_catalogo()
        tudo = [
            {"role": "user", "content": "agenda"},
            {"role": "user", "content": "email"},
            {"role": "user", "content": "drive"},
            {"role": "user", "content": "planilha e documento e notion e video"},
        ]
        with self.app.test_request_context("/"):
            flask_session[auth_mod.CHAVE_SESSAO] = self._sessao_admin()
            schemas = agent.schemas_externos_para("teste", tudo)
        self.assertLessEqual(
            agent._custo_tokens(schemas),
            agent.ORCAMENTO_GATILHO_HISTORICO_TOKENS,
        )

    def test_a_mensagem_atual_nunca_e_cortada_pelo_orcamento(self):
        """
        O orcamento limita o que a JANELA acrescenta. Quem pede varios
        servicos agora continua recebendo todos -- do contrario a correcao
        seria uma regressao disfarcada.
        """
        self._exigir_catalogo()
        servicos = self._servicos_para("veja minha agenda, meu email e meu drive")
        self.assertEqual(
            {"googlecalendar", "gmail", "googledrive"} - servicos,
            set(),
        )

    # ------------------------------------------------------------------
    # O isolamento nao pode ter afrouxado
    # ------------------------------------------------------------------

    def test_usuario_comum_nao_recebe_nada_nem_pelo_historico(self):
        """
        As contas conectadas sao de uma pessoa so. A janela nova nao pode ter
        aberto uma porta lateral para o historico.
        """
        self._exigir_catalogo()
        sessao = self._sessao_comum()
        self.assertEqual(
            self._servicos_para("teste", HISTORICO_DO_DEFEITO, sessao=sessao),
            set(),
        )

    # ------------------------------------------------------------------
    # Auxiliar da janela
    # ------------------------------------------------------------------

    def test_ultimas_mensagens_ignora_o_assistente_e_respeita_o_limite(self):
        recentes = agent._ultimas_mensagens_do_usuario(HISTORICO_DO_DEFEITO, 3)
        self.assertEqual(recentes, ["ola", "ola", "Me mande a lista de arquivos do drive"])
        self.assertEqual(agent._ultimas_mensagens_do_usuario(None, 3), [])
        self.assertEqual(agent._ultimas_mensagens_do_usuario([], 3), [])

    # ------------------------------------------------------------------
    # O caminho inteiro, e nao so a funcao do gatilho
    # ------------------------------------------------------------------

    def test_o_turno_real_entrega_o_historico_ao_gatilho(self):
        """
        Os testes acima chamam o gatilho direto. Se alguem parar de repassar o
        historico em run_chat_turn, eles continuariam verdes e a producao
        voltaria a inventar. Este cobre a ligacao.
        """
        self._exigir_catalogo()
        espiao = ProvedorEspiao()
        with self.app.test_request_context("/"):
            flask_session[auth_mod.CHAVE_SESSAO] = self._sessao_admin()
            agent.run_chat_turn(espiao, HISTORICO_DO_DEFEITO, "teste")
        self.assertIn("googledrive", agent._servicos_dos_schemas(espiao.ferramentas[0]))

    def test_no_turno_real_a_janela_e_quem_manda(self):
        """
        Controle negativo do anterior: com a janela em zero o Drive some. Se o
        historico NAO estivesse chegando ao gatilho, a janela seria
        irrelevante e os dois testes dariam o mesmo resultado.
        """
        self._exigir_catalogo()
        espiao = ProvedorEspiao()
        original = agent.JANELA_GATILHO_HISTORICO
        agent.JANELA_GATILHO_HISTORICO = 0
        try:
            with self.app.test_request_context("/"):
                flask_session[auth_mod.CHAVE_SESSAO] = self._sessao_admin()
                agent.run_chat_turn(espiao, HISTORICO_DO_DEFEITO, "teste")
        finally:
            agent.JANELA_GATILHO_HISTORICO = original
        self.assertNotIn("googledrive", agent._servicos_dos_schemas(espiao.ferramentas[0]))

    # ------------------------------------------------------------------
    # A defesa que vale quando a palavra-chave escapa
    # ------------------------------------------------------------------

    def test_o_prompt_proibe_inventar_conteudo_de_servico_externo(self):
        """
        Palavra-chave vai errar sempre -- em "e os do mes passado?", em "me
        mostra de novo". O que nao pode e o erro virar dado falso. Esta regra
        e a unica defesa que cobre o caso geral; se alguem a apagar, isto
        acusa.
        """
        prompt = agent.SYSTEM_PROMPT_TEMPLATE.lower()
        self.assertIn("estar conectado", prompt)
        self.assertIn("resultado de\nferramenta", prompt)
        self.assertIn("nunca preencha com", prompt)


if __name__ == "__main__":
    unittest.main()
