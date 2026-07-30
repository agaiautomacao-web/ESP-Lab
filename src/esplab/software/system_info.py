#!/usr/bin/env python3
"""
Deteccao do ambiente do sistema (@E2-T2.3).

Coleta as informacoes do "bloco Software" da tela inicial: SO, kernel, Python,
esptool, ESP-IDF e dependencias da aplicacao — todas com versao, sem caminhos.

Cada deteccao e isolada: uma falha vira placeholder honesto ("Nao detectado"),
nunca derruba o conjunto. Retorno (ok, dict); nunca lanca.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from ..core import errors as _errors
from ..core import paths as _paths

NOT_DETECTED = "Não detectado"

# Dependencias da aplicacao a reportar (com versao), lidas do app-venv.
APP_DEPENDENCIES = ["textual", "pyserial", "PyYAML", "rich"]

def _version_with_v(value: str) -> str:
    """
    Normaliza versao para exibicao com prefixo v.

    Exemplos:
      5.4.4   -> v5.4.4
      v5.4.4  -> v5.4.4
      vv5.4.4 -> v5.4.4
    """
    text = str(value or "").strip()
    if not text or text == NOT_DETECTED:
        return NOT_DETECTED

    while text.lower().startswith("v"):
        text = text[1:].strip()

    if not text:
        return NOT_DETECTED

    if re.match(r"^\d", text):
        return "v" + text

    return text



def _os_release() -> Dict[str, str]:
    """Le /etc/os-release; devolve dict (vazio se ausente)."""
    data: Dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.is_file():
        return data
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"')
    except Exception:
        pass
    return data


def detect_os() -> str:
    """Distribuicao + versao (ex. 'Ubuntu 24.04'). Fallback para o sistema."""
    rel = _os_release()
    name = rel.get("NAME") or platform.system() or NOT_DETECTED
    version = rel.get("VERSION_ID") or rel.get("VERSION") or ""
    return f"{name} {version}".strip()


def detect_kernel() -> str:
    """Versao do kernel."""
    return platform.release() or NOT_DETECTED


def detect_python() -> str:
    """Versao do Python que executa a aplicacao."""
    return platform.python_version() or NOT_DETECTED


def detect_esptool_for(tag: str) -> str:
    """
    Versao do esptool no python_env isolado de UMA instalacao especifica
    (identificada por tag, ex. 'v4.4.8'). Tenta pip (ESP-IDF >=5.x) e cai
    para o script vendorizado em components/esptool_py (<5.x) se
    necessario. Nunca lanca; usada por Software > Estado do ambiente
    para mostrar o esptool de CADA slot, nao so o ativo.
    """
    if not tag:
        return NOT_DETECTED

    idf_p = _paths.get_paths().idf_for(tag)
    env_dir = _paths.get_paths().python_env_for(tag)
    if env_dir is None:
        return "ambiente incompleto: esptool ausente"

    py = env_dir / "bin" / "python"
    if not py.is_file():
        return "ambiente incompleto: esptool ausente"

    # Tentativa 1: esptool como pacote pip no venv isolado (ESP-IDF >=5.x).
    ok1, texto1 = _esptool_version_via([str(py), "-m", "esptool", "version"])
    if ok1:
        return texto1

    # Tentativa 2: ESP-IDF <5.x (ex. 4.4) nao instala esptool via pip —
    # vem embutido como submodulo dentro do proprio clone (confirmado
    # no requirements.txt da 4.4.8: "esptool requirements (see
    # components/esptool_py/esptool/setup.py)"). Mesmo argumento
    # "version", so muda o alvo: script vendorizado, nao modulo instalado.
    vendorizado = idf_p / "components" / "esptool_py" / "esptool" / "esptool.py"
    if vendorizado.is_file():
        ok2, texto2 = _esptool_version_via([str(py), str(vendorizado), "version"])
        if ok2:
            return texto2

    return "ambiente incompleto: esptool ausente"


def detect_esptool() -> str:
    """
    Versao do esptool da ESP-IDF ATIVA. Atalho para
    detect_esptool_for(tag_ativa) -- mantido por compatibilidade e para
    uso pontual quando so a ativa importa.
    """
    try:
        from . import idf_manager as _idf_mgr
        ok, ativo = _idf_mgr.active_tag()
        if not ok or not ativo:
            return NOT_DETECTED
    except Exception:
        return NOT_DETECTED
    return detect_esptool_for(ativo)


def _esptool_version_via(cmd: list) -> tuple:
    """Roda um comando de versao do esptool e devolve (True, versao) ou
    (False, ""). Nunca lanca — falha vira (False, "") para o chamador
    tentar o proximo caminho."""
    res = _errors.guard(
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=15),
        context="versao do esptool",
    )
    ok, proc = res
    if not ok or proc.returncode != 0:
        return (False, "")
    text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if not text:
        return (False, "")
    m = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", text)
    return (True, m.group(1) if m else (text.splitlines()[0] or ""))

def detect_idf() -> str:
    """
    Versao do ESP-IDF ATIVA, normalizada para exibicao com prefixo v.
    """
    try:
        from . import idf_manager as _idf_mgr

        ok, ativo = _idf_mgr.active_tag()
        return _version_with_v(ativo) if (ok and ativo) else NOT_DETECTED
    except Exception:
        return NOT_DETECTED

def detect_editor() -> str:
    """
    Editor de terminal que o ESP Lab usaria (o primeiro por prioridade,
    mesmo que 'Programacao > Arquivos do projeto > Abrir arquivo no
    editor' escolheria) + versao + origem (sistema ou ambiente ESP
    Lab — este ultimo hoje nunca ocorre na pratica, ja que nenhum
    editor e empacotado ainda; fica pronto para quando essa melhoria
    futura for implementada). Import local: evita import de topo entre
    pacotes irmaos (software -> programming).
    'Nao detectado' se nenhum editor de terminal compativel for achado.
    """
    try:
        from ..programming import external_editor as _editor
        ok, info = _editor.active_editor_info()
        if not ok or not info:
            return NOT_DETECTED
        return f"{info['label']} {info['version']} ({info['origin']})"
    except Exception:
        return NOT_DETECTED


def _venv_python() -> Path:
    """Interpretador do app-venv, se existir; senao o Python atual."""
    venv_py = _paths.get_paths().app_venv / "bin" / "python"
    return venv_py if venv_py.is_file() else Path(sys.executable)


def detect_dependencies() -> List[Dict[str, str]]:
    """
    Versoes das dependencias da aplicacao, lidas do app-venv.
    Retorna lista de {name, version} com placeholder se nao instalada.
    """
    py = str(_venv_python())
    result: List[Dict[str, str]] = []
    # usa importlib.metadata dentro do interpretador alvo
    code = (
        "import importlib.metadata as m, sys\n"
        "for n in sys.argv[1:]:\n"
        "    try: print(n + '==' + m.version(n))\n"
        "    except Exception: print(n + '==' + 'NAODETECTADO')\n"
    )
    res = _errors.guard(
        lambda: subprocess.run([py, "-c", code, *APP_DEPENDENCIES],
                               capture_output=True, text=True, timeout=30),
        context="versoes das dependencias",
    )
    ok, proc = res
    if not ok or proc.returncode != 0:
        return [{"name": n, "version": NOT_DETECTED} for n in APP_DEPENDENCIES]
    for line in (proc.stdout or "").splitlines():
        if "==" in line:
            name, ver = line.split("==", 1)
            result.append({"name": name, "version": NOT_DETECTED if ver == "NAODETECTADO" else ver})
    return result or [{"name": n, "version": NOT_DETECTED} for n in APP_DEPENDENCIES]


def collect() -> tuple:
    """
    Reune o bloco SOFTWARE da tela inicial (boot: relance rapido).
    Retorna (True, dict). esptool e dependencias NAO entram aqui —
    viraram parte de Software > Estado do ambiente (raio-X completo,
    sob demanda), nao do boot. Menos subprocessos = boot mais rapido.
    """
    info = {
        "os": detect_os(),
        "kernel": detect_kernel(),
        "python": detect_python(),
        "esp_idf": detect_idf(),
        "editor": detect_editor(),
    }
    return (True, info)


__all__ = [
    "collect", "detect_os", "detect_kernel", "detect_python",
    "detect_esptool", "detect_esptool_for", "detect_idf", "detect_editor",
    "detect_dependencies", "NOT_DETECTED", "APP_DEPENDENCIES",
]
