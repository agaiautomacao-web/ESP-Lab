#!/usr/bin/env python3
"""
Gerenciador de templates de projeto (@E8-T8.8).

Carrega o catalogo embarcado (templates.yml) e aplica o template
escolhido sobre um projeto recem-criado pelo workspace.new.
Seguranca: so aplica em projeto vazio (apenas arquivos da estrutura
minima); recusa se o usuario ja tiver codigo no projeto.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core import storage as _storage

Result = Tuple[bool, Any]

# Arquivos da estrutura minima criados pelo workspace.new.
# Aplicar template sobre esses arquivos e seguro (sao placeholders).
_BASELINE_FILES = {
    "CMakeLists.txt",
    "main/CMakeLists.txt",
    "main/main.c",
    "project_config.json",
}

_CATALOG_PATH = Path(__file__).parent / "data" / "templates.yml"


def _load_catalog() -> Result:
    """Carrega o catalogo de templates embarcado."""
    if not _CATALOG_PATH.is_file():
        return (False, "catalogo de templates nao encontrado em '{}'".format(
            _CATALOG_PATH))
    ok, data = _storage.read_yaml(_CATALOG_PATH)
    if not ok:
        return (False, "erro ao ler catalogo de templates: {}".format(data))
    if not isinstance(data, dict) or "templates" not in data:
        return (False, "catalogo de templates malformado")
    return (True, data["templates"])


def list_templates() -> Result:
    """
    Lista os templates disponiveis.
    Retorna (True, lista) onde cada item e {id, name, description}.
    """
    ok, templates = _load_catalog()
    if not ok:
        return (False, templates)
    resumo = [
        {"id": t["id"], "name": t["name"], "description": t["description"]}
        for t in templates
        if isinstance(t, dict) and "id" in t
    ]
    return (True, resumo)


def _is_empty_project(project_dir: Path) -> bool:
    """
    Verifica se o projeto contem apenas os arquivos da estrutura minima.
    Ignora __pycache__ e .git. Retorna True se seguro para aplicar template.
    """
    ignore = {"__pycache__", ".git"}
    for entry in project_dir.rglob("*"):
        if entry.is_dir():
            continue
        parts = entry.relative_to(project_dir).parts
        if any(p in ignore for p in parts):
            continue
        rel = str(entry.relative_to(project_dir))
        if rel not in _BASELINE_FILES:
            return False
    return True


def apply_template(project_dir: str | Path, template_id: str) -> Result:
    """
    Aplica template sobre projeto recem-criado.
    Recusa se o projeto ja tiver arquivos alem da estrutura minima.
    Transacional: reverte arquivos gravados se qualquer escrita falhar.
    """
    root = Path(project_dir).expanduser().resolve()
    if not root.is_dir():
        return (False, "pasta de projeto inexistente: '{}'".format(root))

    if not _is_empty_project(root):
        return (False, "projeto nao esta vazio; template so pode ser "
                       "aplicado em projetos recem-criados")

    ok, templates = _load_catalog()
    if not ok:
        return (False, templates)

    tmpl = next((t for t in templates if t.get("id") == template_id), None)
    if tmpl is None:
        ids = [t.get("id") for t in templates]
        return (False, "template '{}' nao encontrado; disponiveis: {}".format(
            template_id, ids))

    files = tmpl.get("files", [])
    if not files:
        return (True, {"template": template_id,
                       "message": "template '{}' aplicado (sem arquivos extras)".format(
                           tmpl["name"]),
                       "files_written": []})

    # Aplica: grava cada arquivo; reverte em caso de falha.
    written: List[Path] = []
    try:
        for f in files:
            path  = (root / f["path"]).resolve()
            # Seguranca: nao sai da pasta do projeto.
            if not str(path).startswith(str(root)):
                raise ValueError("caminho fora do projeto: {}".format(f["path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f["content"], encoding="utf-8")
            written.append(path)
    except Exception as e:
        # Reverte: remove arquivos ja gravados.
        for p in written:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        return (False, "erro ao aplicar template (revertido): {}".format(e))

    return (True, {
        "template":      template_id,
        "message":       "template '{}' aplicado com sucesso".format(tmpl["name"]),
        "files_written": [str(p.relative_to(root)) for p in written],
    })
