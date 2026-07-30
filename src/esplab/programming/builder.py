#!/usr/bin/env python3
"""
Build de firmware em background (@E8-T8.7).

Compila o projeto via 'idf.py build', ativando o ambiente da versao
de ESP-IDF do projeto. Captura e coloriza erros. Sem barra de % precisa
(o progresso de compilacao nao e confiavel de parsear).

Pre-checagem: a versao de ESP-IDF deve estar instalada e o projeto
deve ter estrutura valida (CMakeLists.txt).

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import os
import re
import signal
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core import logger as _logger
from ..hardware import boards_db as _boards
from ..software import idf_manager as _idf
from ..workspace import project_config as _config
from . import code_chip_validator as _code_chip

Result = Tuple[bool, Any]

# Timeout do build (segundos). Build completo pode demorar.
BUILD_TIMEOUT = 1800  # 30 min
PROCESS_TERM_TIMEOUT = 5

# Marcadores de erro/aviso no output do idf.py (para colorizacao).
_ERROR_MARKERS = ("error:", "fatal error", "FAILED:", "Error ")
_WARNING_MARKERS = ("warning:",)


def _classify_line(line: str) -> str:
    """Classifica uma linha de output: 'error' | 'warning' | 'info'."""
    low = line.lower()
    if any(marker.lower() in low for marker in _ERROR_MARKERS):
        return "error"
    if any(marker.lower() in low for marker in _WARNING_MARKERS):
        return "warning"
    return "info"


def _precheck(project_dir: Path) -> Result:
    """Valida pre-condicoes do build."""
    if not project_dir.is_dir():
        return (False, "pasta de projeto inexistente: {}".format(project_dir))
    if not (project_dir / "CMakeLists.txt").is_file():
        return (False, "CMakeLists.txt nao encontrado; projeto invalido")
    ok, cfg = _config.read(project_dir)
    if not ok:
        return (False, "config do projeto ilegivel: {}".format(cfg))
    idf_version = cfg.get("idf_version", "").strip()
    if not idf_version:
        return (False, "versao de ESP-IDF nao definida no projeto")
    return (True, idf_version)


def _family_to_target(chip_family):
    """Mapeia familia do chip (ex 'ESP32-S3') para target (ex 'esp32s3')."""
    if not chip_family:
        return ""
    return chip_family.strip().lower().replace("-", "")


def _terminate_process_group(proc: subprocess.Popen) -> None:
    """
    Encerra o grupo inteiro e so retorna quando o processo pai terminou.

    SIGTERM permite limpeza normal; apos o prazo, SIGKILL garante que
    idf.py, CMake, Ninja e compiladores descendentes nao fiquem ativos.
    """
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

    # Nao libera a TUI ate o encerramento real estar confirmado.
    proc.wait()


def _remove_path(path: Path) -> None:
    """Remove arquivo, link ou diretorio sem seguir links simbolicos."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _begin_set_target_transaction(root: Path) -> Dict[str, Any]:
    """
    Preserva o estado que idf.py set-target modifica.

    O build anterior e movido atomicamente para um diretorio irmao no mesmo
    filesystem. Arquivos pequenos sao copiados byte a byte com metadados.
    """
    transaction_dir = root.parent / (
        ".{}.esplab-set-target-{}-{}".format(
            root.name, os.getpid(), time.time_ns()
        )
    )
    transaction_dir.mkdir(mode=0o700)

    state: Dict[str, Any] = {
        "dir": transaction_dir,
        "files": {},
        "build_existed": False,
        "build_backup": transaction_dir / "build",
    }

    try:
        for name in (
            "sdkconfig", "sdkconfig.old", "dependencies.lock",
            getattr(_config, "CONFIG_FILENAME", "project_config.json"),
        ):
            source = root / name
            existed = source.exists() or source.is_symlink()
            state["files"][name] = existed
            if existed:
                if not source.is_file() or source.is_symlink():
                    raise RuntimeError(
                        "{} nao e um arquivo regular; transacao recusada"
                        .format(source)
                    )
                shutil.copy2(source, transaction_dir / name)

        build = root / "build"
        if build.exists() or build.is_symlink():
            state["build_existed"] = True
            os.replace(build, state["build_backup"])
        return state
    except Exception:
        # Se a preparacao falhar depois de mover build, devolve-o antes de sair.
        backup = state.get("build_backup")
        build = root / "build"
        if state.get("build_existed") and backup is not None and backup.exists():
            if build.exists() or build.is_symlink():
                _remove_path(build)
            os.replace(backup, build)
        shutil.rmtree(transaction_dir, ignore_errors=True)
        raise


