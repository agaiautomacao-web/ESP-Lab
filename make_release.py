#!/usr/bin/env python3
"""
ESP Lab — Gerador de release (@E12-T12.0).

Grava o zip da release a partir da arvore local do projeto.
Deve ser executado a partir da raiz do repositorio (~/esplab/).

Uso:
    python make_release.py                  gera esplab-vX.Y.Z.zip
    python make_release.py --version v0.2.0 sobrescreve a versao
    python make_release.py --out ~/releases  pasta de saida customizada
    python make_release.py --dry-run         lista o que entraria no zip

O zip gerado contem:
    .esplab_root
    VERSION
    requirements-app.txt
    src/

Nao inclui:
    config/, data/, workspace/   (runtime — gerados pelo instalador)
    __pycache__/                 (bytecode compilado)
    *.pyc, *.pyo                 (bytecode)
    .git/, .gitignore            (controle de versao)
    *.bak, *.bak2                (backups locais)
    SESSAO_RELATORIO.md          (documento interno de sessao)
    make_release.py              (este script)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Itens que vao no zip (caminhos relativos a raiz do projeto)
# ---------------------------------------------------------------------------
INCLUIR = [
    ".esplab_root",
    "VERSION",
    "requirements-app.txt",
    "src",
]

# Padroes de exclusao (nome do arquivo ou sufixo)
EXCLUIR_NOMES = {
    "__pycache__", ".git", ".gitignore",
    ".DS_Store", "Thumbs.db",
}
EXCLUIR_SUFIXOS = {".pyc", ".pyo", ".bak", ".bak2", ".tmp"}
EXCLUIR_ARQUIVOS = {
    "SESSAO_RELATORIO.md",
    "make_release.py",
    "app.py.bak",
    "app.py.bak2",
}


def _deve_incluir(caminho: Path) -> bool:
    """Retorna True se o caminho deve entrar no zip."""
    for parte in caminho.parts:
        if parte in EXCLUIR_NOMES:
            return False
    if caminho.name in EXCLUIR_ARQUIVOS:
        return False
    if caminho.suffix in EXCLUIR_SUFIXOS:
        return False
    return True


def _coletar_arquivos(raiz: Path) -> list[tuple[Path, str]]:
    """
    Coleta (caminho_absoluto, caminho_no_zip) para todos os arquivos
    que devem entrar no zip.
    """
    pares: list[tuple[Path, str]] = []

    for item_rel in INCLUIR:
        origem = raiz / item_rel
        if not origem.exists():
            print(f"  [aviso] nao encontrado, ignorado: {item_rel}")
            continue

        if origem.is_file():
            if _deve_incluir(Path(item_rel)):
                pares.append((origem, item_rel))
        elif origem.is_dir():
            for arq in sorted(origem.rglob("*")):
                if arq.is_file():
                    rel = arq.relative_to(raiz)
                    if _deve_incluir(rel):
                        pares.append((arq, str(rel)))

    return pares


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def _ler_versao(raiz: Path) -> str:
    version_file = raiz / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


def _garantir_sentinela(raiz: Path) -> None:
    """Cria .esplab_root se nao existir."""
    sentinela = raiz / ".esplab_root"
    if not sentinela.exists():
        sentinela.write_text(
            "# ESP Lab root sentinel — nao remova este arquivo.\n",
            encoding="utf-8"
        )
        print(f"  [info] .esplab_root criado em {sentinela}")


def gerar_zip(raiz: Path, versao: str, pasta_saida: Path,
              dry_run: bool = False) -> Path:
    """
    Gera o zip da release.
    Retorna o caminho do zip gerado (ou o que seria gerado em dry_run).
    """
    nome_zip = f"esplab-{versao}.zip"
    caminho_zip = pasta_saida / nome_zip

    _garantir_sentinela(raiz)
    pares = _coletar_arquivos(raiz)

    if not pares:
        print("Nenhum arquivo coletado — abortando.")
        sys.exit(1)

    print(f"\n  Arquivos que entram no zip ({len(pares)}):")
    for _, nome_zip_entry in pares:
        print(f"    {nome_zip_entry}")

    if dry_run:
        print(f"\n  [dry-run] zip nao gerado. Seria: {caminho_zip}")
        return caminho_zip

    pasta_saida.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(caminho_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, nome_entry in pares:
            zf.write(abs_path, nome_entry)

    tamanho_kb = caminho_zip.stat().st_size / 1024
    sha = _sha256(caminho_zip)

    # Grava arquivo de checksum ao lado do zip
    sha_path = pasta_saida / f"{nome_zip}.sha256"
    sha_path.write_text(f"{sha}  {nome_zip}\n", encoding="utf-8")

    print(f"\n  Zip gerado:   {caminho_zip}")
    print(f"  Tamanho:      {tamanho_kb:.1f} KB")
    print(f"  SHA-256:      {sha}")
    print(f"  Checksum:     {sha_path}")

    return caminho_zip


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ESP Lab — Gerador de release",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", metavar="TAG",
                        help="versao da release (padrao: lida do arquivo VERSION)")
    parser.add_argument("--out", metavar="DIR",
                        help="pasta de saida (padrao: ~/esplab/dist/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="lista arquivos sem gerar o zip")
    args = parser.parse_args()

    # Raiz do projeto = pasta onde este script esta
    raiz = Path(__file__).parent.resolve()

    # Valida que e a raiz correta
    if not (raiz / "src" / "esplab").is_dir():
        print(f"Erro: execute este script a partir da raiz do ESP Lab.")
        print(f"  Raiz detectada: {raiz}")
        sys.exit(1)

    versao = args.version or f"v{_ler_versao(raiz)}"
    pasta_saida = Path(args.out).expanduser().resolve() if args.out \
        else raiz / "dist"

    print(f"\033[1mESP Lab — Gerador de release\033[0m")
    print(f"  Raiz:    {raiz}")
    print(f"  Versao:  {versao}")
    print(f"  Saida:   {pasta_saida}")
    print(f"  Dry-run: {'sim' if args.dry_run else 'nao'}")

    gerar_zip(raiz, versao, pasta_saida, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\n\033[1mPosso subir como release no GitHub:\033[0m")
        print(f"  gh release create {versao} {pasta_saida}/esplab-{versao}.zip")
        print(f"  (requer GitHub CLI instalado e repositorio configurado)\n")


if __name__ == "__main__":
    main()
