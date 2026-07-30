#!/usr/bin/env python3
"""
Camada de persistência atômica do ESP Lab (@E1-T1.4).

Toda gravação em disco passa por aqui. A escrita é atômica: o conteúdo vai
primeiro para um arquivo temporário no MESMO diretório do destino, é forçado ao
disco (fsync) e só então substitui o arquivo final por os.replace (troca
atômica no mesmo filesystem). Assim, uma falha no meio da escrita nunca corrompe
nem deixa o arquivo final pela metade — o arquivo antigo permanece intacto.

Contrato de retorno (PROJECT.md): toda função devolve (ok, result_or_error) e
nunca lança exceção para cima. Mensagens em português.

Convenção: identificadores em inglês, strings em português.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Tuple, Union

PathLike = Union[str, Path]
Result = Tuple[bool, Any]  # (ok, result_or_error)


# ==========================================================
# NÚCLEO — escrita atômica de bytes/texto
# ==========================================================

def atomic_write_text(path: PathLike, content: str, encoding: str = "utf-8") -> Result:
    """
    Grava texto de forma atômica.
    Retorna (True, caminho_str) em sucesso, (False, motivo) em falha.
    """
    dest = Path(path).expanduser().resolve()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return (False, f"não foi possível preparar o diretório de destino: {e}")

    tmp_name = None
    try:
        # Temporário no MESMO diretório — garante que os.replace seja atômico
        # (replace entre filesystems diferentes não é atômico).
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding=encoding) as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())  # força os dados ao disco antes da troca
        except Exception:
            # fd já foi consumido pelo fdopen; garante remoção do tmp abaixo
            raise

        os.replace(tmp_name, dest)  # troca atômica
        tmp_name = None  # consumido com sucesso
        return (True, str(dest))

    except Exception as e:
        return (False, f"falha ao gravar '{dest}': {e}")
    finally:
        # Limpeza defensiva: se algo falhou antes do replace, remove o lixo.
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except Exception:
                pass


def read_text(path: PathLike, encoding: str = "utf-8") -> Result:
    """
    Lê texto. (True, conteúdo) em sucesso; (False, motivo) se ausente/ilegível.
    """
    src = Path(path).expanduser().resolve()
    try:
        if not src.is_file():
            return (False, f"arquivo inexistente: '{src}'")
        return (True, src.read_text(encoding=encoding))
    except Exception as e:
        return (False, f"falha ao ler '{src}': {e}")


# ==========================================================
# JSON
# ==========================================================

def atomic_write_json(path: PathLike, data: Any, *, indent: int = 2) -> Result:
    """
    Serializa para JSON e grava de forma atômica.
    ensure_ascii=False preserva acentuação portuguesa nas strings de conteúdo.
    """
    try:
        text = json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=False)
    except Exception as e:
        return (False, f"dados não serializáveis para JSON: {e}")
    return atomic_write_text(path, text + "\n")


def read_json(path: PathLike) -> Result:
    """
    Lê e faz parse de JSON. (True, objeto) ou (False, motivo).
    """
    ok, res = read_text(path)
    if not ok:
        return (ok, res)
    try:
        return (True, json.loads(res))
    except Exception as e:
        return (False, f"JSON inválido em '{path}': {e}")


# ==========================================================
# YAML (opcional — degrada com mensagem clara se PyYAML ausente)
# ==========================================================

def _load_yaml_module():
    try:
        import yaml  # type: ignore
        return yaml
    except Exception:
        return None


def atomic_write_yaml(path: PathLike, data: Any) -> Result:
    """
    Serializa para YAML e grava de forma atômica.
    Requer PyYAML; se ausente, retorna (False, motivo) sem quebrar.
    """
    yaml = _load_yaml_module()
    if yaml is None:
        return (False, "PyYAML não está disponível no ambiente")
    try:
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    except Exception as e:
        return (False, f"dados não serializáveis para YAML: {e}")
    return atomic_write_text(path, text)


def read_yaml(path: PathLike) -> Result:
    """
    Lê e faz parse de YAML. (True, objeto) ou (False, motivo).
    """
    yaml = _load_yaml_module()
    if yaml is None:
        return (False, "PyYAML não está disponível no ambiente")
    ok, res = read_text(path)
    if not ok:
        return (ok, res)
    try:
        return (True, yaml.safe_load(res))
    except Exception as e:
        return (False, f"YAML inválido em '{path}': {e}")


# ==========================================================
# UTILITÁRIO — atualização lida->modifica->grava com segurança
# ==========================================================

def update_json(path: PathLike, mutator: Callable[[Any], Any], *, default: Any = None) -> Result:
    """
    Lê o JSON (ou usa `default` se ausente), aplica `mutator` ao conteúdo e
    regrava de forma atômica. Útil para edições que devem preservar o resto.

    mutator: recebe o objeto atual, devolve o objeto a ser gravado.
    """
    ok, current = read_json(path)
    if not ok:
        # arquivo ausente é aceitável quando há default; outros erros não.
        if default is None:
            return (False, current)
        current = default
    try:
        new_data = mutator(current)
    except Exception as e:
        return (False, f"falha ao aplicar modificação: {e}")
    return atomic_write_json(path, new_data)


__all__ = [
    "atomic_write_text", "read_text",
    "atomic_write_json", "read_json",
    "atomic_write_yaml", "read_yaml",
    "update_json",
    "PathLike", "Result",
]
