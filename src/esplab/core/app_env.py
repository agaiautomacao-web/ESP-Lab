#!/usr/bin/env python3
"""
Venv da propria aplicacao ESP Lab (infraestrutura da ferramenta).

Cria e gerencia o ambiente virtual onde rodam as dependencias da APLICACAO
(textual, pyserial, PyYAML), isolado do sistema. Distinto dos python_env de
ESP-IDF (um por versao, criados pelo install.sh oficial da Espressif,
geridos por idf_manager — venv_manager.py foi removido em 2026-07-02 por
ser codigo morto, ver TASKS.md @E3-T3.7).

Le as dependencias de requirements-app.txt na raiz da aplicacao e as instala
no app-venv via pip. Caminho do venv vem do paths (app_venv); nada fixo.

Retorno (ok, result_or_error); nunca lanca; mensagens em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, List, Tuple

from . import paths as _paths
from . import errors as _errors
from . import logger as _logger

Result = Tuple[bool, Any]  # (ok, result_or_error)

REQUIREMENTS_FILENAME = "requirements-app.txt"
CREATE_TIMEOUT = 120     # criacao do venv
INSTALL_TIMEOUT = 600    # instalacao de dependencias (download da internet)


def venv_dir() -> Path:
    """Caminho do venv da aplicacao (derivado do paths)."""
    return _paths.get_paths().app_venv


def _python_bin(venv: Path) -> Path:
    """Interpretador dentro do venv (layout POSIX)."""
    return venv / "bin" / "python"


def _pip_bin(venv: Path) -> Path:
    """pip dentro do venv."""
    return venv / "bin" / "pip"


def requirements_path() -> Path:
    """Caminho do requirements-app.txt na raiz da aplicacao."""
    return _paths.get_app_root() / REQUIREMENTS_FILENAME


def exists() -> bool:
    """True se o app-venv existe e tem interpretador (integro)."""
    return _python_bin(venv_dir()).is_file()


def create(*, force: bool = False) -> Result:
    """
    Cria o venv da aplicacao usando o Python que esta executando a ferramenta.
    force=False: recusa se ja existir. force=True: remove e recria.
    """
    target = venv_dir()

    if target.exists():
        if not force:
            return (False, "o venv da aplicacao ja existe; use force para recriar")
        import shutil
        rm = _errors.guard(lambda: shutil.rmtree(str(target)), context="remocao do app-venv")
        if not rm[0]:
            return (False, f"falha ao recriar (remocao previa): {rm[1]}")

    target.parent.mkdir(parents=True, exist_ok=True)

    # Usa o mesmo Python que roda a ferramenta (sys.executable) para criar o venv.
    res = _errors.guard(
        lambda: subprocess.run(
            [sys.executable, "-m", "venv", str(target)],
            capture_output=True, text=True, timeout=CREATE_TIMEOUT,
        ),
        context="criacao do app-venv",
    )
    ok, proc = res
    if not ok:
        return (False, proc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return (False, f"app-venv nao criado (codigo {proc.returncode}): {err}")
    if not _python_bin(target).is_file():
        return (False, "app-venv criado mas interpretador ausente; estado invalido")

    _logger.get_logger().info("app-venv criado em %s", target)
    return (True, str(target))


def install_requirements() -> Result:
    """
    Instala as dependencias de requirements-app.txt dentro do app-venv.
    Requer o venv ja criado. Baixa pacotes da internet.
    """
    target = venv_dir()
    if not exists():
        return (False, "app-venv inexistente; crie-o antes de instalar")

    req = requirements_path()
    if not req.is_file():
        return (False, f"requirements ausente: '{req}'")

    pip = _pip_bin(target)
    res = _errors.guard(
        lambda: subprocess.run(
            [str(pip), "install", "-r", str(req)],
            capture_output=True, text=True, timeout=INSTALL_TIMEOUT,
        ),
        context="instalacao de dependencias da aplicacao",
    )
    ok, proc = res
    if not ok:
        return (False, proc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return (False, f"instalacao falhou (codigo {proc.returncode}): {err[:500]}")

    _logger.get_logger().info("dependencias da aplicacao instaladas no app-venv")
    return (True, "dependencias instaladas")


def ensure() -> Result:
    """
    Garante o app-venv pronto: cria se nao existir e instala as dependencias.
    Idempotente. Retorna (True, caminho) ou (False, motivo).
    """
    if not exists():
        ok, res = create()
        if not ok:
            return (False, res)
    ok, res = install_requirements()
    if not ok:
        return (False, res)
    return (True, str(venv_dir()))


def list_installed() -> Result:
    """Lista os pacotes instalados no app-venv (pip freeze)."""
    target = venv_dir()
    if not exists():
        return (False, "app-venv inexistente")
    pip = _pip_bin(target)
    res = _errors.guard(
        lambda: subprocess.run([str(pip), "freeze"], capture_output=True, text=True, timeout=60),
        context="listagem de pacotes do app-venv",
    )
    ok, proc = res
    if not ok:
        return (False, proc)
    if proc.returncode != 0:
        return (False, (proc.stderr or proc.stdout or "").strip())
    pkgs = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return (True, pkgs)


__all__ = [
    "create", "install_requirements", "ensure", "exists",
    "list_installed", "venv_dir", "requirements_path",
]