def _restore_set_target_transaction(root: Path, state: Dict[str, Any]) -> Result:
    """Descarta o estado parcial e restaura exatamente o estado anterior."""
    transaction_dir = Path(state["dir"])
    errors: List[str] = []

    try:
        build = root / "build"
        if build.exists() or build.is_symlink():
            _remove_path(build)
        if state.get("build_existed"):
            backup = Path(state["build_backup"])
            if not backup.exists() and not backup.is_symlink():
                raise RuntimeError("backup do build desapareceu")
            os.replace(backup, build)
    except Exception as exc:
        errors.append("build: {}".format(exc))

    for name, existed in state.get("files", {}).items():
        destination = root / name
        backup = transaction_dir / name
        try:
            if destination.exists() or destination.is_symlink():
                _remove_path(destination)
            if existed:
                if not backup.is_file():
                    raise RuntimeError("backup ausente")
                shutil.copy2(backup, destination)
        except Exception as exc:
            errors.append("{}: {}".format(name, exc))

    try:
        shutil.rmtree(transaction_dir)
    except FileNotFoundError:
        pass
    except Exception as exc:
        errors.append("limpeza da transacao: {}".format(exc))

    if errors:
        return (False, "; ".join(errors))
    return (True, "estado anterior restaurado")


def _commit_set_target_transaction(state: Dict[str, Any]) -> Result:
    """Confirma o novo estado removendo apenas o backup transacional."""
    try:
        shutil.rmtree(Path(state["dir"]))
        return (True, "transacao confirmada")
    except FileNotFoundError:
        return (True, "transacao confirmada")
    except Exception as exc:
        # O novo target ja esta valido. Nao se deve desfaze-lo apenas porque a
        # remocao do backup falhou; informa o caminho para limpeza posterior.
        return (False, "nao foi possivel remover {}: {}".format(
            state["dir"], exc))

def _run_idf(
    args: List[str],
    root: Path,
    idf_py: str,
    env: Dict[str, str],
    progress_cb: Optional[Callable[[str, str], None]] = None,
    rotulo: str = "idf.py",
    cancel_event: Optional[threading.Event] = None,
    timeout: int = BUILD_TIMEOUT,
) -> Result:
    """Roda um subcomando idf.py com cancelamento e diagnostico preservado."""
    if cancel_event is not None and cancel_event.is_set():
        return (False, "{} cancelado pelo usuario".format(rotulo))

    proc: Optional[subprocess.Popen] = None
    state = {"cancelled": False, "timed_out": False}
    watcher: Optional[threading.Thread] = None
    output_tail: List[str] = []

    try:
        proc = subprocess.Popen(
            ["python3", idf_py] + list(args),
            cwd=str(root),
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
            name="idf-command-watch",
        )
        watcher.start()

        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                if not line:
                    continue
                output_tail.append(line)
                if len(output_tail) > 40:
                    del output_tail[0]
                kind = _classify_line(line)
                if progress_cb:
                    progress_cb(kind, line)
                _logger.get_logger().debug("[%s] %s", rotulo, line)

        proc.wait()
        watcher.join(timeout=1)

        if state["cancelled"]:
            message = "{} cancelado pelo usuario".format(rotulo)
            if progress_cb:
                progress_cb("cancelado", message)
            return (False, message)
        if state["timed_out"]:
            message = "{} excedeu o tempo limite ({} s)".format(
                rotulo, timeout)
            if progress_cb:
                progress_cb("error", message)
            return (False, message)
        if cancel_event is not None and cancel_event.is_set():
            message = "{} cancelado pelo usuario".format(rotulo)
            if progress_cb:
                progress_cb("cancelado", message)
            return (False, message)
        if proc.returncode != 0:
            detail = "\n".join(output_tail[-20:]).strip()
            message = "{} falhou (codigo {})".format(
                rotulo, proc.returncode)
            if detail:
                message += "\nUltimas linhas do idf.py:\n" + detail
            return (False, message)
        return (True, {"returncode": 0})
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            _terminate_process_group(proc)
        return (False, "erro em {}: {}".format(rotulo, exc))


