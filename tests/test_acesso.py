"""
N.A.S.H - Testes da porta de entrada e do isolamento entre pessoas.

É a parte com consequência real: o assistente tem contas externas de uma
pessoa conectadas (Gmail, Agenda, Drive). "Quem entra" e "quem vê o quê" não
podem depender de alguém lembrar de proteger a rota certa.
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


class AcessoTestCase(unittest.TestCase):
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

    def _cliente(self):
        return self.app.test_client()

    def _pedir_acesso(self, cliente, email, senha=SENHA_COMUM, nome=""):
        return cliente.post(
            "/api/auth/registrar",
            json={"email": email, "senha": senha, "nome": nome},
        )

    def _admin(self):
        """
        Cliente já autenticado como administradora.

        Na primeira chamada o cadastro é criado (e o e-mail de ADMIN_EMAIL já
        nasce aprovado); nas seguintes ele existe, o cadastro responde 409 e o
        caminho certo é entrar.
        """
        cliente = self._cliente()
        resp = self._pedir_acesso(cliente, EMAIL_ADMIN, SENHA_ADMIN)
        if resp.status_code != 200:
            cliente.post(
                "/api/auth/login",
                json={"email": EMAIL_ADMIN, "senha": SENHA_ADMIN},
            )
        return cliente

    def _aprovado(self, email):
        """Pessoa comum que pediu acesso e foi liberada pela administradora."""
        cliente = self._cliente()
        self._pedir_acesso(cliente, email)

        adm = self._admin()
        alvo = next(
            u for u in adm.get("/api/admin/usuarios").get_json()["usuarios"]
            if u["email"] == email
        )
        adm.post(f"/api/admin/usuarios/{alvo['id']}/aprovar")

        cliente.post("/api/auth/login", json={"email": email, "senha": SENHA_COMUM})
        return cliente

    # ------------------------------------------------------------------
    # Sem sessão não se entra
    # ------------------------------------------------------------------

    def test_api_sem_sessao_responde_401(self):
        cliente = self._cliente()
        for rota in ("/api/tasks", "/api/projects", "/api/memories",
                     "/api/health", "/api/connections", "/api/history"):
            with self.subTest(rota=rota):
                self.assertEqual(cliente.get(rota).status_code, 401)

    def test_chat_sem_sessao_responde_401(self):
        resp = self._cliente().post("/api/chat", json={"message": "oi"})
        self.assertEqual(resp.status_code, 401)

    def test_pagina_sem_sessao_vai_para_login(self):
        resp = self._cliente().get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_pagina_de_login_e_publica(self):
        self.assertEqual(self._cliente().get("/login").status_code, 200)

    def test_toda_rota_nova_nasce_protegida(self):
        """
        A proteção é uma lista de permitidos, não um decorador por rota.

        Quem adicionar uma rota e esquecer de protegê-la continua com ela
        exigindo sessão. Este teste falha se o conjunto público crescer sem
        que alguém tenha pensado a respeito.
        """
        # Rotas que PODEM ser alcançadas sem sessão, e por quê. Qualquer outra
        # tem de barrar. Note que não dá para deduzir isto pelo código de
        # resposta: /api/auth/login também devolve 401 com credencial vazia.
        #
        # Este conjunto é para crescer com relutância. Se um teste falhar aqui,
        # a pergunta certa é "esta rota PRECISA ser pública?", não "como faço
        # o teste passar?".
        PERMITIDAS = {
            "/login",                  # a própria tela de entrada
            "/api/auth/registrar",     # pedir acesso é, por definição, sem sessão
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/eu",            # o front pergunta quem está logado
            "/api/version",            # confere o deploy de fora; só expõe o commit
            "/api/auth/esqueci",       # quem esqueceu a senha não consegue entrar
            "/redefinir",              # a tela aberta pelo link do e-mail
            "/api/auth/redefinir",     # protegida pelo token, não pela sessão
        }

        cliente = self._cliente()
        desprotegidas = []

        for regra in self.app.url_map.iter_rules():
            caminho = str(regra)
            if regra.endpoint == "static" or caminho in PERMITIDAS:
                continue
            # Rota com parâmetro: usa um id que não existe, o que ainda assim
            # tem de esbarrar na sessão antes de chegar ao banco.
            alvo = caminho.replace("<int:pending_id>", "1") \
                          .replace("<int:task_id>", "1") \
                          .replace("<int:project_id>", "1") \
                          .replace("<int:memory_id>", "1") \
                          .replace("<int:user_id>", "1")
            metodo = "POST" if "POST" in regra.methods else \
                     "GET" if "GET" in regra.methods else \
                     sorted(regra.methods - {"HEAD", "OPTIONS"})[0]
            resp = cliente.open(alvo, method=metodo, json={})
            if resp.status_code not in (401, 302):
                desprotegidas.append(f"{metodo} {alvo} -> {resp.status_code}")

        self.assertEqual(desprotegidas, [], "rotas alcançáveis sem sessão")

    # ------------------------------------------------------------------
    # Liberação pelo administrador
    # ------------------------------------------------------------------

    def test_cadastro_comum_nasce_pendente_e_nao_entra(self):
        cliente = self._cliente()
        dados = self._pedir_acesso(cliente, "alguem@exemplo.com").get_json()
        self.assertTrue(dados["ok"])
        self.assertFalse(dados["liberado"])

        # Pedido feito não é acesso concedido.
        self.assertEqual(cliente.get("/api/tasks").status_code, 401)

        login = cliente.post(
            "/api/auth/login",
            json={"email": "alguem@exemplo.com", "senha": SENHA_COMUM},
        )
        self.assertEqual(login.status_code, 403)
        self.assertIn("aguardando", login.get_json()["error"].lower())

    def test_admin_aprova_e_a_pessoa_passa_a_entrar(self):
        visitante = self._cliente()
        self._pedir_acesso(visitante, "novo@exemplo.com")

        adm = self._admin()
        lista = adm.get("/api/admin/usuarios").get_json()["usuarios"]
        pendente = next(u for u in lista if u["email"] == "novo@exemplo.com")
        self.assertEqual(pendente["status"], "pendente")

        aprovacao = adm.post(f"/api/admin/usuarios/{pendente['id']}/aprovar")
        self.assertTrue(aprovacao.get_json()["ok"])

        entrou = visitante.post(
            "/api/auth/login",
            json={"email": "novo@exemplo.com", "senha": SENHA_COMUM},
        )
        self.assertEqual(entrou.status_code, 200)
        self.assertEqual(visitante.get("/api/tasks").status_code, 200)

    def test_recusado_continua_de_fora(self):
        visitante = self._cliente()
        self._pedir_acesso(visitante, "nao@exemplo.com")

        adm = self._admin()
        alvo = next(u for u in adm.get("/api/admin/usuarios").get_json()["usuarios"]
                    if u["email"] == "nao@exemplo.com")
        adm.post(f"/api/admin/usuarios/{alvo['id']}/recusar")

        login = visitante.post(
            "/api/auth/login",
            json={"email": "nao@exemplo.com", "senha": SENHA_COMUM},
        )
        self.assertEqual(login.status_code, 403)

    def test_email_de_admin_entra_direto_como_admin(self):
        cliente = self._cliente()
        dados = self._pedir_acesso(cliente, EMAIL_ADMIN, SENHA_ADMIN).get_json()
        self.assertTrue(dados["liberado"])
        self.assertTrue(dados["usuario"]["is_admin"])
        self.assertEqual(cliente.get("/api/admin/usuarios").status_code, 200)

    def test_usuario_comum_nao_administra(self):
        comum = self._aprovado("comum@exemplo.com")
        self.assertEqual(comum.get("/api/admin/usuarios").status_code, 403)

        adm = self._admin()
        alvo = adm.get("/api/admin/usuarios").get_json()["usuarios"][0]["id"]
        self.assertEqual(
            comum.post(f"/api/admin/usuarios/{alvo}/aprovar").status_code, 403
        )

    def test_logout_encerra_o_acesso(self):
        comum = self._aprovado("saiu@exemplo.com")
        self.assertEqual(comum.get("/api/tasks").status_code, 200)
        comum.post("/api/auth/logout")
        self.assertEqual(comum.get("/api/tasks").status_code, 401)

    # ------------------------------------------------------------------
    # Credenciais
    # ------------------------------------------------------------------

    def test_senha_curta_recusada(self):
        resp = self._pedir_acesso(self._cliente(), "curta@exemplo.com", senha="1234")
        self.assertEqual(resp.status_code, 400)

    def test_email_invalido_recusado(self):
        resp = self._pedir_acesso(self._cliente(), "sem-arroba")
        self.assertEqual(resp.status_code, 400)

    def test_email_duplicado_recusado(self):
        self._pedir_acesso(self._cliente(), "igual@exemplo.com")
        resp = self._pedir_acesso(self._cliente(), "igual@exemplo.com")
        self.assertEqual(resp.status_code, 409)

    def test_senha_nao_fica_em_texto_puro(self):
        from backend.models import User

        self._pedir_acesso(self._cliente(), "hash@exemplo.com", senha=SENHA_COMUM)
        usuario = User.query.filter_by(email="hash@exemplo.com").first()
        self.assertNotIn(SENHA_COMUM, usuario.password_hash)

    def test_login_errado_nao_revela_se_o_email_existe(self):
        """Mensagem idêntica para e-mail inexistente e para senha errada."""
        self._pedir_acesso(self._cliente(), "existe@exemplo.com")
        cliente = self._cliente()

        inexistente = cliente.post(
            "/api/auth/login",
            json={"email": "naoexiste@exemplo.com", "senha": "qualquer12345"},
        )
        senha_errada = cliente.post(
            "/api/auth/login",
            json={"email": "existe@exemplo.com", "senha": "errada1234567"},
        )
        self.assertEqual(
            inexistente.get_json()["error"], senha_errada.get_json()["error"]
        )

    # ------------------------------------------------------------------
    # Isolamento entre pessoas
    # ------------------------------------------------------------------

    def test_tarefa_de_um_nao_aparece_para_o_outro(self):
        ana = self._aprovado("ana@exemplo.com")
        bia = self._aprovado("bia@exemplo.com")

        criada = ana.post("/api/tasks", json={"title": "Segredo da Ana"}).get_json()["task"]

        titulos = [t["title"] for t in bia.get("/api/tasks").get_json()["tasks"]]
        self.assertNotIn("Segredo da Ana", titulos)

        # Nem pelo id direto. Responde 404, não 403: confirmar a existência do
        # registro já entregaria informação sobre a outra pessoa.
        self.assertEqual(
            bia.put(f"/api/tasks/{criada['id']}", json={"title": "invadida"}).status_code,
            404,
        )
        self.assertEqual(bia.delete(f"/api/tasks/{criada['id']}").status_code, 404)

        # E a dona continua enxergando a própria tarefa intacta.
        minhas = [t["title"] for t in ana.get("/api/tasks").get_json()["tasks"]]
        self.assertIn("Segredo da Ana", minhas)

    def test_memoria_e_privada(self):
        ana = self._aprovado("ana2@exemplo.com")
        bia = self._aprovado("bia2@exemplo.com")

        ana.post("/api/memories", json={"content": "Ana mora em Recife"})
        conteudos = [m["content"] for m in bia.get("/api/memories").get_json()["memories"]]
        self.assertNotIn("Ana mora em Recife", conteudos)

    def test_projeto_e_privado(self):
        ana = self._aprovado("ana3@exemplo.com")
        bia = self._aprovado("bia3@exemplo.com")

        proj = ana.post("/api/projects", json={"name": "Projeto da Ana"}).get_json()["project"]
        nomes = [p["name"] for p in bia.get("/api/projects").get_json()["projects"]]
        self.assertNotIn("Projeto da Ana", nomes)
        self.assertEqual(bia.delete(f"/api/projects/{proj['id']}").status_code, 404)

    def test_historico_de_conversa_e_privado(self):
        ana = self._aprovado("ana4@exemplo.com")
        bia = self._aprovado("bia4@exemplo.com")

        ana.post("/api/chat", json={"message": "assunto particular da Ana"})
        historico = bia.get("/api/history").get_json()
        texto = str(historico)
        self.assertNotIn("assunto particular da Ana", texto)

    # ------------------------------------------------------------------
    # Contas externas: só a dona
    # ------------------------------------------------------------------

    def test_acoes_externas_so_para_o_admin(self):
        """
        As contas conectadas pertencem a uma pessoa só. Usuário comum aprovado
        não recebe as ferramentas do Composio nem consegue executá-las.
        """
        from backend.ai import agent
        from backend.security import auth as auth_mod

        comum = self._aprovado("comum2@exemplo.com")
        with comum.session_transaction() as sessao:
            id_comum = sessao[auth_mod.CHAVE_SESSAO]

        mensagem = "Liste os eventos da minha agenda do Google"

        with self.app.test_request_context("/"):
            flask_session[auth_mod.CHAVE_SESSAO] = id_comum
            self.assertEqual(agent.schemas_externos_para(mensagem), [])

    def test_admin_recebe_as_ferramentas_externas(self):
        """Contraprova: sem isto, o teste acima passaria mesmo tudo quebrado."""
        from backend.ai import agent
        from backend.security import auth as auth_mod
        from backend.tools import composio_tools

        if not composio_tools.get_schemas():
            self.skipTest("Catálogo do Composio indisponível (COMPOSIO_API_KEY ausente).")

        adm = self._admin()
        with adm.session_transaction() as sessao:
            id_adm = sessao[auth_mod.CHAVE_SESSAO]

        with self.app.test_request_context("/"):
            flask_session[auth_mod.CHAVE_SESSAO] = id_adm
            self.assertNotEqual(
                agent.schemas_externos_para("Liste os eventos da minha agenda do Google"),
                [],
            )


if __name__ == "__main__":
    unittest.main()
