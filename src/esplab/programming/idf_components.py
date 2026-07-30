#!/usr/bin/env python3
"""
Listagem de componentes internos do ESP-IDF usado pelo projeto.

Esta camada e SOMENTE LEITURA:
  - le project_config.json para descobrir idf_version
  - resolve data/esp-idf/<versao>/components via core.paths
  - lista diretorios de componentes internos do ESP-IDF
  - nao edita CMakeLists.txt
  - nao edita idf_component.yml
  - nao roda idf.py
  - nao compila
  - nao reconfigura

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core import paths as _paths
from ..workspace import project_config as _config

Result = Tuple[bool, Any]


def _resolve_project(project_dir: str | Path) -> Result:
    root = Path(project_dir).expanduser().resolve()
    if not root.is_dir():
        return (False, "pasta de projeto inexistente: '{}'".format(root))
    return (True, root)


def get_project_idf_components_dir(project_dir: str | Path) -> Result:
    """
    Retorna o diretorio 'components' da versao ESP-IDF declarada no projeto.

    Ex.:
      /home/.../esplab/data/esp-idf/v5.4.4/components
    """
    ok, root = _resolve_project(project_dir)
    if not ok:
        return (False, root)

    ok2, cfg = _config.read(root)
    if not ok2:
        return (False, cfg)

    idf_version = str(cfg.get("idf_version", "")).strip()
    if not idf_version:
        return (False, "projeto sem idf_version em project_config.json")

    idf_root = _paths.get_paths().idf_for(idf_version)
    components_dir = idf_root / "components"

    if not idf_root.is_dir():
        return (False, "ESP-IDF '{}' nao encontrado em '{}'".format(
            idf_version, idf_root))

    if not components_dir.is_dir():
        return (False, "diretorio de componentes ausente: '{}'".format(
            components_dir))

    return (True, {
        "idf_version": idf_version,
        "idf_root": str(idf_root),
        "components_dir": str(components_dir),
    })


def list_idf_components(project_dir: str | Path) -> Result:
    """
    Lista componentes internos do ESP-IDF usado pelo projeto.

    Cada item:
      {
        "name": "esp_wifi",
        "path": ".../components/esp_wifi",
        "has_cmake": True,
        "has_component_register": True|False
      }

    Somente leitura.
    """
    ok, info = get_project_idf_components_dir(project_dir)
    if not ok:
        return (False, info)

    components_dir = Path(info["components_dir"])

    items: List[Dict[str, Any]] = []
    for child in sorted(components_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue

        cmake = child / "CMakeLists.txt"
        has_component_register = False
        if cmake.is_file():
            try:
                text = cmake.read_text(encoding="utf-8", errors="ignore")
                has_component_register = "idf_component_register" in text
            except Exception:
                has_component_register = False

        items.append({
            "name": child.name,
            "path": str(child.resolve()),
            "has_cmake": cmake.is_file(),
            "has_component_register": has_component_register,
        })

    return (True, {
        "idf_version": info["idf_version"],
        "idf_root": info["idf_root"],
        "components_dir": info["components_dir"],
        "count": len(items),
        "components": items,
    })


def find_idf_component(project_dir: str | Path, name: str) -> Result:
    """
    Procura um componente interno do ESP-IDF por nome exato.
    Somente leitura.
    """
    target = (name or "").strip()
    if not target:
        return (False, "nome de componente vazio")

    ok, data = list_idf_components(project_dir)
    if not ok:
        return (False, data)

    for item in data["components"]:
        if item["name"] == target:
            return (True, item)

    return (False, "componente ESP-IDF '{}' nao encontrado".format(target))


def get_idf_component_detail(project_dir: str | Path, name: str) -> Result:
    """
    Detalha um componente interno do ESP-IDF no contexto do projeto.

    Junta:
      - dados do componente em data/esp-idf/<versao>/components
      - status atual em main/CMakeLists.txt -> REQUIRES/PRIV_REQUIRES

    Somente leitura.
    """
    ok, comp = find_idf_component(project_dir, name)
    if not ok:
        return (False, comp)

    ok2, info = get_project_idf_components_dir(project_dir)
    if not ok2:
        return (False, info)

    from . import cmake_requires as _cmreq

    ok3, req = _cmreq.list_main_requires(project_dir)
    if not ok3:
        return (False, req)

    comp_name = comp["name"]

    in_requires = comp_name in req.get("requires", [])
    in_priv_requires = comp_name in req.get("priv_requires", [])

    actions = ["view_details"]
    if in_requires:
        actions.append("remove_requires")
    elif in_priv_requires:
        actions.append("already_in_priv_requires")
    else:
        actions.append("add_requires")

    return (True, {
        "name": comp_name,
        "source": "internal_esp_idf",
        "effective_version": info["idf_version"],
        "idf_version": info["idf_version"],
        "idf_root": info["idf_root"],
        "path": comp["path"],
        "has_cmake": comp.get("has_cmake", False),
        "has_component_register": comp.get("has_component_register", False),
        "project_status": {
            "in_requires": in_requires,
            "in_priv_requires": in_priv_requires,
            "requires": req.get("requires", []),
            "priv_requires": req.get("priv_requires", []),
        },
        "available_actions": actions,
    })


__all__ = [
    "get_project_idf_components_dir",
    "list_idf_components",
    "find_idf_component",
    "get_idf_component_detail",
]
