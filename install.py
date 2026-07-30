#!/usr/bin/env python3
"""
ESP Lab — Instalador standalone
Uso:
    python install.py                  # instala versão mais recente
    python install.py --version v0.2.0 # versão específica
    python install.py --branch main    # direto do branch
    python install.py --dest /opt/esplab
    python install.py --update         # atualiza instalação existente
    python install.py --uninstall      # remove instalação
"""

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO — ajuste antes de publicar
# ---------------------------------------------------------------------------
GITHUB_USER   = "agaiautomacao-web"
GITHUB_REPO   = "ESP-Lab"
DEFAULT_DEST  = "~/esplab"             # destino padrão de instalação
SENTINEL_FILE = ".esplab_root"         # arquivo que paths.py usa para detectar raiz
ENTRY_SCRIPT  = "esplab.sh"            # script de entrada gerado na pasta
# ---------------------------------------------------------------------------

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
import zipfile
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Utilitários de saída
# ---------------------------------------------------------------------------

def _print(msg: str) -> None:
    print(msg, flush=True)

def ok(msg: str) -> None:
    _print(f"  \033[32m✔\033[0m  {msg}")

def info(msg: str) -> None:
    _print(f"  \033[34m→\033[0m  {msg}")

def warn(msg: str) -> None:
    _print(f"  \033[33m⚠\033[0m  {msg}")

def erro(msg: str) -> None:
    _print(f"  \033[31m✘\033[0m  {msg}")

def cabecalho(titulo: str) -> None:
    _print(f"\n\033[1m{titulo}\033[0m")
    _print("─" * len(titulo))

def abortar(msg: str) -> None:
    erro(msg)
    sys.exit(1)


# ---------------------------------------------------------------------------
# @E12-T12.3 — Verificação de pré-requisitos
# ---------------------------------------------------------------------------

def verificar_prerequisitos() -> None:
    """Valida o ambiente antes de baixar qualquer coisa."""
    cabecalho("Verificando pré-requisitos")
    falhas: list[str] = []

    # Python 3.10+
    maior, menor = sys.version_info.major, sys.version_info.minor
    if (maior, menor) < (3, 10):
        falhas.append(f"Python 3.10+ necessário (encontrado {maior}.{menor})")
    else:
        ok(f"Python {maior}.{menor}")

    # Sistema operacional
    if platform.system() != "Linux":
        falhas.append(f"Sistema Linux necessário (encontrado {platform.system()})")
    else:
        ok(f"Sistema operacional: Linux")

    # git
    if shutil.which("git") is None:
        falhas.append("git não encontrado — instale com: sudo apt install git")
    else:
        git_ver = subprocess.check_output(["git", "--version"], text=True).strip()
        ok(git_ver)

    # Acesso à internet (teste leve)
    try:
        urllib.request.urlopen("https://api.github.com", timeout=5)
        ok("Acesso à internet")
    except Exception:
        falhas.append("Sem acesso a api.github.com — necessário para baixar o pacote")

    # Acesso a portas seriais (grupo dialout)
    import grp
    usuario = os.environ.get("USER", "")
    try:
        membros_dialout = grp.getgrnam("dialout").gr_mem
        if usuario in membros_dialout:
            ok(f"Usuário '{usuario}' no grupo dialout")
        else:
            warn(f"Usuário '{usuario}' fora do grupo dialout — portas seriais podem ser inacessíveis")
            warn("  Para corrigir: sudo usermod -aG dialout $USER  (requer logout)")
    except KeyError:
        warn("Grupo 'dialout' não encontrado no sistema")

    if falhas:
        cabecalho("Pré-requisitos não atendidos")
        for f in falhas:
            erro(f)
        abortar("Corrija os itens acima e execute o instalador novamente.")

    ok("Todos os pré-requisitos atendidos")


# ---------------------------------------------------------------------------
# Resolução de URL de download
# ---------------------------------------------------------------------------

def _url_release(versao: str) -> str:
    """URL do zip de uma release específica no GitHub."""
    return (
        f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}"
        f"/releases/download/{versao}/esplab-{versao}.zip"
    )

def _url_branch(branch: str) -> str:
    """URL do zip de um branch no GitHub."""
    return (
        f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}"
        f"/archive/refs/heads/{branch}.zip"
    )

