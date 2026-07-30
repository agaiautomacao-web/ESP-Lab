#!/usr/bin/env python3
"""
Monitor serial — leitura nao-bloqueante e escrita explicita (@E10).

Le a porta serial em thread separada e emite linhas via callback.
Principios (PROJECT.md cap. 10):
  - Nunca envia nada por conta propria: so transmite ao chip o que o
    usuario digitar explicitamente. A aplicacao nao injeta comandos.
  - Nunca fecha nem limpa automaticamente.
  - Buffer de exibicao limitado (N linhas); descarta do topo sem
    perder o log em disco.
  - Tela e canal independentes: limpar tela nao afeta o stream.
  - Prioridade do chip: mesma porta em uso pelo flash -> desconecta
    o stream (nao fecha, nao limpa) e oferece reconectar.

Fusao @E10 (banco de provas tests_e10/serial_engine.py -> producao):
  1. stop() idempotente PRESERVADO (corrigiu @E7-T7.6): monitor ja
     parado e estado final valido, nao erro.
  2. Escrita adicionada: self._serial sob _lock, write_bytes(),
     write_text(); _read_loop atribui e limpa self._serial.
  3. Ordem do finally do _read_loop CORRIGIDA: o estado
     (_serial/_connected) e limpo ANTES de fechar a porta. Na ordem
     inversa havia janela em que write_bytes via _connected=True e
     escrevia num objeto ja fechado.
  4. restart_port() decide por ok, nao por substring da mensagem de
     erro. Testar erro por texto e fragil e foi eliminado.

Retorno (ok, result_or_error); nunca lanca; strings em portugues.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Deque, List, Optional, Tuple

Result = Tuple[bool, Any]

DEFAULT_BUFFER_LINES = 500
DEFAULT_BAUDRATE = 115200
READ_TIMEOUT = 0.1


class SerialMonitor:
    """Monitor serial nao-bloqueante. Um monitor por porta."""

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        buffer_lines: int = DEFAULT_BUFFER_LINES,
        on_line: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.port             = port
        self.baudrate         = baudrate
        self.buffer_lines     = buffer_lines
        self._on_line         = on_line
        self._on_error        = on_error
        self._buffer: Deque[str] = deque(maxlen=buffer_lines)
        self._thread: Optional[threading.Thread] = None
        self._stop_event      = threading.Event()
        self._connected       = False
        self._lock            = threading.Lock()
        self._timestamp       = False
        self._wordwrap        = True
        self._flush_requested = False
        self._serial: Any     = None   # objeto Serial vivo, sob _lock

    # ----------------------------------------------------------
    # ESTADO
    # ----------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def get_buffer(self) -> List[str]:
        with self._lock:
            return list(self._buffer)

    def clear_screen_buffer(self) -> None:
        """Limpa buffer de exibicao (nao afeta log em disco)."""
        with self._lock:
            self._buffer.clear()

    # ----------------------------------------------------------
    # ESCRITA NA SERIAL (@E10 — monitor bidirecional)
    # ----------------------------------------------------------
    # A escrita nunca parte da aplicacao: quem chama e sempre um
    # caminho iniciado pelo usuario (tecla digitada no visualizador).

    def write_bytes(self, data: bytes) -> Result:
        """
        Envia bytes ao chip. Requer monitor conectado.
        Thread-safe: serializa a escrita com o _lock existente. O lock
        e mantido durante write+flush; com a UART em velocidade normal
        isso e da ordem de microssegundos e nao atrasa a leitura.
        """
        if not data:
            return (False, "nada a enviar")
        with self._lock:
            ser = self._serial
            if not self._connected or ser is None:
                return (False, "monitor nao esta conectado")
            try:
                written = ser.write(data)
                ser.flush()
                return (True, {"bytes": written})
            except Exception as e:
                return (False, "erro ao escrever na serial: {}".format(e))

    def write_text(self, text: str, newline: str = "\r\n") -> Result:
        """Envia texto ao chip (conveniencia sobre write_bytes)."""
        try:
            payload = "{}{}".format(text, newline).encode("utf-8")
        except Exception as e:
            return (False, "erro ao codificar texto: {}".format(e))
        return self.write_bytes(payload)

    # ----------------------------------------------------------
    # CONTROLES DE EXIBICAO (@E10-T10.3)
    # ----------------------------------------------------------

    def set_timestamp(self, enabled: bool) -> None:
        """Ativa/desativa carimbo de hora nas linhas do buffer."""
        with self._lock:
            self._timestamp = enabled

    def set_wordwrap(self, enabled: bool) -> None:
        """Ativa/desativa quebra de linha na exibicao."""
        with self._lock:
            self._wordwrap = enabled

    def get_display_options(self) -> dict:
        """Retorna opcoes de exibicao atuais."""
        with self._lock:
            return {
                "timestamp": self._timestamp,
                "wordwrap":  self._wordwrap,
            }

    # ----------------------------------------------------------
    # CONTROLE DE CICLO DE VIDA
    # ----------------------------------------------------------

    def start(self) -> Result:
        """Inicia a leitura serial em thread separada."""
        if self.is_running:
            return (False, "monitor ja esta em execucao na porta {}".format(
                self.port))
        try:
            import serial as _serial  # noqa: F401
        except ImportError:
            return (False, "pyserial nao instalado no app-venv")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._read_loop,
            name="monitor-{}".format(self.port),
            daemon=True,
        )
        self._thread.start()
        return (True, {"port": self.port, "baudrate": self.baudrate})

    def stop(self) -> Result:
        """
        Para a leitura e confirma que a thread terminou antes de declarar
        a porta liberada. A operacao e idempotente: monitor ja parado tambem
        representa estado final valido para rotinas de limpeza.
        """
        thread = self._thread
        if thread is None or not thread.is_alive():
            with self._lock:
                self._connected = False
                self._serial    = None
            self._thread = None
            return (True, {
                "message": "monitor ja estava parado (porta liberada)",
                "already_stopped": True,
            })

        self._stop_event.set()
        thread.join(timeout=3)
        if thread.is_alive():
            return (
                False,
                "monitor nao encerrou no tempo limite; "
                "a porta pode continuar em uso",
            )

        with self._lock:
            self._connected = False
            self._serial    = None
        self._thread = None
        return (True, {
            "message": "monitor parado; porta liberada (buffer preservado)",
            "already_stopped": False,
        })

    def disconnect_stream(self) -> Result:
        """Desconecta stream (libera porta para flash) sem limpar painel."""
        return self.stop()

    def reconnect(self) -> Result:
        """Reconecta apos disconnect_stream ou falha."""
        if self.is_running:
            return (False, "monitor ja esta em execucao")
        return self.start()

    # ----------------------------------------------------------
    # CONTROLES DE PORTA (@E10-T10.4)
    # ----------------------------------------------------------

    def flush_port(self) -> Result:
        """
        Esvazia o buffer enfileirado da serial sem fechar a conexao.
        Destrava o fluxo quando dados velhos congestionam o canal.
        So funciona com monitor em execucao.
        """
        if not self.is_running or not self.is_connected:
            return (False, "monitor nao esta conectado")
        with self._lock:
            self._flush_requested = True
        return (True, {"message": "flush solicitado"})

    def close_port(self) -> Result:
        """Encerra a conexao com a porta. Alias semantico de stop()."""
        return self.stop()

    def restart_port(self) -> Result:
        """
        Fecha, limpa e reabre a porta.
        Resolve travamentos persistentes sem perder o buffer de exibicao.
        Como stop() e idempotente, "ja estava parado" e sucesso: qualquer
        False aqui e falha real de encerramento.
        """
        ok, res = self.stop()
        if not ok:
            return (False, "falha ao fechar para restart: {}".format(res))
        return self.reconnect()

    # ----------------------------------------------------------
    # LOOP DE LEITURA
    # ----------------------------------------------------------

    def _read_loop(self) -> None:
        """Thread interna de leitura. Nunca lanca para fora."""
        import serial as _serial
        ser = None
        try:
            ser = _serial.Serial(self.port, self.baudrate, timeout=READ_TIMEOUT)
            with self._lock:
                self._serial    = ser
                self._connected = True
            while not self._stop_event.is_set():
                try:
                    if self._flush_requested:
                        ser.reset_input_buffer()
                        with self._lock:
                            self._flush_requested = False
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    with self._lock:
                        self._buffer.append(line)
                    if self._on_line:
                        try:
                            self._on_line(line)
                        except Exception:
                            pass
                except _serial.SerialException as e:
                    self._emit_error("erro serial: {}".format(e))
                    break
                except Exception as e:
                    self._emit_error("erro de leitura: {}".format(e))
                    time.sleep(0.1)
        except _serial.SerialException as e:
            self._emit_error("falha ao abrir porta {}: {}".format(self.port, e))
        except Exception as e:
            self._emit_error("erro inesperado no monitor: {}".format(e))
        finally:
            # ORDEM IMPORTA: limpar o estado ANTES de fechar a porta.
            # Na ordem inversa, write_bytes poderia ver _connected=True
            # e escrever num objeto Serial ja fechado.
            with self._lock:
                self._serial    = None
                self._connected = False
            if ser is not None and ser.is_open:
                try:
                    ser.close()
                except Exception:
                    pass

    def _emit_error(self, msg: str) -> None:
        if self._on_error:
            try:
                self._on_error(msg)
            except Exception:
                pass


def create_monitor(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    buffer_lines: int = DEFAULT_BUFFER_LINES,
    on_line: Optional[Callable[[str], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> SerialMonitor:
    """Factory: cria e retorna um SerialMonitor configurado."""
    return SerialMonitor(
        port=port,
        baudrate=baudrate,
        buffer_lines=buffer_lines,
        on_line=on_line,
        on_error=on_error,
    )


__all__ = ["SerialMonitor", "create_monitor",
           "DEFAULT_BUFFER_LINES", "DEFAULT_BAUDRATE",
           "READ_TIMEOUT"]
