"""
N.A.S.H - Envio de e-mail pela conta Gmail já conectada no Composio.

Por que por aqui, e não por SMTP próprio: a conexão Gmail já existe, está
ativa e é a mesma que o assistente usa. Não acrescenta credencial nenhuma ao
ambiente. Em troca, os e-mails saem da conta conectada -- adequado a um
projeto pessoal, e a trocar se um dia virar produto (basta reimplementar
`_enviar` sobre SMTP; o resto deste módulo não muda).

REGRA DURA: e-mail nunca pode derrubar o fluxo que o disparou. Cadastro,
aprovação e pedido de recuperação precisam funcionar com o Gmail fora do ar.
Toda função aqui devolve True/False e NUNCA levanta exceção para fora.
"""
import logging
import os

import requests

logger = logging.getLogger("nash.email")

BASE_URL = "https://backend.composio.dev/api/v3"
TIMEOUT = 30

# Nome que aparece nos textos. O remetente real é a conta Gmail conectada.
REMETENTE = "N.A.S.H"


def esta_configurado() -> bool:
    return bool(
        (os.environ.get("COMPOSIO_API_KEY") or "").strip()
        and (os.environ.get("COMPOSIO_USER_ID") or "").strip()
    )


def _enviar(destinatario: str, assunto: str, corpo_html: str) -> bool:
    """Envia de fato. Devolve se deu certo; não levanta exceção."""
    if not esta_configurado():
        logger.warning("E-mail não enviado: Composio não configurado neste servidor.")
        return False

    try:
        resposta = requests.post(
            f"{BASE_URL}/tools/execute/GMAIL_SEND_EMAIL",
            headers={"x-api-key": os.environ["COMPOSIO_API_KEY"].strip()},
            json={
                "user_id": os.environ["COMPOSIO_USER_ID"].strip(),
                "arguments": {
                    "recipient_email": destinatario,
                    "subject": assunto,
                    "body": corpo_html,
                    "is_html": True,
                },
            },
            timeout=TIMEOUT,
        )
        dados = resposta.json()
        if resposta.status_code != 200 or not dados.get("successful"):
            logger.error(
                "Falha ao enviar e-mail para %s: %s",
                destinatario, str(dados.get("error"))[:300],
            )
            return False
        return True
    except Exception:  # noqa: BLE001 — nenhuma falha de rede pode subir daqui
        logger.exception("Erro inesperado ao enviar e-mail para %s", destinatario)
        return False


# ---------------------------------------------------------------------------
# Aparência
# ---------------------------------------------------------------------------

def _moldura(titulo: str, miolo: str) -> str:
    """
    Moldura simples e escura, no tom da aplicação.

    Sem imagem externa e sem CSS moderno de propósito: cliente de e-mail
    costuma ignorar folha de estilo e bloquear imagem remota, então tudo vai
    embutido e com tabela, que é o que sobrevive em todo lugar.
    """
    return f"""\
<div style="background:#05080d;padding:28px 16px;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"
         style="max-width:520px;margin:0 auto;background:#0b131c;
                border:1px solid #17293b;border-radius:6px;">
    <tr><td style="padding:26px 26px 8px;">
      <div style="color:#5b9bff;font-size:20px;font-weight:bold;letter-spacing:3px;">
        N.A.S.H
      </div>
      <div style="color:#6f8ba3;font-size:12px;letter-spacing:2px;text-transform:uppercase;">
        {titulo}
      </div>
    </td></tr>
    <tr><td style="padding:8px 26px 26px;color:#dcedf9;font-size:15px;line-height:1.6;">
      {miolo}
    </td></tr>
    <tr><td style="padding:0 26px 22px;color:#3f5468;font-size:12px;line-height:1.5;">
      Mensagem automática do N.A.S.H. Se não foi você, pode ignorar.
    </td></tr>
  </table>
</div>"""


def _botao(url: str, texto: str) -> str:
    return (
        f'<a href="{url}" style="display:inline-block;background:#2f6fed;color:#ffffff;'
        f'text-decoration:none;padding:12px 22px;border-radius:6px;font-weight:bold;">'
        f"{texto}</a>"
    )


# ---------------------------------------------------------------------------
# Mensagens
# ---------------------------------------------------------------------------

def recuperacao_de_senha(destinatario: str, nome: str, link: str, validade_horas: int) -> bool:
    saudacao = f"Olá, {nome}." if nome else "Olá."
    miolo = f"""
      <p>{saudacao}</p>
      <p>Chegou um pedido para redefinir a senha da sua conta no N.A.S.H.</p>
      <p style="margin:22px 0;">{_botao(link, "Criar uma nova senha")}</p>
      <p style="color:#6f8ba3;font-size:13px;">
        O link vale por {validade_horas} hora(s) e só pode ser usado uma vez.<br>
        Se o botão não abrir, copie este endereço:<br>
        <span style="color:#5b9bff;word-break:break-all;">{link}</span>
      </p>
      <p style="color:#6f8ba3;font-size:13px;">
        Se você não pediu isso, não precisa fazer nada — sua senha continua a mesma.
      </p>"""
    return _enviar(destinatario, "Redefinir sua senha no N.A.S.H", _moldura("Recuperação de acesso", miolo))


def pedido_de_acesso_para_admin(destinatario_admin: str, nome: str, email: str, link_painel: str) -> bool:
    quem = f"{nome} ({email})" if nome else email
    miolo = f"""
      <p><strong>{quem}</strong> pediu acesso ao N.A.S.H.</p>
      <p>Ninguém entra sem a sua liberação. O pedido está esperando na aba
         <strong>Acessos</strong>.</p>
      <p style="margin:22px 0;">{_botao(link_painel, "Abrir o painel de acessos")}</p>"""
    return _enviar(destinatario_admin, f"Novo pedido de acesso: {email}",
                   _moldura("Pedido de acesso", miolo))


def acesso_liberado(destinatario: str, nome: str, link_app: str) -> bool:
    saudacao = f"Boas-vindas, {nome}!" if nome else "Boas-vindas!"
    miolo = f"""
      <p>{saudacao}</p>
      <p>Seu acesso ao N.A.S.H foi liberado. Entre com o e-mail e a senha que
         você cadastrou.</p>
      <p style="margin:22px 0;">{_botao(link_app, "Entrar no N.A.S.H")}</p>"""
    return _enviar(destinatario, "Seu acesso ao N.A.S.H foi liberado",
                   _moldura("Acesso liberado", miolo))


def senha_redefinida_pelo_admin(destinatario: str, nome: str, temporaria: str, link_app: str) -> bool:
    saudacao = f"Olá, {nome}." if nome else "Olá."
    miolo = f"""
      <p>{saudacao}</p>
      <p>O administrador redefiniu a sua senha. Use a senha temporária abaixo
         para entrar e troque-a em <strong>Ajustes</strong>.</p>
      <p style="margin:18px 0;font-family:monospace;font-size:20px;
                letter-spacing:2px;color:#35e2a0;">{temporaria}</p>
      <p style="margin:22px 0;">{_botao(link_app, "Entrar no N.A.S.H")}</p>"""
    return _enviar(destinatario, "Sua senha do N.A.S.H foi redefinida",
                   _moldura("Senha redefinida", miolo))
