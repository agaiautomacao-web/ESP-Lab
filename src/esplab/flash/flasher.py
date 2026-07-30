#!/usr/bin/env python3
"""
Gravacao de firmware (flash) na placa ESP (@E9).

Sequencia: pre-checagem, sanidade, erase opcional, write_flash e verificacao.
Todo subprocesso do esptool roda em grupo proprio, com cancelamento e timeout
independentes da producao de saida. A funcao so retorna depois de confirmar o
encerramento real do processo e de seus descendentes.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core import logger as _logger
from ..programming import builder as _builder
from ..software import idf_manager as _idf
from ..workspace import project_config as _config
from ..hardware import family_profiles as _family_profiles

Result = Tuple[bool, Any]

FLASH_TIMEOUT = 300
ERASE_TIMEOUT = 120
VERIFY_TIMEOUT = 120
PROCESS_TERM_TIMEOUT = 5

_FLASH_SIZES = {
    "1MB": 1 * 1024 * 1024,
    "2MB": 2 * 1024 * 1024,
    "4MB": 4 * 1024 * 1024,
    "8MB": 8 * 1024 * 1024,
    "16MB": 16 * 1024 * 1024,
    "32MB": 32 * 1024 * 1024,
}


def _read_flasher_args(build_dir: Path) -> Result:
    """Le e valida o flasher_args.json gerado pelo build."""
    args_path = build_dir / "flasher_args.json"
    if not args_path.is_file():
        return (False, "flasher_args.json nao encontrado; compile o projeto antes")
    try:
        data = json.loads(args_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return (False, "flasher_args.json ilegivel: {}".format(exc))
    if not data.get("flash_files", {}):
        return (False, "flasher_args.json sem flash_files; build incompleto")
    return (True, data)


def _parse_flash_size_bytes(size_str: str) -> Optional[int]:
    return _FLASH_SIZES.get(size_str.strip().upper())


def sanity_check(project_dir: str | Path,
                 chip_flash_size: str = "") -> Result:
    """Confirma que todos os binarios cabem no tamanho de flash informado."""
    root = Path(project_dir).expanduser().resolve()
    build_dir = root / "build"
    ok, data = _read_flasher_args(build_dir)
    if not ok:
        return (False, data)

    flash_files = data["flash_files"]
    flash_settings = data.get("flash_settings", {})
    size_str = chip_flash_size or flash_settings.get("flash_size", "")
    flash_bytes = _parse_flash_size_bytes(size_str) if size_str else None

    offsets = []
    maior_fim = 0
    for offset_hex, relative_path in flash_files.items():
        try:
            offset = int(offset_hex, 16)
        except ValueError:
            return (False, "offset invalido no flasher_args: {}".format(
                offset_hex))
        bin_path = build_dir / relative_path
        if not bin_path.is_file():
            return (False, "binario ausente: {}".format(relative_path))
        tamanho = bin_path.stat().st_size
        fim = offset + tamanho
        maior_fim = max(maior_fim, fim)
        offsets.append({
            "offset": offset_hex,
            "arquivo": relative_path,
            "tamanho": tamanho,
            "fim": fim,
        })

    if flash_bytes is not None and maior_fim > flash_bytes:
        return (
            False,
            "binarios excedem o flash do chip: precisam de {} bytes, "
            "flash tem {} ({})".format(maior_fim, flash_bytes, size_str),
        )
    return (True, {
        "ok": True,
        "offsets": offsets,
        "maior_fim": maior_fim,
        "flash_size": size_str or "desconhecido",
        "flash_bytes": flash_bytes,
    })


def _build_flash_env(
    idf_version: str,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """Ativa o ambiente ESP-IDF sem ignorar uma solicitacao de cancelamento."""
    if cancel_event is not None and cancel_event.is_set():
        return (False, "gravacao cancelada pelo usuario")
    if not _idf._is_installed(idf_version):
        return (False, "ESP-IDF {} nao instalado".format(idf_version))
    ok, ativacao = _idf.activate(
        idf_version, cancel_event=cancel_event)
    if not ok:
        return (False, "falha ao ativar ESP-IDF: {}".format(ativacao))
    env = os.environ.copy()
    env.update(ativacao["env_vars"])
    return (True, env)


def _esptool_base(port: str, chip_family: str) -> List[str]:
    chip = chip_family.strip().lower().replace("-", "")
    return ["esptool.py", "--chip", chip, "--port", port]


def _terminate_process_group(proc: subprocess.Popen) -> None:
    """Encerra esptool e descendentes; so retorna apos termino confirmado."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=PROCESS_TERM_TIMEOUT)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    proc.wait()


