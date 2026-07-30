#!/usr/bin/env python3
"""
Log interno da aplicação ESP Lab (@E1-T1.6).

Registra eventos da própria aplicação — operações relevantes, erros tratados,
falhas capturadas pelo guard. NÃO é o log do monitor serial (saída do ESP32),
que é tratado separadamente na etapa Monitor (@E10).

Características:
  - Arquivo no diretório derivado pelo paths (data_home/logs); nada fixo.
  - Rotação por tamanho (RotatingFileHandler).
  - Mensagens em português.
  - Nunca derruba a aplicação: se não conseguir escrever em arquivo
    (permissão, disco cheio), degrada para console sem quebrar.

Convenção: identificadores em inglês, strings em português.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import paths as _paths

# --- Parâmetros de rotação (ajustáveis conforme a necessidade real) ---------
MAX_BYTES = 5 * 1024 * 1024   # 5 MB por arquivo
BACKUP_COUNT = 3              # mantém 3 backups (~20 MB de histórico no total)
LOG_FILENAME = "esplab.log"
LOGGER_NAME = "esplab"

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LINE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# Evita adicionar handlers repetidos se get_logger() for chamado várias vezes.
_configured = False


def log_file() -> Path:
    """Caminho do arquivo de log interno, sob data_home/logs."""
    return _paths.get_paths().logs / LOG_FILENAME


def get_logger() -> logging.Logger:
    """
    Devolve o logger da aplicação, configurado uma única vez.

    Tenta escrever em arquivo rotativo; se falhar, cai para console, sempre
    sem lançar exceção para a camada de cima.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)

    if _configured:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(_LINE_FORMAT, datefmt=_DATE_FORMAT)

    # Tenta handler de arquivo rotativo.
    try:
        path = log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(path),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        # Degrada para console — a aplicação não pode cair por causa do log.
        fallback = logging.StreamHandler()
        fallback.setFormatter(formatter)
        logger.addHandler(fallback)
        logger.warning("log em arquivo indisponível, usando console: %s", e)

    _configured = True
    return logger


def reset() -> None:
    """
    Remove os handlers e permite reconfigurar. Útil em testes e ao trocar de
    diretório de dados. Fora de teste, raramente necessário.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    _configured = False


__all__ = ["get_logger", "log_file", "reset", "MAX_BYTES", "BACKUP_COUNT"]