def set_target(
    project_dir,
    target,
    idf_version,
    progress_cb=None,
    cancel_event: Optional[threading.Event] = None,
):
    """
    Executa set-target como transacao recuperavel.

    Em cancelamento ou falha, sdkconfig, sdkconfig.old, dependencies.lock e
    build retornam exatamente ao estado anterior. O chamador so pode persistir
    o novo target depois de receber sucesso.
    """
    root = Path(project_dir).expanduser().resolve()
    if cancel_event is not None and cancel_event.is_set():
        return (False, "set-target cancelado pelo usuario")
    if not _idf._is_installed(idf_version):
        return (False, "ESP-IDF {} nao instalado".format(idf_version))

    ok, activation = _idf.activate(
        idf_version, cancel_event=cancel_event)
    if not ok:
        return (False, "falha ao ativar ESP-IDF: {}".format(activation))
    if cancel_event is not None and cancel_event.is_set():
        return (False, "set-target cancelado pelo usuario")

    try:
        transaction = _begin_set_target_transaction(root)
    except Exception as exc:
        return (False, "nao foi possivel preservar o projeto antes de "
                "set-target: {}".format(exc))

    env = os.environ.copy()
    env.update(activation["env_vars"])
    idf_py = str(Path(activation["IDF_PATH"]) / "tools" / "idf.py")

    try:
        ok_run, result = _run_idf(
            ["set-target", target],
            root,
            idf_py,
            env,
            progress_cb,
            rotulo="idf.py set-target",
            cancel_event=cancel_event,
        )
        if not ok_run:
            restored, restore_result = _restore_set_target_transaction(
                root, transaction)
            if not restored:
                return (False, "{}\nERRO CRITICO: falha ao restaurar o "
                        "estado anterior: {}".format(result, restore_result))
            return (False, "{}\nEstado anterior restaurado.".format(result))

        if cancel_event is not None and cancel_event.is_set():
            restored, restore_result = _restore_set_target_transaction(
                root, transaction)
            if not restored:
                return (False, "set-target cancelado pelo usuario\n"
                        "ERRO CRITICO: falha ao restaurar o estado "
                        "anterior: {}".format(restore_result))
            return (False, "set-target cancelado pelo usuario\n"
                    "Estado anterior restaurado.")

        ok_config, config_result = _config.set_target(root, target)
        if not ok_config:
            restored, restore_result = _restore_set_target_transaction(
                root, transaction)
            if not restored:
                return (False, "ESP-IDF configurado, mas o registro do "
                        "projeto falhou: {}\nERRO CRITICO: falha ao "
                        "restaurar o estado anterior: {}".format(
                            config_result, restore_result))
            return (False, "registro do projeto nao foi atualizado: {}\n"
                    "Estado anterior restaurado.".format(config_result))

        if cancel_event is not None and cancel_event.is_set():
            restored, restore_result = _restore_set_target_transaction(
                root, transaction)
            if not restored:
                return (False, "set-target cancelado pelo usuario\n"
                        "ERRO CRITICO: falha ao restaurar o estado "
                        "anterior: {}".format(restore_result))
            return (False, "set-target cancelado pelo usuario\n"
                    "Estado anterior restaurado.")

        committed, commit_result = _commit_set_target_transaction(transaction)
        response = {"target": target, "config": config_result}
        if not committed:
            response["cleanup_warning"] = commit_result
        return (True, response)
    except Exception as exc:
        restored, restore_result = _restore_set_target_transaction(
            root, transaction)
        if restored:
            return (False, "erro durante set-target: {}\n"
                    "Estado anterior restaurado.".format(exc))
        return (False, "erro durante set-target: {}\nERRO CRITICO: "
                "falha ao restaurar o estado anterior: {}".format(
                    exc, restore_result))


