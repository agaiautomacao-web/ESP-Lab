#!/usr/bin/env python3
"""
esplab_monitor.py — visualizador do monitor serial (@E10).

Modulo de producao de esplab.monitor. Conversa com o daemon por socket
Unix local, exibe o stream colorizado e envia ao chip o que voce digita
(monitor bidirecional). Roda na propria TTY do ESP Lab via App.suspend()
ou em outra aba; nos dois casos o daemon continua lendo e gravando log.

Uso:
    cd ~/esplab && PYTHONPATH=src python -m esplab.monitor.esplab_monitor /dev/ttyUSB0
    ... -m esplab.monitor.esplab_monitor --socket /caminho/monitor-ttyUSB0.sock
    ... -m esplab.monitor.esplab_monitor /dev/ttyUSB0 --no-color --no-wrap

Modo arquivo (le um log gravado, mesma colorizacao, e sai):
    ... -m esplab.monitor.esplab_monitor --file ttyUSB0 | less -R
    ... -m esplab.monitor.esplab_monitor --file /caminho/x.monitor.log --tail 500

Os diretorios de socket e de log vem de core/paths.py; --run-dir e
caminho explicito so para casos fora do padrao.

Controles (nao vao para a serial):
    Ctrl+P  pausa/retoma a exibicao (leitura e log seguem no daemon)
    Ctrl+L  limpa a tela (nao afeta o log em disco)
    Ctrl+F  define/remove filtro de texto
    Ctrl+]  sai do cliente (a porta continua aberta no daemon)
Qualquer outra tecla e enviada ao chip.

Principios:
  - O cliente so desenha: pausa e filtro sao estado local; reconexao e
    responsabilidade do daemon (PROJECT.md cap. 10 / Adendo 16).
  - Tela e log sao canais separados: limpar/filtrar/pausar nao afeta o
    arquivo em disco.
  - Linha longa nao e quebrada "as cegas": a continuacao vai indentada,
    para nao parecer uma linha nova.

Retorno (ok, result_or_error) nas funcoes de biblioteca; nunca lanca.
Strings em portugues; identificadores em ingles.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import shutil
import socket
import sys
import termios
import tty
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from ..core import paths as _paths
from .log_writer import make_log_path

Result = Tuple[bool, Any]

# Teclas de controle (bytes)
KEY_PAUSE = 0x10   # Ctrl+P
KEY_CLEAR = 0x0C   # Ctrl+L
KEY_FILTER = 0x06  # Ctrl+F
KEY_QUIT = 0x1D    # Ctrl+]

PAUSE_QUEUE_MAX = 2000

# Formato de log do ESP-IDF: "I (12345) tag: mensagem"
RE_LEVEL = re.compile(r"^([EWIDV])\s*\(\s*\d+\s*\)")

# Linhas do ROM/bootloader que valem destaque proprio
RE_BOOT = re.compile(r"^(ESP-ROM:|rst:0x|Build:|entry 0x|load:0x|mode:)")
RE_PANIC = re.compile(r"(Guru Meditation|panic'ed|Backtrace:|abort\(\))")

# Formato gravado pelo log_writer: "[HH:MM:SS.mmm] <linha>".
# As demais expressoes sao ancoradas em ^, entao a linha do arquivo
# precisa ser separada em carimbo + texto antes de colorizar — senao
# nada casa e o log sai todo branco.
RE_LOG_TS = re.compile(r"^\[(\d{2}:\d{2}:\d{2}\.\d{3})\]\s?(.*)$")


class Cores:
    """Paleta ANSI. Desliga sozinha quando a saida nao e terminal."""

    def __init__(self, enabled: bool = True) -> None:
        self.on = enabled

    def _w(self, code: str, text: str) -> str:
        return "\033[{}m{}\033[0m".format(code, text) if self.on else text

    def erro(self, t: str) -> str:      return self._w("1;31", t)   # vermelho
    def aviso(self, t: str) -> str:     return self._w("1;33", t)   # amarelo
    def info(self, t: str) -> str:      return self._w("0;32", t)   # verde
    def debug(self, t: str) -> str:     return self._w("0;36", t)   # ciano
    def verbose(self, t: str) -> str:   return self._w("0;90", t)   # cinza
    def boot(self, t: str) -> str:      return self._w("0;35", t)   # magenta
    def panic(self, t: str) -> str:     return self._w("1;37;41", t)
    def ts(self, t: str) -> str:        return self._w("0;90", t)
    def status(self, t: str) -> str:    return self._w("1;36", t)
    def alerta(self, t: str) -> str:    return self._w("1;33", t)


def colorize(cores: Cores, text: str) -> str:
    """Aplica cor conforme o nivel de log do ESP-IDF."""
    if RE_PANIC.search(text):
        return cores.panic(text)
    m = RE_LEVEL.match(text)
    if m:
        nivel = m.group(1)
        return {
            "E": cores.erro,
            "W": cores.aviso,
            "I": cores.info,
            "D": cores.debug,
            "V": cores.verbose,
        }[nivel](text)
    if RE_BOOT.match(text):
        return cores.boot(text)
    return text


def wrap_indent(text: str, width: int, indent: str = "  \u21b3 ") -> List[str]:
    """
    Quebra a linha na largura do terminal indentando a continuacao.
    Sem isso, uma linha longa parece duas linhas distintas na tela.
    """
    if width <= 10 or len(text) <= width:
        return [text]
    out: List[str] = []
    primeira = True
    resto = text
    while resto:
        limite = width if primeira else width - len(indent)
        if len(resto) <= limite:
            pedaco, resto = resto, ""
        else:
            corte = resto.rfind(" ", 0, limite + 1)
            if corte <= limite // 2:
                corte = limite
            pedaco, resto = resto[:corte], resto[corte:].lstrip(" ")
        out.append(pedaco if primeira else indent + pedaco)
        primeira = False
    return out


def formata_linha(
    cores: Cores,
    msg: Dict[str, Any],
    timestamp: bool,
    wrap: bool,
    largura: int,
    filtro: str = "",
) -> List[str]:
    """
    Renderiza uma linha ja pronta para impressao (com cor e quebra).
    Caminho UNICO de desenho: usada tanto pelo stream do socket quanto
    pela leitura de arquivo (PROJECT.md 10.5). Lista vazia = filtrada.
    """
    text = msg.get("text", "")
    if filtro and filtro.lower() not in text.lower():
        return []
    prefixo = ""
    if timestamp and msg.get("ts"):
        prefixo = cores.ts("[{}] ".format(msg["ts"]))
    visivel = len(re.sub(r"\033\[[0-9;]*m", "", prefixo))
    partes = (wrap_indent(text, max(20, largura - visivel))
              if wrap else [text])
    return [(prefixo if i == 0 else " " * visivel) + colorize(cores, parte)
            for i, parte in enumerate(partes)]


def parse_log_line(linha: str) -> Dict[str, Any]:
    """
    Desfaz "[HH:MM:SS.mmm] texto" no mesmo dicionario que o daemon manda
    pelo socket. Linha sem carimbo passa inteira como texto.
    """
    m = RE_LOG_TS.match(linha)
    if m:
        return {"ts": m.group(1), "text": m.group(2)}
    return {"ts": "", "text": linha}


def mostra_arquivo(
    caminho: Path,
    cores: Cores,
    timestamp: bool = True,
    wrap: bool = True,
    largura: int = 100,
    tail: int = 0,
) -> Result:
    """
    Escreve o log colorizado em stdout e retorna. Sem socket, sem modo
    raw: e um filtro. A paginacao (less -R) fica a cargo de quem chama.
    """
    if not caminho.is_file():
        return (False, "log nao encontrado: {}".format(caminho))
    try:
        linhas = caminho.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
    except Exception as e:
        return (False, "erro ao ler o log: {}".format(e))
    if tail > 0:
        linhas = linhas[-tail:]
    for linha in linhas:
        for pronta in formata_linha(cores, parse_log_line(linha),
                                    timestamp, wrap, largura):
            sys.stdout.write(pronta + "\n")
    sys.stdout.flush()
    return (True, {"linhas": len(linhas), "log": str(caminho)})


def resolve_log(alvo: str, logs_dir: Path) -> Path:
    """Aceita caminho de log, porta (/dev/ttyUSB0) ou nome de porta."""
    p = Path(alvo)
    if p.is_file():
        return p
    return make_log_path(alvo, logs_dir)


class MonitorClient:
    """Cliente de exibicao. Nao possui a porta; apenas desenha e digita."""

    def __init__(
        self,
        sock_path: Path,
        color: bool = True,
        wrap: bool = True,
        timestamp: bool = True,
        backlog: int = 200,
    ) -> None:
        self.sock_path = sock_path
        self.cores = Cores(color)
        self.wrap = wrap
        self.timestamp = timestamp
        self.backlog = backlog

        self._sock: Optional[socket.socket] = None
        self._buf = b""
        self._paused = False
        self._filtro = ""
        self._fila: Deque[Dict[str, Any]] = deque(maxlen=PAUSE_QUEUE_MAX)
        self._perdidas_na_pausa = 0
        self._termios_saved: Any = None
        self._porta = "?"
        self._log = "?"

    # ----------------------------------------------------------
    # SAIDA
    # ----------------------------------------------------------

    def _out(self, text: str) -> None:
        try:
            sys.stdout.write(text + "\r\n")
            sys.stdout.flush()
        except Exception:
            pass

    def _status(self, text: str) -> None:
        self._out(self.cores.status("── " + text))

    def _largura(self) -> int:
        try:
            return shutil.get_terminal_size((100, 24)).columns
        except Exception:
            return 100

    def _mostra_linha(self, msg: Dict[str, Any]) -> None:
        # Desenho delegado a formata_linha: mesmo caminho do modo --file.
        for pronta in formata_linha(self.cores, msg, self.timestamp,
                                    self.wrap, self._largura(),
                                    self._filtro):
            self._out(pronta)

    # ----------------------------------------------------------
    # PROTOCOLO
    # ----------------------------------------------------------

    def _send(self, msg: Dict[str, Any]) -> bool:
        if self._sock is None:
            return False
        try:
            self._sock.sendall(
                (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            return True
        except Exception:
            return False

    def _trata(self, msg: Dict[str, Any]) -> None:
        t = msg.get("t", "")

        if t == "line":
            if self._paused:
                if len(self._fila) == PAUSE_QUEUE_MAX:
                    self._perdidas_na_pausa += 1
                self._fila.append(msg)
                return
            self._mostra_linha(msg)
            return

        if t == "snapshot":
            linhas = msg.get("lines", [])
            if linhas:
                self._status("{} linha(s) anteriores (buffer do daemon)"
                             .format(len(linhas)))
                for texto in linhas:
                    self._mostra_linha({"text": texto, "ts": ""})
                self._status("fim do historico — ao vivo a partir daqui")
            return

        if t == "state":
            if msg.get("released"):
                motivo = msg.get("reason") or "operacao externa"
                self._status("porta liberada para {} — o daemon reabre "
                             "sozinho ao terminar".format(motivo))
            elif msg.get("connected"):
                self._status("porta {} conectada".format(msg.get("port", "")))
            else:
                self._status("porta {} desconectada — o daemon tentara "
                             "reconectar".format(msg.get("port", "")))
            return

        if t == "ok" and msg.get("re") == "hello":
            self._porta = msg.get("port", "?")
            self._log = msg.get("log", "?")
            return

        if t == "error":
            self._out(self.cores.alerta("── erro: {}".format(msg.get("msg", ""))))
            return

    def _le_socket(self) -> bool:
        """Le do socket. Retorna False quando o daemon encerra."""
        assert self._sock is not None
        try:
            chunk = self._sock.recv(65536)
        except OSError:
            return False
        if not chunk:
            return False
        self._buf += chunk
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            if not raw.strip():
                continue
            try:
                msg = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(msg, dict):
                self._trata(msg)
        return True

    # ----------------------------------------------------------
    # CONTROLES LOCAIS
    # ----------------------------------------------------------

    def _toggle_pausa(self) -> None:
        self._paused = not self._paused
        if self._paused:
            self._status("PAUSADO — Ctrl+P retoma (a leitura e o log "
                         "continuam no daemon)")
            return
        pendentes = list(self._fila)
        self._fila.clear()
        perdidas = self._perdidas_na_pausa
        self._perdidas_na_pausa = 0
        self._status("retomado — {} linha(s) durante a pausa{}".format(
            len(pendentes),
            "; {} descartada(s) por limite de fila".format(perdidas)
            if perdidas else ""))
        for msg in pendentes:
            self._mostra_linha(msg)

    def _limpa_tela(self) -> None:
        try:
            sys.stdout.write("\033[H\033[2J\033[3J")
            sys.stdout.flush()
        except Exception:
            pass
        self._cabecalho()
        self._status("tela limpa — o log em disco esta intacto ({})"
                     .format(self._log))

    def _pede_filtro(self) -> None:
        """Le uma linha em modo normal (fora do raw) e aplica o filtro."""
        self._restaura_terminal()
        try:
            atual = " [atual: {}]".format(self._filtro) if self._filtro else ""
            sys.stdout.write(self.cores.status(
                "── filtro{} (vazio remove): ".format(atual)))
            sys.stdout.flush()
            texto = sys.stdin.readline().strip()
        except Exception:
            texto = ""
        finally:
            self._modo_raw()
        self._filtro = texto
        if texto:
            self._status("filtro ativo: exibindo apenas linhas com {!r} "
                         "(o log segue completo)".format(texto))
        else:
            self._status("filtro removido")

    # ----------------------------------------------------------
    # TERMINAL
    # ----------------------------------------------------------

    def _modo_raw(self) -> None:
        if not sys.stdin.isatty():
            return
        try:
            self._termios_saved = termios.tcgetattr(sys.stdin.fileno())
            tty.setraw(sys.stdin.fileno())
        except Exception:
            self._termios_saved = None

    def _restaura_terminal(self) -> None:
        if self._termios_saved is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN,
                                  self._termios_saved)
            except Exception:
                pass

    def _trata_teclas(self, data: bytes) -> bool:
        """Processa teclas. Retorna False para sair."""
        envio = bytearray()
        for b in data:
            if b == KEY_QUIT:
                if envio:
                    self._send({"t": "input", "data": envio.decode(
                        "utf-8", errors="replace")})
                return False
            if b == KEY_PAUSE:
                self._toggle_pausa()
                continue
            if b == KEY_CLEAR:
                self._limpa_tela()
                continue
            if b == KEY_FILTER:
                self._pede_filtro()
                continue
            envio.append(b)
        if envio:
            if not self._send({"t": "input",
                               "data": envio.decode("utf-8", errors="replace")}):
                return False
        return True

    # ----------------------------------------------------------
    # CICLO DE VIDA
    # ----------------------------------------------------------

    def conecta(self) -> Result:
        if not self.sock_path.exists():
            return (False, "socket nao encontrado: {}\n"
                           "  O daemon esta rodando? "
                           "(run_daemon.py <porta>)".format(self.sock_path))
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(self.sock_path))
            self._sock = s
        except OSError as e:
            return (False, "falha ao conectar em {}: {}".format(self.sock_path, e))
        if not self._send({"t": "hello", "role": "viewer",
                           "backlog": self.backlog}):
            return (False, "falha ao apresentar-se ao daemon")
        return (True, {"socket": str(self.sock_path)})

    def _cabecalho(self) -> None:
        self._out(self.cores.status("=" * 62))
        self._out(self.cores.status(" ESP Lab — monitor serial"))
        self._out(self.cores.status("=" * 62))
        self._out(self.cores.status(
            " Ctrl+P pausa | Ctrl+L limpa | Ctrl+F filtro | Ctrl+] sai"))
        self._out(self.cores.status(
            " Demais teclas vao para o chip."))
        self._out(self.cores.status("=" * 62))

    def run(self) -> int:
        ok, res = self.conecta()
        if not ok:
            print("✘ {}".format(res), file=sys.stderr)
            return 1

        self._cabecalho()
        self._modo_raw()
        assert self._sock is not None
        entradas = [self._sock]
        if sys.stdin.isatty():
            entradas.append(sys.stdin)

        try:
            while True:
                try:
                    r, _w, _x = select.select(entradas, [], [], 0.2)
                except (OSError, select.error):
                    break
                for origem in r:
                    if origem is self._sock:
                        if not self._le_socket():
                            self._status("daemon encerrou a conexao")
                            return 0
                    else:
                        try:
                            data = os.read(sys.stdin.fileno(), 1024)
                        except OSError:
                            return 0
                        if not data:
                            return 0
                        if not self._trata_teclas(data):
                            return 0
        except KeyboardInterrupt:
            pass
        finally:
            self._restaura_terminal()
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
            self._out("")
            self._status("cliente encerrado — a porta continua aberta "
                         "no daemon")
        return 0


def resolve_socket(alvo: str, run_dir: Path) -> Path:
    """Aceita porta (/dev/ttyUSB0) ou caminho de socket."""
    p = Path(alvo)
    if p.suffix == ".sock" or p.exists() and not alvo.startswith("/dev/"):
        return p
    return run_dir / "monitor-{}.sock".format(p.name)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cliente do monitor serial do ESP Lab (@E10-T10.10)")
    ap.add_argument("porta", nargs="?", default=None,
                    help="porta serial (ex.: /dev/ttyUSB0) ou caminho do socket")
    ap.add_argument("--socket", default=None, help="caminho do socket Unix")
    ap.add_argument("--run-dir", default=None,
                    help="diretorio dos sockets (padrao: o do core/paths.py)")
    ap.add_argument("--backlog", type=int, default=200,
                    help="linhas de historico ao conectar (0 desliga)")
    ap.add_argument("--no-color", action="store_true", help="sem cores ANSI")
    ap.add_argument("--no-wrap", action="store_true",
                    help="nao quebrar linhas longas na largura do terminal")
    ap.add_argument("--no-timestamp", action="store_true",
                    help="nao exibir o carimbo de hora")
    ap.add_argument("--file", default=None, metavar="ALVO",
                    help="exibir um log gravado (caminho, porta ou nome de "
                         "porta) em vez do stream ao vivo; escreve em stdout "
                         "e sai")
    ap.add_argument("--tail", type=int, default=0, metavar="N",
                    help="com --file: so as ultimas N linhas (0 = todas)")
    args = ap.parse_args()

    if args.file:
        # Modo arquivo: filtro puro. A cor NAO depende de isatty, porque
        # o destino normal e um cano para o `less -R` — checar isatty
        # aqui apagaria justamente as cores que o less sabe renderizar.
        try:
            logs_dir = _paths.get_paths().monitor_logs
        except Exception as e:
            print("✘ nao foi possivel resolver o diretorio de logs: {}"
                  .format(e), file=sys.stderr)
            return 1
        largura = 100
        try:
            largura = shutil.get_terminal_size((100, 24)).columns
        except Exception:
            pass
        ok, res = mostra_arquivo(
            caminho=resolve_log(args.file, logs_dir),
            cores=Cores(not args.no_color),
            timestamp=not args.no_timestamp,
            wrap=not args.no_wrap,
            largura=largura,
            tail=max(0, args.tail),
        )
        if not ok:
            print("✘ {}".format(res), file=sys.stderr)
            return 1
        return 0

    if not args.porta and not args.socket:
        ap.error("informe a porta (ex.: /dev/ttyUSB0), --socket ou --file")

    run_dir = args.run_dir
    if run_dir is None:
        try:
            run_dir = str(_paths.get_paths().run_dir)
        except Exception as e:
            print("✘ nao foi possivel resolver o diretorio de sockets: {}"
                  .format(e), file=sys.stderr)
            return 1

    sock_path = (Path(args.socket) if args.socket
                 else resolve_socket(args.porta, Path(run_dir)))

    cliente = MonitorClient(
        sock_path=sock_path,
        color=not args.no_color and sys.stdout.isatty(),
        wrap=not args.no_wrap,
        timestamp=not args.no_timestamp,
        backlog=max(0, args.backlog),
    )
    return cliente.run()


if __name__ == "__main__":
    sys.exit(main())