def _versao_mais_recente() -> str:
    """Consulta a GitHub Releases API e devolve a tag da última release."""
    api = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
    try:
        with urllib.request.urlopen(api, timeout=10) as resp:
            dados = json.loads(resp.read().decode())
            tag = dados.get("tag_name", "")
            if not tag:
                abortar("GitHub não retornou uma tag de release válida.")
            return tag
    except urllib.error.HTTPError as e:
        abortar(f"Erro ao consultar releases: HTTP {e.code} — {e.reason}")
    except Exception as e:
        abortar(f"Falha ao consultar releases: {e}")


def resolver_url(versao: str | None, branch: str | None) -> tuple[str, str]:
    """
    Devolve (url, rotulo) conforme os argumentos recebidos.
    Prioridade: branch > versao > latest release.
    """
    if branch:
        return _url_branch(branch), f"branch:{branch}"
    if versao:
        return _url_release(versao), versao
    # Sem branch nem versao: tenta a ultima release; se nao houver
    # nenhuma publicada, cai para o branch main (que sempre existe).
    try:
        tag = _versao_mais_recente()
        return _url_release(tag), tag
    except SystemExit:
        # _versao_mais_recente() chama abortar() (SystemExit) quando
        # nao ha release. Nesse caso, usamos o branch main.
        warn("Nenhuma release publicada — instalando do branch main.")
        return _url_branch("main"), "branch:main"


# ---------------------------------------------------------------------------
# Download e extração
# ---------------------------------------------------------------------------

def baixar_zip(url: str, destino_tmp: Path) -> Path:
    """Baixa o zip para um arquivo temporário com barra de progresso simples."""
    caminho_zip = destino_tmp / "esplab.zip"
    info(f"Baixando: {url}")

    def progresso(contagem, tamanho_bloco, tamanho_total):
        if tamanho_total > 0:
            pct = min(int(contagem * tamanho_bloco * 100 / tamanho_total), 100)
            print(f"\r     {pct}%", end="", flush=True)

    try:
        urllib.request.urlretrieve(url, caminho_zip, reporthook=progresso)
        print()  # quebra de linha após progresso
        ok(f"Download concluído: {caminho_zip.name}")
        return caminho_zip
    except urllib.error.HTTPError as e:
        abortar(f"Erro no download: HTTP {e.code} — verifique se a release existe no repositório")
    except Exception as e:
        abortar(f"Falha no download: {e}")


def extrair_zip(caminho_zip: Path, destino_tmp: Path) -> Path:
    """Extrai o zip e devolve o diretório raiz extraído."""
    info("Extraindo pacote...")
    with zipfile.ZipFile(caminho_zip, "r") as zf:
        zf.extractall(destino_tmp)

    # O zip do GitHub envolve tudo numa pasta com o nome do repo/tag
    # Precisamos encontrar a raiz real (que contém .esplab_root ou src/)
    raizes = [
        p for p in destino_tmp.iterdir()
        if p.is_dir() and p.name != "__MACOSX"
    ]
    if len(raizes) == 1:
        raiz = raizes[0]
    else:
        # Tenta encontrar quem tem src/ ou .esplab_root
        candidatos = [r for r in raizes if (r / "src").exists() or (r / SENTINEL_FILE).exists()]
        if len(candidatos) == 1:
            raiz = candidatos[0]
        else:
            abortar(f"Estrutura inesperada no zip — raízes encontradas: {[r.name for r in raizes]}")

    ok(f"Extraído em: {raiz}")
    return raiz


# ---------------------------------------------------------------------------
# @E12-T12.1 — Instalação
# ---------------------------------------------------------------------------