# Arquivo de lock gerado pelo IDF Component Manager na raiz do projeto.
# A aplicacao NUNCA o edita nem o apaga. Aqui ele e apenas LIDO, so o
# mtime, para decidir reconfigure.
DEPENDENCIES_LOCK = "dependencies.lock"
COMPONENT_MANIFEST = "idf_component.yml"


def needs_reconfigure(project_dir: str | Path) -> Result:
    """Decide se o projeto precisa de 'idf.py reconfigure' antes do build."""
    root = Path(project_dir).expanduser().resolve()
    manifest = root / "main" / COMPONENT_MANIFEST
    if not manifest.is_file():
        return (True, {"needed": False,
                       "reason": "projeto sem manifesto de bibliotecas"})

    cache = root / "build" / "CMakeCache.txt"
    if not cache.is_file():
        return (True, {"needed": False,
                       "reason": "projeto ainda nao configurado; o proprio "
                                 "build faz a configuracao inicial"})

    manifest_mtime = manifest.stat().st_mtime
    lock = root / DEPENDENCIES_LOCK
    if not lock.is_file():
        return (True, {"needed": True,
                       "reason": "manifesto presente, sem dependencies.lock"})
    if manifest_mtime > lock.stat().st_mtime:
        return (True, {"needed": True,
                       "reason": "manifesto mais novo que dependencies.lock"})
    if manifest_mtime > cache.stat().st_mtime:
        return (True, {"needed": True,
                       "reason": "manifesto mais novo que a configuracao "
                                 "do build"})
    return (True, {"needed": False, "reason": "manifesto ja aplicado"})


def validate_code_chip(project_dir: str | Path) -> Result:
    """Valida recursos declarados contra o perfil associado ao projeto.

    Não interroga hardware e não altera arquivos. Projeto sem recursos
    declarados não exige perfil físico. Quando há recursos, a associação por
    MAC e a prontidão do perfil tornam-se pré-condições do build.
    """
    root = Path(project_dir).expanduser().resolve()
    ok, cfg = _config.read(root)
    if not ok:
        return (False, {
            "status": "error",
            "blocking": True,
            "message": "config do projeto ilegível: {}".format(cfg),
        })

    features = cfg.get("features", [])
    if not isinstance(features, list):
        return (False, {
            "status": "error",
            "blocking": True,
            "message": "campo features do projeto está corrompido",
        })

    declared = [str(item).strip().lower() for item in features if str(item).strip()]
    if not declared:
        return (True, {
            "status": "not_declared",
            "blocking": False,
            "message": "o projeto não declarou recursos opcionais para validar",
            "declared": [],
            "conflitos": [],
            "avisos": [],
            "ignorados": [],
            "profile_mac": "",
            "board_name": "",
            "chip_family": "",
        })

    mac = str(cfg.get("board_profile_mac") or "").strip().lower()
    if not mac:
        return (False, {
            "status": "error",
            "blocking": True,
            "message": (
                "o projeto declara recursos, mas não possui perfil físico "
                "associado; associe um perfil antes de compilar"
            ),
            "declared": declared,
        })

    ok_profile, profile = _boards.get_profile(mac)
    if not ok_profile:
        return (False, {
            "status": "error",
            "blocking": True,
            "message": "perfil associado '{}' indisponível: {}".format(
                mac, profile
            ),
            "declared": declared,
            "profile_mac": mac,
        })

    if not bool(profile.get("profile_ready")):
        reasons = profile.get("profile_readiness_reasons") or []
        detail = "; ".join(str(item) for item in reasons) or "motivo não informado"
        return (False, {
            "status": "error",
            "blocking": True,
            "message": (
                "perfil associado ainda não está pronto: {}".format(detail)
            ),
            "declared": declared,
            "profile_mac": mac,
            "board_name": str(profile.get("board_name") or "Não identificada"),
            "chip_family": str(profile.get("chip_family") or ""),
        })

    ok_report, report = _code_chip.evaluate(declared, profile)
    if not ok_report:
        return (False, {
            "status": "error",
            "blocking": True,
            "message": str(report),
            "declared": declared,
            "profile_mac": mac,
        })

    result = dict(report)
    result.update({
        "profile_mac": mac,
        "board_name": str(profile.get("board_name") or "Não identificada"),
        "chip_family": str(profile.get("chip_family") or report.get("chip_family") or ""),
    })
    if result.get("blocking"):
        return (False, result)
    return (True, result)


