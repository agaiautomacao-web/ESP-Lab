#!/usr/bin/env python3
"""
Wrapper cancelável de subprocess para a inspeção de hardware.

Executa cada comando em grupo próprio. Cancelamento e timeout encerram a
árvore inteira antes do retorno.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import Optional

from .models import ExecResult

PROCESS_TERM_TIMEOUT = 5


def _terminate_process_group(proc: subprocess.Popen) -> None:
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


def run_cmd(
    cmd: list[str],
    timeout: int = 60,
    cancel_event: Optional[threading.Event] = None,
) -> ExecResult:
    """Executa sem shell; nunca lança."""
    if cancel_event is not None and cancel_event.is_set():
        return ExecResult(
            cmd=cmd, ok=False, rc=None,
            erro="cancelado pelo usuário",
        )

    proc: subprocess.Popen | None = None
    state = {"cancelled": False, "timed_out": False}
    watcher: threading.Thread | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
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
            target=_watch, daemon=True, name="inspection-command-watch"
        )
        watcher.start()
        stdout, stderr = proc.communicate()
        watcher.join(timeout=1)

        if state["cancelled"] or (
            cancel_event is not None and cancel_event.is_set()
        ):
            return ExecResult(
                cmd=cmd, ok=False, rc=proc.returncode,
                stdout=stdout or "", stderr=stderr or "",
                erro="cancelado pelo usuário",
            )
        if state["timed_out"]:
            return ExecResult(
                cmd=cmd, ok=False, rc=proc.returncode,
                stdout=stdout or "", stderr=stderr or "",
                erro=f"timeout após {timeout}s", timeout=True,
            )
        return ExecResult(
            cmd=cmd, ok=(proc.returncode == 0), rc=proc.returncode,
            stdout=stdout or "", stderr=stderr or "",
        )
    except FileNotFoundError as exc:
        return ExecResult(
            cmd=cmd, ok=False, rc=None,
            erro=f"comando não encontrado: {exc.filename}",
        )
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            _terminate_process_group(proc)
        return ExecResult(
            cmd=cmd, ok=False, rc=None,
            erro=f"exceção: {type(exc).__name__}: {exc}",
        )


__all__ = ["run_cmd", "PROCESS_TERM_TIMEOUT"]
