#!/usr/bin/env python3
"""
Gestao de bibliotecas do projeto (@E8-T8.3 / @E8-T8.4).

Fonte unica de verdade: o manifesto 'main/idf_component.yml' — o mesmo
arquivo que o IDF Component Manager le. Nada e duplicado em
project_config.json (decisao de Antonio, 2026-07-09; mesmo principio de
fonte unica do Adendo 6, que pos sdkconfig.defaults no lugar de
project_config para os campos de build). Ver adendo no PROJECT.md.

Esta camada NAO baixa componente nem toca 'managed_components/' ou
'dependencies.lock' — esses sao gerados e apagados pelo proprio Component
Manager, e a documentacao oficial da Espressif diz explicitamente que o
usuario nao deve modifica-los. O download acontece no 'idf.py reconfigure'
disparado por builder.needs_reconfigure() antes do build.

Regras de fronteira (PROJECT.md §2, item 1):
  - Manifesto ilegivel NUNCA e sobrescrito: a operacao falha e avisa.
  - Entrada em formato dict (dependencia de Git, override_path, rules...)
    e preservada; so o campo 'version' e alterado.
  - 'idf' e chave RESERVADA dentro de 'dependencies' — nao e biblioteca,
    e o requisito de versao do proprio ESP-IDF. Nao removivel, nao
    travavel (mesmo espirito da chave 'default' do boards_db, §6.5).

@E8-T8.4 — Lock de versao:
  lock_lib  : trava uma biblioteca numa versao exata (ex. '1.2.3').
              Recusa '*', ranges ('>=', '~>', '^') e strings vazias.
  unlock_lib: remove o lock, volta para '*' (qualquer versao).

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core import storage as _storage

Result = Tuple[bool, Any]

MANIFEST_FILENAME = "idf_component.yml"

# Componente que hospeda o manifesto do projeto (padrao ESP-IDF).
MAIN_COMPONENT = "main"

# Chaves de 'dependencies' que nao sao bibliotecas do usuario.
RESERVED_DEPS = ("idf",)

# Formato valido: 'namespace/nome' ou 'nome', alfanumerico + hifens/underscores.
_RE_LIB_NAME = re.compile(r'^[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)?$')

# Versao exata: apenas digitos e pontos (ex. '1.2.3', '0.10.1').
_RE_EXACT_VERSION = re.compile(r'^\d+(\.\d+)*$')

# Caracteres aceitos numa restricao de versao (exata, range ou wildcard).
_RE_VERSION_SPEC = re.compile(r'^[0-9a-zA-Z.,*^~<>=!+\- ]+$')

# Marcadores de range que indicam versao NAO exata.
_RANGE_MARKERS = ("*", ">=", "<=", ">", "<", "~>", "^", "~")


# ==========================================================
# Manifesto — leitura, escrita e helpers
# ==========================================================

def _manifest_path(project_dir: Path) -> Path:
    """
    O Component Manager do ESP-IDF exige o manifesto na raiz do
    COMPONENTE, nao do projeto. Para o componente 'main' (padrao de todo
    projeto ESP-IDF deste app), isso e 'main/idf_component.yml'.
    """
    return project_dir / MAIN_COMPONENT / MANIFEST_FILENAME


def _load_manifest(project_dir: Path) -> Result:
    """
    Carrega o manifesto do projeto.

    Distingue tres situacoes, deliberadamente:
      - arquivo ausente  -> (True, estrutura minima vazia)
      - arquivo vazio    -> (True, estrutura minima vazia)
      - arquivo ilegivel -> (False, motivo)  <- NUNCA sobrescreve

    Absorver um manifesto quebrado como "vazio" e depois grava-lo de volta
    apagaria as chaves de topo do usuario (version, description, url,
    repository, targets, examples) sem aviso. Ver PROJECT.md §2, item 1.
    """
    path = _manifest_path(project_dir)
    if not path.is_file():
        return (True, {"dependencies": {}})

    ok, data = _storage.read_yaml(path)
    if not ok:
        return (False, "manifesto '{}' ilegivel: {}. Corrija ou remova o "
                       "arquivo a mao — a aplicacao nao o sobrescreve"
                       .format(path, data))
    if data is None:
        return (True, {"dependencies": {}})
    if not isinstance(data, dict):
        return (False, "manifesto '{}' tem formato invalido: esperado um "
                       "mapa YAML no topo".format(path))

    deps = data.get("dependencies")
    if deps is None:
        data["dependencies"] = {}
    elif not isinstance(deps, dict):
        return (False, "campo 'dependencies' do manifesto '{}' tem formato "
                       "invalido: esperado um mapa".format(path))
    return (True, data)


def _save_manifest(project_dir: Path, manifest: Dict[str, Any]) -> Result:
    """Grava o manifesto atomicamente. Cria 'main/' se necessario."""
    path = _manifest_path(project_dir)
    if not path.parent.is_dir():
        return (False, "componente '{}' nao existe no projeto; "
                       "estrutura ESP-IDF invalida".format(MAIN_COMPONENT))
    return _storage.atomic_write_yaml(path, manifest)


def _get_version_str(entry: Any) -> str:
    """Extrai string de versao de uma entrada do manifesto (str ou dict)."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("version", "*"))
    return "*"


