#!/usr/bin/env python3
"""
terminal_launcher.py — Abre um comando numa JANELA de terminal nova.

Usado pelo Monitor para abrir o visualizador (esplab_monitor) numa janela
separada, mantendo a TUI viva. Nao bloqueia: dispara e volta.

So faz sentido com ambiente grafico (DISPLAY/WAYLAND_DISPLAY). Sem ele
(SSH puro), retorna (False, motivo) e o chamador decide o fallback
(ex.: suspend() na propria TTY).

Contrato: (ok, result_or_error), nunca lanca, strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from shutil import which
from typing import Callable, Sequence

Result = tuple[bool, str]


# Cada construtor recebe o argv do comando (lista) e devolve o argv do
# emulador que roda esse comando numa janela nova.
def _cmd_gnome(argv: list[str]) -> list[str]:
    return ["gnome-terminal", "--", *argv]


def _cmd_konsole(argv: list[str]) -> list[str]:
    return ["konsole", "-e", *argv]


def _cmd_xfce4(argv: list[str]) -> list[str]:
    return ["xfce4-terminal", "--command",
            " ".join(shlex.quote(a) for a in argv)]


def _cmd_kitty(argv: list[str]) -> list[str]:
    return ["kitty", *argv]


def _cmd_alacritty(argv: list[str]) -> list[str]:
    return ["alacritty", "-e", *argv]


def _cmd_tilix(argv: list[str]) -> list[str]:
    return ["tilix", "-e", " ".join(shlex.quote(a) for a in argv)]


def _cmd_xterm(argv: list[str]) -> list[str]:
    return ["xterm", "-e", *argv]


def _cmd_xte(argv: list[str]) -> list[str]:
    return ["x-terminal-emulator", "-e", *argv]


# Ordem de preferencia. gnome-terminal antes do x-terminal-emulator: a
# sintaxe nativa "--" e mais robusta que o "-e" do wrapper.
_EMULADORES: list[tuple[str, Callable[[list[str]], list[str]]]] = [
    ("gnome-terminal", _cmd_gnome),
    ("konsole", _cmd_konsole),
    ("xfce4-terminal", _cmd_xfce4),
    ("kitty", _cmd_kitty),
    ("alacritty", _cmd_alacritty),
    ("tilix", _cmd_tilix),
    ("xterm", _cmd_xterm),
    ("x-terminal-emulator", _cmd_xte),
]


def has_gui() -> bool:
    """True se ha ambiente grafico (X11 ou Wayland)."""
    return bool(os.environ.get("DISPLAY")
                or os.environ.get("WAYLAND_DISPLAY"))


def detectar_emulador() -> tuple[str, Callable] | None:
    """Primeiro emulador disponivel no PATH, ou None."""
    for nome, construtor in _EMULADORES:
        if which(nome):
            return (nome, construtor)
    return None


def open_in_terminal(
    argv: Sequence[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    hold_on_error: bool = True,
    title: str | None = None,
) -> Result:
    """
    Abre `argv` numa janela de terminal nova. NAO bloqueia.

    - Sem ambiente grafico  -> (False, motivo): chamador faz o fallback.
    - Sem emulador conhecido -> (False, motivo).
    - hold_on_error: se o comando sair com erro, mantem a janela aberta
      para o usuario ler a mensagem. Saida limpa (rc 0) fecha sozinha.

    IMPORTANTE (gnome-terminal): o comando roda sob o gnome-terminal-server,
    que NAO herda o env deste processo. Por isso o env vai explicito no
    proprio comando, via `env VAR=val ...`, e nao pelo parametro env= do
    Popen.

    Retorna (True, nome_do_emulador) ou (False, motivo).
    """
    if not has_gui():
        return (False, "sem ambiente grafico "
                       "(DISPLAY/WAYLAND_DISPLAY ausentes)")
    det = detectar_emulador()
    if det is None:
        return (False, "nenhum emulador de terminal reconhecido no sistema")
    nome, construtor = det

    comando = list(argv)

    # Env explicito no comando (contorna o server-env do gnome-terminal).
    if env:
        comando = ["env"] + [f"{k}={v}" for k, v in env.items()] + comando

    # Envolve em shell para segurar a janela so em caso de erro.
    if hold_on_error or title:
        linha = " ".join(shlex.quote(a) for a in comando)
        if title:
            linha = ("printf '\\033]0;%s\\007' "
                     + shlex.quote(title) + "; " + linha)
        payload = (
            linha
            + "; __ec=$?; "
            + "[ $__ec -ne 0 ] && { echo; "
            + "read -r -p \"[saiu com erro $__ec - Enter para fechar] \"; }; "
            + "exit $__ec"
        )
        comando = ["bash", "-c", payload]

    cmd = construtor(comando)
    try:
        subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        return (False, f"falha ao abrir terminal ({nome}): "
                       f"{type(exc).__name__}: {exc}")
    return (True, nome)


__all__ = ["open_in_terminal", "detectar_emulador", "has_gui"]