def instalar(dest: Path, raiz_extraida: Path) -> dict:
    """
    Copia o conteúdo do zip para dest, cria app-venv, instala dependências,
    gera script de entrada e devolve o manifesto.
    """
    cabecalho("Instalando ESP Lab")
    manifesto: dict = {
        "instalado_em": datetime.now().isoformat(),
        "destino": str(dest),
        "arquivos": [],
        "diretorios": [],
        "venv": "",
        "script_entrada": "",
    }

    # 1. Criar diretório de destino
    dest.mkdir(parents=True, exist_ok=True)
    info(f"Destino: {dest}")

    # 2. Copiar arquivos do pacote (src/, VERSION, requirements-app.txt, .esplab_root)
    itens_para_copiar = ["src", "VERSION", "requirements-app.txt", SENTINEL_FILE]
    for item in itens_para_copiar:
        origem = raiz_extraida / item
        if not origem.exists():
            warn(f"Item não encontrado no pacote: {item} — ignorado")
            continue
        destino_item = dest / item
        if origem.is_dir():
            if destino_item.exists():
                shutil.rmtree(destino_item)
            shutil.copytree(origem, destino_item)
            manifesto["diretorios"].append(str(destino_item))
            ok(f"Copiado: {item}/")
        else:
            shutil.copy2(origem, destino_item)
            manifesto["arquivos"].append(str(destino_item))
            ok(f"Copiado: {item}")

    # 3. Garantir diretórios de runtime (config/, data/, workspace/)
    for subdir in ["config", "data", "workspace"]:
        d = dest / subdir
        d.mkdir(exist_ok=True)
        manifesto["diretorios"].append(str(d))

    # 4. Criar app-venv
    venv_path = dest / "data" / "app-venv"
    info(f"Criando app-venv em {venv_path}...")
    resultado = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_path)],
        capture_output=True, text=True
    )
    if resultado.returncode != 0:
        abortar(f"Falha ao criar venv: {resultado.stderr}")
    manifesto["venv"] = str(venv_path)
    ok("app-venv criado")

    # 5. Instalar dependências no venv
    pip = venv_path / "bin" / "pip"
    req = dest / "requirements-app.txt"
    if not req.exists():
        warn("requirements-app.txt não encontrado — dependências não instaladas")
    else:
        info("Instalando dependências...")
        resultado = subprocess.run(
            [str(pip), "install", "--upgrade", "pip", "--quiet"],
            capture_output=True, text=True
        )
        resultado = subprocess.run(
            [str(pip), "install", "-r", str(req), "--quiet"],
            capture_output=True, text=True
        )
        if resultado.returncode != 0:
            abortar(f"Falha ao instalar dependências:\n{resultado.stderr}")
        ok("Dependências instaladas")

    # 6. Gerar script de entrada
    script_path = dest / ENTRY_SCRIPT
    python_venv = venv_path / "bin" / "python"
    conteudo_script = f"""#!/usr/bin/env bash
# ESP Lab — script de entrada
# Gerado automaticamente pelo instalador. Não edite manualmente.
ESPLAB_DIR="{dest}"
PYTHON="{python_venv}"
exec "$PYTHON" -m esplab "$@"
"""
    script_path.write_text(conteudo_script, encoding="utf-8")
    script_path.chmod(0o755)
    manifesto["script_entrada"] = str(script_path)
    manifesto["arquivos"].append(str(script_path))
    ok(f"Script de entrada: {script_path}")

    # 7. Adicionar src/ ao PYTHONPATH no script (para importação sem pip install -e)
    src_path = dest / "src"
    conteudo_script_completo = f"""#!/usr/bin/env bash
# ESP Lab — script de entrada
# Gerado automaticamente pelo instalador. Não edite manualmente.
ESPLAB_DIR="{dest}"
PYTHON="{python_venv}"
export PYTHONPATH="{src_path}:$PYTHONPATH"
exec "$PYTHON" -m esplab "$@"
"""
    script_path.write_text(conteudo_script_completo, encoding="utf-8")

    return manifesto


# ---------------------------------------------------------------------------
# @E12-T12.1 — Manifesto
# ---------------------------------------------------------------------------

def gravar_manifesto(manifesto: dict, dest: Path) -> None:
    """Grava o manifesto de instalação em data/install_manifest.json."""
    manifesto_path = dest / "data" / "install_manifest.json"
    manifesto_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifesto_path, "w", encoding="utf-8") as f:
        json.dump(manifesto, f, indent=2, ensure_ascii=False)
    ok(f"Manifesto gravado: {manifesto_path}")