def _set_version(entry: Any, version: str) -> Any:
    """
    Devolve a entrada com a versao trocada, PRESERVANDO a forma original.

    Entrada em dict carrega campos que nao sao versao ('git', 'path',
    'override_path', 'public', 'rules', 'registry_url', 'pre_release').
    Gravar uma string pura no lugar apagaria todos eles — uma dependencia
    de repositorio Git viraria uma busca no Registry por um componente que
    nao existe la.
    """
    if isinstance(entry, dict):
        novo = dict(entry)
        novo["version"] = version
        return novo
    return version


def _entry_source(entry: Any) -> str:
    """Origem da dependencia: 'registry' | 'git' | 'local'."""
    if isinstance(entry, dict):
        if entry.get("git"):
            return "git"
        if entry.get("path") or entry.get("override_path"):
            return "local"
    return "registry"


def _is_locked(version: str) -> bool:
    """Retorna True se a versao e um lock exato (sem ranges ou wildcards)."""
    return bool(_RE_EXACT_VERSION.match(str(version).strip()))


# ==========================================================
# Validacao de fronteira
# ==========================================================

def _validate_name(name: str) -> Optional[str]:
    """Valida nome de componente. Retorna motivo de erro ou None se valido."""
    if not name or not name.strip():
        return "nome de biblioteca vazio"
    if not _RE_LIB_NAME.match(name.strip()):
        return ("nome invalido '{}': use apenas letras, numeros, "
                "hifens e underscores (formato: 'namespace/nome' ou 'nome')"
                .format(name))
    return None


def _validate_not_reserved(name: str, acao: str) -> Optional[str]:
    """
    'idf' vive dentro de 'dependencies' mas nao e biblioteca: e o requisito
    de versao do proprio ESP-IDF. Nao pode ser adicionado, removido nem
    travado por este menu.
    """
    if name.strip().lower() in RESERVED_DEPS:
        return ("'{}' nao e uma biblioteca: e o requisito de versao do "
                "proprio ESP-IDF, declarado no manifesto. Nao pode ser {}"
                .format(name, acao))
    return None


def _validate_version_spec(version: str) -> Optional[str]:
    """
    Valida uma restricao de versao para add_lib (@E8-T8.3).
    Aceita '*', versoes exatas ('1.2.3') e ranges ('>=1.0.0', '~2.0.0').
    Recusa texto arbitrario ('banana'), que so falharia la no build.
    Validacao offline, sem consulta ao Registry (PROJECT.md §5.9).
    """
    v = (version or "").strip()
    if not v:
        return "versao vazia; use '*' para qualquer versao"
    if v == "*":
        return None
    if not _RE_VERSION_SPEC.match(v):
        return ("versao '{}' contem caracteres invalidos".format(v))
    if not any(c.isdigit() for c in v):
        return ("versao '{}' invalida: informe um numero (ex. '1.2.3', "
                "'>=1.0.0', '~2.0.0') ou '*' para qualquer versao".format(v))
    return None



