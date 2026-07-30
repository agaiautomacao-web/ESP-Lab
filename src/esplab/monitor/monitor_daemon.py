#!/usr/bin/env python3
"""
monitor_daemon.py — daemon do monitor serial (@E10).

Modulo de producao de esplab.monitor (veio do banco de provas
tests_e10/ em @E10-T10.11). Diretorios de log e socket vem de
core/paths.py — nenhum caminho fixo (PROJECT.md 4).

Daemon do monitor serial: unico dono da porta. Le a serial via
SerialMonitor, grava em log rotativo via MonitorLogWriter e distribui
as linhas por socket Unix local (JSONL) para clientes.

Papeis (declarados no hello):
  - control : ESP Lab (um por vez). release_port/acquire_port/status/shutdown.
  - viewer  : cliente no outro terminal (varios). input + recebe linhas.

Protocolo (uma mensagem JSON por linha, UTF-8):

  control -> daemon
    {"t":"hello","role":"control"}
    {"t":"release_port","reason":"flash"}   -> so responde ok apos fechar
    {"t":"acquire_port"}
    {"t":"status"}
    {"t":"shutdown"}

  viewer -> daemon
    {"t":"hello","role":"viewer","backlog":200}
    {"t":"input","data":"..."}

  daemon -> clientes
    {"t":"line","ts":"...","text":"..."}
    {"t":"state","connected":bool,"port":"...","reason":"..."}
    {"t":"snapshot","lines":[...]}
    {"t":"ok","re":"release_port", ...}
    {"t":"error","msg":"..."}

Principios:
  - Pausa/filtro sao do cliente (estado de exibicao por viewer).
  - release_port e SINCRONO: confirma so depois da porta fechada.
  - Reconexao e do daemon; o cliente so desenha.
  - IPC local por socket Unix, sem rede (PROJECT.md 5.9).
  - Encerra junto com o pai (vigia getppid) e no shutdown.

Retorno (ok, result_or_error) nas funcoes de biblioteca; nunca lanca
para fora do loop. Strings em portugues; identificadores em ingles.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core import paths as _paths
from .log_writer import MonitorLogWriter, make_log_path
from .serial_reader import SerialMonitor, DEFAULT_BAUDRATE

Result = Tuple[bool, Any]

SOCKET_PREFIX = "monitor-"
SOCKET_SUFFIX = ".sock"
# Limite rigido do sun_path no Linux. Estourar produz um OSError
# incompreensivel no bind; conferimos antes e explicamos.
SUN_PATH_MAX = 108
PARENT_WATCH_INTERVAL = 2.0
RECONNECT_INTERVAL = 2.0


def make_socket_path(port: str, run_dir: str | Path) -> Path:
    """Deriva o socket a partir da porta: /dev/ttyUSB0 -> monitor-ttyUSB0.sock"""
    port_name = Path(port).name
    return Path(run_dir) / "{}{}{}".format(SOCKET_PREFIX, port_name, SOCKET_SUFFIX)


def _cmdline(pid: int) -> str:
    """Nome do processo, para a mensagem de recusa. Vazio se sumiu."""
    try:
        raw = Path("/proc/{}/cmdline".format(pid)).read_bytes()
        txt = raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        if txt:
            return txt
        return Path("/proc/{}/comm".format(pid)).read_text().strip()
    except Exception:
        return ""


def _ctty_users(device: str | Path) -> List[Tuple[int, str]]:
    """
    Processos cujo TERMINAL DE CONTROLE e este dispositivo.

    Nao serve tcgetpgrp() aqui: o Linux so responde quando o terminal e o
    do proprio processo que pergunta — de fora vem ENOTTY, igual a um PTY
    livre. A informacao confiavel esta no campo tty_nr de /proc/<pid>/stat.

    Um shell numa aba SSH aparece nessa lista; o PTY do fake_esp e uma
    serial de verdade, nao (ninguem os adotou como terminal de controle).
    """
    try:
        st = os.stat(str(device))
        alvo = (os.major(st.st_rdev), os.minor(st.st_rdev))
    except OSError:
        return []

    achados: List[Tuple[int, str]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            data = (entry / "stat").read_text()
        except OSError:
            continue
        try:
            # comm pode conter espacos e parenteses: corta no ultimo ')'
            resto = data[data.rindex(")") + 2:].split()
            tty_nr = int(resto[4])          # campo 7 do stat
        except (ValueError, IndexError):
            continue
        if tty_nr <= 0:
            continue
        # Codificacao do kernel (new_encode_dev):
        #   valor = (minor & 0xff) | (major << 8) | ((minor & ~0xff) << 12)
        # Logo os bits altos do minor voltam de >> 20 (nao de >> 12).
        maj = (tty_nr >> 8) & 0xFFF
        mnr = (tty_nr & 0xFF) | ((tty_nr >> 20) << 8)
        if (maj, mnr) == alvo:
            achados.append((int(entry.name), _cmdline(int(entry.name))))
    return achados


def check_port_safe(port: str) -> Result:
    """
    Recusa portas que sejam TERMINAIS EM USO.

    Motivo (bug real): quando o fake_esp reinicia, ele ganha um /dev/pts
    novo e o numero antigo pode passar a ser uma sessao SSH do usuario.
    Abrir esse pts pelo pyserial coloca o terminal em modo raw — o que
    desliga o ISIG e mata o Ctrl+C daquela aba, alem de o daemon passar
    a "ler" o que a pessoa digita.
    """
    p = Path(port)
    if not p.exists():
        return (False, "porta nao encontrada: {}".format(port))

    # 1) E o proprio terminal deste processo?
    for fd_std in (0, 1, 2):
        try:
            if os.ttyname(fd_std) == str(port):
                return (False,
                        "{} e o terminal desta propria sessao — abri-lo "
                        "deixaria o terminal mudo e sem Ctrl+C".format(port))
        except OSError:
            pass

    # 2) E o terminal de controle de alguem?
    usuarios = _ctty_users(port)
    if usuarios:
        quem = "; ".join("{} ({})".format(pid, cmd[:40] or "?")
                         for pid, cmd in usuarios[:3])
        return (False,
                "{} e um terminal em uso por {} — provavelmente outra aba "
                "SSH, nao a porta do fake_esp.\n"
                "  A porta do fake_esp muda a cada reinicio: use a que ele "
                "imprimiu agora.\n"
                "  Para forcar mesmo assim: --force (nao recomendado)."
                .format(port, quem))

    return (True, {"port": port})


class _Client:
    """Conexao individual. Escrita serializada por lock proprio."""

    def __init__(self, conn: socket.socket, addr: Any) -> None:
        self.conn = conn
        self.addr = addr
        self.role: Optional[str] = None
        self._wlock = threading.Lock()
        self.alive = True

    def send(self, msg: Dict[str, Any]) -> bool:
        if not self.alive:
            return False
        try:
            data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        except Exception:
            return False
        with self._wlock:
            try:
                self.conn.sendall(data)
                return True
            except Exception:
                self.alive = False
                return False

    def close(self) -> None:
        self.alive = False
        try:
            self.conn.close()
        except Exception:
            pass


class MonitorDaemon:
    """Daemon do monitor serial para uma porta."""

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        logs_dir: str | Path | None = None,
        run_dir: str | Path | None = None,
        watch_parent: bool = True,
        verbose: bool = False,
        force: bool = False,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self._init_error = ""

        # Diretorios: o que vier por parametro manda; o resto vem do
        # paths. Nunca cai para o diretorio atual — isso seria caminho
        # fixo disfarcado. Se o paths falhar, start() reporta.
        if logs_dir is None or run_dir is None:
            try:
                pp = _paths.get_paths()
                if logs_dir is None:
                    logs_dir = pp.monitor_logs
                if run_dir is None:
                    run_dir = pp.run_dir
            except Exception as e:
                self._init_error = (
                    "nao foi possivel resolver os diretorios da aplicacao: "
                    "{}".format(e))
                logs_dir = logs_dir or "."
                run_dir = run_dir or "."

        self.socket_path = make_socket_path(port, run_dir)
        self.log_path = make_log_path(port, logs_dir)
        self._watch_parent = watch_parent
        self._verbose = verbose
        self._force = force

        self._clients: Set[_Client] = set()
        self._clients_lock = threading.Lock()
        self._server: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._released = False          # porta liberada de proposito
        self._release_reason = ""
        self._state_lock = threading.Lock()

        self._log = MonitorLogWriter(self.log_path)
        self._monitor = SerialMonitor(
            port=port,
            baudrate=baudrate,
            on_line=self._on_line,
            on_error=self._on_error,
        )

    # --------------------------------------------------------------
    # LOG INTERNO
    # --------------------------------------------------------------

    def _say(self, msg: str) -> None:
        if self._verbose:
            print("[daemon] {}".format(msg), flush=True)

    # --------------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------------

    def _broadcast(self, msg: Dict[str, Any]) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        for c in clients:
            if not c.send(msg):
                self._drop(c)

    def _drop(self, client: _Client) -> None:
        client.close()
        with self._clients_lock:
            self._clients.discard(client)

    def _state_msg(self, reason: str = "") -> Dict[str, Any]:
        return {
            "t": "state",
            "connected": self._monitor.is_connected,
            "port": self.port,
            "released": self._released,
            "reason": reason or self._release_reason,
        }

    # --------------------------------------------------------------
    # CALLBACKS DA SERIAL
    # --------------------------------------------------------------

    def _on_line(self, line: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log.write_line(line)
        self._broadcast({"t": "line", "ts": ts, "text": line})

    def _on_error(self, msg: str) -> None:
        self._say("erro serial: {}".format(msg))
        self._broadcast({"t": "error", "msg": msg})
        self._broadcast(self._state_msg())

    # --------------------------------------------------------------
    # PORTA
    # --------------------------------------------------------------

    def release_port(self, reason: str = "") -> Result:
        """Libera a porta (sincrono): so retorna apos fechar de fato."""
        with self._state_lock:
            self._released = True
            self._release_reason = reason
            if self._monitor.is_running:
                # stop() e idempotente: "ja estava parado" volta como
                # sucesso com already_stopped=True. Qualquer False aqui
                # e falha real de encerramento. Nao testar por substring
                # da mensagem: texto de erro nao e contrato.
                ok, res = self._monitor.disconnect_stream()
                if not ok:
                    return (False, "falha ao liberar porta: {}".format(res))
            # Confirma que fechou de fato antes de responder.
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if not self._monitor.is_running and not self._monitor.is_connected:
                    break
                time.sleep(0.05)
            else:
                return (False, "porta nao liberou dentro do prazo")
        self._say("porta liberada ({})".format(reason or "sem motivo"))
        self._broadcast(self._state_msg(reason))
        return (True, {"port": self.port, "released": True})

    def acquire_port(self) -> Result:
        """Reabre a porta apos release_port."""
        with self._state_lock:
            self._released = False
            self._release_reason = ""
            if self._monitor.is_running:
                return (True, {"port": self.port, "message": "ja estava aberta"})
            ok, res = self._monitor.reconnect()
            if not ok:
                return (False, "falha ao reabrir porta: {}".format(res))
        # Espera a conexao efetiva (o open acontece na thread).
        deadline = time.time() + 5.0
        while time.time() < deadline and not self._monitor.is_connected:
            time.sleep(0.05)
        self._say("porta readquirida (conectado={})".format(
            self._monitor.is_connected))
        self._broadcast(self._state_msg("reaberta"))
        return (True, {"port": self.port, "connected": self._monitor.is_connected})

    def _reconnect_loop(self) -> None:
        """Reconexao automatica: do daemon, nao do cliente."""
        while not self._stop_event.is_set():
            time.sleep(RECONNECT_INTERVAL)
            if self._stop_event.is_set():
                break
            with self._state_lock:
                if self._released:
                    continue
                if self._monitor.is_running:
                    continue
                self._say("tentando reconectar...")
                ok, _res = self._monitor.reconnect()
            if ok:
                deadline = time.time() + 3.0
                while time.time() < deadline and not self._monitor.is_connected:
                    time.sleep(0.05)
                if self._monitor.is_connected:
                    self._broadcast(self._state_msg("reconectado"))

    # --------------------------------------------------------------
    # ATENDIMENTO DE CLIENTES
    # --------------------------------------------------------------

    def _handle_client(self, client: _Client) -> None:
        buf = b""
        try:
            while not self._stop_event.is_set() and client.alive:
                try:
                    chunk = client.conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    if not raw.strip():
                        continue
                    self._handle_message(client, raw)
        finally:
            self._drop(client)

    def _handle_message(self, client: _Client, raw: bytes) -> None:
        try:
            msg = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            client.send({"t": "error", "msg": "mensagem invalida (JSON esperado)"})
            return
        if not isinstance(msg, dict):
            client.send({"t": "error", "msg": "mensagem invalida (objeto esperado)"})
            return

        t = msg.get("t", "")

        if t == "hello":
            role = msg.get("role", "")
            if role not in ("control", "viewer"):
                client.send({"t": "error", "msg": "papel desconhecido: {}".format(role)})
                return
            if role == "control":
                with self._clients_lock:
                    ja_tem = any(c.role == "control" and c is not client
                                 for c in self._clients)
                if ja_tem:
                    client.send({"t": "error",
                                 "msg": "ja existe um control conectado"})
                    return
            client.role = role
            client.send({"t": "ok", "re": "hello", "role": role,
                         "port": self.port, "log": str(self.log_path)})
            if role == "viewer":
                n = msg.get("backlog", 200)
                try:
                    n = max(0, int(n))
                except Exception:
                    n = 200
                lines = self._monitor.get_buffer()[-n:] if n else []
                client.send({"t": "snapshot", "lines": lines})
            client.send(self._state_msg())
            self._say("cliente conectado: {}".format(role))
            return

        if client.role is None:
            client.send({"t": "error", "msg": "envie hello antes"})
            return

        if t == "input":
            if client.role != "viewer":
                client.send({"t": "error", "msg": "input e exclusivo de viewer"})
                return
            data = msg.get("data", "")
            if not isinstance(data, str):
                client.send({"t": "error", "msg": "campo data deve ser string"})
                return
            ok, res = self._monitor.write_bytes(data.encode("utf-8"))
            if not ok:
                client.send({"t": "error", "msg": str(res)})
            return

        if t == "status":
            client.send({"t": "ok", "re": "status",
                         "port": self.port,
                         "connected": self._monitor.is_connected,
                         "released": self._released,
                         "log": str(self.log_path),
                         "clients": len(self._clients)})
            return

        if t == "release_port":
            if client.role != "control":
                client.send({"t": "error", "msg": "release_port e exclusivo de control"})
                return
            ok, res = self.release_port(str(msg.get("reason", "")))
            client.send({"t": "ok", "re": "release_port", "result": res} if ok
                        else {"t": "error", "msg": str(res)})
            return

        if t == "acquire_port":
            if client.role != "control":
                client.send({"t": "error", "msg": "acquire_port e exclusivo de control"})
                return
            ok, res = self.acquire_port()
            client.send({"t": "ok", "re": "acquire_port", "result": res} if ok
                        else {"t": "error", "msg": str(res)})
            return

        if t == "shutdown":
            if client.role != "control":
                client.send({"t": "error", "msg": "shutdown e exclusivo de control"})
                return
            client.send({"t": "ok", "re": "shutdown"})
            self._say("shutdown solicitado pelo control")
            self.stop()
            return

        client.send({"t": "error", "msg": "comando desconhecido: {}".format(t)})

    # --------------------------------------------------------------
    # VIGIA DO PAI
    # --------------------------------------------------------------

    def _parent_watch_loop(self) -> None:
        """Encerra junto com o ESP Lab (requisito: monitor fecha junto)."""
        original = os.getppid()
        while not self._stop_event.is_set():
            time.sleep(PARENT_WATCH_INTERVAL)
            if os.getppid() != original or os.getppid() == 1:
                self._say("processo pai encerrou; encerrando daemon")
                self.stop()
                return

    # --------------------------------------------------------------
    # CICLO DE VIDA
    # --------------------------------------------------------------

    def start(self) -> Result:
        """Sobe socket, log e leitura serial."""
        if self._init_error:
            return (False, self._init_error)

        # Guarda: o caminho do socket precisa caber no sun_path.
        tam = len(str(self.socket_path).encode("utf-8"))
        if tam >= SUN_PATH_MAX:
            return (False,
                    "caminho do socket longo demais ({} bytes; o limite do "
                    "sistema e {}): {}\n"
                    "  Instale a aplicacao num caminho mais curto ou aponte "
                    "ESPLAB_BASE para um.".format(
                        tam, SUN_PATH_MAX, self.socket_path))

        # Guarda: nunca abrir o terminal de alguem (mata o Ctrl+C da aba).
        if not self._force:
            ok_port, res_port = check_port_safe(self.port)
            if not ok_port:
                return (False, res_port)

        # Socket obsoleto de execucao anterior
        if self.socket_path.exists():
            try:
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                probe.settimeout(0.5)
                probe.connect(str(self.socket_path))
                probe.close()
                return (False, "ja existe um daemon ativo em {}".format(
                    self.socket_path))
            except OSError:
                try:
                    self.socket_path.unlink()
                except OSError as e:
                    return (False, "socket obsoleto nao removivel: {}".format(e))

        try:
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(self.socket_path))
            os.chmod(str(self.socket_path), 0o600)
            srv.listen(8)
            srv.settimeout(0.5)
            self._server = srv
        except Exception as e:
            return (False, "falha ao criar socket: {}".format(e))

        ok_log, res_log = self._log.open()
        if not ok_log:
            self._say("aviso: log indisponivel ({})".format(res_log))

        ok, res = self._monitor.start()
        if not ok:
            self._say("aviso: serial nao abriu agora ({}); "
                      "reconexao automatica ativa".format(res))

        threading.Thread(target=self._reconnect_loop,
                         name="daemon-reconnect", daemon=True).start()
        if self._watch_parent:
            threading.Thread(target=self._parent_watch_loop,
                             name="daemon-parent-watch", daemon=True).start()

        self._say("ouvindo em {}".format(self.socket_path))
        self._say("porta {} | log {}".format(self.port, self.log_path))
        return (True, {"socket": str(self.socket_path),
                       "port": self.port,
                       "log": str(self.log_path)})

    def serve_forever(self) -> None:
        """Loop de aceite. Retorna quando stop() e chamado."""
        assert self._server is not None
        while not self._stop_event.is_set():
            try:
                conn, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client = _Client(conn, addr)
            with self._clients_lock:
                self._clients.add(client)
            threading.Thread(target=self._handle_client, args=(client,),
                             name="daemon-client", daemon=True).start()

    def stop(self) -> Result:
        """Encerra tudo: serial, log, clientes, socket."""
        if self._stop_event.is_set():
            return (True, {"message": "ja encerrado"})
        self._stop_event.set()
        try:
            self._monitor.stop()
        except Exception:
            pass
        try:
            self._log.close()
        except Exception:
            pass
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for c in clients:
            c.close()
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except OSError:
            pass
        self._say("daemon encerrado")
        return (True, {"message": "daemon encerrado"})


def run(port: str, baudrate: int = DEFAULT_BAUDRATE,
        logs_dir: str | Path | None = None,
        run_dir: str | Path | None = None,
        watch_parent: bool = True, verbose: bool = True,
        force: bool = False) -> int:
    daemon = MonitorDaemon(port=port, baudrate=baudrate, logs_dir=logs_dir,
                           run_dir=run_dir, watch_parent=watch_parent,
                           verbose=verbose, force=force)

    def _sig(_signum: int, _frame: Any) -> None:
        daemon.stop()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGHUP, _sig)

    ok, res = daemon.start()
    if not ok:
        print("✘ {}".format(res), file=sys.stderr)
        return 1
    try:
        daemon.serve_forever()
    except KeyboardInterrupt:
        print("\n[daemon] interrompido pelo teclado", flush=True)
    finally:
        daemon.stop()
    return 0


__all__ = ["MonitorDaemon", "make_socket_path", "check_port_safe", "run"]