def build(
    project_dir: str | Path,
    progress_cb: Optional[Callable[[str, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    *,
    background: bool = True,
) -> Result:
    """Compila o projeto com reconfigure opcional e cancelamento confirmado."""
    root = Path(project_dir).expanduser().resolve()

    ok, idf_version = _precheck(root)
    if not ok:
        return (False, idf_version)
    if cancel_event is not None and cancel_event.is_set():
        return (False, "build cancelado pelo usuario")

    ok_code_chip, code_chip = validate_code_chip(root)
    if not ok_code_chip:
        message = (
            code_chip.get("message", "validação código × chip falhou")
            if isinstance(code_chip, dict) else str(code_chip)
        )
        return (False, "validação código × chip: {}".format(message))
    if code_chip.get("status") == "warning" and progress_cb:
        progress_cb("warning", "Validação código × chip: {}".format(
            code_chip.get("message", "capacidade desconhecida")
        ))

    if not _idf._is_installed(idf_version):
        return (False, "ESP-IDF {} nao esta instalado; instale antes de "
                       "compilar".format(idf_version))

    ok_activate, ativacao = _idf.activate(
        idf_version, cancel_event=cancel_event)
    if not ok_activate:
        return (False, "falha ao ativar ESP-IDF {}: {}".format(
            idf_version, ativacao))

    env = os.environ.copy()
    env.update(ativacao["env_vars"])
    idf_py = str(Path(ativacao["IDF_PATH"]) / "tools" / "idf.py")

    def _do_build():
        if cancel_event is not None and cancel_event.is_set():
            return (False, "build cancelado pelo usuario")

        ok_reconfigure, info_reconfigure = needs_reconfigure(root)
        if ok_reconfigure and info_reconfigure.get("needed"):
            if progress_cb:
                progress_cb(
                    "info",
                    "Bibliotecas mudaram ({}); reconfigurando o projeto..."
                    .format(info_reconfigure.get("reason", "")),
                )
            ok_run, result_run = _run_idf(
                ["reconfigure"],
                root,
                idf_py,
                env,
                progress_cb,
                rotulo="idf.py reconfigure",
                cancel_event=cancel_event,
            )
            if not ok_run:
                return (False, result_run)

        if cancel_event is not None and cancel_event.is_set():
            return (False, "build cancelado pelo usuario")

        ok_run, result_run = _run_idf(
            ["build"],
            root,
            idf_py,
            env,
            progress_cb,
            rotulo="idf.py build",
            cancel_event=cancel_event,
        )
        if not ok_run:
            return (False, result_run)

        message = "build concluido com sucesso"
        if progress_cb:
            progress_cb("info", message)
        _logger.get_logger().info("build de '%s' concluido", root.name)
        return (True, {
            "version": idf_version,
            "project": root.name,
            "success": True,
            "message": message,
            "code_chip_validation": code_chip,
        })

    if background:
        thread = threading.Thread(
            target=_do_build,
            daemon=True,
            name="idf-build",
        )
        thread.start()
        return (True, {
            "status": "iniciado",
            "version": idf_version,
            "project": root.name,
        })
    return _do_build()


def check_build_valid(
    project_dir: str | Path,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """Verifica o build sem ignorar cancelamento durante a busca de fontes."""
    root = Path(project_dir).expanduser().resolve()
    if cancel_event is not None and cancel_event.is_set():
        return (False, "verificacao do build cancelada pelo usuario")
    build_dir = root / "build"
    if not build_dir.is_dir():
        return (True, {"valid": False, "reason": "projeto ainda nao compilado"})

    bins = list(build_dir.glob("*.bin"))
    app_bins = [item for item in bins if item.name not in
                ("bootloader.bin", "partition-table.bin")]
    if not app_bins:
        return (True, {"valid": False, "reason": "binario do app nao encontrado"})

    bin_path = app_bins[0]
    bin_mtime = bin_path.stat().st_mtime
    for src_dir in (root / "main", root / "components"):
        if not src_dir.is_dir():
            continue
        for src in src_dir.rglob("*"):
            if cancel_event is not None and cancel_event.is_set():
                return (False, "verificacao do build cancelada pelo usuario")
            if src.suffix in (".c", ".cpp", ".h", ".hpp") and src.is_file():
                if src.stat().st_mtime > bin_mtime:
                    return (True, {
                        "valid": False,
                        "reason": "fonte mais novo que o binario; "
                                  "recompile antes de gravar",
                        "bin_path": str(bin_path),
                    })

    return (True, {"valid": True, "bin_path": str(bin_path)})



def list_supported_targets(
    idf_version: str,
    cancel_event: Optional[threading.Event] = None,
) -> Result:
    """
    Consulta a própria instalação da versão do projeto com
    `idf.py --list-targets`.
    """
    version = str(idf_version or "").strip()
    if not version:
        return (False, "versão ESP-IDF não definida")
    if cancel_event is not None and cancel_event.is_set():
        return (False, "consulta de targets cancelada pelo usuário")
    if not _idf._is_installed(version):
        return (False, f"ESP-IDF {version} não instalado")

    ok_activation, activation = _idf.activate(
        version, cancel_event=cancel_event
    )
    if not ok_activation:
        return (False, f"falha ao ativar ESP-IDF: {activation}")

    lines: List[str] = []

    def _collect(_kind: str, line: str) -> None:
        lines.append(line)

    env = os.environ.copy()
    env.update(activation["env_vars"])
    idf_root = Path(activation["IDF_PATH"])
    idf_py = str(idf_root / "tools" / "idf.py")
    ok_run, result = _run_idf(
        ["--list-targets"],
        idf_root,
        idf_py,
        env,
        progress_cb=_collect,
        rotulo="idf.py --list-targets",
        cancel_event=cancel_event,
        timeout=120,
    )
    if not ok_run:
        return (False, result)

    targets: List[str] = []
    for line in lines:
        for token in re.findall(r"\b(?:esp32[a-z0-9]*|linux)\b", line.lower()):
            if token not in targets:
                targets.append(token)
    if not targets:
        return (
            False,
            "idf.py --list-targets não devolveu uma lista reconhecível"
            + (f": {' | '.join(lines[-5:])}" if lines else ""),
        )
    return (True, targets)

__all__ = [
    "build", "validate_code_chip", "set_target", "list_supported_targets",
    "check_build_valid", "needs_reconfigure",
    "BUILD_TIMEOUT", "DEPENDENCIES_LOCK", "COMPONENT_MANIFEST",
]