def ler_manifesto(dest: Path) -> dict | None:
    """Lê o manifesto de uma instalação existente."""
    manifesto_path = dest / "data" / "install_manifest.json"
    if not manifesto_path.exists():
        return None
    try:
        with open(manifesto_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Validação pós-instalação
# ---------------------------------------------------------------------------

def validar_instalacao(dest: Path) -> None:
    """Verifica que os componentes críticos estão presentes após a instalação."""
    cabecalho("Validando instalação")
    falhas: list[str] = []

    checagens = [
        (dest / SENTINEL_FILE,             "Sentinela .esplab_root"),
        (dest / "VERSION",                 "Arquivo VERSION"),
        (dest / "src" / "esplab",          "Código-fonte src/esplab/"),
        (dest / "data" / "app-venv",       "app-venv"),
        (dest / "data" / "app-venv" / "bin" / "python", "Python do venv"),
        (dest / ENTRY_SCRIPT,              "Script de entrada esplab.sh"),
        (dest / "data" / "install_manifest.json", "Manifesto de instalação"),
    ]

    for caminho, rotulo in checagens:
        if caminho.exists():
            ok(rotulo)
        else:
            erro(f"Ausente: {rotulo} ({caminho})")
            falhas.append(rotulo)

    # Testa importação básica
    python = dest / "data" / "app-venv" / "bin" / "python"
    src = dest / "src"
    if python.exists() and src.exists():
        resultado = subprocess.run(
            [str(python), "-c",
             f"import sys; sys.path.insert(0, '{src}'); import esplab; print('ok')"],
            capture_output=True, text=True
        )
        if resultado.returncode == 0 and "ok" in resultado.stdout:
            ok("Importação do módulo esplab")
        else:
            falhas.append("Importação do módulo esplab falhou")
            erro(f"Importação falhou: {resultado.stderr.strip()}")

    if falhas:
        warn("Instalação incompleta — itens com falha:")
        for f in falhas:
            warn(f"  • {f}")
    else:
        ok("Instalação validada com sucesso")


# ---------------------------------------------------------------------------
# @E12-T12.2 — Desinstalador
# ---------------------------------------------------------------------------

def desinstalar(dest: Path) -> None:
    """Remove a instalação usando o manifesto como guia."""
    cabecalho("Desinstalando ESP Lab")

    manifesto = ler_manifesto(dest)
    if manifesto is None:
        warn("Manifesto não encontrado — remoção manual necessária")
        warn(f"Diretório de instalação: {dest}")
        confirmacao = input("  Remover o diretório inteiro? [s/N] ").strip().lower()
        if confirmacao == "s":
            shutil.rmtree(dest)
            ok(f"Diretório removido: {dest}")
        else:
            info("Desinstalação cancelada.")
        return

    info(f"Instalação de {manifesto.get('instalado_em', 'data desconhecida')}")
    info(f"Destino: {manifesto.get('destino', dest)}")
    print()
    confirmacao = input("  Confirma remoção completa? Dados do workspace serão perdidos. [s/N] ").strip().lower()
    if confirmacao != "s":
        info("Desinstalação cancelada.")
        return

    # Remove venv
    venv = manifesto.get("venv", "")
    if venv and Path(venv).exists():
        shutil.rmtree(venv)
        ok(f"venv removido: {venv}")

    # Remove arquivos listados no manifesto
    for arq in manifesto.get("arquivos", []):
        p = Path(arq)
        if p.exists():
            p.unlink()
            ok(f"Removido: {p.name}")

    # Remove diretórios listados (do mais profundo para o mais raso)
    diretorios = sorted(
        [Path(d) for d in manifesto.get("diretorios", [])],
        key=lambda p: len(p.parts),
        reverse=True
    )
    for d in diretorios:
        if d.exists():
            try:
                shutil.rmtree(d)
                ok(f"Diretório removido: {d.name}/")
            except Exception as e:
                warn(f"Não foi possível remover {d}: {e}")

    # Remove o diretório de destino se vazio
    if dest.exists():
        try:
            dest.rmdir()  # só remove se vazio
            ok(f"Diretório raiz removido: {dest}")
        except OSError:
            warn(f"Diretório não vazio, não removido: {dest}")
            warn("  Remova manualmente se desejar.")

    ok("Desinstalação concluída")


# ---------------------------------------------------------------------------
# Atualização
# ---------------------------------------------------------------------------

def atualizar(dest: Path, versao: str | None, branch: str | None) -> None:
    """Atualiza uma instalação existente preservando config/ e workspace/."""
    cabecalho("Atualizando ESP Lab")

    manifesto_antigo = ler_manifesto(dest)
    if manifesto_antigo is None:
        abortar(f"Instalação não encontrada em {dest} — use sem --update para instalar.")

    info(f"Instalação atual: {manifesto_antigo.get('instalado_em', 'desconhecida')}")

    url, rotulo = resolver_url(versao, branch)
    info(f"Versão alvo: {rotulo}")

    with tempfile.TemporaryDirectory(prefix="esplab_update_") as tmp:
        tmp_path = Path(tmp)
        caminho_zip = baixar_zip(url, tmp_path)
        raiz = extrair_zip(caminho_zip, tmp_path)

        # Atualiza apenas src/, VERSION e requirements-app.txt
        # Preserva config/, data/ (exceto app-venv que é recriado), workspace/
        cabecalho("Aplicando atualização")
        for item in ["src", "VERSION", "requirements-app.txt", SENTINEL_FILE]:
            origem = raiz / item
            if not origem.exists():
                warn(f"Item não encontrado no pacote: {item} — ignorado")
                continue
            destino_item = dest / item
            if origem.is_dir():
                if destino_item.exists():
                    shutil.rmtree(destino_item)
                shutil.copytree(origem, destino_item)
            else:
                shutil.copy2(origem, destino_item)
            ok(f"Atualizado: {item}")

        # Recria app-venv e reinstala dependências
        venv_path = dest / "data" / "app-venv"
        if venv_path.exists():
            shutil.rmtree(venv_path)
        info("Recriando app-venv...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
        pip = venv_path / "bin" / "pip"
        req = dest / "requirements-app.txt"
        if req.exists():
            subprocess.run([str(pip), "install", "--quiet", "-r", str(req)], check=True)
            ok("Dependências atualizadas")

        # Atualiza manifesto
        manifesto_novo = {
            "instalado_em": datetime.now().isoformat(),
            "atualizado_de": manifesto_antigo.get("instalado_em", ""),
            "destino": str(dest),
            "arquivos": manifesto_antigo.get("arquivos", []),
            "diretorios": manifesto_antigo.get("diretorios", []),
            "venv": str(venv_path),
            "script_entrada": manifesto_antigo.get("script_entrada", ""),
        }
        gravar_manifesto(manifesto_novo, dest)

    ok("Atualização concluída")
    validar_instalacao(dest)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ESP Lab — Instalador standalone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python install.py                        instala a versão mais recente
  python install.py --version v0.2.0       versão específica
  python install.py --branch main          direto do branch main
  python install.py --dest /opt/esplab    destino customizado
  python install.py --update               atualiza instalação existente
  python install.py --uninstall            remove instalação
        """
    )
    parser.add_argument("--version",   metavar="TAG",   help="versão a instalar (ex: v0.2.0)")
    parser.add_argument("--branch",    metavar="NOME",  help="branch do GitHub a instalar")
    parser.add_argument("--dest",      metavar="DIR",   help=f"diretório de instalação (padrão: {DEFAULT_DEST})")
    parser.add_argument("--update",    action="store_true", help="atualiza instalação existente")
    parser.add_argument("--uninstall", action="store_true", help="remove instalação")
    args = parser.parse_args()

    dest = Path(args.dest).expanduser().resolve() if args.dest else Path(DEFAULT_DEST).expanduser().resolve()

    _print("\n\033[1mESP Lab — Instalador\033[0m")
    _print(f"Repositório: https://github.com/{GITHUB_USER}/{GITHUB_REPO}")
    _print(f"Destino:     {dest}")

    # Modos especiais
    if args.uninstall:
        desinstalar(dest)
        return

    if args.update:
        verificar_prerequisitos()
        atualizar(dest, args.version, args.branch)
        return

    # Instalação normal
    verificar_prerequisitos()

    # Avisa se já existe instalação
    if (dest / SENTINEL_FILE).exists():
        warn(f"Instalação existente detectada em {dest}")
        confirmacao = input("  Sobrescrever? [s/N] ").strip().lower()
        if confirmacao != "s":
            info("Instalação cancelada. Use --update para atualizar.")
            return

    # Instalacao nova: avisa o que sera feito e pede confirmacao
    # explicita antes de agir (nada age sozinho). So chega aqui quem
    # nao tem instalacao existente (o bloco acima ja tratou esse caso).
    if not (dest / SENTINEL_FILE).exists():
        _print("")
        _print("O instalador vai:")
        _print(f"  - baixar o ESP Lab do GitHub (repositorio publico)")
        _print(f"  - criar um ambiente virtual isolado em {dest / 'data' / 'app-venv'}")
        _print(f"  - gerar o script de inicializacao ({ENTRY_SCRIPT})")
        _print(f"Nada fora de {dest} e modificado (exceto a regra sudoers")
        _print("opcional, se voce autorizar depois).")
        confirmacao = input("  Continuar? [s/N] ").strip().lower()
        if confirmacao != "s":
            info("Instalacao cancelada pelo usuario.")
            return

    url, rotulo = resolver_url(args.version, args.branch)
    info(f"Versão: {rotulo}")

    with tempfile.TemporaryDirectory(prefix="esplab_install_") as tmp:
        tmp_path = Path(tmp)
        caminho_zip = baixar_zip(url, tmp_path)
        raiz = extrair_zip(caminho_zip, tmp_path)
        manifesto = instalar(dest, raiz)

    gravar_manifesto(manifesto, dest)
    validar_instalacao(dest)

    cabecalho("Instalação concluída")
    _print(f"\n  Para iniciar o ESP Lab:")
    _print(f"  \033[1mbash {dest / ENTRY_SCRIPT}\033[0m\n")


if __name__ == "__main__":
    main()
