#!/usr/bin/env python3
"""
run_daemon.py — sobe o daemon do monitor sem a TUI (@E10).

Modulo de producao de esplab.monitor. Serve tanto para porta simulada
(PTY do fake_esp) quanto para hardware real (/dev/ttyUSB0, /dev/ttyACM0).

Uso:
    cd ~/esplab && PYTHONPATH=src python -m esplab.monitor.run_daemon /dev/pts/3
    ... -m esplab.monitor.run_daemon /dev/ttyUSB0            # hardware real
    ... -m esplab.monitor.run_daemon /dev/ttyUSB0 -b 9600    # outro baudrate

Logs e socket vem de core/paths.py (--logs-dir / --run-dir so para
casos fora do padrao).

Ctrl+C encerra. Strings em portugues; identificadores em ingles.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core import paths as _paths
from .monitor_daemon import run, make_socket_path
from .serial_reader import DEFAULT_BAUDRATE


def main() -> int:
    ap = argparse.ArgumentParser(description="Daemon do monitor serial (@E10)")
    ap.add_argument("port", help="porta serial (ex.: /dev/ttyUSB0 ou /dev/pts/3)")
    ap.add_argument("-b", "--baudrate", type=int, default=DEFAULT_BAUDRATE,
                    help="baudrate (padrao: {})".format(DEFAULT_BAUDRATE))
    ap.add_argument("--logs-dir", default=None,
                    help="diretorio do log rotativo "
                         "(padrao: o do core/paths.py)")
    ap.add_argument("--run-dir", default=None,
                    help="diretorio do socket Unix "
                         "(padrao: o do core/paths.py)")
    ap.add_argument("--no-watch-parent", action="store_true",
                    help="nao encerrar quando o processo pai sair "
                         "(uso avulso no terminal)")
    ap.add_argument("--force", action="store_true",
                    help="abrir a porta mesmo que pareca um terminal em uso "
                         "(perigoso: pode travar a aba)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="menos mensagens no terminal")
    args = ap.parse_args()

    logs_dir, run_dir = args.logs_dir, args.run_dir
    if logs_dir is None or run_dir is None:
        try:
            pp = _paths.get_paths()
            logs_dir = logs_dir or str(pp.monitor_logs)
            run_dir = run_dir or str(pp.run_dir)
        except Exception as e:
            print("✘ nao foi possivel resolver os diretorios da aplicacao: "
                  "{}".format(e), file=sys.stderr)
            return 1

    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    Path(run_dir).mkdir(parents=True, exist_ok=True)

    sock = make_socket_path(args.port, run_dir)
    if not args.quiet:
        print("=" * 62)
        print(" Daemon do monitor — @E10")
        print("=" * 62)
        print(" porta:  {}".format(args.port))
        print(" socket: {}".format(sock))
        print(" log:    {}/".format(logs_dir))
        print()
        print(" Ctrl+C para encerrar.")
        print("=" * 62, flush=True)

    return run(
        port=args.port,
        baudrate=args.baudrate,
        logs_dir=logs_dir,
        run_dir=run_dir,
        watch_parent=not args.no_watch_parent,
        verbose=not args.quiet,
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
