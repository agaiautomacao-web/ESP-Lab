#!/usr/bin/env python3
"""
Módulo de resolução de caminhos do ESP Lab.

Fronteira única de localização no disco (PROJECT.md §4):
nenhum outro módulo monta caminho próprio — todos pedem aqui.

Dois domínios de caminho, deliberadamente separados:

  1. app_root  -> raiz da APLICAÇÃO (código). Pode nascer em qualquer lugar;
                  é descoberta em runtime ou informada por ESPLAB_BASE.
  2. XDG       -> diretórios do USUÁRIO (config, dados, logs), seguindo
                  XDG_CONFIG_HOME / XDG_DATA_HOME quando definidos.

Artefatos pesados (venvs e ESP-IDF, um por versão) ficam sob os dados XDG,
não sob a pasta da aplicação — mantém a raiz leve e portável.

Convenção: identificadores em inglês, mensagens em português.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Union

PathLike = Union[str, Path]

# Nome do projeto — usado para compor diretórios XDG e variáveis de ambiente.
APP_NAME = "esplab"

# Arquivo-sentinela que marca a raiz da aplicação de forma explícita e única.
# Detectar por um marcador nosso é mais seguro do que inferir por nomes de
# pastas, que poderiam coincidir com outros projetos.
ROOT_SENTINEL = ".esplab_root"

# Variável de ambiente que, se definida, sobrepõe a auto-detecção da raiz.
ENV_BASE = "ESPLAB_BASE"


class ESPLabPaths:
    """
    Gerenciador central de caminhos do ESP Lab.

    - Fonte única de verdade para paths.
    - Resolve a raiz da aplicação e os diretórios XDG do usuário.
    - Entrega caminhos derivados por composição (nunca constantes fixas).
    - Cria diretórios sob demanda (ensure_dirs).
    """

    def __init__(self, base: PathLike | None = None):
        """
        base:
            - Se informado  -> usado como raiz da aplicação.
            - Senão:
                1) variável de ambiente ESPLAB_BASE
                2) auto-detecção pelo arquivo-sentinela
        """
        if base is None:
            env = os.environ.get(ENV_BASE)
            base = env if env else get_app_root()

        self._app_root: Path = Path(base).expanduser().resolve()

    # ==========================================================
    # DOMÍNIO 1 — RAIZ DA APLICAÇÃO (código)
    # ==========================================================

    @property
    def app_root(self) -> Path:
        """Raiz absoluta da aplicação (onde o código vive)."""
        return self._app_root

    # ==========================================================
    # DOMÍNIO 2 — XDG (usuário): config, dados, logs
    # ==========================================================

    @property
    def config_home(self) -> Path:
        """
        Base de configuracao do usuario.
        Default: app_root/config (isolamento total dentro do projeto).
        Respeita XDG_CONFIG_HOME apenas se explicitamente definido.
        """
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return (Path(xdg).expanduser() / APP_NAME).resolve()
        return (self._app_root / "config").resolve()

    @property
    def data_home(self) -> Path:
        """
        Base de dados do usuario.
        Default: app_root/data (isolamento total dentro do projeto).
        Respeita XDG_DATA_HOME apenas se explicitamente definido.
        """
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            return (Path(xdg).expanduser() / APP_NAME).resolve()
        return (self._app_root / "data").resolve()

    @property
    def logs(self) -> Path:
        """Logs da aplicação e do monitor (sob os dados do usuário)."""
        return self.data_home / "logs"

    @property
    def monitor_logs(self) -> Path:
        """
        Logs do monitor serial (@E10), um arquivo por porta.
        Subdiretório próprio para não se misturar ao log da aplicação.
        Logs antigos gravados direto em `logs/` continuam onde estão —
        a aplicação não move dado do usuário.
        """
        return self.logs / "monitor"

    @property
    def run_dir(self) -> Path:
        """
        Estado de execução (sockets Unix do monitor, um por porta).
        Efêmero por natureza: some quando os daemons encerram.
        """
        return self.data_home / "run"

    # ==========================================================
    # SUBCAMINHOS DE CONFIGURAÇÃO (config_home)
    # ==========================================================

    @property
    def boards_db(self) -> Path:
        """Banco de placas (JSON), manipulado via key_json_manager."""
        return self.config_home / "boards_db.json"

    @property
    def compat_matrix(self) -> Path:
        """Matriz de compatibilidade ESP-IDF x dependências (YAML)."""
        return self.config_home / "compat_matrix.yml"

    @property
    def app_config(self) -> Path:
        """Configurações gerais da aplicação (YAML)."""
        return self.config_home / "config.yml"

    @property
    def editor_config(self) -> Path:
        """Configuração do editor de terminal preferido."""
        return self.config_home / "editor_config.json"

    @property
    def install_manifest(self) -> Path:
        """Manifesto do instalador (tudo que foi tocado)."""
        return self.config_home / "install_manifest.json"

    @property
    def workspace_config(self) -> Path:
        """Preferencia global do diretorio de workspace (fora dos projetos)."""
        return self.config_home / "workspace.json"

    @property
    def monitor_config(self) -> Path:
        """Preferencias globais de leitura do monitor serial (@E10)."""
        return self.config_home / "monitor.json"

    # ==========================================================
    # SUBCAMINHOS DE DADOS PESADOS (data_home)
    # ==========================================================

    @property
    def envs_root(self) -> Path:
        """Raiz dos ambientes virtuais — um venv por versão de ESP-IDF."""
        return self.data_home / "envs"

    def venv_for(self, idf_version: str) -> Path:
        """Caminho do venv de uma versão específica de ESP-IDF."""
        return self.envs_root / f"idf-{idf_version}"

    @property
    def idf_root(self) -> Path:
        """Raiz das instalações de ESP-IDF — uma por versão."""
        return self.data_home / "esp-idf"

    @property
    def app_venv(self) -> Path:
        """Venv da propria aplicacao ESP Lab (dependencias da ferramenta)."""
        return self.data_home / "app-venv"

    def idf_for(self, idf_version: str) -> Path:
        """Caminho da instalação de uma versão específica de ESP-IDF."""
        return self.idf_root / idf_version

    @property
    def idf_tools_root(self) -> Path:
        """
        Raiz das ferramentas por-versão da ESP-IDF (python_env, toolchains),
        criada pelo install.sh oficial da Espressif — não pelo venv_manager.
        """
        return self.data_home / "idf-tools"

    def python_env_for(self, idf_version: str) -> Path | None:
        """
        Caminho do python_env isolado de uma versão de ESP-IDF
        (idf-tools/python_env/idf<major.minor>_py*_env). Retorna None se a
        versão for inválida ou o ambiente não existir — nunca lança,
        nunca inventa caminho.
        """
        m = re.match(r"^v?(\d+)\.(\d+)", idf_version or "")
        if not m:
            return None
        root = self.idf_tools_root / "python_env"
        if not root.is_dir():
            return None
        matches = sorted(root.glob(f"idf{m.group(1)}.{m.group(2)}_py*_env"))
        return matches[0] if matches else None

    # ==========================================================
    # WORKSPACE (projetos do usuário)
    # ==========================================================

    @property
    def workspace_default(self) -> Path:
        """
        Pasta default de workspace de projetos.
        Dentro do app_root para manter isolamento total.
        O usuario pode redefinir; este e o ponto de partida.
        """
        return (self._app_root / "workspace").resolve()

    @property
    def backups(self) -> Path:
        """Diretorio de backups da aplicacao (sob app_root, como o
        workspace). Criado sob demanda pelos proprios mecanismos."""
        return (self._app_root / "backups").resolve()

    @property
    def workbench(self) -> Path:
        """Area de manutencao/scripts (dev): patches e arquivos mortos,
        sob app_root. Criada sob demanda; pode nao existir em producao."""
        return (self._app_root / "_workbench").resolve()

    # ==========================================================
    # UTILITÁRIOS
    # ==========================================================

    def ensure_dirs(self) -> "ESPLabPaths":
        """
        Garante que os diretórios essenciais existam.
        Idempotente: seguro para rodar múltiplas vezes.
        Cria apenas diretórios — arquivos (JSON/YAML) são criados pelos
        seus próprios gerenciadores, com escrita atômica.
        """
        dirs = [
            self.app_root,
            self.config_home,
            self.data_home,
            self.logs,
            self.monitor_logs,
            self.run_dir,
            self.envs_root,
            self.idf_root,
            self.workspace_default,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        return self

    @staticmethod
    def shorten(path: PathLike) -> str:
        """
        Converte um caminho absoluto sob o HOME em forma curta para UI/log:
            /home/usuario/.config/esplab/...  ->  /HOME/.config/esplab/...
        """
        try:
            p = Path(path).expanduser().resolve()
            home = Path.home().resolve()
            s, h = str(p), str(home)
            if s.startswith(h):
                return "/HOME" + s[len(h):]
            return s
        except Exception:
            return str(path)

    def to_dict(self, summarized: bool = True) -> Dict[str, str]:
        """
        Exporta os caminhos principais.
        summarized=True  -> forma curta (/HOME...), ideal para a tela inicial.
        summarized=False -> caminho absoluto real.
        """
        data: Dict[str, Path] = {
            "app_root": self.app_root,
            "config_home": self.config_home,
            "data_home": self.data_home,
            "logs": self.logs,
            "boards_db": self.boards_db,
            "compat_matrix": self.compat_matrix,
            "workspace_config": self.workspace_config,
            "envs_root": self.envs_root,
            "idf_root": self.idf_root,
            "workspace_default": self.workspace_default,
            "backups": self.backups,
            "workbench": self.workbench,
        }
        if summarized:
            return {k: self.shorten(v) for k, v in data.items()}
        return {k: str(v) for k, v in data.items()}


# ==========================================================
# DETECÇÃO DA RAIZ DA APLICAÇÃO
# ==========================================================

def find_candidate_roots(start: Path) -> List[Path]:
    """
    Sobe a árvore de diretórios a partir de `start` procurando o
    arquivo-sentinela que marca a raiz da aplicação.
    """
    candidates: List[Path] = []
    for parent in [start, *start.parents]:
        if (parent / ROOT_SENTINEL).is_file():
            candidates.append(parent)
    return candidates


def get_app_root() -> Path:
    """
    Resolve a raiz REAL da aplicação.

    Estratégia: a partir do arquivo atual, sobe diretórios até encontrar o
    arquivo-sentinela ROOT_SENTINEL. Erro explícito se nenhuma ou múltiplas
    raízes forem encontradas (ambiguidade não é tolerada).
    """
    current = Path(__file__).resolve()
    candidates = find_candidate_roots(current)

    if not candidates:
        raise RuntimeError(
            "Raiz da aplicação não encontrada: "
            f"arquivo-sentinela '{ROOT_SENTINEL}' ausente na árvore de "
            f"diretórios a partir de {current}."
        )
    if len(candidates) > 1:
        raise RuntimeError(
            f"Múltiplas raízes detectadas ({len(candidates)}): {candidates}. "
            "A estrutura deve ter um único arquivo-sentinela."
        )
    return candidates[0]


# ==========================================================
# FACTORY
# ==========================================================

def get_paths(base: PathLike | None = None) -> ESPLabPaths:
    """
    Retorna uma instância pronta para uso, com os diretórios já criados.
    """
    return ESPLabPaths(base).ensure_dirs()


__all__ = [
    "ESPLabPaths",
    "get_paths",
    "get_app_root",
    "find_candidate_roots",
    "PathLike",
    "APP_NAME",
    "ROOT_SENTINEL",
    "ENV_BASE",
]