def _validate_git_url(url: str) -> Optional[str]:
    """
    Valida URL Git para dependencia do Component Manager.

    Validacao offline: nao clona, nao acessa rede, nao consulta GitHub.
    """
    u = (url or "").strip()
    if not u:
        return "url Git vazia"
    if any(c.isspace() for c in u):
        return "url Git invalida: nao use espacos"
    if not (
        u.startswith("https://")
        or u.startswith("http://")
        or u.startswith("ssh://")
        or u.startswith("git@")
    ):
        return ("url Git invalida '{}': use https://, http://, ssh:// "
                "ou git@".format(url))
    return None


def _validate_git_ref(ref: str) -> Optional[str]:
    """
    Valida tag/branch/commit informado para dependencia Git.

    Ao contrario de versao de Registry, Git pode usar 'main', 'v1.2.3',
    'feature/x' ou hash de commit.
    """
    r = (ref or "").strip()
    if not r:
        return "referencia Git vazia"
    if ".." in r:
        return "referencia Git invalida: nao use '..'"
    if r.startswith("/") or r.endswith("/"):
        return "referencia Git invalida: nao comece/termine com '/'"
    if not re.match(r'^[0-9a-zA-Z._/\-+]+$', r):
        return ("referencia Git '{}' contem caracteres invalidos".format(ref))
    return None


def _validate_component_path(path_value: str) -> Optional[str]:
    """
    Valida caminho local usado no campo 'path' do manifesto.

    Primeira versao: aceita apenas caminho relativo ao manifesto
    main/idf_component.yml, por exemplo '../components/minha_lib'.
    """
    p = (path_value or "").strip()
    if not p:
        return "path vazio"
    if "\x00" in p or "\n" in p or "\r" in p:
        return "path invalido: contem caractere de controle"
    if Path(p).is_absolute():
        return ("path '{}' invalido: use caminho relativo ao manifesto, "
                "ex. '../components/minha_lib'".format(path_value))
    if p.startswith("~"):
        return ("path '{}' invalido: use caminho relativo ao manifesto, "
                "nao '~'".format(path_value))
    return None

def _validate_exact_version(version: str) -> Optional[str]:
    """
    Valida versao exata para lock (@E8-T8.4).
    Aceita apenas 'X', 'X.Y', 'X.Y.Z' (somente digitos e pontos).
    Recusa '*', ranges, strings vazias.
    """
    v = (version or "").strip()
    if not v:
        return "versao vazia; informe uma versao exata (ex. '1.2.3')"
    for marker in _RANGE_MARKERS:
        if marker in v:
            return ("versao '{}' contem '{}' — lock requer versao exata "
                    "(ex. '1.2.3'), sem ranges ou wildcards".format(v, marker))
    if not _RE_EXACT_VERSION.match(v):
        return ("versao '{}' invalida para lock — use apenas digitos e pontos "
                "(ex. '1.2.3')".format(v))
    return None


def _resolve_root(project_dir: str | Path) -> Result:
    root = Path(project_dir).expanduser().resolve()
    if not root.is_dir():
        return (False, "pasta de projeto inexistente: '{}'".format(root))
    return (True, root)


# ==========================================================
# API PUBLICA — list / add / remove
# ==========================================================

