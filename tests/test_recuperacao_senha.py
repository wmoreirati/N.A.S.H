"""
N.A.S.H - Recuperação e troca de senha.

Antes disto, esquecer a senha era beco sem saída: não havia recuperação, e o
único conserto era editar o banco à mão. Estes testes fixam as garantias do
fluxo novo -- em especial as que, se falharem, viram porta aberta.

O envio de e-mail é dublado: teste não manda e-mail de verdade, e a promessa
que interessa é "o fluxo funciona mesmo com o e-mail fora do ar".
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("OPENAI_API_KEY", "")

from app import create_app  # noqa: E402
from backend.models import User, db  # noqa: E402
from backend.security import auth  # noqa: E402
from backend.tools import email as email_mod  # noqa: E402

SENHA = "senha-de-teste-123"


class RecuperacaoTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()

        # Dublê de e-mail: guarda o que teria sido enviado.
        self.enviados = []
        self._originais = {}
        for nome in ("recuperacao_de_senha", "pedido_de_acesso_para_admin",
                     "acesso_liberado", "senha_redefinida_pelo_admin"):
            self._originais[nome] = getattr(email_mod, nome)
            setattr(email_mod, nome, self._espiao(nome))

        self.admin_antes = os.environ.get("ADMIN_EMAIL")
        os.environ["ADMIN_EMAIL"] = "dona@teste.local"

    def _espiao(self, nome):
        def registrar(*args, **kwargs):
            self.enviados.append({"tipo": nome, "args": args, "kwargs": kwargs})
            return True
        return registrar

    def tearDown(self):
        for nome, original in self._originais.items():
            setattr(email_mod, nome, original)
        if self.admin_antes is None:
            os.environ.pop("ADMIN_EMAIL", None)
        else:
            os.environ["ADMIN_EMAIL"] = self.admin_antes

        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------

    def _conta(self, email, senha=SENHA):
        cliente = self.app.test_client()
        cliente.post("/api/auth/registrar", json={"email": email, "senha": senha})
        return cliente

    def _link_enviado_para(self, email):
        for e in self.enviados:
            if e["tipo"] == "recuperacao_de_senha" and e["kwargs"].get("destinatario") == email:
                return e["kwargs"]["link"]
        return None

    def _token_de(self, link):
        return link.split("token=", 1)[1] if link and "token=" in link else None

    # ------------------------------------------------------------------
    # Pedido de recuperação
    # ------------------------------------------------------------------

    def test_pedido_gera_link_por_email(self):
        self._conta("dona@teste.local")
        cliente = self.app.test_client()

        resp = cliente.post("/api/auth/esqueci", json={"email": "dona@teste.local"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(self._link_enviado_para("dona@teste.local"))

    def test_email_inexistente_responde_igual_e_nao_envia_nada(self):
        """
        A rota é pública. Se respondesse diferente para e-mail que existe,
        viraria uma forma de descobrir quem tem conta aqui.
        """
        self._conta("dona@teste.local")
        cliente = self.app.test_client()

        existe = cliente.post("/api/auth/esqueci", json={"email": "dona@teste.local"})
        self.enviados.clear()
        nao_existe = cliente.post("/api/auth/esqueci", json={"email": "ninguem@x.com"})

        self.assertEqual(existe.status_code, nao_existe.status_code)
        self.assertEqual(existe.get_json(), nao_existe.get_json())
        self.assertEqual(self.enviados, [], "não pode enviar e-mail para quem não existe")

    def test_token_nao_fica_em_texto_no_banco(self):
        self._conta("dona@teste.local")
        self.app.test_client().post("/api/auth/esqueci", json={"email": "dona@teste.local"})

        token = self._token_de(self._link_enviado_para("dona@teste.local"))
        usuario = User.query.filter_by(email="dona@teste.local").first()
        self.assertIsNotNone(usuario.reset_token_hash)
        self.assertNotIn(token, usuario.reset_token_hash)

    # ------------------------------------------------------------------
    # Uso do link
    # ------------------------------------------------------------------

    def test_link_valido_troca_a_senha(self):
        self._conta("dona@teste.local")
        cliente = self.app.test_client()
        cliente.post("/api/auth/esqueci", json={"email": "dona@teste.local"})
        token = self._token_de(self._link_enviado_para("dona@teste.local"))

        resp = cliente.post("/api/auth/redefinir",
                            json={"token": token, "nova_senha": "outra-senha-999"})
        self.assertEqual(resp.status_code, 200, resp.get_json())

        entrou = cliente.post("/api/auth/login",
                              json={"email": "dona@teste.local", "senha": "outra-senha-999"})
        self.assertEqual(entrou.status_code, 200)

    def test_link_so_serve_uma_vez(self):
        self._conta("dona@teste.local")
        cliente = self.app.test_client()
        cliente.post("/api/auth/esqueci", json={"email": "dona@teste.local"})
        token = self._token_de(self._link_enviado_para("dona@teste.local"))

        cliente.post("/api/auth/redefinir", json={"token": token, "nova_senha": "primeira-vez-1"})
        segunda = cliente.post("/api/auth/redefinir",
                               json={"token": token, "nova_senha": "segunda-vez-2"})
        self.assertEqual(segunda.status_code, 400)

    def test_link_expirado_nao_serve(self):
        self._conta("dona@teste.local")
        cliente = self.app.test_client()
        cliente.post("/api/auth/esqueci", json={"email": "dona@teste.local"})
        token = self._token_de(self._link_enviado_para("dona@teste.local"))

        usuario = User.query.filter_by(email="dona@teste.local").first()
        usuario.reset_expira_em = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

        resp = cliente.post("/api/auth/redefinir",
                            json={"token": token, "nova_senha": "tarde-demais-1"})
        self.assertEqual(resp.status_code, 400)

    def test_token_inventado_nao_serve(self):
        self._conta("dona@teste.local")
        resp = self.app.test_client().post(
            "/api/auth/redefinir",
            json={"token": "token-que-eu-inventei", "nova_senha": "nova-senha-123"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_token_de_um_nao_troca_a_senha_do_outro(self):
        self._conta("dona@teste.local")
        self._conta("outro@teste.local")
        cliente = self.app.test_client()

        cliente.post("/api/auth/esqueci", json={"email": "dona@teste.local"})
        token = self._token_de(self._link_enviado_para("dona@teste.local"))
        cliente.post("/api/auth/redefinir", json={"token": token, "nova_senha": "trocada-aqui-1"})

        # A senha do outro continua a mesma.
        outro = User.query.filter_by(email="outro@teste.local").first()
        from werkzeug.security import check_password_hash
        self.assertTrue(check_password_hash(outro.password_hash, SENHA))

    def test_senha_curta_recusada_na_recuperacao(self):
        self._conta("dona@teste.local")
        cliente = self.app.test_client()
        cliente.post("/api/auth/esqueci", json={"email": "dona@teste.local"})
        token = self._token_de(self._link_enviado_para("dona@teste.local"))

        resp = cliente.post("/api/auth/redefinir", json={"token": token, "nova_senha": "123"})
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    # Troca da própria senha
    # ------------------------------------------------------------------

    def test_troca_exige_a_senha_atual(self):
        cliente = self._conta("dona@teste.local")
        resp = cliente.post("/api/auth/trocar-senha",
                            json={"senha_atual": "chute-errado", "nova_senha": "nova-senha-123"})
        self.assertEqual(resp.status_code, 403)

    def test_troca_funciona_com_a_senha_certa(self):
        cliente = self._conta("dona@teste.local")
        resp = cliente.post("/api/auth/trocar-senha",
                            json={"senha_atual": SENHA, "nova_senha": "nova-senha-123"})
        self.assertEqual(resp.status_code, 200, resp.get_json())

        cliente.post("/api/auth/logout")
        entrou = cliente.post("/api/auth/login",
                              json={"email": "dona@teste.local", "senha": "nova-senha-123"})
        self.assertEqual(entrou.status_code, 200)

    def test_troca_exige_sessao(self):
        resp = self.app.test_client().post(
            "/api/auth/trocar-senha",
            json={"senha_atual": SENHA, "nova_senha": "nova-senha-123"},
        )
        self.assertEqual(resp.status_code, 401)

    # ------------------------------------------------------------------
    # Redefinição pelo administrador
    # ------------------------------------------------------------------

    def test_admin_redefine_e_a_temporaria_funciona(self):
        adm = self._conta("dona@teste.local")
        self._conta("colega@teste.local")

        alvo = next(u for u in adm.get("/api/admin/usuarios").get_json()["usuarios"]
                    if u["email"] == "colega@teste.local")
        adm.post(f"/api/admin/usuarios/{alvo['id']}/aprovar")

        resp = adm.post(f"/api/admin/usuarios/{alvo['id']}/redefinir-senha")
        self.assertEqual(resp.status_code, 200)
        temporaria = resp.get_json()["senha_temporaria"]

        entrou = self.app.test_client().post(
            "/api/auth/login",
            json={"email": "colega@teste.local", "senha": temporaria},
        )
        self.assertEqual(entrou.status_code, 200)

    def test_usuario_comum_nao_redefine_senha_de_ninguem(self):
        adm = self._conta("dona@teste.local")
        comum = self._conta("comum@teste.local")
        alvo = next(u for u in adm.get("/api/admin/usuarios").get_json()["usuarios"]
                    if u["email"] == "comum@teste.local")
        adm.post(f"/api/admin/usuarios/{alvo['id']}/aprovar")
        comum.post("/api/auth/login", json={"email": "comum@teste.local", "senha": SENHA})

        resp = comum.post(f"/api/admin/usuarios/{alvo['id']}/redefinir-senha")
        self.assertEqual(resp.status_code, 403)

    # ------------------------------------------------------------------
    # E-mail não pode derrubar o fluxo
    # ------------------------------------------------------------------

    def test_cadastro_e_aprovacao_funcionam_com_o_email_fora_do_ar(self):
        """
        Envio de e-mail é acessório. Se o Gmail estiver fora, o cadastro e a
        liberação precisam continuar funcionando -- só sem aviso.
        """
        def explode(*args, **kwargs):
            raise RuntimeError("Gmail fora do ar")

        for nome in ("pedido_de_acesso_para_admin", "acesso_liberado"):
            setattr(email_mod, nome, explode)

        adm = self._conta("dona@teste.local")
        visitante = self.app.test_client()
        pedido = visitante.post("/api/auth/registrar",
                                json={"email": "novo@teste.local", "senha": SENHA})
        self.assertEqual(pedido.status_code, 200, "cadastro não pode falhar por e-mail")

        alvo = next(u for u in adm.get("/api/admin/usuarios").get_json()["usuarios"]
                    if u["email"] == "novo@teste.local")
        aprovacao = adm.post(f"/api/admin/usuarios/{alvo['id']}/aprovar")
        self.assertEqual(aprovacao.status_code, 200, "aprovação não pode falhar por e-mail")

    def test_envio_real_nunca_levanta_excecao(self):
        """`_enviar` devolve False em vez de estourar, mesmo sem configuração."""
        original = email_mod.esta_configurado
        email_mod.esta_configurado = lambda: False
        try:
            self.assertFalse(email_mod._enviar("x@y.com", "assunto", "<p>oi</p>"))
        finally:
            email_mod.esta_configurado = original


if __name__ == "__main__":
    unittest.main()
