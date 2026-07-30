#!/usr/bin/env python3
"""
bump.py — incremento manual-assistido da versao do ESP Lab.

Ferramenta de desenvolvimento (roda fora da aplicacao, como o publish.py).
Le a versao atual do arquivo VERSION (fonte unica), aplica um incremento
SemVer e grava de volta — de forma atomica.

Uso:
    python3 bump.py patch      # 0.1.0 -> 0.1.1
    python3 bump.py minor      # 0.1.3 -> 0.2.0
    python3 bump.py major      # 0.2.5 -> 1.0.0

    # preservar sufixo pre-release (ex.: -beta) apos o incremento:
    python3 bump.py patch --keep-suffix   # 0.1.0-beta -> 0.1.1-beta

    # definir a versao explicitamente (valida antes de gravar):
    python3 bump.py --set 1.0.0
    python3 bump.py --set 1.0.0-rc1

Regras SemVer:
    major  -> incrementa MAJOR, zera MINOR e PATCH.
    minor  -> incrementa MINOR, zera PATCH.
    patch  -> incrementa PATCH.
    Por padrao, um bump DESCARTA o sufixo pre-release (a pre-release virou
    release). Use --keep-suffix para mante-lo.

O bump NAO faz commit nem toca no git — versionar continua sendo sua decisao
consciente. Depois de rodar, a barra da TUI e a tela "Sobre" passam a exibir
o novo numero na proxima abertura (leem o VERSION em runtime).

Convencao: identificadores em ingles, mensagens em portugues.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

# Reusa a fonte unica de validacao/leitura do proprio projeto, em vez de
# reimplementar regra de SemVer aqui (evita duas verdades divergindo).
SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

try:
    from esplab.core import version as _version
except Exception as e:  # pragma: no cover
    print(f"ERRO: nao consegui importar esplab.core.version: {e}")
    print("Rode este script a partir da raiz do projeto (~/esplab).")
    sys.exit(1)


def _split(raw: str) -> tuple[int, int, int, str]:
    """Quebra 'X.Y.Z' ou 'X.Y.Z-sufixo' em (major, minor, patch, sufixo)."""
    core, _, suffix = raw.partition("-")
    a, b, c = core.split(".")
    return int(a), int(b), int(c), suffix


def _compose(major: int, minor: int, patch: int, suffix: str = "") -> str:
    base = f"{major}.{minor}.{patch}"
    return f"{base}-{suffix}" if suffix else base


def _atomic_write(path: Path, texto: str) -> None:
    """Grava de forma atomica: tmp no mesmo diretorio + os.replace."""
    d = path.parent
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".VERSION.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Incremento manual-assistido da versao (VERSION).")
    ap.add_argument("nivel", nargs="?", choices=["patch", "minor", "major"],
                    help="parte do SemVer a incrementar")
    ap.add_argument("--set", dest="set_to", metavar="X.Y.Z[-suf]",
                    help="define a versao explicitamente (valida antes)")
    ap.add_argument("--keep-suffix", action="store_true",
                    help="preserva o sufixo pre-release apos o incremento")
    args = ap.parse_args()

    if not args.nivel and not args.set_to:
        ap.error("informe um nivel (patch/minor/major) ou --set X.Y.Z")
    if args.nivel and args.set_to:
        ap.error("use nivel OU --set, nao os dois")

    # versao atual (via fonte unica; nunca lanca — devolve UNKNOWN em falha)
    ok, atual = _version.read_version()
    if not ok:
        print(f"ERRO: VERSION atual invalido/ilegivel: {atual}")
        return 2

    path = _version.version_file()

    # --- caminho A: --set explicito ---
    if args.set_to:
        novo = args.set_to.strip()
        if not _version._is_semver(novo):
            print(f"ERRO: '{novo}' nao e um SemVer valido (X.Y.Z[-sufixo]).")
            return 2
        _atomic_write(path, novo + "\n")
        print(f"{atual}  ->  {novo}")
        return 0

    # --- caminho B: incremento por nivel ---
    major, minor, patch, suffix = _split(atual)
    if args.nivel == "major":
        major, minor, patch = major + 1, 0, 0
    elif args.nivel == "minor":
        minor, patch = minor + 1, 0
    else:  # patch
        patch += 1

    novo_suffix = suffix if args.keep_suffix else ""
    novo = _compose(major, minor, patch, novo_suffix)

    # sanidade: o resultado tem de passar na propria validacao do projeto
    if not _version._is_semver(novo):
        print(f"ERRO interno: versao composta invalida '{novo}'. Nada gravado.")
        return 3

    _atomic_write(path, novo + "\n")
    print(f"{atual}  ->  {novo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
