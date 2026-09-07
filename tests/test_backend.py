"""
N.A.S.H - Testes automatizados do backend.

Executar (dentro do venv, com dependências instaladas):
    pytest tests/ -v

ou, sem pytest instalado:
    python -m unittest discover -s tests -v

Estes testes usam um banco SQLite em arquivo temporário (nunca o banco
real em instance/nash.db) e NÃO fazem nenhuma chamada de rede — o
provedor de IA fica deliberadamente "não configurado" (sem OPENAI_API_KEY),
então /api/chat é testado apenas no caminho "IA offline", que não depende
de internet.
"""
import os
import tempfile
import unittest

os.environ.setdefault("OPENAI_API_KEY", "")  # garante que o provider fica "não configurado" nos testes

from app import create_app
from backend.models import db, PendingAction


class NashTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
        })
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        # No Windows o arquivo só pode ser apagado depois que o SQLAlchemy
        # soltar a conexão — sem isso, todo teste falha com WinError 32.
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    # -----------------------------------------------------------------
    # Saúde
    # -----------------------------------------------------------------

    def test_health(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertIn("ai_configured", data)
        self.assertIn("connections", data)

    # -----------------------------------------------------------------
    # Tarefas: criação, edição, conclusão, exclusão, restauração
    # -----------------------------------------------------------------

    def test_task_lifecycle(self):
        # Criar
        resp = self.client.post("/api/tasks", json={"title": "Estudar química", "priority": "alta"})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["ok"])
        task_id = data["task"]["id"]
        self.assertEqual(data["task"]["status"], "pendente")

        # Editar
        resp = self.client.put(f"/api/tasks/{task_id}", json={"title": "Estudar química orgânica"})
        self.assertEqual(resp.get_json()["task"]["title"], "Estudar química orgânica")

        # Concluir
        resp = self.client.post(f"/api/tasks/{task_id}/complete")
        self.assertEqual(resp.get_json()["task"]["status"], "concluida")

        # Excluir (lógica)
        resp = self.client.delete(f"/api/tasks/{task_id}")
        self.assertEqual(resp.get_json()["result"]["status"], "excluida")

        # Restaurar
        resp = self.client.post(f"/api/tasks/{task_id}/restore")
        self.assertEqual(resp.get_json()["task"]["status"], "pendente")

    def test_task_requires_title(self):
        resp = self.client.post("/api/tasks", json={"title": "  "})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(data["ok"])

    def test_task_invalid_priority_rejected(self):
        resp = self.client.post("/api/tasks", json={"title": "X", "priority": "urgentíssimo"})
        self.assertEqual(resp.status_code, 400)

    def test_task_invalid_date_rejected(self):
        resp = self.client.post("/api/tasks", json={"title": "X", "date": "31/12/2026"})
        self.assertEqual(resp.status_code, 400)

    # -----------------------------------------------------------------
    # Projetos — excluir projeto não apaga as tarefas ligadas a ele
    # -----------------------------------------------------------------

    def test_project_delete_preserves_tasks(self):
        resp = self.client.post("/api/projects", json={"name": "Vestibular"})
        project_id = resp.get_json()["project"]["id"]

        resp = self.client.post("/api/tasks", json={"title": "Revisar física", "project_id": project_id})
        task_id = resp.get_json()["task"]["id"]

        resp = self.client.delete(f"/api/projects/{project_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["result"]["tasks_unlinked"], 1)

        # A tarefa continua existindo, só perdeu o vínculo com o projeto
        resp = self.client.get("/api/tasks")
        tasks = resp.get_json()["tasks"]
        found = next(t for t in tasks if t["id"] == task_id)
        self.assertIsNone(found["project_id"])

    def test_project_progress_bounds(self):
        resp = self.client.post("/api/projects", json={"name": "X"})
        project_id = resp.get_json()["project"]["id"]
        resp = self.client.put(f"/api/projects/{project_id}", json={"progress": 150})
        self.assertEqual(resp.status_code, 400)

    # -----------------------------------------------------------------
    # Memória
    # -----------------------------------------------------------------

    def test_memory_lifecycle(self):
        resp = self.client.post("/api/memories", json={"content": "Prefere explicações detalhadas", "category": "preferencia"})
        data = resp.get_json()
        self.assertTrue(data["ok"])
        memory_id = data["memory"]["id"]

        resp = self.client.get("/api/memories")
        self.assertEqual(len(resp.get_json()["memories"]), 1)

        resp = self.client.delete(f"/api/memories/{memory_id}")
        self.assertTrue(resp.get_json()["ok"])

        resp = self.client.get("/api/memories")
        self.assertEqual(len(resp.get_json()["memories"]), 0)

    def test_memory_empty_content_rejected(self):
        resp = self.client.post("/api/memories", json={"content": ""})
        self.assertEqual(resp.status_code, 400)

    # -----------------------------------------------------------------
    # PendingAction: confirmação, cancelamento, dupla execução, expiração
    # -----------------------------------------------------------------

    def test_pending_action_confirm_executes_once(self):
        from backend.ai.agent import create_pending_action, resolve_pending_action

        pending = create_pending_action("tool_create_task", {"title": "Tarefa via IA"})
        self.assertEqual(pending.status, "pendente")

        result = resolve_pending_action(pending, confirmed=True)
        self.assertEqual(result["type"], "message")
        self.assertEqual(pending.status, "confirmada")

        # Tarefa foi realmente criada
        resp = self.client.get("/api/tasks")
        titles = [t["title"] for t in resp.get_json()["tasks"]]
        self.assertIn("Tarefa via IA", titles)

        # Tentar confirmar de novo deve ser rejeitado (nunca executa duas vezes)
        result2 = resolve_pending_action(pending, confirmed=True)
        self.assertEqual(result2["type"], "error")

    def test_pending_action_cancel(self):
        from backend.ai.agent import create_pending_action, resolve_pending_action

        pending = create_pending_action("tool_delete_all_tasks", {})
        result = resolve_pending_action(pending, confirmed=False)
        self.assertEqual(result["type"], "message")
        self.assertEqual(pending.status, "cancelada")

    def test_pending_action_api_confirm_cancel_routes(self):
        from backend.ai.agent import create_pending_action

        pending = create_pending_action("tool_create_task", {"title": "Via API"})
        resp = self.client.post(f"/api/pending-actions/{pending.id}/confirm")
        self.assertTrue(resp.get_json()["ok"])

        # Segunda tentativa de confirmar a MESMA ação deve falhar com 409
        resp2 = self.client.post(f"/api/pending-actions/{pending.id}/confirm")
        self.assertEqual(resp2.status_code, 409)

    def test_pending_action_expiration(self):
        from datetime import datetime, timedelta
        from backend.ai.agent import create_pending_action, expire_old_pending_actions

        pending = create_pending_action("tool_create_task", {"title": "Vai expirar"})
        # Força a data de criação para o passado
        pending.created_at = datetime.utcnow() - timedelta(minutes=999)
        db.session.commit()

        expired_count = expire_old_pending_actions(minutes=30)
        self.assertEqual(expired_count, 1)

        refreshed = PendingAction.query.get(pending.id)
        self.assertEqual(refreshed.status, "expirada")

    # -----------------------------------------------------------------
    # Permissões
    # -----------------------------------------------------------------

    def test_permissions_read_vs_write(self):
        from backend.security import permissions

        self.assertFalse(permissions.requires_confirmation("tool_list_tasks"))
        self.assertFalse(permissions.requires_confirmation("tool_list_memories"))
        for tool in (
            "tool_create_task", "tool_update_task", "tool_delete_task",
            "tool_create_project", "tool_update_project", "tool_delete_project",
            "tool_save_memory", "tool_update_memory", "tool_delete_memory",
            "tool_spotify_control",
        ):
            self.assertTrue(permissions.requires_confirmation(tool), f"{tool} deveria exigir confirmação")

    def test_tool_schema_permission_dispatcher_consistency(self):
        """Garante que todo tool do schema tem permissão E dispatcher — o bug original do projeto."""
        from backend.ai.tools_schema import get_tools_schema
        from backend.ai.agent import READ_TOOL_NAMES, WRITE_TOOL_NAMES
        from backend.security import permissions

        schema_names = {t["function"]["name"] for t in get_tools_schema()}
        dispatched = READ_TOOL_NAMES | WRITE_TOOL_NAMES
        permission_names = set(permissions.TOOL_PERMISSIONS.keys())

        self.assertEqual(schema_names, dispatched, "Ferramentas do schema e dos dispatchers devem ser idênticas")
        self.assertTrue(schema_names.issubset(permission_names), "Toda ferramenta do schema precisa de permissão declarada")

    # -----------------------------------------------------------------
    # Segurança básica
    # -----------------------------------------------------------------

    def test_unknown_task_returns_404_not_500(self):
        resp = self.client.put("/api/tasks/99999", json={"title": "X"})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()["ok"])

    def test_error_responses_never_expose_traceback(self):
        resp = self.client.delete("/api/tasks/99999")
        data = resp.get_json()
        self.assertNotIn("Traceback", data.get("error", ""))


if __name__ == "__main__":
    unittest.main()