def _run_esptool_process(
    cmd: List[str],
    *,
    env: Dict[str, str],
    cwd: Optional[Path],
    progress_cb: Optional[Callable[[str, str], None]],
    cancel_event: Optional[threading.Event],
    etapa: str,
    timeout: int,
) -> Result:
    """Executa uma etapa do esptool com observador independente da saida."""
    if cancel_event is not None and cancel_event.is_set():
        return (False, "{} cancelado pelo usuario".format(etapa))

    proc: Optional[subprocess.Popen] = None
    state = {"cancelled": False, "timed_out": False}
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            start_new_session=True,
            bufsize=1,
        )

        def _watch() -> None:
            deadline = time.monotonic() + timeout
            while proc is not None and proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    state["cancelled"] = True
                    _terminate_process_group(proc)
                    return
                if time.monotonic() >= deadline:
                    state["timed_out"] = True
                    _terminate_process_group(proc)
                    return
                time.sleep(0.1)

        watcher = threading.Thread(
            target=_watch,
            daemon=True,
            name="esptool-{}-watch".format(etapa),
        )
        watcher.start()

        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                if not line:
                    continue
                kind = (
                    "error"
                    if "error" in line.lower() or "fatal" in line.lower()
                    else "info"
                )
                if progress_cb:
                    progress_cb(kind, line)
                _logger.get_logger().debug("[flash:%s] %s", etapa, line)

        proc.wait()
        watcher.join(timeout=1)

        if state["cancelled"]:
            message = "{} cancelado pelo usuario".format(etapa)
            if progress_cb:
                progress_cb(
                    "cancelado",
                    "Cancelamento concluido; esptool encerrado.",
                )
            _logger.get_logger().warning("%s", message)
            return (False, message)
        if state["timed_out"]:
            message = "{} excedeu o tempo limite ({} s)".format(
                etapa, timeout)
            if progress_cb:
                progress_cb("error", message)
            return (False, message)
        if cancel_event is not None and cancel_event.is_set():
            message = "{} cancelado pelo usuario".format(etapa)
            if progress_cb:
                progress_cb("cancelado", "Cancelamento concluido.")
            return (False, message)
        if proc.returncode != 0:
            return (False, "{} falhou (codigo {})".format(
                etapa, proc.returncode))
        return (True, {"returncode": 0})
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            _terminate_process_group(proc)
        return (False, "erro durante {}: {}".format(etapa, exc))


