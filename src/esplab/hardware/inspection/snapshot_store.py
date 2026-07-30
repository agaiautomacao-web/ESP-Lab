#!/usr/bin/env python3
"""
Persistencia de dados brutos por sessao de inspecao.

Cada leitura completa (esptool + espefuse + boot log + particoes) gera um
snapshot em ~/.local/share/esplab/snapshots/<mac>/<YYYYMMDD_HHMMSS>/.

Auditoria e historico, NAO fonte ativa. A fonte ativa do perfil e o
boards_db. O snapshot preserva o texto cru de cada comando + um JSON com
o parse consolidado, sem duplicar o que ja esta no perfil.

Escrita atomica: usa tmp + os.replace, resistente a queda de energia.

Consumido por service.scan_hardware() quando quiser gravar historico.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

Result = tuple[bool, Any]

# Raiz de dados do ESP Lab (padrao XDG conforme README/PROJECT.md).
_SNAPSHOTS_ROOT = (
    Path(os.environ.get("XDG_DATA_HOME",
                        Path.home() / ".local" / "share"))
    / "esplab" / "snapshots"
)


def _normalize_mac(mac: str) -> str:
    """Normaliza MAC para nome de diretorio (minusculo, sem :)."""
    return re.sub(r"[^0-9a-f]", "", (mac or "").lower())


def _write_atomic(path: Path, data: bytes) -> Result:
    """
    Escrita atomica: tmp no mesmo diretorio + fsync + os.replace.
    Sobrevive a queda de energia sem arquivo corrompido pela metade.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".tmp_", dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return (True, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        return (False, f"falha ao gravar {path}: {e}")


def _write_text(path: Path, texto: str) -> Result:
    """Grava texto UTF-8 atomicamente."""
    return _write_atomic(path, (texto or "").encode("utf-8"))


def _write_json(path: Path, obj: Any) -> Result:
    """Grava JSON atomicamente com indent=2."""
    try:
        data = json.dumps(
            obj, indent=2, ensure_ascii=False, default=str,
        ).encode("utf-8")
    except Exception as e:
        return (False, f"falha ao serializar JSON: {e}")
    return _write_atomic(path, data)


def save_snapshot(
    mac: str,
    raw_outputs: dict[str, str],
    parsed: dict[str, Any],
    root: Path | None = None,
) -> Result:
    """
    Salva um snapshot completo de uma leitura de inspecao.

    mac         : MAC da placa (usado como diretorio, normalizado).
    raw_outputs : dict {"chip": "...", "flash": "...", "efuse": "...",
                        "seg": "...", "part": "...", "boot": "..."}
                  Cada chave vira <chave>.txt no disco.
    parsed      : dict consolidado (resultado de analyze.py) que vira
                  dados_parseados.json.
    root        : raiz custom (default: ~/.local/share/esplab/snapshots).
                  Injecao existe para teste; producao usa o padrao.

    Retorna (True, path_do_diretorio) ou (False, motivo).
    """
    mac_norm = _normalize_mac(mac)
    if not mac_norm:
        return (False, "MAC vazio ou invalido; snapshot nao gravado")

    raiz = root or _SNAPSHOTS_ROOT
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = raiz / mac_norm / stamp

    try:
        outdir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return (False, f"nao criou diretorio {outdir}: {e}")

    for nome, conteudo in (raw_outputs or {}).items():
        nome_seguro = re.sub(r"[^a-z0-9_.-]+", "_", nome.lower())
        ok, res = _write_text(outdir / f"{nome_seguro}.txt", conteudo)
        if not ok:
            return (False, res)

    ok, res = _write_json(outdir / "dados_parseados.json", parsed)
    if not ok:
        return (False, res)

    return (True, outdir)


def list_snapshots(
    mac: str, root: Path | None = None,
) -> Result:
    """Lista snapshots de um MAC, do mais recente ao mais antigo."""
    mac_norm = _normalize_mac(mac)
    if not mac_norm:
        return (False, "MAC vazio ou invalido")
    raiz = (root or _SNAPSHOTS_ROOT) / mac_norm
    if not raiz.is_dir():
        return (True, [])
    dirs = sorted(
        (p for p in raiz.iterdir() if p.is_dir()),
        reverse=True,
    )
    return (True, dirs)
