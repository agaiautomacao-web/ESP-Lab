#!/usr/bin/env python3
"""
Geracao opcional de regra sudoers restrita (@E2-T2.2).

Cria uma regra em /etc/sudoers.d/esplab que permite ao usuario atual
executar APENAS os comandos necessarios ao ESP Lab sem senha.
Opcional, com consentimento explicito — nunca automatico.
Reversivel: remove_rule() desfaz tudo que install_rule() tocou.
O instalador registra no manifesto o que foi criado.

Seguranca:
  - Regra valida sintaxe antes de gravar (visudo --check).
  - Arquivo com permissao 0440 (exigencia do sudo).
  - Nunca sobrescreve regra existente em silencio.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import grp
import os
import pwd
import subprocess
import tempfile
from pathlib import Path
from typing import Any, List, Tuple

from . import sudo_wrapper as _sudo

Result = Tuple[bool, Any]

SUDOERS_DIR  = Path("/etc/sudoers.d")
RULE_FILENAME = "esplab"
RULE_PATH     = SUDOERS_DIR / RULE_FILENAME

# Comandos permitidos sem senha (caminhos absolutos, minimo necessario).
# Apenas instalacao de pre-requisitos do sistema para o ESP-IDF.
_ALLOWED_CMDS: List[str] = [
    "/usr/bin/apt-get install *",
    "/usr/bin/apt-get update",
]


def _current_user() -> str:
    """Retorna o nome do usuario real (nao root, mesmo sob sudo)."""
    uid = int(os.environ.get("SUDO_UID", os.getuid()))
    return pwd.getpwuid(uid).pw_name


def _build_rule(username: str) -> str:
    """Monta o conteudo da regra sudoers."""
    linhas = [
        "# Regra gerada pelo ESP Lab — nao edite manualmente.",
        "# Remova com: sudo rm /etc/sudoers.d/esplab",
        "",
    ]
    for cmd in _ALLOWED_CMDS:
        linhas.append(f"{username} ALL=(root) NOPASSWD: {cmd}")
    return "\n".join(linhas) + "\n"


def _validate_rule(content: str, password: str) -> Result:
    """Valida a regra com visudo --check antes de gravar."""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sudoers",
                                         delete=False) as tf:
            tf.write(content)
            tf_path = tf.name
        ok, res = _sudo.run_sudo(
            ["visudo", "--check", "--file", tf_path],
            password, timeout=15,
        )
        Path(tf_path).unlink(missing_ok=True)
        if not ok:
            return (False, "regra invalida (visudo): {}".format(res))
        return (True, None)
    except Exception as e:
        return (False, "erro ao validar regra: {}".format(e))


def rule_exists() -> bool:
    """True se a regra ja existe em /etc/sudoers.d/esplab."""
    return RULE_PATH.is_file()


def install_rule(password: str) -> Result:
    """
    Instala a regra sudoers. Requer consentimento explicito da TUI.
    Recusa se a regra ja existir. Valida com visudo antes de gravar.
    """
    if not password:
        return (False, "senha nao pode ser vazia")
    if rule_exists():
        return (False, "regra sudoers ja existe em {}".format(RULE_PATH))

    username = _current_user()
    content  = _build_rule(username)

    # Valida antes de gravar.
    ok, err = _validate_rule(content, password)
    if not ok:
        return (False, err)

    # Grava via sudo em arquivo temporario, depois move para sudoers.d.
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".esplab_rule",
                                         delete=False) as tf:
            tf.write(content)
            tf_path = tf.name

        # Copia para sudoers.d com permissao correta.
        ok2, r2 = _sudo.run_sudo(
            ["cp", tf_path, str(RULE_PATH)], password)
        Path(tf_path).unlink(missing_ok=True)
        if not ok2:
            return (False, "falha ao copiar regra: {}".format(r2))

        ok3, r3 = _sudo.run_sudo(
            ["chmod", "0440", str(RULE_PATH)], password)
        if not ok3:
            _sudo.run_sudo(["rm", "-f", str(RULE_PATH)], password)
            return (False, "falha ao definir permissao da regra: {}".format(r3))

        return (True, {
            "path":     str(RULE_PATH),
            "user":     username,
            "commands": _ALLOWED_CMDS,
            "message":  "regra sudoers instalada para '{}'".format(username),
        })
    except Exception as e:
        return (False, "erro ao instalar regra: {}".format(e))


def remove_rule(password: str) -> Result:
    """
    Remove a regra sudoers. Reversivel e limpo.
    """
    if not password:
        return (False, "senha nao pode ser vazia")
    if not rule_exists():
        return (False, "regra sudoers nao encontrada em {}".format(RULE_PATH))

    ok, res = _sudo.run_sudo(["rm", "-f", str(RULE_PATH)], password)
    if not ok:
        return (False, "falha ao remover regra: {}".format(res))

    return (True, {"message": "regra sudoers removida de {}".format(RULE_PATH)})


def show_rule(password: str = "") -> Result:
    """
    Exibe o conteudo da regra atual (para a TUI mostrar ao usuario).
    Leitura via sudo (arquivo 0440 root:root).
    Retorna (True, conteudo_str) ou (False, motivo).
    """
    if not rule_exists():
        return (False, "regra sudoers nao encontrada")
    if not password:
        return (False, "senha necessaria para ler a regra (arquivo protegido)")
    ok, res = _sudo.run_sudo(["cat", str(RULE_PATH)], password, timeout=10)
    if not ok:
        return (False, "erro ao ler regra: {}".format(res))
    return (True, res["stdout"])


__all__ = [
    "install_rule", "remove_rule", "rule_exists", "show_rule",
    "RULE_PATH", "RULE_FILENAME",
]