def list_libs(project_dir: str | Path) -> Result:
    """
    Lista as bibliotecas do usuario registradas no manifesto.
    As chaves reservadas (RESERVED_DEPS) NAO entram na lista — para o
    requisito de ESP-IDF, use get_idf_requirement().

    Retorna (True, lista), cada item {name, version, locked, source}.
    """
    ok, root = _resolve_root(project_dir)
    if not ok:
        return (False, root)
    ok2, manifest = _load_manifest(root)
    if not ok2:
        return (False, manifest)

    libs: List[Dict[str, Any]] = []
    for nome, entrada in manifest["dependencies"].items():
        if str(nome).lower() in RESERVED_DEPS:
            continue
        versao = _get_version_str(entrada)
        item: Dict[str, Any] = {
            "name":    nome,
            "version": versao,
            "locked":  _is_locked(versao),
            "source":  _entry_source(entrada),
        }

        # Para a UI do Gerenciador de Bibliotecas: expor detalhes
        # relevantes de dependencias em dict sem alterar o manifesto.
        if isinstance(entrada, dict):
            for chave in (
                "git",
                "path",
                "override_path",
                "registry_url",
                "public",
            ):
                if chave in entrada:
                    item[chave] = entrada.get(chave)

        libs.append(item)
    return (True, libs)


def get_idf_requirement(project_dir: str | Path) -> Result:
    """
    Retorna (True, str) com o requisito de versao do ESP-IDF declarado no
    manifesto (ex. '>=5.0'), ou (True, None) se nao houver.
    Somente leitura — este menu nao edita o requisito.
    """
    ok, root = _resolve_root(project_dir)
    if not ok:
        return (False, root)
    ok2, manifest = _load_manifest(root)
    if not ok2:
        return (False, manifest)
    entrada = manifest["dependencies"].get("idf")
    if entrada is None:
        return (True, None)
    return (True, _get_version_str(entrada))


def add_lib(project_dir: str | Path,
            name: str, version: str = "*") -> Result:
    """
    Adiciona biblioteca ao manifesto 'main/idf_component.yml'.

    name   : 'namespace/componente' ou 'componente'.
    version: restricao de versao ('*', '1.2.3', '>=1.0.0', '~2.0.0').

    O download acontece no proximo 'idf.py reconfigure' — disparado
    automaticamente pelo builder quando detecta o manifesto mais novo que
    o build. Ver builder.needs_reconfigure().
    """
    err = _validate_name(name)
    if err:
        return (False, err)
    name = name.strip()

    err = _validate_not_reserved(name, "adicionada")
    if err:
        return (False, err)

    # Vazio ou so espaco significa "qualquer versao" — mesma leitura do
    # menu ("Enter = '*'"). Normaliza antes de validar, senao "" e "  "
    # tomariam caminhos diferentes.
    version = (version or "").strip() or "*"
    err = _validate_version_spec(version)
    if err:
        return (False, err)

    ok, root = _resolve_root(project_dir)
    if not ok:
        return (False, root)

    manifesto_existia = _manifest_path(root).is_file()
    ok2, manifest = _load_manifest(root)
    if not ok2:
        return (False, manifest)

    if name in manifest["dependencies"]:
        return (False, "biblioteca '{}' ja esta no projeto".format(name))

    manifest["dependencies"][name] = version
    ok3, res = _save_manifest(root, manifest)
    if not ok3:
        return (False, "erro ao gravar manifesto: {}".format(res))

    return (True, {
        "name":             name,
        "version":          version,
        "manifest_created": not manifesto_existia,
        "manifest_path":    str(_manifest_path(root)),
        "message": "biblioteca '{}' adicionada".format(name),
    })



