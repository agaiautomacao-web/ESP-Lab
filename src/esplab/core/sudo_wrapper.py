#!/usr/bin/env python3
"""
Wrapper de sudo seguro (@E2-T2.1).

Executa comandos com privilegio via 'sudo -S' (senha pelo stdin).
A senha NUNCA e persistida, logada, ou colocada em variavel de ambiente.
E descartada da memoria apos o uso — responsabilidade da camada acima
solicitar via prompt seguro e nao armazenar.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import subprocess
from typing import Any, List, Optional, Tuple

Result = Tuple[bool, Any]

# Timeout padrao para comandos sudo (segundos).
DEFAULT_TIMEOUT = 60


def _build_sudo_cmd(cmd: List[str]) -> List[str]:
    """Monta o comando sudo com -S (le senha do stdin) e -k (invalida cache)."""
    return ["sudo", "-S", "-k", "--"] + cmd


def check_sudo(password: str, timeout: int = 10) -> Result:
    """
    Verifica se a senha sudo esta correta sem executar nada destrutivo.
    Usa 'sudo -S -k true' — comando inofensivo que valida a senha.
    Retorna (True, None) se correta, (False, motivo) se incorreta.
    """
    if not password:
        return (False, "senha nao pode ser vazia")
    try:
        proc = subprocess.run(
            ["sudo", "-S", "-k", "true"],
            input=password + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return (True, None)
        return (False, "senha incorreta ou sudo nao disponivel")
    except subprocess.TimeoutExpired:
        return (False, "timeout ao verificar senha sudo")
    except FileNotFoundError:
        return (False, "sudo nao encontrado no sistema")
    except Exception as e:
        return (False, "erro ao verificar sudo: {}".format(e))
    finally:
        # Garante que a referencia a senha seja descartada.
        password = ""  # noqa: F841


def run_sudo(cmd: List[str], password: str,
             timeout: int = DEFAULT_TIMEOUT,
             capture: bool = True) -> Result:
    """
    Executa um comando com privilegio sudo.

    cmd     : lista de strings (ex. ['chmod', '777', '/dev/ttyACM0']).
    password: senha sudo (descartada apos uso; nunca logada).
    timeout : segundos antes de abortar.
    capture : True -> captura stdout/stderr; False -> herda o terminal.

    Retorna (True, {stdout, stderr, returncode}) ou (False, motivo).
    """
    if not cmd:
        return (False, "comando vazio")
    if not password:
        return (False, "senha nao pode ser vazia")

    sudo_cmd = _build_sudo_cmd(cmd)
    try:
        proc = subprocess.run(
            sudo_cmd,
            input=password + "\n",
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        stdout = (proc.stdout or "").strip() if capture else ""
        stderr = (proc.stderr or "").strip() if capture else ""

        # Remove linha de prompt do sudo do stderr (nao e erro real).
        stderr_limpo = "\n".join(
            l for l in stderr.splitlines()
            if not l.startswith("[sudo]")
        ).strip()

        if proc.returncode != 0:
            motivo = stderr_limpo or "comando falhou sem mensagem de erro"
            return (False, "sudo falhou (codigo {}): {}".format(
                proc.returncode, motivo))

        return (True, {
            "stdout":     stdout,
            "stderr":     stderr_limpo,
            "returncode": proc.returncode,
        })
    except subprocess.TimeoutExpired:
        return (False, "timeout ({} s) ao executar: {}".format(
            timeout, " ".join(cmd)))
    except FileNotFoundError:
        return (False, "sudo nao encontrado no sistema")
    except Exception as e:
        return (False, "erro ao executar sudo: {}".format(e))
    finally:
        password = ""  # noqa: F841


__all__ = ["check_sudo", "run_sudo"]
