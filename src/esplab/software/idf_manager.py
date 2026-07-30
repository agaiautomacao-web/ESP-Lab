#!/usr/bin/env python3
"""
Gerenciador de versoes de ESP-IDF (@E3-T3.6) — modelo de SLOTS.

Substitui o modelo de "janela deslizante generica" pelo de slots fixos
com identidade (PROJECT.md 5.7): 3 fixas + 1 atualizavel, definidos em
compat_matrix.yml (schema v2). O usuario nunca escolhe tag/patch/branch
livremente — so opera sobre o slot que o menu oferece.

Cinco operacoes, mapeadas 1:1 nas funcoes publicas abaixo:

  Instalar  (install_slot)   : slot sem release no registro -> clona o
                                tag da matriz (fixo) ou o seed_tag
                                (atualizavel, so na 1a instalacao).
  Reparar   (repair_slot)    : slot com release registrada mas com a
                                instalacao suspeita -> reinstala a MESMA
                                tag. Nunca promove patch.
  Validar   (check_health)   : roda 'idf_tools.py export' pela instalacao;
                                prova que o ambiente resolve sem reinstalar
                                nada. Usada tambem dentro de Reparar/Atualizar.
  Atualizar (check_update +
             apply_update)   : SO o slot atualizavel. Busca o patch mais
                                novo da MESMA familia (nunca atravessa de
                                slot), instala ao lado, valida, so entao
                                troca o ponteiro do registro. A release
                                anterior vira rollback (1 geracao apenas).
  Reverter  (revert_slot)    : SO o slot atualizavel, so quando ha
                                rollback. Troca release<->rollback no
                                registro — nunca escolha livre de versao.

Isolamento (PROJECT.md 5.9-5.11): cada instalacao e um diretorio proprio
nomeado pelo tag (esp-idf/<tag>), nunca movido fisicamente — o registro
(idf_registry.json) e quem decide qual tag e "a release do slot" e qual
e "o rollback"; ambos podem coexistir em disco ao mesmo tempo durante
uma atualizacao. Instalar/Reparar/Atualizar nunca mutam um diretorio
existente — sempre lado a lado, nunca in-place.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core import paths as _paths
from ..core import errors as _errors
from ..core import logger as _logger
from ..core import storage as _storage
from . import compat_matrix as _matrix
from . import idf_releases as _idf_rel

Result = Tuple[bool, Any]

# Repositorio oficial do ESP-IDF.
IDF_REPO = "https://github.com/espressif/esp-idf.git"

# Arquivo de registro do estado dos slots (dentro de data_home).
_REGISTRY_NAME = "idf_registry.json"

# Espaco minimo livre exigido para uma Atualizacao (duas instalacoes
# completas convivem em disco durante o swap — cada uma gira em torno
# de 2-3 GB com toolchain).
_MIN_DISK_GB_UPDATE = 4.0


# ==========================================================
# CAMINHOS E REGISTRO
# ==========================================================

def _idf_path(tag: str) -> Path:
    """Caminho da instalacao do ESP-IDF para uma tag (ex. 'v5.4.4')."""
    return _paths.get_paths().idf_for(tag)


def _registry_path() -> Path:
    return _paths.get_paths().data_home / _REGISTRY_NAME


def _load_registry() -> Dict[str, Any]:
    """
    Carrega o registro de slots. Formato esperado:
      {"active": tag|None, "slots": {slot_key: {...}}}
    Ausente/corrompido -> registro vazio (nunca lanca).
    Formato antigo (pre-slots, chave 'installed') -> degrada para vazio
    com aviso no log; operacoes vao falhar de forma clara (diretorio ja
    existe) em vez de inventar estado — rode a migracao antes de usar.
    """
    ok, data = _storage.read_json(_registry_path())
    if not ok or not isinstance(data, dict):
        return {"active": None, "slots": {}}
    if "installed" in data and "slots" not in data:
        _logger.get_logger().warning(
            "idf_registry.json ainda no formato antigo (pre-slots); "
            "rode a migracao antes de instalar/reparar/atualizar")
        return {"active": data.get("active"), "slots": {}}
    data.setdefault("active", None)
    data.setdefault("slots", {})
    return data


def _save_registry(data: Dict[str, Any]) -> Result:
    return _storage.atomic_write_json(_registry_path(), data)


def _is_installed(tag: str) -> bool:
    """True se a instalacao existe e tem o idf_tools.py (integra)."""
    return (_idf_path(tag) / "tools" / "idf_tools.py").is_file()


# ==========================================================
# LEITURA CONSOLIDADA (matriz + registro + disco)
# ==========================================================

def list_slots_status() -> Result:
    """
    Retrato pronto para exibicao de todos os slots: papel, eol, release
    corrente, se esta de fato em disco, se e a ativa, e rollback.
    (True, {slot_key: {...}}) ou (False, motivo).
    """
    ok_m, keys = _matrix.list_slots()
    if not ok_m:
        return (False, keys)

    reg = _load_registry()
    reg_slots = reg.get("slots", {})
    active = reg.get("active")

    out: Dict[str, Any] = {}
    for key in keys:
        ok_s, slot_def = _matrix.get_slot(key)
        if not ok_s:
            continue
        entry = reg_slots.get(key, {})
        release = entry.get("release")
        out[key] = {
            "role":      slot_def.get("role"),
            "eol":       slot_def.get("eol"),
            "python":    slot_def.get("python"),
            "release":   release,
            "installed": bool(release) and _is_installed(release),
            "active":    bool(release) and release == active,
            "rollback":  entry.get("rollback"),
        }
    return (True, out)


# ==========================================================
# OPERACOES DE DISCO (puras — nao tocam registro)
# ==========================================================

def _terminate_process_group(proc: subprocess.Popen, label: str) -> Result:
    """Encerra e confirma o termino da arvore do subprocesso."""
    if proc.poll() is not None:
        return (True, "processo encerrado")
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return (True, "processo encerrado")
    except Exception:
        try:
            proc.terminate()
        except Exception as e:
            return (False, "falha ao enviar SIGTERM a {}: {}".format(label, e))
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:
            try:
                proc.kill()
            except Exception as e:
                return (False, "falha ao forcar encerramento de {}: {}".format(label, e))
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return (False, "nao foi possivel confirmar o encerramento de {}".format(label))
    if proc.poll() is None:
        return (False, "{} continuou ativo apos o cancelamento".format(label))
    return (True, "processo encerrado")


def _run_step(cmd: List[str], cwd: Optional[Path],
              env: Optional[Dict],
              progress_cb: Optional[Callable],
              label: str,
              cancel_event: Optional["threading.Event"] = None) -> Result:
    """
    Executa um passo externo com streaming e cancelamento confirmado.

    O processo nasce em uma sessao propria. No cancelamento, toda a arvore
    recebe SIGTERM, depois SIGKILL se necessario. O retorno so acontece
    depois que o termino foi confirmado.
    """
    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")

    proc: Optional[subprocess.Popen] = None
    stop_watch = threading.Event()
    cancel_result: list[Result] = []
    watcher: Optional[threading.Thread] = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

        if cancel_event is not None:
            def _watch() -> None:
                while not stop_watch.wait(0.1):
                    if cancel_event.is_set():
                        cancel_result.append(_terminate_process_group(proc, label))
                        return
            watcher = threading.Thread(
                target=_watch, daemon=True, name="idf-cancel-watch")
            watcher.start()

        if proc.stdout is None:
            return (False, "{} sem canal de saida".format(label))

        buf = bytearray()
        while True:
            byte = proc.stdout.read(1)
            if not byte:
                break
            if byte in (b"\r", b"\n"):
                part = buf.decode("utf-8", errors="replace").strip()
                buf.clear()
                if part:
                    same_line = byte == b"\r"
                    if progress_cb:
                        progress_cb(label, part, same_line)
                    _logger.get_logger().debug("[%s] %s", label, part)
                continue
            buf += byte

        rest = buf.decode("utf-8", errors="replace").strip()
        if rest:
            if progress_cb:
                progress_cb(label, rest, False)
            _logger.get_logger().debug("[%s] %s", label, rest)

        stop_watch.set()
        if watcher is not None:
            watcher.join(timeout=11)

        if cancel_event is not None and cancel_event.is_set():
            if not cancel_result:
                cancel_result.append(_terminate_process_group(proc, label))
            ok_t, reason_t = cancel_result[-1]
            if not ok_t:
                return (False, reason_t)
            return (False, "cancelado pelo usuario")

        proc.wait()
        if proc.returncode != 0:
            return (False, "{} falhou (codigo {})".format(label, proc.returncode))
        return (True, label)
    except Exception as e:
        if proc is not None and proc.poll() is None:
            _terminate_process_group(proc, label)
        return (False, "erro em {}: {}".format(label, e))
    finally:
        stop_watch.set()
        if watcher is not None and watcher.is_alive():
            watcher.join(timeout=1)
        if proc is not None and proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass


def _clone_tag(tag: str, progress_cb: Optional[Callable] = None,
               cancel_event: Optional["threading.Event"] = None,
               *, target_path: Optional[Path] = None) -> Result:
    """Clona e instala uma tag em um destino novo, sem tocar o registro."""
    target = target_path or _idf_path(tag)
    if target.exists():
        return (False, "diretorio '{}' ja existe".format(target))
    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")

    target.parent.mkdir(parents=True, exist_ok=True)
    ok1, r1 = _run_step(
        ["git", "clone", "--progress", "--branch", tag, "--depth", "1",
         IDF_REPO, str(target)],
        cwd=None, env=None, progress_cb=progress_cb, label="git clone",
        cancel_event=cancel_event)
    if not ok1:
        shutil.rmtree(target, ignore_errors=True)
        return (False, r1)

    if cancel_event is not None and cancel_event.is_set():
        shutil.rmtree(target, ignore_errors=True)
        return (False, "cancelado pelo usuario")

    ok2, r2 = _run_step(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=target, env=None, progress_cb=progress_cb, label="submodulos",
        cancel_event=cancel_event)
    if not ok2:
        shutil.rmtree(target, ignore_errors=True)
        return (False, r2)

    install_sh = target / "install.sh"
    if not install_sh.is_file():
        shutil.rmtree(target, ignore_errors=True)
        return (False, "install.sh nao encontrado em {}".format(target))

    if cancel_event is not None and cancel_event.is_set():
        shutil.rmtree(target, ignore_errors=True)
        return (False, "cancelado pelo usuario")

    env = os.environ.copy()
    env["IDF_PATH"] = str(target)
    env["IDF_TOOLS_PATH"] = str(_paths.get_paths().idf_tools_root)
    ok3, r3 = _run_step(
        ["bash", str(install_sh), "all"],
        cwd=target, env=env, progress_cb=progress_cb, label="install.sh",
        cancel_event=cancel_event)
    if not ok3:
        shutil.rmtree(target, ignore_errors=True)
        return (False, r3)

    if cancel_event is not None and cancel_event.is_set():
        shutil.rmtree(target, ignore_errors=True)
        return (False, "cancelado pelo usuario")
    return (True, {"tag": tag, "path": str(target)})


def _reinstall_tag(tag: str, progress_cb: Optional[Callable] = None,
                   cancel_event: Optional["threading.Event"] = None) -> Result:
    """
    Repara de forma transacional.

    A instalacao registrada permanece no lugar durante clone, install.sh e
    validacao da nova copia. A troca so ocorre depois da nova copia estar
    integra. Falha ou Ctrl+C preserva a instalacao anterior.
    """
    target = _idf_path(tag)
    token = "{}-{}".format(os.getpid(), time.time_ns())
    staging = target.with_name(
        "{}.repair-new-{}".format(target.name, token))
    previous = target.with_name(
        "{}.repair-old-{}".format(target.name, token))
    had_previous = target.exists()
    moved_previous = False

    try:
        ok_c, result_c = _clone_tag(
            tag,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            target_path=staging,
        )
        if not ok_c:
            return (False, result_c)

        ok_h, result_h = check_health(
            tag, cancel_event=cancel_event, idf_path=staging)
        if not ok_h:
            return (False, result_h)

        if cancel_event is not None and cancel_event.is_set():
            return (False, "cancelado pelo usuario")

        try:
            if had_previous:
                target.rename(previous)
                moved_previous = True
            staging.rename(target)
        except Exception as e:
            if moved_previous and previous.exists() and not target.exists():
                previous.rename(target)
            return (False, "falha ao trocar instalacao reparada: {}".format(e))

        ok_final, result_final = check_health(
            tag, cancel_event=cancel_event)
        if not ok_final:
            shutil.rmtree(target, ignore_errors=True)
            if moved_previous and previous.exists():
                previous.rename(target)
            return (
                False,
                "nova instalacao rejeitada; anterior restaurada: {}".format(
                    result_final),
            )

        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
        return (
            True,
            {"tag": tag, "path": str(target), "saudavel": True},
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if previous.exists() and target.exists():
            shutil.rmtree(previous, ignore_errors=True)


def _check_disk_space(path: Path, minimo_gb: float = _MIN_DISK_GB_UPDATE) -> Result:
    """
    Confere espaco livre antes de uma Atualizacao (as duas instalacoes
    convivem em disco durante o swap). Falha na propria checagem nao
    bloqueia a operacao — vira aviso, nao trava quem so quer tentar.
    """
    try:
        base = path if path.exists() else path.parent
        livre_gb = shutil.disk_usage(base).free / (1024 ** 3)
    except Exception as e:
        return (True, "nao foi possivel checar espaco livre: {}".format(e))
    if livre_gb < minimo_gb:
        return (False,
                "espaco em disco insuficiente ({:.1f} GB livres; minimo "
                "recomendado {:.0f} GB para manter as duas instalacoes "
                "durante a atualizacao)".format(livre_gb, minimo_gb))
    return (True, "{:.1f} GB livres".format(livre_gb))


# ==========================================================
# AMBIENTE DA INSTALACAO (compartilhado entre Ativar e Validar)
# ==========================================================

def _resolve_env_vars(tag: str,
                      cancel_event: Optional["threading.Event"] = None,
                      *, idf_path: Optional[Path] = None) -> Result:
    """Executa idf_tools.py export com timeout e cancelamento confirmado."""
    idf_p = idf_path or _idf_path(tag)
    if not (idf_p / "tools" / "idf_tools.py").is_file():
        return (False, "ESP-IDF {} nao esta instalado".format(tag))
    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")

    tools_path = _paths.get_paths().idf_tools_root
    env = os.environ.copy()
    env["IDF_PATH"] = str(idf_p)
    env["IDF_TOOLS_PATH"] = str(tools_path)
    cmd = [
        "python3", str(idf_p / "tools" / "idf_tools.py"), "export",
        "--format", "key-value",
    ]

    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        deadline = time.monotonic() + 30
        while True:
            if cancel_event is not None and cancel_event.is_set():
                ok_t, reason_t = _terminate_process_group(
                    proc, "idf_tools export")
                if not ok_t:
                    return (False, reason_t)
                return (False, "cancelado pelo usuario")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_group(proc, "idf_tools export")
                return (False, "idf_tools export excedeu 30 segundos")
            try:
                stdout, stderr = proc.communicate(
                    timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue

        if proc.returncode != 0:
            return (False, "idf_tools export falhou: {}".format(
                (stderr or stdout or "").strip()[:300]))

        env_vars: Dict[str, str] = {}
        for line in stdout.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
        env_vars["IDF_PATH"] = str(idf_p)
        env_vars["IDF_TOOLS_PATH"] = str(tools_path)
        if "PATH" in env_vars and "$PATH" in env_vars["PATH"]:
            env_vars["PATH"] = env_vars["PATH"].replace(
                "$PATH", os.environ.get("PATH", ""))
        return (True, env_vars)
    except Exception as e:
        if proc is not None and proc.poll() is None:
            _terminate_process_group(proc, "idf_tools export")
        return (False, "erro em idf_tools export: {}".format(e))


def check_health(tag: str,
                 cancel_event: Optional["threading.Event"] = None,
                 *, idf_path: Optional[Path] = None) -> Result:
    """Valida uma instalacao sem alterar registro ou ambiente global."""
    ok, result = _resolve_env_vars(
        tag, cancel_event=cancel_event, idf_path=idf_path)
    if not ok:
        return (False, result)
    return (True, "instalacao integra")


def active_tag() -> Result:
    """
    Tag ESP-IDF atualmente marcada como ativa no registro (ou None).
    NAO depende da matriz — 'active' e um fato do registro, nao da
    matriz, entao isto continua funcionando mesmo se compat_matrix.yml
    estiver invalido (usado pelo painel SOFTWARE do boot).
    """
    reg = _load_registry()
    return (True, reg.get("active"))


def updatable_slot_key() -> Result:
    """Atalho: chave do (unico) slot atualizavel. Ver compat_matrix.updatable_slot()."""
    return _matrix.updatable_slot()


def activate(tag: str,
             cancel_event: Optional["threading.Event"] = None) -> Result:
    """Valida a instalacao e marca a tag ativa por escrita atomica."""
    ok, env_vars = _resolve_env_vars(tag, cancel_event=cancel_event)
    if not ok:
        return (False, env_vars)
    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")

    reg = _load_registry()
    reg["active"] = tag
    ok_s, result_s = _save_registry(reg)
    if not ok_s:
        return (False, result_s)

    _logger.get_logger().info("ESP-IDF %s ativado", tag)
    return (
        True,
        {
            "tag": tag,
            "IDF_PATH": str(_idf_path(tag)),
            "env_vars": env_vars,
        },
    )


# ==========================================================
# INSTALAR
# ==========================================================

def install_slot(slot_key: str,
                 progress_cb: Optional[Callable[[str, str], None]] = None,
                 *, background: bool = True,
                 cancel_event: Optional["threading.Event"] = None) -> Result:
    """Instala um slot novo; cancelamento nunca registra copia incompleta."""
    ok, slot = _matrix.get_slot(slot_key)
    if not ok:
        return (False, slot)

    reg = _load_registry()
    current = reg.get("slots", {}).get(slot_key, {})
    if current.get("release"):
        return (
            False,
            "slot '{}' ja tem release registrada ({}); "
            "use Reparar ou Atualizar".format(
                slot_key, current["release"]),
        )

    role = slot.get("role")
    tag = slot.get("tag") if role == "fixed" else slot.get("seed_tag")
    if not tag:
        return (
            False,
            "slot '{}': matriz sem tag instalavel "
            "(dado invalido)".format(slot_key),
        )

    def _do() -> Result:
        ok_c, result_c = _clone_tag(
            tag,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        if not ok_c:
            if progress_cb:
                kind = (
                    "cancelado"
                    if cancel_event is not None and cancel_event.is_set()
                    else "erro"
                )
                progress_cb(kind, result_c)
            return (False, result_c)

        ok_h, result_h = check_health(
            tag, cancel_event=cancel_event)
        if not ok_h:
            shutil.rmtree(_idf_path(tag), ignore_errors=True)
            if progress_cb:
                kind = (
                    "cancelado"
                    if cancel_event is not None and cancel_event.is_set()
                    else "erro"
                )
                progress_cb(kind, result_h)
            return (False, result_h)

        if cancel_event is not None and cancel_event.is_set():
            shutil.rmtree(_idf_path(tag), ignore_errors=True)
            return (False, "cancelado pelo usuario")

        current_registry = _load_registry()
        slots = current_registry.setdefault("slots", {})
        entry = dict(slots.get(slot_key, {}))
        entry["role"] = role
        entry["release"] = tag
        if role == "updatable":
            entry.setdefault("rollback", None)
        slots[slot_key] = entry

        ok_s, result_s = _save_registry(current_registry)
        if not ok_s:
            shutil.rmtree(_idf_path(tag), ignore_errors=True)
            return (False, result_s)

        message = "ESP-IDF {} instalado no slot '{}'".format(
            tag, slot_key)
        _logger.get_logger().info(message)
        if progress_cb:
            progress_cb("concluido", message)
        return (True, {"slot": slot_key, "tag": tag})

    if background:
        thread = threading.Thread(
            target=_do,
            daemon=True,
            name="idf-install-{}".format(slot_key),
        )
        thread.start()
        return (
            True,
            {"status": "iniciado", "slot": slot_key, "tag": tag},
        )
    return _do()


# ==========================================================
# REPARAR
# ==========================================================

def repair_slot(slot_key: str,
                progress_cb: Optional[Callable[[str, str], None]] = None,
                *, background: bool = True,
                cancel_event: Optional["threading.Event"] = None) -> Result:
    """Reinstala a mesma tag por troca transacional de diretorios."""
    reg = _load_registry()
    entry = reg.get("slots", {}).get(slot_key)
    if not entry or not entry.get("release"):
        return (
            False,
            "slot '{}' nao tem release registrada; use Instalar".format(
                slot_key),
        )
    tag = entry["release"]

    def _do() -> Result:
        ok_c, result_c = _reinstall_tag(
            tag,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        if not ok_c:
            if progress_cb:
                kind = (
                    "cancelado"
                    if cancel_event is not None and cancel_event.is_set()
                    else "erro"
                )
                progress_cb(kind, result_c)
            return (False, result_c)

        message = "ESP-IDF {} reparado no slot '{}'".format(
            tag, slot_key)
        _logger.get_logger().info(message)
        if progress_cb:
            progress_cb("concluido", message)
        return (
            True,
            {"slot": slot_key, "tag": tag, "saudavel": True},
        )

    if background:
        thread = threading.Thread(
            target=_do,
            daemon=True,
            name="idf-repair-{}".format(slot_key),
        )
        thread.start()
        return (
            True,
            {"status": "iniciado", "slot": slot_key, "tag": tag},
        )
    return _do()


# ==========================================================
# ATUALIZAR (so o slot atualizavel)
# ==========================================================

def _fetch_stable_versions_cancelable(
    cancel_event: Optional["threading.Event"] = None,
) -> Result:
    """Executa a consulta de releases em subprocesso cancelavel."""
    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")

    marker = "__ESPLAB_RELEASES__"
    code = (
        "import json\n"
        "from esplab.software import idf_releases as module\n"
        "ok, result = module.fetch_stable_versions()\n"
        "print(" + repr(marker) + " + json.dumps([ok, result]))\n"
    )
    env = os.environ.copy()
    src_root = Path(__file__).resolve().parents[2]
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(src_root)
        if not current_pythonpath
        else str(src_root) + os.pathsep + current_pythonpath
    )

    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        deadline = time.monotonic() + 20
        while True:
            if cancel_event is not None and cancel_event.is_set():
                ok_t, reason_t = _terminate_process_group(
                    proc, "consulta de releases")
                if not ok_t:
                    return (False, reason_t)
                return (False, "cancelado pelo usuario")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_group(
                    proc, "consulta de releases")
                return (
                    False,
                    "consulta de releases excedeu 20 segundos",
                )
            try:
                stdout, stderr = proc.communicate(
                    timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue

        if proc.returncode != 0:
            return (
                False,
                "consulta de releases falhou: {}".format(
                    (stderr or stdout or "").strip()[:300]),
            )

        result_line = ""
        for line in stdout.splitlines():
            if line.startswith(marker):
                result_line = line[len(marker):]
        if not result_line:
            return (
                False,
                "consulta de releases retornou resposta invalida",
            )
        parsed = json.loads(result_line)
        if (
            not isinstance(parsed, list)
            or len(parsed) != 2
            or not isinstance(parsed[0], bool)
        ):
            return (
                False,
                "consulta de releases retornou formato invalido",
            )
        return (parsed[0], parsed[1])
    except Exception as e:
        if proc is not None and proc.poll() is None:
            _terminate_process_group(
                proc, "consulta de releases")
        return (
            False,
            "erro na consulta de releases: {}".format(e),
        )


def check_update(slot_key: str,
                 cancel_event: Optional["threading.Event"] = None) -> Result:
    """Consulta a release mais nova com subprocesso cancelavel."""
    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")

    ok, updatable_key = _matrix.updatable_slot()
    if not ok:
        return (False, updatable_key)
    if slot_key != updatable_key:
        return (
            False,
            "slot '{}' nao e o slot atualizavel ('{}')".format(
                slot_key, updatable_key),
        )

    reg = _load_registry()
    current = reg.get("slots", {}).get(
        slot_key, {}).get("release")
    if not current:
        return (
            False,
            "slot '{}' ainda nao tem instalacao; use Instalar".format(
                slot_key),
        )

    ok2, releases = _fetch_stable_versions_cancelable(
        cancel_event=cancel_event)
    if not ok2:
        return (False, releases)

    candidates = [
        release for release in releases
        if release["version_key"] == slot_key
    ]
    if not candidates:
        return (
            False,
            "nenhuma release encontrada para a familia '{}'".format(
                slot_key),
        )

    latest = candidates[0]["tag"]
    return (
        True,
        {
            "current": current,
            "latest": latest,
            "update_disponivel": latest != current,
        },
    )


def apply_update(slot_key: str,
                 progress_cb: Optional[Callable[[str, str], None]] = None,
                 *, background: bool = True,
                 cancel_event: Optional["threading.Event"] = None) -> Result:
    """Instala ao lado, valida e somente depois troca o registro."""
    ok, updatable_key = _matrix.updatable_slot()
    if not ok:
        return (False, updatable_key)
    if slot_key != updatable_key:
        return (
            False,
            "slot '{}' nao e o slot atualizavel".format(slot_key),
        )

    ok_check, info = check_update(
        slot_key, cancel_event=cancel_event)
    if not ok_check:
        return (False, info)
    if not info["update_disponivel"]:
        return (
            True,
            {
                "status": "ja_atualizado",
                "release": info["current"],
            },
        )

    new_tag = info["latest"]
    old_tag = info["current"]
    ok_space, space_message = _check_disk_space(
        _paths.get_paths().idf_root)
    if not ok_space:
        return (False, space_message)

    def _do() -> Result:
        ok_c, result_c = _clone_tag(
            new_tag,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        if not ok_c:
            if progress_cb:
                kind = (
                    "cancelado"
                    if cancel_event is not None and cancel_event.is_set()
                    else "erro"
                )
                progress_cb(kind, result_c)
            return (False, result_c)

        ok_h, result_h = check_health(
            new_tag, cancel_event=cancel_event)
        if not ok_h:
            shutil.rmtree(_idf_path(new_tag), ignore_errors=True)
            if progress_cb:
                kind = (
                    "cancelado"
                    if cancel_event is not None and cancel_event.is_set()
                    else "erro"
                )
                progress_cb(kind, result_h)
            return (False, result_h)

        if cancel_event is not None and cancel_event.is_set():
            shutil.rmtree(_idf_path(new_tag), ignore_errors=True)
            return (False, "cancelado pelo usuario")

        registry = _load_registry()
        slots = registry.setdefault("slots", {})
        entry = dict(slots.get(slot_key, {}))
        previous_rollback = entry.get("rollback")
        entry["release"] = new_tag
        entry["rollback"] = old_tag
        slots[slot_key] = entry
        if registry.get("active") == old_tag:
            registry["active"] = new_tag

        ok_s, result_s = _save_registry(registry)
        if not ok_s:
            shutil.rmtree(_idf_path(new_tag), ignore_errors=True)
            return (False, result_s)

        if previous_rollback and previous_rollback != old_tag:
            shutil.rmtree(
                _idf_path(previous_rollback), ignore_errors=True)

        message = "slot '{}' atualizado: {} -> {}".format(
            slot_key, old_tag, new_tag)
        _logger.get_logger().info(message)
        if progress_cb:
            progress_cb("concluido", message)
        return (
            True,
            {"slot": slot_key, "de": old_tag, "para": new_tag},
        )

    if background:
        thread = threading.Thread(
            target=_do,
            daemon=True,
            name="idf-update-{}".format(slot_key),
        )
        thread.start()
        return (
            True,
            {
                "status": "iniciado",
                "slot": slot_key,
                "de": old_tag,
                "para": new_tag,
            },
        )
    return _do()


# ==========================================================
# REVERTER (so o slot atualizavel, so com rollback disponivel)
# ==========================================================

def revert_slot(slot_key: str,
                cancel_event: Optional["threading.Event"] = None) -> Result:
    """Troca release e rollback; Ctrl+C e aceito ate a escrita atomica."""
    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")

    ok, updatable_key = _matrix.updatable_slot()
    if not ok:
        return (False, updatable_key)
    if slot_key != updatable_key:
        return (
            False,
            "slot '{}' nao e o slot atualizavel".format(slot_key),
        )

    reg = _load_registry()
    slots = reg.get("slots", {})
    entry = slots.get(slot_key)
    if not entry or not entry.get("rollback"):
        return (
            False,
            "nao ha rollback disponivel para o slot '{}'".format(
                slot_key),
        )

    current_release = entry["release"]
    current_rollback = entry["rollback"]
    if not _is_installed(current_rollback):
        return (
            False,
            "rollback '{}' nao esta mais presente em disco "
            "(foi removido manualmente?)".format(current_rollback),
        )
    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")

    updated_entry = dict(entry)
    updated_entry["release"] = current_rollback
    updated_entry["rollback"] = current_release
    slots[slot_key] = updated_entry
    reg["slots"] = slots
    if reg.get("active") == current_release:
        reg["active"] = current_rollback

    if cancel_event is not None and cancel_event.is_set():
        return (False, "cancelado pelo usuario")
    ok_s, result_s = _save_registry(reg)
    if not ok_s:
        return (False, result_s)

    message = "slot '{}' revertido: {} -> {}".format(
        slot_key, current_release, current_rollback)
    _logger.get_logger().info(message)
    return (
        True,
        {
            "slot": slot_key,
            "de": current_release,
            "para": current_rollback,
        },
    )


__all__ = [
    "list_slots_status",
    "install_slot", "repair_slot", "check_health",
    "check_update", "apply_update", "revert_slot",
    "activate", "active_tag", "updatable_slot_key",
    "IDF_REPO",
]
