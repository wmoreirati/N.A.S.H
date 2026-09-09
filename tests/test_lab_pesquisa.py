"""
N.A.S.H - Laboratório e pesquisa em artigos.

O Laboratório é dado pessoal como qualquer outro: precisa do mesmo isolamento
por dono que tarefas e memórias.

A pesquisa tem uma exigência própria, e é a que mais importa aqui: a resposta
crua do Consensus tem ~43.600 caracteres (~11 mil tokens), quase o dobro do
teto de 6.000 tokens/minuto da camada gratuita. Se o enxugamento parar de
funcionar, o assistente para de responder -- e não de forma óbvia.
"""
import json
import os
import tempfile
import unittest

os.environ.setdefault("OPENAI_API_KEY", "")

from app import create_app  # noqa: E402
from backend.models import db  # noqa: E402
from backend.tools import email as email_mod  # noqa: E402
from backend.tools import pesquisa  # noqa: E402

SENHA = "senha-de-teste-123"


class LabTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.admin_antes = os.environ.get("ADMIN_EMAIL")
        os.environ["ADMIN_EMAIL"] = "dona@teste.local"

        # Sem dublê, cadastrar alguém dispara e-mail de verdade: teste lento,
        # dependente de rede e batendo num serviço externo sem necessidade.
        self._emails = {}
        for nome in ("pedido_de_acesso_para_admin", "acesso_liberado"):
            self._emails[nome] = getattr(email_mod, nome)
            setattr(email_mod, nome, lambda *a, **k: True)

    def tearDown(self):
        for nome, original in self._emails.items():
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

    def _dona(self):
        """
        Administradora autenticada. Na primeira chamada o cadastro é criado;
        nas seguintes ele já existe, o cadastro responde 409 e o caminho certo
        é entrar -- senão o cliente fica sem sessão e a falha aparece longe
        daqui, como um KeyError na resposta.
        """
        c = self.app.test_client()
        resp = c.post("/api/auth/registrar",
                      json={"email": "dona@teste.local", "senha": SENHA})
        if resp.status_code != 200:
            c.post("/api/auth/login", json={"email": "dona@teste.local", "senha": SENHA})
        return c

    def _aprovado(self, email):
        cliente = self.app.test_client()
        cliente.post("/api/auth/registrar", json={"email": email, "senha": SENHA})
        adm = self._dona()
        alvo = next(u for u in adm.get("/api/admin/usuarios").get_json()["usuarios"]
                    if u["email"] == email)
        adm.post(f"/api/admin/usuarios/{alvo['id']}/aprovar")
        cliente.post("/api/auth/login", json={"email": email, "senha": SENHA})
        return cliente

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def test_ciclo_de_um_registro(self):
        c = self._dona()

        criado = c.post("/api/lab", json={
            "title": "Titulação ácido-base",
            "area": "quimica",
            "hypothesis": "O ponto de viragem fica perto de pH 8,2.",
        }).get_json()["entry"]
        self.assertEqual(criado["status"], "aberto")
        self.assertEqual(criado["area"], "quimica")

        atualizado = c.put(f"/api/lab/{criado['id']}", json={
            "results": "Viragem observada em pH 8,4.",
            "status": "concluido",
        }).get_json()["entry"]
        self.assertIn("8,4", atualizado["results"])
        self.assertEqual(atualizado["status"], "concluido")
        # Atualizar um campo não pode apagar os outros.
        self.assertIn("8,2", atualizado["hypothesis"])

        self.assertEqual(c.delete(f"/api/lab/{criado['id']}").status_code, 200)
        self.assertEqual(c.get("/api/lab").get_json()["entries"], [])

    def test_titulo_e_obrigatorio(self):
        c = self._dona()
        self.assertEqual(c.post("/api/lab", json={"title": "   "}).status_code, 400)

    def test_area_desconhecida_vira_geral(self):
        """Valor inventado não pode virar categoria nova em silêncio."""
        c = self._dona()
        e = c.post("/api/lab", json={"title": "X", "area": "astrologia"}).get_json()["entry"]
        self.assertEqual(e["area"], "geral")

    def test_registro_nasce_pela_metade_e_tudo_bem(self):
        """Experimento começa pela hipótese; exigir tudo faria anotar noutro lugar."""
        c = self._dona()
        e = c.post("/api/lab", json={"title": "Só o título"}).get_json()["entry"]
        self.assertEqual(e["hypothesis"], "")
        self.assertEqual(e["procedure"], "")

    # ------------------------------------------------------------------
    # Isolamento
    # ------------------------------------------------------------------

    def test_registro_de_um_nao_aparece_para_o_outro(self):
        ana = self._aprovado("ana@teste.local")
        bia = self._aprovado("bia@teste.local")

        criado = ana.post("/api/lab", json={"title": "Experimento da Ana"}).get_json()["entry"]

        titulos = [e["title"] for e in bia.get("/api/lab").get_json()["entries"]]
        self.assertNotIn("Experimento da Ana", titulos)

        # Nem pelo id direto — 404, não 403.
        self.assertEqual(bia.put(f"/api/lab/{criado['id']}", json={"title": "invadido"}).status_code, 404)
        self.assertEqual(bia.delete(f"/api/lab/{criado['id']}").status_code, 404)

    def test_lab_exige_sessao(self):
        self.assertEqual(self.app.test_client().get("/api/lab").status_code, 401)


