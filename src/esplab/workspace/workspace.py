#!/usr/bin/env python3
"""
Operacoes de ciclo de vida de projeto do ESP Lab (@E7-T7.1).

New / Open / Close / Clone. Sem "Save" manual — os metadados sao persistidos
pela peca project_config. Cada projeto vive numa pasta do workspace, com
estrutura minima ESP-IDF mais os arquivos da aplicacao.

Regras:
  - New   : cria a pasta + estrutura minima (main/main.c, CMakeLists.txt) +
            project_config.json. Aborta se a pasta ja existir.
  - Open  : carrega os metadados; falha se nao houver config legivel. (Ativar
            o venv e responsabilidade da camada de execucao, nao desta peca.)
  - Close : valida a fronteira de fechamento. Flash em andamento bloqueia;
            o chamador encerra o monitor e limpa a referencia persistente.
  - Clone : duplica um projeto para novo nome, EXCLUINDO build/. Recusa se o
            destino ja existir.

Retorno (ok, result_or_error); nunca lanca; mensagens em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Tuple

from ..core import errors as _errors
from ..core import storage as _storage
from ..core import logger as _logger
from ..core import paths as _paths
from . import project_config as _config
from ..software import idf_manager as _idf

Result = Tuple[bool, Any]  # (ok, result_or_error)

# Itens que nunca sao copiados numa clonagem (lixo de compilacao).
CLONE_EXCLUDE = {"build", "sdkconfig.old", "__pycache__"}

# CMakeLists.txt minimo de projeto ESP-IDF.
_ROOT_CMAKE = """cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(__PROJECT_NAME__)
"""

# CMakeLists.txt do componente main.
_MAIN_CMAKE = """idf_component_register(SRCS "main.c"
                    INCLUDE_DIRS ".")
"""

# main.c placeholder.
_MAIN_C = """#include <stdio.h>

