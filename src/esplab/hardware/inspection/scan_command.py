#!/usr/bin/env python3
"""
Interface de linha de comando da inspecao completa.

Orquestra: descoberta -> sondagem -> coleta completa -> analise ->
renderizacao -> gravacao de snapshot.

E a UNICA parte do subpacote que imprime (junto de render.py que so
devolve string). A TUI, quando integrar, chama service.scan_hardware
diretamente, ignorando este modulo.

Consumido por diag/scan.py como wrapper fino.

Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .analyze import analyze_report
from .command import run_cmd
from .discovery import discover_all_devices
from .models import Device
from .probe import capture_boot_log, probe_esptool
from .render import render_devices, render_report
from .snapshot_store import save_snapshot

# Diretorio de dados brutos por sessao de CLI (separado dos snapshots
# por MAC do snapshot_store; aqui e um dump-tudo por rodada).
_RAW_ROOT = Path.home() / "esplab" / "diag"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(s: str) -> str:
    """Normaliza string para uso em path (sem espaco, sem char especial)."""
    s = (s or "sem_nome").strip().lower().replace("/dev/", "")
    s = s.replace(":", "_")
    s = re.sub(r"[^a-z0-9_.-]+", "_", s)
    return s.strip("_") or "sem_nome"


def _ler_particoes(port: str, outdir: Path) -> str:
    """Le tabela de particoes em 0x8000 e passa pelo gen_esp32part.py."""
    import os
    idf = Path(os.environ.get("IDF_PATH",
                              str(Path.home() / "esp" / "esp-idf")))
    ptable = outdir / "ptable.bin"
    res = run_cmd(
        ["esptool", "-p", port, "read-flash",
         "0x8000", "0xC00", str(ptable)],
        90,
    )
    _salvar_texto(outdir / "part_read_flash.txt", res.texto or res.erro)
    if not ptable.exists():
        return "Falha ao ler flash em 0x8000"
    gen = idf / "components" / "partition_table" / "gen_esp32part.py"
    if not gen.exists():
        return f"Tabela lida, mas gen_esp32part.py nao esta em {gen}"
    res2 = run_cmd([sys.executable, str(gen), str(ptable)], 30)
    out = res2.texto or res2.erro
    uteis = [
        l for l in out.splitlines()
        if l.startswith("#") or ("," in l and "Parsing" not in l)
    ]
    return "\n".join(uteis) if uteis else "Tabela invalida em 0x8000"


def _salvar_texto(path: Path, texto: str) -> None:
    """Grava texto simples (nao-atomico, dump de sessao)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto or "", encoding="utf-8", errors="replace")


def _coletar_alvo(disp: Device, outdir: Path) -> dict[str, str]:
    """Roda esptool + espefuse + boot log e devolve dict de textos brutos."""
    port = disp.porta or ""
    outdir.mkdir(parents=True, exist_ok=True)

    dados: dict[str, str] = {"chip": disp.probe.get("saida", "")}
    _salvar_texto(outdir / "chip.txt", dados["chip"])

    etapas = [
        ("flash", ["esptool", "-p", port, "flash-id"], 60),
        ("seg",   ["esptool", "-p", port, "get-security-info"], 60),
        ("efuse", ["espefuse", "-p", port, "summary"], 120),
    ]
    for nome, cmd, timeout in etapas:
        res = run_cmd(cmd, timeout)
        dados[nome] = res.texto or res.erro
        _salvar_texto(outdir / f"{nome}.txt", dados[nome])

    dados["part"] = _ler_particoes(port, outdir)
    _salvar_texto(outdir / "part.txt", dados["part"])

    dados["boot"] = capture_boot_log(port)
    _salvar_texto(outdir / "boot.txt", dados["boot"])
    return dados


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Diagnostico automatico de placas ESP conectadas.",
    )
    ap.add_argument(
        "--mostrar-falhas", action="store_true",
        help="exibe candidatos que falharam na sondagem",
    )
    ap.add_argument(
        "--somente-listar", action="store_true",
        help="varre e exibe dispositivos; nao coleta dados",
    )
    return ap.parse_args()


def main() -> int:
    """Ponto de entrada da CLI. Retorna codigo de saida."""
    args = _parse_args()
    stamp = _stamp()
    raw_dir = _RAW_ROOT / f"raw_{stamp}"
    raw_dir.mkdir(parents=True, exist_ok=True)

    dispositivos = discover_all_devices()

    import json
    (raw_dir / "portas_raw.json").write_text(
        json.dumps([asdict(d) for d in dispositivos],
                    indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for d in dispositivos:
        if d.classe in {"serial_esptool", "serial_virtual"} and d.exibir:
            probe_esptool(d)

    painel = render_devices(
        dispositivos, mostrar_falhas=args.mostrar_falhas,
    )
    _salvar_texto(raw_dir / "portas_exibidas.txt", painel)
    print(painel)

    if args.somente_listar:
        print(f"\nDados brutos salvos em: {raw_dir}")
        return 0

    return _coletar_e_reportar(dispositivos, raw_dir, stamp)


def _coletar_e_reportar(
    dispositivos: list[Device], raw_dir: Path, stamp: str,
) -> int:
    """Segunda metade do main: coleta completa dos alvos sondados com OK."""
    alvos = [
        d for d in dispositivos
        if d.classe in {"serial_esptool", "serial_virtual"}
        and d.probe.get("ok")
    ]

    if not alvos:
        print("\nERRO: nenhum alvo valido para esptool. "
              "Coleta completa nao executada.")
        print(f"Dados brutos salvos em: {raw_dir}")
        return 1

    resumos: list[str] = []

    for idx, alvo in enumerate(alvos, 1):
        chip = alvo.probe.get("chip", {})
        mac = chip.get("mac")
        if not mac:
            alvo.motivo = "MAC ausente apos sondagem; coleta bloqueada"
            continue

        outdir = (raw_dir if len(alvos) == 1
                  else raw_dir / _safe_name(f"{mac}_{alvo.porta}"))
        print(f"\n[{idx}/{len(alvos)}] Coletando alvo {alvo.porta} "
              f"| MAC {mac}...")

        dados = _coletar_alvo(alvo, outdir)
        # Perfil por MAC fica com boards_db; aqui so passa o que temos.
        relatorio = analyze_report(
            dados, alvo,
            perfil={"mac": mac}, perfil_novo=False,
        )
        texto = render_report(relatorio, stamp=stamp)
        _salvar_texto(outdir / "RESUMO.txt", texto)

        ok_snap, res_snap = save_snapshot(mac, dados, relatorio)
        if not ok_snap:
            print(f"AVISO: nao gravou snapshot: {res_snap}")

        resumos.append(texto)
        print("\n" + texto)
        print(f"\nArquivos deste alvo: {outdir}")

    if len(resumos) > 1:
        _salvar_texto(raw_dir / "RESUMO_GERAL.txt",
                      "\n\n".join(resumos))

    print(f"\nDados brutos salvos em: {raw_dir}")
    return 0