class PesquisaTestCase(unittest.TestCase):
    """
    O enxugamento roda sobre uma resposta com a MESMA forma da real -- campos
    conferidos contra o serviço (`publish_year`, `journal_name`, `authors`,
    `takeaway`). Chutar esses nomes já me custou uma versão que devolvia
    artigo sem ano nem revista.
    """

    def _resposta_falsa(self, quantos=20, tamanho_resumo=2000):
        return {
            "results": [{
                "title": f"Artigo número {i} sobre fotossíntese",
                "publish_year": 2000 + i,
                "journal_name": "Revista de Testes",
                "authors": [f"Autor {i}", "Outro Autor"],
                "abstract": "resumo longo. " * (tamanho_resumo // 14),
                "takeaway": f"Conclusão curta do artigo {i}.",
                "study_type": "review",
                "citation_count": i * 3,
                "doi": f"10.0000/teste.{i}",
                "url": f"https://consensus.app/papers/teste-{i}",
            } for i in range(quantos)]
        }

    def test_corta_o_numero_de_artigos(self):
        artigos = pesquisa._enxugar(self._resposta_falsa(quantos=20))
        self.assertEqual(len(artigos), pesquisa.MAX_RESULTADOS)

    def test_resposta_enxuta_cabe_no_orcamento_de_tokens(self):
        """
        A crua tem ~11 mil tokens e o teto do provedor gratuito é 6.000 por
        minuto. Este teste é o que impede a busca de derrubar a resposta.
        """
        enxuta = json.dumps(
            {"ok": True, "artigos": pesquisa._enxugar(self._resposta_falsa())},
            ensure_ascii=False,
        )
        tokens_estimados = len(enxuta) / 4
        self.assertLess(tokens_estimados, 1500, f"{len(enxuta)} caracteres é demais")

    def test_usa_os_nomes_de_campo_reais_do_servico(self):
        artigo = pesquisa._enxugar(self._resposta_falsa(quantos=1))[0]
        self.assertEqual(artigo["ano"], 2000)
        self.assertEqual(artigo["publicacao"], "Revista de Testes")
        self.assertEqual(artigo["autor"], "Autor 0")
        self.assertEqual(artigo["citacoes"], 0)
        self.assertIn("consensus.app", artigo["link"])

    def test_prefere_a_conclusao_ao_resumo_inteiro(self):
        artigo = pesquisa._enxugar(self._resposta_falsa(quantos=1))[0]
        self.assertIn("Conclusão curta", artigo["conclusao"])
        self.assertNotIn("resumo longo", artigo["conclusao"])

    def test_cai_para_o_resumo_quando_nao_ha_conclusao(self):
        bruto = self._resposta_falsa(quantos=1)
        bruto["results"][0]["takeaway"] = None
        artigo = pesquisa._enxugar(bruto)[0]
        self.assertIn("resumo longo", artigo["conclusao"])
        self.assertLessEqual(len(artigo["conclusao"]), pesquisa.MAX_RESUMO + 1)

    def test_corte_respeita_palavra_inteira(self):
        """Cortar no meio da palavra faz o modelo tratar o caco como termo técnico."""
        cortado = pesquisa._texto("palavra " * 200, 50)
        self.assertTrue(cortado.endswith("…"))
        self.assertNotIn("pala…", cortado)

    def test_busca_vazia_nao_chama_o_servico(self):
        self.assertFalse(pesquisa.buscar_artigos("   ")["ok"])

    def test_sem_configuracao_avisa_em_vez_de_estourar(self):
        original = pesquisa.esta_configurado
        pesquisa.esta_configurado = lambda: False
        try:
            r = pesquisa.buscar_artigos("fotossíntese")
            self.assertFalse(r["ok"])
            self.assertIn("não está configurada", r["message"])
        finally:
            pesquisa.esta_configurado = original


if __name__ == "__main__":
    unittest.main()