def add_git_lib(project_dir: str | Path,
                name: str,
                git_url: str,
                version: str | None = None,
                path: str | None = None) -> Result:
    """
    Adiciona dependencia Git ao manifesto 'main/idf_component.yml'.

    Exemplo gerado:
      dependencies:
        minha_lib:
          git: "https://github.com/autor/minha_lib.git"
          version: "v1.2.3"

    Se 'path' for informado, ele aponta para uma subpasta do repositorio:
      dependencies:
        button:
          git: "https://github.com/espressif/esp-iot-solution.git"
          path: "components/button"
          version: "v1.0.0"

    Esta funcao NAO clona, NAO baixa e NAO roda idf.py.
    """
    err = _validate_name(name)
    if err:
        return (False, err)
    name = name.strip()

    err = _validate_not_reserved(name, "adicionada")
    if err:
        return (False, err)

    git_url = (git_url or "").strip()
    err = _validate_git_url(git_url)
    if err:
        return (False, err)

    version_norm = (version or "").strip()
    if version_norm:
        err = _validate_git_ref(version_norm)
        if err:
            return (False, err)

    path_norm = (path or "").strip()
    if path_norm:
        err = _validate_component_path(path_norm)
        if err:
            return (False, err)

    ok, root = _resolve_root(project_dir)
    if not ok:
        return (False, root)

    manifesto_existia = _manifest_path(root).is_file()
    ok2, manifest = _load_manifest(root)
    if not ok2:
        return (False, manifest)

    if name in manifest["dependencies"]:
        return (False, "biblioteca '{}' ja esta no projeto".format(name))

    entry: Dict[str, Any] = {
        "git": git_url,
    }
    if path_norm:
        entry["path"] = path_norm
    if version_norm:
        entry["version"] = version_norm

    manifest["dependencies"][name] = entry
    ok3, res = _save_manifest(root, manifest)
    if not ok3:
        return (False, "erro ao gravar manifesto: {}".format(res))

    return (True, {
        "name":             name,
        "source":           "git",
        "git":              git_url,
        "path":             path_norm or None,
        "version":          version_norm or None,
        "manifest_created": not manifesto_existia,
        "manifest_path":    str(_manifest_path(root)),
        "message": "biblioteca Git '{}' adicionada".format(name),
    })


def add_path_lib(project_dir: str | Path,
                 name: str,
                 path_value: str) -> Result:
    """
    Adiciona dependencia local via campo 'path' no manifesto.

    Exemplo gerado:
      dependencies:
        minha_lib:
          path: "../components/minha_lib"

    Esta funcao NAO copia arquivos, NAO cria components/ e NAO roda idf.py.
    """
    err = _validate_name(name)
    if err:
        return (False, err)
    name = name.strip()

    err = _validate_not_reserved(name, "adicionada")
    if err:
        return (False, err)

    path_norm = (path_value or "").strip()
    err = _validate_component_path(path_norm)
    if err:
        return (False, err)

    ok, root = _resolve_root(project_dir)
    if not ok:
        return (False, root)

    manifesto_existia = _manifest_path(root).is_file()
    ok2, manifest = _load_manifest(root)
    if not ok2:
        return (False, manifest)

    if name in manifest["dependencies"]:
        return (False, "biblioteca '{}' ja esta no projeto".format(name))

    manifest["dependencies"][name] = {
        "path": path_norm,
    }
    ok3, res = _save_manifest(root, manifest)
    if not ok3:
        return (False, "erro ao gravar manifesto: {}".format(res))

    return (True, {
        "name":             name,
        "source":           "local",
        "path":             path_norm,
        "manifest_created": not manifesto_existia,
        "manifest_path":    str(_manifest_path(root)),
        "message": "biblioteca local '{}' adicionada".format(name),
    })


def remove_lib(project_dir: str | Path, name: str) -> Result:
    """
    Remove a biblioteca do manifesto.

    NAO apaga arquivos em disco: 'managed_components/' e
    'dependencies.lock' sao gerenciados pelo Component Manager, que remove
    sozinho o componente nao usado no proximo reconfigure. A documentacao
    oficial da Espressif diz que esses caminhos nao devem ser modificados
    pelo usuario.
    """
    err = _validate_name(name)
    if err:
        return (False, err)
    name = name.strip()

    err = _validate_not_reserved(name, "removida")
    if err:
        return (False, err)

    ok, root = _resolve_root(project_dir)
    if not ok:
        return (False, root)

    ok2, manifest = _load_manifest(root)
    if not ok2:
        return (False, manifest)

    if name not in manifest["dependencies"]:
        return (False, "biblioteca '{}' nao encontrada no projeto".format(name))

    del manifest["dependencies"][name]
    ok3, res = _save_manifest(root, manifest)
    if not ok3:
        return (False, "erro ao gravar manifesto: {}".format(res))

    return (True, {
        "name": name,
        "message": "biblioteca '{}' removida do manifesto".format(name),
    })


