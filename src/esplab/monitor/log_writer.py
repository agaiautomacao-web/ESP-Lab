#!/usr/bin/env python3
"""
Gravacao de log do monitor serial (@E10-T10.6).

Grava o stream serial em arquivo rotativo por tamanho, independente
da exibicao na tela. Tela e log sao canais separados — limpar a tela
nao afeta o arquivo; parar o monitor nao fecha o log forcadamente.

Principios (PROJECT.md cap. 10):
  - Log completo em disco (a tela tem buffer limitado, o log nao).
  - Rotativo por tamanho (padrao: 5MB x 3 backups).
  - Abertura pelo menu reutiliza o monitor como visualizador (@E10-T10.7).
  - Thread-safe: multiplas threads podem chamar write_line().
  - Carimbo em HORA LOCAL, igual ao que o daemon manda para a tela.
    Antes o log usava UTC e a tela hora local: a mesma linha saia com
    horarios diferentes nos dois canais, e comparar tela com arquivo
    (o que se faz depurando) enganava.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import logging
import logging.handlers
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

Result = Tuple[bool, Any]

DEFAULT_MAX_BYTES  = 5 * 1024 * 1024  # 5 MB
DEFAULT_BACKUPS    = 3
LOG_SUFFIX         = ".monitor.log"


class MonitorLogWriter:
    """
    Grava linhas do monitor serial em arquivo rotativo.
    Thread-safe. Independente do buffer de exibicao.
    """

    def __init__(
        self,
        log_path: str | Path,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUPS,
        add_timestamp: bool = True,
    ) -> None:
        self._path          = Path(log_path)
        self._max_bytes     = max_bytes
        self._backup_count  = backup_count
        self._add_timestamp = add_timestamp
        self._handler: Optional[logging.handlers.RotatingFileHandler] = None
        self._logger: Optional[logging.Logger] = None
        self._lock   = threading.Lock()
        self._open   = False

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def log_path(self) -> Path:
        return self._path

    def open(self) -> Result:
        """Abre (ou reabre) o arquivo de log."""
        with self._lock:
            if self._open:
                return (False, "log ja esta aberto em {}".format(self._path))
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.handlers.RotatingFileHandler(
                    str(self._path),
                    maxBytes=self._max_bytes,
                    backupCount=self._backup_count,
                    encoding="utf-8",
                )
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger_name = "monitor.{}".format(id(self))
                logger = logging.getLogger(logger_name)
                logger.setLevel(logging.DEBUG)
                logger.propagate = False
                logger.addHandler(handler)
                self._handler = handler
                self._logger  = logger
                self._open    = True
                return (True, {"path": str(self._path)})
            except Exception as e:
                return (False, "erro ao abrir log: {}".format(e))

    def write_line(self, line: str) -> Result:
        """Grava uma linha no log. Thread-safe."""
        with self._lock:
            if not self._open or self._logger is None:
                return (False, "log nao esta aberto")
            try:
                if self._add_timestamp:
                    ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    msg = "[{}] {}".format(ts, line)
                else:
                    msg = line
                self._logger.info(msg)
                return (True, None)
            except Exception as e:
                return (False, "erro ao gravar linha: {}".format(e))

    def close(self) -> Result:
        """Fecha o arquivo de log (flush + close)."""
        with self._lock:
            if not self._open:
                return (False, "log nao esta aberto")
            try:
                if self._handler:
                    self._handler.flush()
                    self._handler.close()
                    if self._logger:
                        self._logger.removeHandler(self._handler)
                self._open    = False
                self._handler = None
                self._logger  = None
                return (True, {"message": "log fechado: {}".format(self._path)})
            except Exception as e:
                return (False, "erro ao fechar log: {}".format(e))

    def read_tail(self, n_lines: int = 100) -> Result:
        """
        Le as ultimas N linhas do log do disco (para o visualizador @E10-T10.7).
        Funciona mesmo com o log aberto (leitura independente).
        """
        if not self._path.is_file():
            return (False, "arquivo de log nao encontrado: {}".format(self._path))
        try:
            lines = self._path.read_text(encoding="utf-8",
                                          errors="replace").splitlines()
            return (True, lines[-n_lines:])
        except Exception as e:
            return (False, "erro ao ler log: {}".format(e))


def make_log_path(port: str, logs_dir: str | Path) -> Path:
    """
    Deriva o caminho do log a partir da porta e do diretorio de logs.
    Ex.: /dev/ttyACM0 -> logs_dir/ttyACM0.monitor.log
    """
    port_name = Path(port).name
    return Path(logs_dir) / "{}{}".format(port_name, LOG_SUFFIX)


__all__ = ["MonitorLogWriter", "make_log_path",
           "DEFAULT_MAX_BYTES", "DEFAULT_BACKUPS"]
