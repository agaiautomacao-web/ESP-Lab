#!/usr/bin/env python3
"""
Integracao com editor externo (@E8-T8.2).

Detecta e gerencia editores de TERMINAL disponiveis no sistema ou
empacotados dentro do ambiente do ESP Lab. A escrita do codigo e
sempre delegada ao editor externo (PROJECT.md 7.1); este modulo so
localiza, configura, instala editor interno suportado e monta o
comando — nunca abre editor em segundo plano.

Decisao de arquitetura (2026-07-01): so editores de TERMINAL sao
suportados (vim, nvim, nano, hx, micro). Editores graficos foram
removidos por quebrarem a promessa de isolamento do ESP Lab.

Um editor de terminal disputa a mesma TTY que o Textual esta usando.
Quem chama (app.py) precisa suspender o Textual primeiro:

    with app.suspend():
        ok, res = run_terminal_editor(caminho, editor)

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

Result = Tuple[bool, Any]


# ----------------------------------------------------------------------
# EDITORES DE TERMINAL CONHECIDOS
# ----------------------------------------------------------------------
# Ordem base quando nao ha editor preferido salvo.
# O binario interno do ESP Lab tem prioridade sobre o sistema quando
# prefer_internal=True na configuracao.
_KNOWN_EDITORS: List[Dict[str, str]] = [
    {"id": "micro", "bin": "micro", "label": "Micro"},
    {"id": "nano",  "bin": "nano",  "label": "Nano"},
    {"id": "hx",    "bin": "hx",    "label": "Helix"},
    {"id": "nvim",  "bin": "nvim",  "label": "Neovim"},
    {"id": "vim",   "bin": "vim",   "label": "Vim"},
]

# Instalacao interna implementada agora.
# micro/helix ficam visiveis como planejados, mas sem instalador neste patch.
_INSTALLABLE_EDITORS: List[Dict[str, Any]] = [
    {
        "id": "nano",
        "label": "Nano",
        "implemented": True,
        "source": "apt-get download + dpkg -x",
        "note": "pacote oficial do Ubuntu, extraido para o ambiente ESP Lab",
    },
    {
        "id": "micro",
        "label": "Micro",
        "implemented": False,
        "source": "pendente",
        "note": "instalador interno ainda nao implementado",
    },
    {
        "id": "hx",
        "label": "Helix",
        "implemented": False,
        "source": "pendente",
        "note": "instalador interno ainda nao implementado",
    },
]

_CONFIG_DEFAULT: Dict[str, Any] = {
    "preferred_editor": "",
    "prefer_internal": True,
}


def _known_ids() -> set[str]:
    return {e["id"] for e in _KNOWN_EDITORS}


def _editor_config_path() -> Path:
    """
    Caminho da configuracao de editor.

    Preferencia: propriedade paths.editor_config, se existir.
    Fallback: config_home/editor_config.json para manter compatibilidade
    caso paths.py ainda nao tenha recebido a propriedade.
    """
    from ..core import paths as _paths

    p = _paths.get_paths()
    return getattr(p, "editor_config", p.config_home / "editor_config.json")


def get_editor_config() -> Result:
    """
    Le a configuracao do editor.
    Ausencia do arquivo nao e erro: devolve default.
    """
    try:
        from ..core import storage as _storage

        cfg_path = _editor_config_path()
        ok, data = _storage.read_json(cfg_path)
        if not ok:
            return (True, dict(_CONFIG_DEFAULT))
        if not isinstance(data, dict):
            return (True, dict(_CONFIG_DEFAULT))

        cfg = dict(_CONFIG_DEFAULT)
        preferred = str(data.get("preferred_editor", "") or "").strip()
        if preferred in _known_ids():
            cfg["preferred_editor"] = preferred
        cfg["prefer_internal"] = bool(data.get("prefer_internal", True))
        return (True, cfg)
    except Exception as ex:
        return (False, "erro ao ler configuracao de editor: {}".format(ex))


def set_preferred_editor(editor_id: str, *, prefer_internal: bool = True) -> Result:
    """
    Salva o editor padrao do ESP Lab.
    """
    editor_id = (editor_id or "").strip()
    if editor_id not in _known_ids():
        return (False, "editor desconhecido: '{}'".format(editor_id))

    try:
        from ..core import storage as _storage

        cfg_path = _editor_config_path()

        def _mutate(current: Any) -> Dict[str, Any]:
            data = current if isinstance(current, dict) else {}
            data["preferred_editor"] = editor_id
            data["prefer_internal"] = bool(prefer_internal)
            return data

        ok, res = _storage.update_json(
            cfg_path,
            _mutate,
            default=dict(_CONFIG_DEFAULT),
        )
        if not ok:
            return (False, res)
        return (True, {
            "preferred_editor": editor_id,
            "prefer_internal": bool(prefer_internal),
            "path": str(cfg_path),
        })
    except Exception as ex:
        return (False, "erro ao salvar configuracao de editor: {}".format(ex))


def clear_preferred_editor() -> Result:
    """Remove a preferencia de editor, mantendo prefer_internal=True."""
    try:
        from ..core import storage as _storage

        cfg_path = _editor_config_path()

        def _mutate(current: Any) -> Dict[str, Any]:
            data = current if isinstance(current, dict) else {}
            data["preferred_editor"] = ""
            data["prefer_internal"] = True
            return data

        ok, res = _storage.update_json(
            cfg_path,
            _mutate,
            default=dict(_CONFIG_DEFAULT),
        )
        if not ok:
            return (False, res)
        return (True, {"path": str(cfg_path)})
    except Exception as ex:
        return (False, "erro ao limpar configuracao de editor: {}".format(ex))


def get_preferred_editor() -> Result:
    """Devolve o id do editor preferido ou string vazia."""
    ok, cfg = get_editor_config()
    if not ok:
        return (False, cfg)
    return (True, cfg.get("preferred_editor", ""))


def _internal_path(bin_name: str) -> Optional[str]:
    try:
        from ..core import paths as _paths

        candidato = _paths.get_paths().app_venv / "bin" / bin_name
        if candidato.is_file() and os.access(str(candidato), os.X_OK):
            return str(candidato)
    except Exception:
        pass
    return None


def _system_path(bin_name: str) -> Optional[str]:
    caminho = shutil.which(bin_name)
    return caminho or None


def _candidate_paths(bin_name: str, *, prefer_internal: bool = True) -> List[Dict[str, str]]:
    """
    Devolve candidatos reais para um binario.
    Remove duplicatas por caminho resolvido.
    """
    if prefer_internal:
        ordered = [("ambiente ESP Lab", _internal_path(bin_name)),
                   ("sistema", _system_path(bin_name))]
    else:
        ordered = [("sistema", _system_path(bin_name)),
                   ("ambiente ESP Lab", _internal_path(bin_name))]

    vistos: set[str] = set()
    candidatos: List[Dict[str, str]] = []
    for origin, caminho in ordered:
        if not caminho:
            continue
        try:
            resolvido = str(Path(caminho).resolve())
        except Exception:
            resolvido = caminho
        if resolvido in vistos:
            continue
        vistos.add(resolvido)
        candidatos.append({"origin": origin, "path": resolvido})
    return candidatos


def _mk_editor(meta: Dict[str, str], cand: Dict[str, str]) -> Dict[str, str]:
    return {
        "kind":   "terminal",
        "id":     meta["id"],
        "label":  meta["label"],
        "bin":    cand["path"],
        "path":   cand["path"],
        "origin": cand["origin"],
    }


def _sort_for_preference(editores: List[Dict[str, str]], preferred_id: str) -> List[Dict[str, str]]:
    if not preferred_id:
        return editores
    preferidos = [e for e in editores if e.get("id") == preferred_id]
    outros = [e for e in editores if e.get("id") != preferred_id]
    return preferidos + outros


def detect_editors() -> Result:
    """
    Detecta editores de terminal disponiveis.

    Retorna (True, lista), cada item:
      {kind, id, label, bin, path, origin}

    Lista vazia e valida. Nunca lanca.
    """
    try:
        ok_cfg, cfg = get_editor_config()
        if ok_cfg:
            prefer_internal = bool(cfg.get("prefer_internal", True))
            preferred_id = str(cfg.get("preferred_editor", "") or "")
        else:
            prefer_internal = True
            preferred_id = ""

        encontrados: List[Dict[str, str]] = []
        for meta in _KNOWN_EDITORS:
            candidatos = _candidate_paths(meta["bin"], prefer_internal=prefer_internal)
            if candidatos:
                encontrados.append(_mk_editor(meta, candidatos[0]))

        return (True, _sort_for_preference(encontrados, preferred_id))
    except Exception as ex:
        return (False, "erro ao detectar editores: {}".format(ex))


def list_installable_editors() -> Result:
    """
    Lista fixa de editores internos instalaveis pelo ESP Lab.

    Por enquanto:
      - nano
      - micro

    Nao aceita digitacao livre de nome de editor.
    """
    itens = []
    for editor_id, label, package, binary in [
        ("nano", "Nano", "nano", "nano"),
        ("micro", "Micro", "micro", "micro"),
    ]:
        interno = _candidate_paths(binary, prefer_internal=True)
        instalado = any(c.get("origin") == "ambiente ESP Lab" for c in interno)
        itens.append({
            "id": editor_id,
            "label": label,
            "package": package,
            "binary": binary,
            "installed": instalado,
        })
    return (True, itens)


def _is_executable(path_value: str) -> bool:
    try:
        p = Path(path_value).expanduser().resolve()
        return p.is_file() and os.access(str(p), os.X_OK)
    except Exception:
        return False


def build_command(path: str | Path, editor: Dict[str, Any]) -> Result:
    """
    Valida o caminho e o editor, e MONTA o comando a executar — mas NAO
    executa nada. Aceita binario absoluto interno ou nome no PATH.
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return (False, "caminho nao encontrado: '{}'".format(target))

    bin_value = str(editor.get("bin") or editor.get("path") or "").strip()
    if not bin_value:
        return (False, "editor sem binario definido")

    if os.sep in bin_value or bin_value.startswith("."):
        if not _is_executable(bin_value):
            return (False, "editor '{}' nao encontrado ou nao executavel".format(bin_value))
        cmd_bin = str(Path(bin_value).expanduser().resolve())
    else:
        found = shutil.which(bin_value)
        if not found:
            return (False, "editor '{}' nao encontrado no PATH".format(bin_value))
        cmd_bin = found

    return (True, {
        "cmd":   [cmd_bin, str(target)],
        "id":    editor.get("id", cmd_bin),
        "label": editor.get("label", cmd_bin),
    })


