#!/usr/bin/env python3
"""
Explorador de arquivos do projeto (@E8-T8.1).

Operacoes: list_tree, create_file, create_dir, rename, move, delete.
SEM edicao de conteudo — abrir para editar e funcao do editor externo.
Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Principio transacional: operacao completa ou nao deixa rastro.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any, List, Tuple

Result = Tuple[bool, Any]

# Entradas ocultadas por padrao na listagem (lixo de compilacao/vcs).
HIDDEN = {"build", "sdkconfig.old", "__pycache__", ".git",
          ".gitignore", "sdkconfig"}


def list_tree(project_dir: str | Path,
              show_hidden: bool = False) -> Result:
    """
    Lista a arvore de arquivos do projeto como dados normalizados.
    Retorna (True, lista) ou (False, motivo).
    Cada item: {name, relative, type: 'file'|'dir', depth}.
    """
    root = Path(project_dir).expanduser().resolve()
    if not root.is_dir():
        return (False, "pasta de projeto inexistente: '{}'".format(root))

    items: List[dict] = []
    try:
        for entry in sorted(root.rglob("*")):
            # Filtra ocultos em qualquer nivel do caminho.
            parts = entry.relative_to(root).parts
            if not show_hidden and any(p in HIDDEN for p in parts):
                continue
            rel = entry.relative_to(root)
            items.append({
                "name":     entry.name,
                "relative": str(rel),
                "type":     "dir" if entry.is_dir() else "file",
                "depth":    len(parts) - 1,
            })
    except Exception as e:
        return (False, "erro ao listar arvore: {}".format(e))

    return (True, items)


def create_file(project_dir: str | Path, relative_path: str) -> Result:
    """
    Cria arquivo vazio no projeto. Recusa se ja existir.
    relative_path: caminho relativo a raiz do projeto (ex. 'main/sensor.c').
    """
    root = Path(project_dir).expanduser().resolve()
    target = (root / relative_path).resolve()
    if not str(target).startswith(str(root)):
        return (False, "caminho fora da pasta do projeto")
    if target.exists():
        return (False, "arquivo ja existe: '{}'".format(relative_path))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        return (True, str(target.relative_to(root)))
    except Exception as e:
        return (False, "erro ao criar arquivo: {}".format(e))


def create_dir(project_dir: str | Path, relative_path: str) -> Result:
    """
    Cria diretorio no projeto. Recusa se ja existir.
    """
    root = Path(project_dir).expanduser().resolve()
    target = (root / relative_path).resolve()
    if not str(target).startswith(str(root)):
        return (False, "caminho fora da pasta do projeto")
    if target.exists():
        return (False, "diretorio ja existe: '{}'".format(relative_path))
    try:
        target.mkdir(parents=True)
        return (True, str(target.relative_to(root)))
    except Exception as e:
        return (False, "erro ao criar diretorio: {}".format(e))


def rename(project_dir: str | Path,
           relative_path: str, new_name: str) -> Result:
    """
    Renomeia arquivo ou diretorio (mesmo pai). Recusa se destino existir.
    new_name: so o nome, sem separadores de caminho.
    """
    if "/" in new_name or "\\" in new_name:
        return (False, "novo nome nao pode conter separadores de caminho")
    root   = Path(project_dir).expanduser().resolve()
    source = (root / relative_path).resolve()
    if not str(source).startswith(str(root)):
        return (False, "caminho fora da pasta do projeto")
    if not source.exists():
        return (False, "origem nao encontrada: '{}'".format(relative_path))
    dest = source.parent / new_name
    if dest.exists():
        return (False, "ja existe item com o nome '{}' nesta pasta".format(new_name))
    try:
        source.rename(dest)
        return (True, str(dest.relative_to(root)))
    except Exception as e:
        return (False, "erro ao renomear: {}".format(e))


def move(project_dir: str | Path,
         relative_src: str, relative_dest_dir: str) -> Result:
    """
    Move arquivo ou diretorio para outra pasta dentro do projeto.
    relative_dest_dir: pasta de destino (deve existir).
    """
    root     = Path(project_dir).expanduser().resolve()
    source   = (root / relative_src).resolve()
    dest_dir = (root / relative_dest_dir).resolve()
    if not str(source).startswith(str(root)):
        return (False, "origem fora da pasta do projeto")
    if not str(dest_dir).startswith(str(root)):
        return (False, "destino fora da pasta do projeto")
    if not source.exists():
        return (False, "origem nao encontrada: '{}'".format(relative_src))
    if not dest_dir.is_dir():
        return (False, "pasta de destino inexistente: '{}'".format(relative_dest_dir))
    dest = dest_dir / source.name
    if dest.exists():
        return (False, "ja existe '{}' na pasta de destino".format(source.name))
    try:
        shutil.move(str(source), str(dest))
        return (True, str(dest.relative_to(root)))
    except Exception as e:
        return (False, "erro ao mover: {}".format(e))


def delete(project_dir: str | Path,
           relative_path: str, confirm: bool = False) -> Result:
    """
    Remove arquivo ou diretorio. Requer confirm=True (operacao destrutiva).
    Diretorio e removido com todo o conteudo.
    """
    if not confirm:
        return (False, "remocao requer confirmacao explicita (confirm=True)")
    root   = Path(project_dir).expanduser().resolve()
    target = (root / relative_path).resolve()
    if not str(target).startswith(str(root)):
        return (False, "caminho fora da pasta do projeto")
    if not target.exists():
        return (False, "item nao encontrado: '{}'".format(relative_path))
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return (True, "removido: '{}'".format(relative_path))
    except Exception as e:
        return (False, "erro ao remover: {}".format(e))