# ==========================================================
# @E8-T8.4 — Lock / Unlock de versao
# ==========================================================

def lock_lib(project_dir: str | Path, name: str, version: str) -> Result:
    """
    Trava a biblioteca numa versao exata (@E8-T8.4).
    Recusa '*', ranges ('>=', '~>', '^', etc.) e strings vazias.
    Preserva a forma da entrada (dependencia de Git continua sendo de Git).
    """
    err = _validate_name(name)
    if err:
        return (False, err)
    name = name.strip()

    err = _validate_not_reserved(name, "travada")
    if err:
        return (False, err)

    err = _validate_exact_version(version)
    if err:
        return (False, err)
    version = version.strip()

    ok, root = _resolve_root(project_dir)
    if not ok:
        return (False, root)

    ok2, manifest = _load_manifest(root)
    if not ok2:
        return (False, manifest)

    if name not in manifest["dependencies"]:
        return (False, "biblioteca '{}' nao encontrada no projeto; "
                       "adicione-a antes de travar".format(name))

    entrada = manifest["dependencies"][name]
    versao_anterior = _get_version_str(entrada)
    if versao_anterior == version:
        return (False, "biblioteca '{}' ja esta travada em '{}'".format(
            name, version))

    manifest["dependencies"][name] = _set_version(entrada, version)
    ok3, res = _save_manifest(root, manifest)
    if not ok3:
        return (False, "erro ao gravar manifesto: {}".format(res))

    return (True, {
        "name":             name,
        "version_anterior": versao_anterior,
        "version_locked":   version,
        "message": "biblioteca '{}' travada em '{}'".format(name, version),
    })


def unlock_lib(project_dir: str | Path, name: str) -> Result:
    """
    Remove o lock de versao, voltando para '*' (qualquer versao).
    Preserva a forma da entrada (dependencia de Git continua sendo de Git).
    """
    err = _validate_name(name)
    if err:
        return (False, err)
    name = name.strip()

    err = _validate_not_reserved(name, "destravada")
    if err:
        return (False, err)

    ok, root = _resolve_root(project_dir)
    if not ok:
        return (False, root)

    ok2, manifest = _load_manifest(root)
    if not ok2:
        return (False, manifest)

    if name not in manifest["dependencies"]:
        return (False, "biblioteca '{}' nao encontrada no projeto".format(name))

    entrada = manifest["dependencies"][name]
    versao_atual = _get_version_str(entrada)
    if not _is_locked(versao_atual):
        return (False, "biblioteca '{}' nao esta travada (versao: '{}')".format(
            name, versao_atual))

    manifest["dependencies"][name] = _set_version(entrada, "*")
    ok3, res = _save_manifest(root, manifest)
    if not ok3:
        return (False, "erro ao gravar manifesto: {}".format(res))

    return (True, {
        "name":             name,
        "version_anterior": versao_atual,
        "message": "lock removido de '{}'; versao volta para '*'".format(name),
    })


def get_lock_status(project_dir: str | Path) -> Result:
    """
    Status de lock de todas as bibliotecas do projeto.
    Retorna (True, lista) onde cada item e {name, version, locked, source}.
    """
    return list_libs(project_dir)


__all__ = [
    "list_libs", "add_lib", "add_git_lib", "add_path_lib", "remove_lib",
    "lock_lib", "unlock_lib", "get_lock_status",
    "get_idf_requirement",
    "MANIFEST_FILENAME", "MAIN_COMPONENT", "RESERVED_DEPS",
]