def erase_flash(
    port: str,
    idf_version: str,
    chip_family: str,
    confirm: bool = False,
    progress_cb: Optional[Callable[[str, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """Apaga todo o flash somente com confirmacao explicita."""
    if not confirm:
        return (False, "erase requer confirmacao explicita (confirm=True); "
                       "operacao apaga TODO o flash, irreversivel")
    ok, env = _build_flash_env(idf_version, cancel_event=cancel_event)
    if not ok:
        return (False, env)
    cmd = _esptool_base(port, chip_family) + ["erase_flash"]
    ok_run, result = _run_esptool_process(
        cmd,
        env=env,
        cwd=None,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
        etapa="erase",
        timeout=ERASE_TIMEOUT,
    )
    if not ok_run:
        return (False, result)
    _logger.get_logger().info("flash apagado em %s", port)
    return (True, {"message": "flash apagado com sucesso"})


def write_flash(
    project_dir: str | Path,
    port: str,
    idf_version: str,
    chip_family: str,
    baudrate: int = 460800,
    progress_cb: Optional[Callable[[str, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """Grava os arquivos e offsets canonicos do flasher_args.json."""
    root = Path(project_dir).expanduser().resolve()
    build_dir = root / "build"
    ok, data = _read_flasher_args(build_dir)
    if not ok:
        return (False, data)
    ok_env, env = _build_flash_env(idf_version, cancel_event=cancel_event)
    if not ok_env:
        return (False, env)

    flash_files = data["flash_files"]
    flash_settings = data.get("flash_settings", {})
    cmd = _esptool_base(port, chip_family)
    cmd += ["--baud", str(baudrate), "write_flash"]
    if flash_settings.get("flash_mode"):
        cmd += ["--flash_mode", flash_settings["flash_mode"]]
    if flash_settings.get("flash_freq"):
        cmd += ["--flash_freq", flash_settings["flash_freq"]]
    if flash_settings.get("flash_size"):
        cmd += ["--flash_size", flash_settings["flash_size"]]
    for offset_hex in sorted(flash_files, key=lambda value: int(value, 16)):
        cmd += [offset_hex, str(build_dir / flash_files[offset_hex])]

    ok_run, result = _run_esptool_process(
        cmd,
        env=env,
        cwd=build_dir,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
        etapa="gravacao",
        timeout=FLASH_TIMEOUT,
    )
    if not ok_run:
        return (False, result)
    _logger.get_logger().info("firmware gravado em %s", port)
    return (True, {
        "message": "firmware gravado com sucesso",
        "port": port,
        "files": len(flash_files),
    })


def verify_flash(
    project_dir: str | Path,
    port: str,
    idf_version: str,
    chip_family: str,
    progress_cb: Optional[Callable[[str, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """Confirma que o conteudo gravado corresponde aos binarios."""
    root = Path(project_dir).expanduser().resolve()
    build_dir = root / "build"
    ok, data = _read_flasher_args(build_dir)
    if not ok:
        return (False, data)
    ok_env, env = _build_flash_env(idf_version, cancel_event=cancel_event)
    if not ok_env:
        return (False, env)

    flash_files = data["flash_files"]
    cmd = _esptool_base(port, chip_family) + ["verify_flash"]
    for offset_hex in sorted(flash_files, key=lambda value: int(value, 16)):
        cmd += [offset_hex, str(build_dir / flash_files[offset_hex])]

    ok_run, result = _run_esptool_process(
        cmd,
        env=env,
        cwd=build_dir,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
        etapa="verificacao",
        timeout=VERIFY_TIMEOUT,
    )
    if not ok_run:
        return (False, result)
    _logger.get_logger().info("verificacao pos-gravacao OK em %s", port)
    return (True, {"message": "verificacao concluida: conteudo confere"})


def flash(
    project_dir: str | Path,
    port: str,
    chip_family: str,
    chip_flash_size: str = "",
    baudrate: int = 460800,
    do_erase: bool = False,
    erase_confirmed: bool = False,
    progress_cb: Optional[Callable[[str, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    *,
    expected_mac: str = "",
    confirmed_mac: str = "",
    expected_chip_family: str = "",
    confirmed_chip_family: str = "",
    profile_ready: Optional[bool] = None,
    background: bool = True,
) -> Result:
    """Orquestra o flash e exige identidade confirmada quando informada."""
    root = Path(project_dir).expanduser().resolve()

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    expected_mac = str(expected_mac or "").strip().lower()
    confirmed_mac = str(confirmed_mac or "").strip().lower()
    if expected_mac:
        if profile_ready is not True:
            return (False, "perfil associado não está pronto para uso físico")
        if not confirmed_mac:
            return (False, "MAC vivo não foi confirmado antes da gravação")
        if confirmed_mac != expected_mac:
            return (
                False,
                f"MAC vivo {confirmed_mac} diverge do perfil {expected_mac}",
            )

        expected_family = _family_profiles.normalize_family(
            expected_chip_family
        )
        confirmed_family = _family_profiles.normalize_family(
            confirmed_chip_family or chip_family
        )
        if expected_family == _family_profiles.UNKNOWN:
            return (False, "família do perfil associado não está definida")
        if confirmed_family == _family_profiles.UNKNOWN:
            return (False, "família viva não foi confirmada antes da gravação")
        if confirmed_family != expected_family:
            return (
                False,
                f"família viva {confirmed_family} diverge do perfil "
                f"{expected_family}",
            )

    if _cancelled():
        return (False, "gravacao cancelada pelo usuario")
    ok, cfg = _config.read(root)
    if not ok:
        return (False, "config do projeto ilegivel: {}".format(cfg))
    idf_version = cfg.get("idf_version", "").strip()
    if not idf_version:
        return (False, "versao de ESP-IDF nao definida no projeto")

    if _cancelled():
        return (False, "gravacao cancelada pelo usuario")
    ok_build, check = _builder.check_build_valid(
        root, cancel_event=cancel_event)
    if not ok_build:
        return (False, "falha ao verificar build: {}".format(check))
    if not check.get("valid"):
        return (False, "build invalido ou desatualizado: {}; recompile antes "
                       "de gravar".format(check.get(
                           "reason", "motivo desconhecido")))

    if _cancelled():
        return (False, "gravacao cancelada pelo usuario")
    ok_sanity, sanity = sanity_check(root, chip_flash_size)
    if not ok_sanity:
        return (False, "sanidade falhou: {}".format(sanity))

    def _sequence() -> Result:
        if do_erase:
            if not erase_confirmed:
                return (False, "erase solicitado sem confirmacao destrutiva")
            if _cancelled():
                return (False, "gravacao cancelada pelo usuario")
            if progress_cb:
                progress_cb("info", ">>> Apagando flash...")
            ok_erase, result_erase = erase_flash(
                port,
                idf_version,
                chip_family,
                confirm=True,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
            )
            if not ok_erase:
                return (False, "erase falhou: {}".format(result_erase))

        if _cancelled():
            return (False, "gravacao cancelada pelo usuario")
        if progress_cb:
            progress_cb("info", ">>> Gravando firmware...")
        ok_write, result_write = write_flash(
            root,
            port,
            idf_version,
            chip_family,
            baudrate=baudrate,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        if not ok_write:
            return (False, "gravacao falhou: {}".format(result_write))

        if _cancelled():
            return (False, "gravacao concluida, mas verificacao cancelada "
                           "pelo usuario")
        if progress_cb:
            progress_cb("info", ">>> Verificando gravacao...")
        ok_verify, result_verify = verify_flash(
            root,
            port,
            idf_version,
            chip_family,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        if not ok_verify:
            return (False, "VERIFICACAO FALHOU apos gravacao: {}".format(
                result_verify))

        if progress_cb:
            progress_cb("info", ">>> Gravacao concluida e verificada.")
        _logger.get_logger().info("flash completo e verificado em %s", port)
        return (True, {
            "status": "concluido",
            "port": port,
            "project": root.name,
            "verified": True,
            "confirmed_mac": confirmed_mac,
            "confirmed_chip_family": confirmed_chip_family or chip_family,
        })

    if background:
        thread = threading.Thread(
            target=_sequence,
            daemon=True,
            name="idf-flash",
        )
        thread.start()
        return (True, {
            "status": "iniciado",
            "port": port,
            "project": root.name,
        })
    return _sequence()


__all__ = [
    "sanity_check", "erase_flash", "write_flash", "verify_flash", "flash",
    "FLASH_TIMEOUT", "ERASE_TIMEOUT", "VERIFY_TIMEOUT",
]