def run_terminal_editor(path: str | Path, editor: Dict[str, Any]) -> Result:
    """
    Executa um editor de TERMINAL em PRIMEIRO PLANO, bloqueando ate o
    usuario fechar o editor. Chamar somente dentro de App.suspend().
    """
    ok, info = build_command(path, editor)
    if not ok:
        return (False, info)

    try:
        resultado = subprocess.run(info["cmd"])
        return (True, {
            "id":         info["id"],
            "label":      info["label"],
            "kind":       "terminal",
            "returncode": resultado.returncode,
        })
    except Exception as ex:
        return (False, "erro ao executar editor '{}': {}".format(
            info["label"], ex))


def _parse_version(texto: str) -> str:
    """
    Extrai o primeiro numero de versao (X.Y ou X.Y.Z) de um texto.
    'versao desconhecida' se nao encontrar nenhum numero no formato.
    """
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", texto)
    return m.group(1) if m else "versao desconhecida"


def detect_editor_version(bin_name: str) -> str:
    """
    Tenta obter a versao do editor via '<bin> --version'.
    Aceita caminho absoluto ou nome no PATH.
    """
    bin_name = str(bin_name or "").strip()
    if not bin_name:
        return "versao desconhecida"

    try:
        if os.sep in bin_name or bin_name.startswith("."):
            if not _is_executable(bin_name):
                return "versao desconhecida"
            cmd_bin = str(Path(bin_name).expanduser().resolve())
        else:
            cmd_bin = shutil.which(bin_name) or ""
            if not cmd_bin:
                return "versao desconhecida"

        proc = subprocess.run(
            [cmd_bin, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        saida = (proc.stdout or proc.stderr or "").strip()
        if not saida:
            return "versao desconhecida"
        primeira_linha = saida.splitlines()[0]
        return _parse_version(primeira_linha)
    except Exception:
        return "versao desconhecida"


def _origem(caminho: str) -> str:
    """
    Classifica a origem do binario do editor.
    """
    try:
        from ..core import paths as _paths

        data_home = _paths.get_paths().data_home
        p = Path(caminho).resolve()
        if p.is_relative_to(data_home):
            return "ambiente ESP Lab"
    except Exception:
        pass
    return "sistema"


def active_editor() -> Result:
    """
    Devolve o editor efetivamente usado pelo ESP Lab, respeitando
    configuracao de preferencia e disponibilidade real.
    """
    ok, editores = detect_editors()
    if not ok:
        return (False, editores)
    if not editores:
        return (True, None)
    return (True, editores[0])


def active_editor_info() -> Result:
    """
    Devolve {label, version, path, origin, id} do editor ativo, ou
    (True, None) se nenhum editor de terminal for encontrado.
    Usado pelo painel SOFTWARE da tela inicial.
    """
    ok, editor = active_editor()
    if not ok:
        return (False, editor)
    if not editor:
        return (True, None)

    caminho = editor.get("path", "") or editor.get("bin", "")
    origem = editor.get("origin") or (_origem(caminho) if caminho else "sistema")
    versao = detect_editor_version(caminho)

    return (True, {
        "id":      editor.get("id", ""),
        "label":  editor.get("label", ""),
        "version": versao,
        "path":   caminho,
        "origin": origem,
    })


def validate_active_editor() -> Result:
    """
    Valida o editor ativo sem abrir o editor.
    """
    ok, info = active_editor_info()
    if not ok:
        return (False, info)
    if not info:
        return (False, "nenhum editor de terminal detectado")

    path = info.get("path", "")
    if not _is_executable(path):
        return (False, "editor ativo nao e executavel: {}".format(path))

    version = info.get("version") or "versao desconhecida"
    return (True, {
        "id":      info.get("id", ""),
        "label":   info.get("label", ""),
        "version": version,
        "path":    path,
        "origin":  info.get("origin", ""),
    })


def editor_status() -> Result:
    """
    Estado completo para a TUI: editor ativo, disponiveis e instalaveis.
    """
    ok_cfg, cfg = get_editor_config()
    if not ok_cfg:
        cfg = dict(_CONFIG_DEFAULT)

    prefer_internal = bool(cfg.get("prefer_internal", True))
    preferred_id = str(cfg.get("preferred_editor", "") or "")

    available: List[Dict[str, Any]] = []
    for meta in _KNOWN_EDITORS:
        candidatos = _candidate_paths(meta["bin"], prefer_internal=prefer_internal)
        for cand in candidatos:
            editor = _mk_editor(meta, cand)
            editor["version"] = detect_editor_version(editor["path"])
            available.append(editor)

    ok_active, active = active_editor_info()
    if not ok_active:
        active = None

    installed_internal = {
        e["id"]: any(
            c["origin"] == "ambiente ESP Lab"
            for c in _candidate_paths(e["bin"], prefer_internal=True)
        )
        for e in _KNOWN_EDITORS
    }

    installable = []
    for item in _INSTALLABLE_EDITORS:
        x = dict(item)
        x["installed"] = bool(installed_internal.get(item["id"], False))
        installable.append(x)

    return (True, {
        "config": {
            "preferred_editor": preferred_id,
            "prefer_internal": prefer_internal,
            "path": str(_editor_config_path()),
        },
        "active": active,
        "available": available,
        "installable": installable,
    })


def install_editor(
    editor_id: str,
    progress_cb: Optional[Callable[[str, str], None]] = None,
    *,
    set_as_default: bool = True,
) -> Result:
    """
    Instala editor interno por id fixo.

    Aceitos:
      - nano
      - micro
    """
    editor_id = (editor_id or "").strip().lower()
    if editor_id not in {"nano", "micro"}:
        return (False, "editor interno nao suportado: '{}'".format(editor_id))

    ok, res = bundle_editor(editor_id, progress_cb=progress_cb)
    if not ok:
        return (False, res)

    if set_as_default:
        ok2, cfg_res = set_preferred_editor(editor_id, prefer_internal=True)
        if not ok2:
            return (
                False,
                "{} instalado, mas falha ao salvar preferencia: {}".format(editor_id, cfg_res),
            )

    return (True, res)


def _bundle_deb_binary(
    package_name: str,
    binary_name: str,
    progress_cb: Optional[Callable[[str, str], None]] = None,
) -> Result:
    """
    Baixa pacote .deb via apt-get download e extrai somente o binario
    para data/app-venv/bin.

    Nao instala no sistema, nao usa sudo e nao registra pacote no dpkg.
    """
    if not package_name or not binary_name:
        return (False, "pacote/binario vazio")

    if not shutil.which("apt-get"):
        return (False, "apt-get nao disponivel neste sistema")
    if not shutil.which("dpkg"):
        return (False, "dpkg nao disponivel neste sistema")

    from ..core import paths as _paths

    destino_bin = _paths.get_paths().app_venv / "bin"

    with tempfile.TemporaryDirectory(prefix="esplab-{}-".format(binary_name)) as tmpdir:
        if progress_cb:
            progress_cb("info", "Baixando pacote '{}' via apt...".format(package_name))

        try:
            proc = subprocess.run(
                ["apt-get", "download", package_name],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except Exception as ex:
            return (False, "erro ao baixar pacote '{}': {}".format(package_name, ex))

        if proc.returncode != 0:
            erro = (proc.stderr or proc.stdout or "").strip()
            return (
                False,
                "apt-get download falhou para '{}': {}".format(package_name, erro[:300]),
            )

        debs = sorted(Path(tmpdir).glob("{}_*.deb".format(package_name)))
        if not debs:
            debs = sorted(Path(tmpdir).glob("*.deb"))
        if not debs:
            return (False, "pacote .deb de '{}' nao foi baixado".format(package_name))

        if progress_cb:
            progress_cb("info", "Extraindo pacote sem instalar no sistema...")

        extract_dir = Path(tmpdir) / "extraido"
        try:
            proc2 = subprocess.run(
                ["dpkg", "-x", str(debs[0]), str(extract_dir)],
                capture_output=True,
                text=True,
                timeout=45,
            )
        except Exception as ex:
            return (False, "erro ao extrair pacote '{}': {}".format(package_name, ex))

        if proc2.returncode != 0:
            erro = (proc2.stderr or proc2.stdout or "").strip()
            return (False, "dpkg -x falhou para '{}': {}".format(package_name, erro[:300]))

        candidato = extract_dir / "usr" / "bin" / binary_name
        if not candidato.is_file():
            achados = [p for p in extract_dir.rglob(binary_name) if p.is_file()]
            if achados:
                candidato = achados[0]

        if not candidato.is_file():
            return (
                False,
                "binario '{}' nao encontrado no pacote '{}'".format(binary_name, package_name),
            )

        try:
            destino_bin.mkdir(parents=True, exist_ok=True)
            destino_final = destino_bin / binary_name
            shutil.copy2(candidato, destino_final)
            destino_final.chmod(destino_final.stat().st_mode | 0o111)
        except Exception as ex:
            return (
                False,
                "erro ao copiar '{}' para o ambiente: {}".format(binary_name, ex),
            )

    if progress_cb:
        progress_cb("info", "{} instalado em {}".format(binary_name, destino_final))

    return (True, {"path": str(destino_final)})


def bundle_micro(progress_cb: Optional[Callable[[str, str], None]] = None) -> Result:
    """Baixa e empacota o editor Micro dentro do ambiente do ESP Lab."""
    return _bundle_deb_binary("micro", "micro", progress_cb=progress_cb)


def bundle_editor(
    editor_id: str,
    progress_cb: Optional[Callable[[str, str], None]] = None,
) -> Result:
    """
    Instala editor interno por id fixo.

    Aceitos:
      - nano
      - micro
    """
    editor_id = (editor_id or "").strip().lower()
    if editor_id == "nano":
        return bundle_nano(progress_cb=progress_cb)
    if editor_id == "micro":
        return bundle_micro(progress_cb=progress_cb)
    return (False, "editor interno nao suportado: '{}'".format(editor_id))


def bundle_nano(progress_cb: Optional[Callable[[str, str], None]] = None) -> Result:
    """
    Baixa o pacote oficial 'nano' dos repositorios do Ubuntu via
    'apt-get download' (NAO instala no sistema, NAO precisa de sudo)
    e extrai o binario para data/app-venv/bin/nano via 'dpkg -x'.
    """
    if not shutil.which("apt-get"):
        return (False, "apt-get nao disponivel neste sistema — "
                       "nao e possivel empacotar automaticamente")
    if not shutil.which("dpkg"):
        return (False, "dpkg nao disponivel neste sistema")

    from ..core import paths as _paths

    destino_bin = _paths.get_paths().app_venv / "bin"

    with tempfile.TemporaryDirectory(prefix="esplab-nano-") as tmpdir:
        if progress_cb:
            progress_cb("info", "Baixando pacote 'nano' via apt (rede)...")
        try:
            proc = subprocess.run(
                ["apt-get", "download", "nano"],
                cwd=tmpdir, capture_output=True, text=True, timeout=60,
            )
        except Exception as ex:
            return (False, "erro ao baixar pacote: {}".format(ex))
        if proc.returncode != 0:
            erro = (proc.stderr or proc.stdout or "").strip()
            return (False, "apt-get download falhou: {}".format(erro[:300]))

        debs = list(Path(tmpdir).glob("nano_*.deb"))
        if not debs:
            return (False, "pacote .deb do nano nao foi baixado "
                           "(verifique a conexao com a internet)")

        if progress_cb:
            progress_cb("info", "Extraindo pacote (sem instalar no sistema)...")
        extract_dir = Path(tmpdir) / "extraido"
        try:
            proc2 = subprocess.run(
                ["dpkg", "-x", str(debs[0]), str(extract_dir)],
                capture_output=True, text=True, timeout=30,
            )
        except Exception as ex:
            return (False, "erro ao extrair pacote: {}".format(ex))
        if proc2.returncode != 0:
            erro = (proc2.stderr or proc2.stdout or "").strip()
            return (False, "dpkg -x falhou: {}".format(erro[:300]))

        nano_extraido = extract_dir / "usr" / "bin" / "nano"
        if not nano_extraido.is_file():
            return (False, "binario 'nano' nao encontrado dentro do "
                           "pacote extraido")

        try:
            destino_bin.mkdir(parents=True, exist_ok=True)
            destino_final = destino_bin / "nano"
            shutil.copy2(nano_extraido, destino_final)
            modo_atual = destino_final.stat().st_mode
            destino_final.chmod(modo_atual | 0o111)
        except Exception as ex:
            return (False, "erro ao copiar binario para o ambiente: {}".format(ex))

    if progress_cb:
        progress_cb("info", "nano instalado em {}".format(destino_final))
    return (True, {"path": str(destino_final)})


__all__ = [
    "detect_editors",
    "list_installable_editors",
    "build_command",
    "run_terminal_editor",
    "detect_editor_version",
    "active_editor",
    "active_editor_info",
    "validate_active_editor",
    "editor_status",
    "install_editor",
    "bundle_nano",
    "bundle_micro",
    "bundle_editor",
    "get_editor_config",
    "set_preferred_editor",
    "clear_preferred_editor",
    "get_preferred_editor",
    "Result",
]