void app_main(void)
{
    // Ponto de entrada do projeto ESP-IDF.
    printf("ESP Lab: projeto iniciado\\n");
}
"""



# ==========================================================
# WORKSPACE GLOBAL CONFIGURAVEL (@E7-T7.2)
# ==========================================================

_WORKSPACE_SCHEMA_VERSION = 1


def _workspace_config_path() -> Path:
    """Arquivo global da preferencia; nunca vive dentro de um projeto."""
    return _paths.get_paths().workspace_config


def default_workspace_dir() -> Path:
    """Diretorio padrao, calculado em runtime a partir da raiz da aplicacao."""
    return _paths.get_paths().workspace_default


def normalize_workspace_dir(value: Path | str) -> Result:
    """Normaliza entrada do usuario sem criar nem alterar o diretorio."""
    raw = str(value or "").strip()
    if not raw:
        return (False, "diretorio de workspace vazio")
    try:
        path = Path(raw).expanduser().resolve()
    except Exception as exc:
        return (False, f"caminho de workspace invalido: {exc}")
    return (True, path)


def validate_workspace_dir(
    value: Path | str,
    *,
    verify_write: bool = True,
) -> Result:
    """
    Valida existencia, leitura e escrita.

    A verificacao de escrita e real: cria, sincroniza e remove um arquivo
    temporario no proprio diretorio. Nenhuma preferencia e persistida aqui.
    """
    ok, normalized = normalize_workspace_dir(value)
    if not ok:
        return (False, normalized)
    path: Path = normalized

    if not path.exists():
        return (False, f"diretorio inexistente: '{path}'")
    if not path.is_dir():
        return (False, f"o caminho nao e um diretorio: '{path}'")

    try:
        with os.scandir(path):
            pass
    except Exception as exc:
        return (False, f"diretorio sem permissao de leitura: '{path}': {exc}")

    if verify_write:
        temp_name = None
        fd = None
        try:
            fd, temp_name = tempfile.mkstemp(
                prefix=".esplab_workspace_test_",
                suffix=".tmp",
                dir=str(path),
            )
            os.write(fd, b"esplab-workspace-check\n")
            os.fsync(fd)
            os.close(fd)
            fd = None
            os.unlink(temp_name)
            temp_name = None
        except Exception as exc:
            return (
                False,
                f"diretorio sem permissao de escrita: '{path}': {exc}",
            )
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
            if temp_name and os.path.exists(temp_name):
                try:
                    os.unlink(temp_name)
                except Exception:
                    pass

    return (True, {
        "path": str(path),
        "readable": True,
        "writable": True if verify_write else None,
    })


def get_workspace_state() -> Result:
    """
    Le a preferencia global e descreve o workspace efetivo.

    Arquivo ausente ou workspace_dir nulo significa usar o padrao. Uma
    preferencia customizada indisponivel nao e substituida silenciosamente.
    """
    config_path = _workspace_config_path()
    default_dir = default_workspace_dir()
    configured = False
    source = "default"
    selected = default_dir

    if config_path.exists():
        ok, data = _storage.read_json(config_path)
        if not ok:
            return (False, f"configuracao de workspace invalida: {data}")
        if not isinstance(data, dict):
            return (False, "configuracao de workspace corrompida")
        schema = data.get("schema_version", _WORKSPACE_SCHEMA_VERSION)
        if schema != _WORKSPACE_SCHEMA_VERSION:
            return (
                False,
                "versao da configuracao de workspace nao suportada: "
                f"{schema}",
            )
        raw = data.get("workspace_dir")
        if raw not in (None, ""):
            ok, normalized = normalize_workspace_dir(raw)
            if not ok:
                return (False, normalized)
            selected = normalized
            configured = True
            source = "user"

    ok_valid, validation = validate_workspace_dir(
        selected,
        verify_write=False,
    )
    error = None if ok_valid else str(validation)

    return (True, {
        "path": str(selected),
        "default_path": str(default_dir),
        "config_path": str(config_path),
        "configured": configured,
        "source": source,
        "usable": bool(ok_valid),
        "error": error,
    })


def get_workspace_dir() -> Result:
    """Retorna o workspace efetivo somente quando ele estiver utilizavel."""
    ok, state = get_workspace_state()
    if not ok:
        return (False, state)
    if not state.get("usable"):
        return (
            False,
            "workspace configurado indisponivel: "
            f"{state.get('path')} — {state.get('error')}",
        )
    return (True, Path(state["path"]))


def set_workspace_dir(value: Path | str) -> Result:
    """Valida e persiste atomicamente o workspace escolhido pelo usuario."""
    ok, validation = validate_workspace_dir(value, verify_write=True)
    if not ok:
        return (False, validation)

    selected = Path(validation["path"])
    default_dir = default_workspace_dir()
    payload = {
        "schema_version": _WORKSPACE_SCHEMA_VERSION,
        "workspace_dir": (
            None if selected == default_dir else str(selected)
        ),
    }
    ok, result = _storage.atomic_write_json(_workspace_config_path(), payload)
    if not ok:
        return (False, result)

    ok, state = get_workspace_state()
    if not ok:
        return (False, state)
    _logger.get_logger().info(
        "workspace definido: %s (%s)",
        state["path"],
        state["source"],
    )
    return (True, state)


def reset_workspace_dir() -> Result:
    """Restaura o workspace padrao sem mover ou excluir projetos existentes."""
    return set_workspace_dir(default_workspace_dir())

def project_dir(workspace_dir: Path | str, project_name: str) -> Path:
    """Caminho da pasta de um projeto dentro do workspace."""
    return Path(workspace_dir).expanduser().resolve() / project_name


# ==========================================================
# NEW
# ==========================================================

def new(workspace_dir: Path | str, project_name: str, idf_version: str) -> Result:
    """
    Cria um novo projeto com estrutura minima ESP-IDF. Aborta se a pasta existir.
    """
    name = (project_name or "").strip()
    if not name:
        return (False, "nome do projeto vazio ou invalido")
    if not (idf_version or "").strip():
        return (False, "versao de ESP-IDF vazia ou invalida")

    pdir = project_dir(workspace_dir, name)
    if pdir.exists():
        return (False, f"ja existe um projeto em '{pdir}'; operacao abortada")

    def _build():
        (pdir / "main").mkdir(parents=True, exist_ok=False)
        (pdir / "CMakeLists.txt").write_text(_ROOT_CMAKE.replace("__PROJECT_NAME__", name), encoding="utf-8")
        (pdir / "main" / "CMakeLists.txt").write_text(_MAIN_CMAKE, encoding="utf-8")
        (pdir / "main" / "main.c").write_text(_MAIN_C, encoding="utf-8")
        return True

    res = _errors.guard(_build, context="criacao da estrutura do projeto")
    if not res[0]:
        # limpeza defensiva se algo falhou no meio
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)
        return (False, res[1])

    ok, cfg = _config.create(pdir, name, idf_version.strip())
    if not ok:
        shutil.rmtree(pdir, ignore_errors=True)
        return (False, cfg)

    _logger.get_logger().info("projeto '%s' criado em %s", name, pdir)
    return (True, {"project_dir": str(pdir), "config": cfg})


# ==========================================================
# OPEN
# ==========================================================

def open_project(project_path: Path | str) -> Result:
    """
    Abre um projeto: carrega os metadados. Falha se nao houver config legivel.
    """
    pdir = Path(project_path).expanduser().resolve()
    if not pdir.is_dir():
        return (False, f"pasta de projeto inexistente: '{pdir}'")
    ok, cfg = _config.read(pdir)
    if not ok:
        return (False, cfg)
    _logger.get_logger().info("projeto aberto: %s", pdir)
    return (True, {"project_dir": str(pdir), "config": cfg})


# ==========================================================
# CLOSE
# ==========================================================

def close_project(session=None):
    """
    @E7-T7.6: valida a fronteira de fechamento.

    Flash em andamento bloqueia. Monitor ativo nao bloqueia: ele deve ser
    encerrado pelo chamador como parte atomica do fluxo de fechamento, pois
    esta camada nao possui a instancia do canal serial.
    """
    if session is None:
        session = {}
    if not isinstance(session, dict):
        return (False, "sessao invalida")

    flash_in_progress = bool(
        session.get("flash_in_progress")
        or session.get("flash_em_andamento")
        or session.get("busy")
    )
    if flash_in_progress:
        return (
            False,
            "flash em andamento; aguarde terminar antes de fechar o projeto",
        )

    _logger.get_logger().debug("fechamento de projeto autorizado")
    return (True, {
        "allowed": True,
        "monitor_connected": bool(session.get("monitor_connected")),
    })


# ==========================================================
# CLONE
# ==========================================================


def activate_project(project_path):
    """@E7-T7.4: abre projeto e ativa ambiente da versao de ESP-IDF registrada."""
    ok, info = open_project(project_path)
    if not ok:
        return (False, info)
    cfg = info["config"]
    versao = cfg.get("idf_version", "")
    if not versao:
        return (False, "projeto sem versao de ESP-IDF definida")
    if not _idf._is_installed(versao):
        return (False, "ESP-IDF {} nao instalado".format(versao))
    ok, ativ = _idf.activate(versao)
    if not ok:
        return (False, "falha ao ativar ESP-IDF: {}".format(ativ))
    sessao = {
        "project_dir": info["project_dir"],
        "idf_version": versao,
        "target": cfg.get("target", ""),
        "env_vars": ativ["env_vars"],
        "busy": False,
        "monitor_connected": False,
    }
    return (True, {"config": cfg, "session": sessao})


def installed_idf_versions():
    """@E7-T7.5: lista versoes instaladas para o usuario escolher."""
    return _idf.list_installed()


def clone(source_path: Path | str, workspace_dir: Path | str, new_name: str) -> Result:
    """
    Clona um projeto para um novo nome, excluindo build/ e afins.
    Recusa se o destino ja existir.
    """
    src = Path(source_path).expanduser().resolve()
    name = (new_name or "").strip()
    if not name:
        return (False, "nome do clone vazio ou invalido")
    if not src.is_dir():
        return (False, f"projeto de origem inexistente: '{src}'")

    ok, _src_cfg = _config.read(src)
    if not ok:
        return (False, f"origem nao e um projeto valido: {_src_cfg}")

    dst = project_dir(workspace_dir, name)
    if dst.exists():
        return (False, f"ja existe um projeto em '{dst}'; clonagem recusada")

    def _ignore(_dir, names):
        return [n for n in names if n in CLONE_EXCLUDE]

    res = _errors.guard(
        lambda: shutil.copytree(str(src), str(dst), ignore=_ignore),
        context="copia da estrutura do projeto",
    )
    if not res[0]:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        return (False, res[1])

    # Atualiza identidade do clone: novo nome + created_at PROPRIO (data da
    # clonagem). O clone nasce agora, nao herda a data do original.
    ok, cfg = _config.read(dst)
    if not ok:
        shutil.rmtree(dst, ignore_errors=True)
        return (False, cfg)
    now = _config._now()
    cfg["project_name"] = name
    cfg["created_at"] = now
    cfg["updated_at"] = now
    ok, res = _storage.atomic_write_json(_config.config_path(dst), cfg)
    if not ok:
        shutil.rmtree(dst, ignore_errors=True)
        return (False, res)

    _logger.get_logger().info("projeto clonado de %s para %s", src, dst)
    return (True, {"project_dir": str(dst), "config": cfg})


__all__ = [
    "new", "open_project", "close_project", "clone", "project_dir",
    "default_workspace_dir", "normalize_workspace_dir",
    "validate_workspace_dir", "get_workspace_state", "get_workspace_dir",
    "set_workspace_dir", "reset_workspace_dir", "CLONE_EXCLUDE",
]
