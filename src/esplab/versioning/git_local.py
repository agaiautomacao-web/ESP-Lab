#!/usr/bin/env python3
"""Versionamento Git LOCAL do ESP Lab (@E11).

Apenas local: sem nuvem, API, token, push/pull ou rede. Prepara o projeto
para versionamento sob demanda (git init + .gitignore + primeiro commit) e
permite commits manuais seguintes.

Retorno (ok, result_or_error); nunca lanca; mensagens em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Tuple

from ..core import errors as _errors
from ..core import logger as _logger

Result = Tuple[bool, Any]  # (ok, result_or_error)

# Identidade local neutra para o primeiro commit nunca falhar por falta de
# config. E local ao repo (nao mexe no git global do usuario).
DEFAULT_USER_NAME = "ESP Lab"
DEFAULT_USER_EMAIL = "esplab@localhost"

GITIGNORE_CONTENT = """# Gerado pelo ESP Lab.
# Artefatos de compilacao e arquivos que nao devem ser versionados.
build/
sdkconfig.old
*.pyc
__pycache__/
.DS_Store
"""


def _git_available() -> bool:
    return shutil.which("git") is not None


def _run_git(repo: Path, args: List[str], timeout: int = 30) -> Result:
    """Roda 'git -C <repo> <args>'. (True, saida) ou (False, motivo)."""
    res = _errors.guard(
        lambda: subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout,
        ),
        context="execucao do git",
    )
    ok, proc = res
    if not ok:
        return (False, proc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return (False, f"git falhou (codigo {proc.returncode}): {err[:300]}")
    return (True, (proc.stdout or "").strip())


def is_repo(project_dir: Path | str) -> bool:
    """True se a pasta ja e um repositorio git."""
    return (Path(project_dir).expanduser().resolve() / ".git").is_dir()


def _write_gitignore(repo: Path) -> Result:
    """Grava o .gitignore (sobrescreve). (True, caminho) ou (False, motivo)."""
    res = _errors.guard(
        lambda: (repo / ".gitignore").write_text(GITIGNORE_CONTENT, encoding="utf-8"),
        context="gravacao do .gitignore",
    )
    ok, _ = res
    return (True, str(repo / ".gitignore")) if ok else (False, res[1])


def prepare(project_dir: Path | str) -> Result:
    """
    Prepara o versionamento do projeto (sob demanda):
    git init + .gitignore + identidade local + primeiro commit.
    Idempotente: se ja for repo, nao reinicializa.
    """
    if not _git_available():
        return (False, "git nao esta instalado no sistema")

    repo = Path(project_dir).expanduser().resolve()
    if not repo.is_dir():
        return (False, f"pasta de projeto inexistente: '{repo}'")

    if is_repo(repo):
        return (False, "o projeto ja possui versionamento (repositorio git existente)")

    ok, res = _run_git(repo, ["init"])
    if not ok:
        return (False, res)

    # identidade local ao repo (nao global)
    _run_git(repo, ["config", "user.name", DEFAULT_USER_NAME])
    _run_git(repo, ["config", "user.email", DEFAULT_USER_EMAIL])

    ok, res = _write_gitignore(repo)
    if not ok:
        return (False, res)

    ok, res = _run_git(repo, ["add", "."])
    if not ok:
        return (False, res)

    ok, res = _run_git(repo, ["commit", "-m", "Primeiro commit (ESP Lab)"])
    if not ok:
        return (False, res)

    _logger.get_logger().info("versionamento preparado em %s", repo)
    return (True, "versionamento preparado: repositorio criado e primeiro commit feito")


def commit(project_dir: Path | str, message: str) -> Result:
    """
    Faz um commit manual de todas as alteracoes. Requer repo ja preparado.
    (True, msg) ou (False, motivo). Mensagem vazia e recusada.
    """
    if not _git_available():
        return (False, "git nao esta instalado no sistema")
    repo = Path(project_dir).expanduser().resolve()
    if not is_repo(repo):
        return (False, "projeto sem versionamento; prepare antes de commitar")
    msg = (message or "").strip()
    if not msg:
        return (False, "mensagem de commit vazia")

    ok, res = _run_git(repo, ["add", "."])
    if not ok:
        return (False, res)

    # se nao ha mudancas, git commit retorna codigo != 0; tratamos como aviso
    ok, res = _run_git(repo, ["commit", "-m", msg])
    if not ok:
        if "nothing to commit" in str(res) or "nada a submeter" in str(res):
            return (False, "nada a commitar (sem alteracoes)")
        return (False, res)

    _logger.get_logger().info("commit manual em %s", repo)
    return (True, f"commit realizado: {msg}")


def status(project_dir: Path | str) -> Result:
    """Retorna o status resumido do repo. (True, texto) ou (False, motivo)."""
    if not _git_available():
        return (False, "git nao esta instalado no sistema")
    repo = Path(project_dir).expanduser().resolve()
    if not is_repo(repo):
        return (False, "projeto sem versionamento")
    return _run_git(repo, ["status", "--short", "--branch"])


__all__ = ["prepare", "commit", "status", "is_repo", "GITIGNORE_CONTENT"]
