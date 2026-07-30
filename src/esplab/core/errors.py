#!/usr/bin/env python3
"""
Padrão de resultado e encapsulamento de erros do ESP Lab (@E1-T1.5).

Toda a aplicação fala a mesma língua de retorno: (ok, result_or_error).
Nenhuma operação relevante lança exceção para a camada de cima — falha vira
um par (False, motivo) que a TUI exibe no painel de status, sem derrubar nada.

Este módulo oferece:
  - helpers ok()/err() para construir o par de forma legível;
  - guard(): encapsula uma operação externa (esptool, git, subprocess, IO),
    convertendo qualquer exceção em (False, motivo) com mensagem em português;
  - is_ok()/unwrap() para consumir resultados.

Convenção: identificadores em inglês, strings em português.
"""
from __future__ import annotations

from typing import Any, Callable, Tuple, TypeVar

Result = Tuple[bool, Any]  # (ok, result_or_error)
T = TypeVar("T")


# ==========================================================
# CONSTRUTORES
# ==========================================================

def ok(value: Any = None) -> Result:
    """Resultado de sucesso: (True, value)."""
    return (True, value)


def err(reason: Any) -> Result:
    """Resultado de falha: (False, reason). 'reason' costuma ser uma string PT."""
    return (False, reason)


# ==========================================================
# ENCAPSULAMENTO DE OPERAÇÕES EXTERNAS
# ==========================================================

def guard(operation: Callable[[], T], *, context: str = "") -> Result:
    """
    Executa `operation()` capturando qualquer exceção.

    Sucesso -> (True, retorno_da_operacao)
    Exceção -> (False, motivo)  — com o contexto opcional para facilitar o log.

    Uso típico:
        res = guard(lambda: subprocess.run(...), context="leitura do chip")
    """
    try:
        return (True, operation())
    except Exception as e:
        prefix = f"{context}: " if context else ""
        return (False, f"{prefix}{type(e).__name__}: {e}")


# ==========================================================
# CONSUMO DE RESULTADOS
# ==========================================================

def is_ok(result: Result) -> bool:
    """True se o resultado representa sucesso."""
    return bool(result and result[0] is True)


def unwrap(result: Result, default: Any = None) -> Any:
    """
    Devolve o valor em caso de sucesso; senão devolve `default`.
    Não lança — coerente com a filosofia de não derrubar a aplicação.
    """
    return result[1] if is_ok(result) else default


def reason(result: Result) -> Any:
    """Devolve o motivo da falha (ou None se foi sucesso)."""
    return None if is_ok(result) else (result[1] if result else "resultado vazio")


__all__ = [
    "Result", "ok", "err", "guard", "is_ok", "unwrap", "reason",
]
