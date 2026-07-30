#!/usr/bin/env python3
"""Aplicacao TUI do ESP Lab — navegacao por menus numerados.
Regras: itens 1-8 (8 e teto); 0=Sair (so no principal); 9=Voltar (submenus).
Navegacao por digitacao de numero. Breadcrumb completo no topo.
A arvore de menus e DADO (MENU_TREE); a logica de navegar e generica.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations
import glob
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path as _Path
from typing import Any, Dict, List

from textual.app import (App, ComposeResult, SuspendNotSupported, SystemCommand)
from textual import events, work
from textual.binding import Binding as _Binding
from textual.screen import Screen as _PaletteScreen
from textual.command import CommandPalette as _CommandPalette
from textual.widgets._header import HeaderIcon as _HeaderIcon
from typing import Iterable as _Iterable
from textual.widgets import Header, Footer, Static, RichLog
from textual.containers import VerticalScroll

from ..core import version as _version
from ..core import paths as _paths
from ..core import session as _session
from ..software import system_info as _sysinfo
from ..hardware import ports as _ports
from ..hardware import port_config as _port_config
from ..monitor import monitor_prefs as _monitor_prefs
from ..hardware import port_config as _port_config
from ..hardware import chip_info as _chip
from ..hardware import boards_db as _boards
from ..hardware import partition_tables as _partitions
from ..hardware import board_ascii as _board_ascii
from ..hardware import family_profiles as _family_profiles
from ..hardware import context as _hardware_context
from ..software import idf_manager as _idf_mgr
from ..versioning import git_local as _git
from ..monitor.log_writer import MonitorLogWriter, make_log_path
from ..hardware import scanner as _scanner
from ..software import updates as _updates
from .dialogs import confirmar as _confirmar, pedir_input as _pedir_input
from ..monitor.serial_reader import SerialMonitor, create_monitor
from ..workspace import workspace as _workspace
from ..workspace import project_config as _project_config
from ..flash import flasher as _flasher
from ..programming import builder as _builder
from ..programming import code_chip_validator as _code_chip
from ..programming import sdkconfig_defaults as _sdk
from ..programming import file_explorer as _file_explorer
from ..programming import external_editor as _external_editor
from ..programming import library_manager as _libmgr
from ..programming import library_inspector as _libinsp
from ..programming import idf_components as _idfcomp
from ..programming import cmake_requires as _cmreq

MENU_TREE: Dict[str, Any] = {
    "title": "Principal",
    "items": [
        {"label": "Software", "node": {"title": "Software", "items": [
            {"label": "Estado do ambiente",       "node": None, "action": "updates"},
            {"label": "Instalar / Reparar",       "node": None, "action": "idf_install_repair"},
            {"label": "Ativar versao",            "node": None, "action": "idf_ativar"},
            {"label": "Atualizar versao corrente", "node": None, "action": "idf_atualizar"},
            {"label": "Reverter atualizacao",     "node": None, "action": "idf_reverter"},
            {"label": "Editores de terminal", "node": {"title": "Editores de terminal", "items": [
                {"label": "Estado dos editores",      "node": None, "action": "editor_status"},
                {"label": "Instalar editor interno",  "node": None, "action": "editor_install"},
                {"label": "Escolher editor padrao",   "node": None, "action": "editor_choose"},
                {"label": "Remover editor interno", "node": None, "action": "editor_remove"},
            ]}}]}},
        {"label": "Hardware", "node": {"title": "Hardware", "items": [
            {"label": "Identificar e selecionar porta", "node": None, "action": "definir_portas"},
            {"label": "Exibir layout da placa", "node": None, "action": "layout"},
            {"label": "Cadastrar / atualizar placa", "node": None, "action": "cadastrar_placa"},
            {"label": "Associar perfil ao projeto", "node": None, "action": "associar_perfil"},
            {"label": "Configurar target do projeto", "node": None, "action": "configurar_target"},
            {"label": "Gerenciar perfis do banco", "node": None, "action": "gerenciar_perfis"}]}},
        {"label": "Programacao", "node": {"title": "Programacao", "items": [
            {"label": "Carregar",         "node": None, "action": "programming_carregar"},
            {"label": "Compilar",         "node": None, "action": "programming_compilar"},
            {"label": "Gravar (Flash)",   "node": None, "action": "programming_gravar"},
            {"label": "Estado do build",  "node": None, "action": "programming_status"},
            {"label": "Recursos do projeto", "node": None, "action": "programming_features"},
            {"label": "Arquivos do projeto", "node": {"title": "Arquivos do projeto", "items": [
                {"label": "Listar arquivos",                  "node": None, "action": "files_list"},
                {"label": "Criar arquivo",                    "node": None, "action": "files_create_file"},
                {"label": "Criar pasta",                      "node": None, "action": "files_create_dir"},
                {"label": "Renomear",                         "node": None, "action": "files_rename"},
                {"label": "Mover",                            "node": None, "action": "files_move"},
                {"label": "Excluir",                          "node": None, "action": "files_delete"},
                {"label": "Abrir arquivo no editor",          "node": None, "action": "files_open_file"},
            ]}},
            {"label": "Bibliotecas", "node": {"title": "Bibliotecas", "items": [
                {"label": "Dependências atuais",        "node": None, "action": "libs_list"},
                {"label": "Componentes ESP-IDF internos", "node": None, "action": "libs_idf_components"},
                {"label": "Adicionar",                  "node": None, "action": "libs_add"},
                {"label": "Inspecionar pasta local",    "node": None, "action": "libs_inspect"}]}},
        ]}},
        {"label": "Configurações", "node": {"title": "Configurações", "items": [
            {"label": "Conexão",   "node": None, "action": "config_conexao"},
            {"label": "Placa",     "node": None, "action": "config_placa"},
            {"label": "Flash",     "node": {"title": "Flash", "items": [
                {"label": "Modo",    "node": None, "action": "config_flash_modo"},
                {"label": "Tamanho", "node": None, "action": "config_flash_tamanho"}]}},
            {"label": "PSRAM",     "node": None, "action": "config_psram"},
            {"label": "Partição",  "node": {"title": "Partição", "items": [
                {"label": "4MB",  "node": None, "action": "config_particao_4mb"},
                {"label": "8MB",  "node": None, "action": "config_particao_8mb"},
                {"label": "16MB", "node": None, "action": "config_particao_16mb"},
                {"label": "32MB", "node": None, "action": "config_particao_32mb"}]}},
            {"label": "CPU",       "node": None, "action": "config_cpu"},
            {"label": "Depuração", "node": None, "action": "config_depuracao"}]}},
        {"label": "Monitor", "node": {"title": "Monitor", "items": [
            {"label": "Monitorar porta",   "node": None, "action": "monitor_start"},
            {"label": "Monitores ativos",  "node": None, "action": "monitor_active"},
            {"label": "Abrir log gravado", "node": None, "action": "monitor_log"},
            {"label": "Preferencias",      "node": None, "action": "monitor_prefs"}]}},
        {"label": "Workspace", "node": {"title": "Workspace", "items": [
            {"label": "Estado atual",   "node": None, "action": "workspace_status"},
            {"label": "Abrir projeto",  "node": None, "action": "workspace_abrir"},
            {"label": "Novo projeto",   "node": None, "action": "workspace_novo"},
            {"label": "Fechar projeto", "node": None, "action": "workspace_fechar"},
            {"label": "Diretório do workspace", "node": {
                "title": "Diretório do workspace", "items": [
                    {"label": "Estado atual", "node": None,
                     "action": "workspace_diretorio_status"},
                    {"label": "Alterar diretório", "node": None,
                     "action": "workspace_diretorio_alterar"},
                    {"label": "Restaurar padrão", "node": None,
                     "action": "workspace_diretorio_padrao"},
                ]}},
        ]}},
        {"label": "Versionamento", "node": {"title": "Versionamento", "items": [
            {"label": "Estado",                 "node": None, "action": "versioning_status"},
            {"label": "Preparar versionamento",  "node": None, "action": "versioning_prepare"},
            {"label": "Commit",                 "node": None, "action": "versioning_commit"},
        ]}},
        {"label": "Ajuda", "node": {"title": "Ajuda", "items": [
            {"label": "Atalhos", "node": None, "action": "shortcuts"},
            {"label": "Sobre",   "node": None, "action": "about"}]}},
    ],
}

# Acoes que fazem I/O e precisam rodar em worker (nao bloqueiam o teclado).
# Acoes ausentes desta lista sao consideradas instantaneas (sem worker).
# Campos editaveis de um perfil de placa (Hardware > Editar perfil).
# tipo: texto | numero | lista (opcoes fixas) | particao (depende do
# flash_size_mb do proprio perfil) | pinos (submenu proprio, pino a pino).
_EDITAR_PERFIL_CAMPOS = [
    {"key": "board_name", "label": "Nome da placa", "tipo": "texto"},
    {"key": "flash_size_mb", "label": "Tamanho da flash", "tipo": "lista",
     "opcoes": ["1MB", "2MB", "4MB", "8MB", "16MB", "32MB"]},
    {"key": "psram_enabled", "label": "PSRAM", "tipo": "lista",
     "opcoes": ["Nenhum", "2MB", "4MB", "8MB", "16MB", "32MB"]},
    {"key": "usb_mode", "label": "Modo USB", "tipo": "lista",
     "opcoes": ["USB-Serial/JTAG", "USB-OTG", "Desconhecido"]},
    {"key": "partition_table", "label": "Tabela de particao", "tipo": "particao"},
    {"key": "total_pins", "label": "Total de pinos", "tipo": "numero"},
    {"key": "pinout_mapping", "label": "Mapeamento de pinos", "tipo": "pinos"},
    {"key": "usb_ports", "label": "Portas USB", "tipo": "portas_usb"},
]

# Legenda de categorias de pino (mesma convencao de hardware/board_ascii.py).
_LEGENDA_CATEGORIAS = {
    "A": "GPIO", "B": "ADC", "C": "Touch", "D": "SPI",
    "E": "UART", "F": "USB", "G": "Strapping", "H": "Octal",
}

_ACOES_LENTAS = {
    "monitor_start",
    "definir_portas", "cadastrar_placa", "configurar_target",
    "programming_gravar", "updates",
    "versioning_status",
    "workspace_status", "workspace_abrir", "flash",
    "programming_status", "idf_install_repair", "idf_ativar",
    "idf_atualizar", "idf_reverter", "editor_install",
    "files_list", "files_rename", "files_move", "files_delete",
    "files_open_file",
}

# Estado central de operacoes. Nesta primeira fase ele controla teclado e
# ciclo de vida; os cancel_event dos demais modulos serao conectados nas
# fases seguintes, um dominio por vez.
_OPERATION_IDLE = "ocioso"
_OPERATION_RUNNING = "executando"
_OPERATION_CANCELLING = "cancelando"

# Acoes cujo backend recebe o evento central de cancelamento nesta fase.
_CANCELABLE_ACTIONS = {
    "idf_install_repair", "idf_ativar", "idf_atualizar", "idf_reverter",
    "programming_gravar", "definir_portas", "cadastrar_placa",
    "configurar_target",
}


# ----------------------------------------------------------------------
# Renderizacao de arvore de arquivos (Programacao > Arquivos do projeto)
# ----------------------------------------------------------------------
# A entrada vem de file_explorer.list_tree(): lista plana de
# {name, relative, type, depth}, ja ordenada por caminho (sorted(rglob)).
# A renderizacao reconstroi os conectores "├── " / "└── " / "│   " a
# partir dessa ordem, sem precisar remontar a arvore em memoria.

def _is_last_at_depth(items: list[dict], idx: int) -> bool:
    """
    True se items[idx] e o ultimo filho do seu pai direto.
    O proximo item com depth menor confirma que o nivel atual fechou;
    um proximo item de depth IGUAL significa que ha irmao depois.
    """
    depth = items[idx]["depth"]
    for j in range(idx + 1, len(items)):
        if items[j]["depth"] < depth:
            return True
        if items[j]["depth"] == depth:
            return False
    return True


def _render_file_tree(items: list[dict], root_label: str) -> str:
    """
    Renderiza a saida de file_explorer.list_tree() como arvore visual
    (estilo `tree` do Linux), com a raiz nomeada pelo projeto e pastas
    destacadas em ciano. Pastas vazias aparecem como item terminal sem
    filhos. Projeto vazio devolve mensagem amigavel, sem arvore.
    """
    if not items:
        return f"[b cyan]{root_label}[/b cyan]\n\n[dim](projeto vazio)[/dim]"

    linhas = [f"[b cyan]{root_label}[/b cyan]"]
    # ramo_aberto[d] = True enquanto o nivel de profundidade d ainda tem
    # itens pendentes a frente — controla "│   " vs "    " nas colunas
    # de continuacao acima do item atual.
    ramo_aberto: dict[int, bool] = {}

    for idx, it in enumerate(items):
        depth = it["depth"]
        ultimo = _is_last_at_depth(items, idx)
        ramo_aberto[depth] = not ultimo

        prefixo = "".join(
            "│   " if ramo_aberto.get(d, False) else "    "
            for d in range(depth)
        )
        conector = "└── " if ultimo else "├── "
        nome = f"[cyan]{it['name']}[/cyan]" if it["type"] == "dir" else it["name"]
        linhas.append(f"{prefixo}{conector}{nome}")

    return "\n".join(linhas)


# ======================================================================
# INDICE DE REGIOES DA CLASSE ESPLabApp
# Navegue buscando por  "# ===  ["  (pula de regiao em regiao).
# Cross-cutting omitidos do 'usa': _confirmar, _paths, _pedir_input, _session, _version.
# ----------------------------------------------------------------------
#   [NAV] NAVEGACAO E INFRAESTRUTURA .................  19 func
#   [PANEIS] PAINEIS DA TELA INICIAL .................  6 func
#   [HW] HARDWARE - portas / perfil / scan / layout ... 5 func
#   [IDF] SOFTWARE / ESP-IDF .......................... 8 func
#   [MON] MONITOR ..................................... 1 func
#   [VER] VERSIONAMENTO ............................... 3 func
#   [PERFIL] HARDWARE - editar perfil ................. 13 func
#   [AJUDA] AJUDA / MENSAGENS ......................... 4 func
#   [PROG] PROGRAMACAO / BUILD ........................ 13 func
#   [FLASH] FLASH ..................................... 3 func
#   [CONFIG] CONFIGURACOES ............................ 15 func
#   [WS] WORKSPACE .................................... 5 func
#   [EDIT] EDITORES DE TERMINAL ....................... 8 func
#   [FILES] ARQUIVOS DO PROJETO ....................... 7 func
#   [LIBS] BIBLIOTECAS ................................ 43 func
# ======================================================================
class ESPLabApp(App):
    """Aplicacao principal do ESP Lab."""

    def get_system_commands(
        self, screen: "_PaletteScreen"
    ) -> "_Iterable[SystemCommand]":
        """Comandos de sistema da command palette, em portugues.

        Espelha a logica do Textual 8.2.7, traduzindo titulo e ajuda e
        omitindo o comando 'Screenshot'. Os callbacks (funcoes internas)
        sao os mesmos do framework — nada de comportamento muda.
        """
        yield SystemCommand(
            "Tema",
            "Alterna o tema atual",
            self.action_change_theme,
        )
        yield SystemCommand(
            "Sair",
            "Encerra a aplicacao assim que possivel",
            self.action_quit,
        )
        if screen.query("HelpPanel"):
            yield SystemCommand(
                "Teclas",
                "Oculta o painel de teclas e ajuda",
                self.action_hide_help_panel,
            )
        else:
            yield SystemCommand(
                "Teclas",
                "Mostra a ajuda do widget em foco e as teclas disponiveis",
                self.action_show_help_panel,
            )
        if screen.maximized is not None:
            yield SystemCommand(
                "Minimizar",
                "Restaura o widget ao tamanho normal",
                screen.action_minimize,
            )
        elif screen.focused is not None and screen.focused.allow_maximize:
            yield SystemCommand(
                "Maximizar",
                "Maximiza o widget em foco",
                screen.action_maximize,
            )

    def _traduzir_tooltip_paleta(self) -> None:
        """Traduz o tooltip do botao da command palette no header.

        O texto e um literal do Textual (HeaderIcon.tooltip). Ajustamos
        apos a montagem; protegido para nunca derrubar o on_mount caso o
        icone nao exista (ex.: header sem botao).
        """
        try:
            icone = self.query_one(_HeaderIcon)
            icone.tooltip = "Abrir a paleta de comandos"
        except Exception:
            pass

    def action_command_palette(self) -> None:
        """Abre a command palette com placeholder em portugues.

        Espelha a acao do Textual 8.2.7, trocando apenas o texto exibido
        na caixa de busca. Comportamento (providers, abertura) inalterado.
        """
        if self.use_command_palette and not _CommandPalette.is_open(self):
            self.push_screen(
                _CommandPalette(
                    placeholder="Buscar comandos\u2026",
                    id="--command-palette",
                )
            )

    TITLE = "ESP Lab"
    BINDINGS = [
        ("q", "quit", "Sair"),
        ("ctrl+q", "quit", "Sair"),
        ("ctrl+c", "cancel_current", "Cancelar"),
        _Binding("ctrl+p", "command_palette", "Paleta de comandos",
                 show=False),
    ]
    CSS = """
    #body { padding: 1 2; }
    #breadcrumb { text-style: bold; color: $accent; margin-bottom: 1; }
    #content { border: round $primary; padding: 1 2; margin-top: 1; margin-bottom: 1; height: auto; overflow-y: hidden; }
    #statusbar { dock: top; background: $warning; color: $background; padding: 0 2; height: 1; display: none; }
    #statusbar.ativo { display: block; }
    .section_title { text-style: bold; color: $primary; margin-top: 1; }
    .section_box { border: round $primary-darken-1; padding: 1 2; margin-bottom: 1; }
    """
    # ==================================================================
    # ===  [NAV] NAVEGACAO E INFRAESTRUTURA
    # ===  compose / dispatch / on_key / ciclo de vida
    # ===  usa: MonitorLogWriter, SerialMonitor
    # ==================================================================


    def __init__(self) -> None:
        super().__init__()
        self._stack: List[Dict[str, Any]] = [MENU_TREE]
        self._worker_ativo: bool = False
        self._operation_state: str = _OPERATION_IDLE
        self._operation_id: int = 0
        self._operation_name: str = ""
        self._operation_cancelable: bool = False
        self._operation_cancel_event: threading.Event = threading.Event()
        self._projeto_ativo: str | None = None

        # Contexto de hardware exclusivamente de runtime.
        self._porta_ativa: str | None = None
        self._mac_porta_ativa: str | None = None
        self._hardware_por_porta: dict[str, dict[str, Any]] = {}
        self._hardware_scan_performed: bool = False

        self._editar_perfil_estado: dict = {}
        self._monitor: Any = None            # orfao: parada agora e por daemon
        self._monitor_log_writer: Any = None  # orfao: log e do daemon
        self._monitor_procs: Dict[str, Any] = {}  # porta -> Popen do daemon
        self._flash_em_andamento: bool = False
        self._cancelar_flash: threading.Event = self._operation_cancel_event
        self._status_base: str = ""
        self._status_dots: int = 1
        self._status_timer: Any = None
        self._stream_historico: List[str] = []

    # ------------------------------------------------------------------
    # Composicao e montagem
    # ------------------------------------------------------------------


    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="body"):
            yield Static(id="statusbar")
            yield Static(id="breadcrumb")
            yield Static(id="menu")
            yield RichLog(id="content", wrap=True, highlight=False, markup=True)
            yield Static("SOFTWARE", classes="section_title")
            yield Static(
                self._software_text(),
                id="software-panel",
                classes="section_box",
            )
            yield Static("HARDWARE", classes="section_title")
            yield Static(
                self._hardware_text(),
                id="hardware-panel",
                classes="section_box",
            )
            yield Static("PROJETOS", classes="section_title")
            yield Static(
                self._projetos_text(),
                id="projetos-panel",
                classes="section_box",
            )
            yield Static("LOCAIS", classes="section_title")
            yield Static(self._paths_text(), id="paths-panel", classes="section_box")
        yield Footer()


    def on_mount(self) -> None:
        self.sub_title = f"v{_version.get_version()}"
        self._projeto_ativo = _session.get_projeto_ativo()
        self._clear_runtime_hardware(scan_performed=False)
        if self._projeto_ativo:
            from pathlib import Path
            nome = Path(self._projeto_ativo).name
            self.sub_title = f"v{_version.get_version()} — {nome}"
        self._render_menu()
        self._refresh_hardware_panel()
        self._iniciar_varredura_boot()
        self._traduzir_tooltip_paleta()

    def _iniciar_varredura_boot(self) -> None:
        """Etapa 1: varredura completa no boot (mesma identificação do
        menu 'Identificar e selecionar portas'), sem modal, com
        auto-conexão pela placa do projeto ativo. Roda em worker para não
        bloquear a montagem da tela."""
        self._cw("[dim]Varredura inicial de hardware...[/dim]")
        self._start_operation("varredura inicial de portas", cancelable=True)
        self._set_status("Varredura inicial de portas")
        self._run_action_worker("_action_boot_scan")

    def _action_boot_scan(self) -> None:
        """Varredura inicial em thread; aplica o resultado sem modal."""
        from ..hardware.inspection import service as _inspection

        self.call_from_thread(self._clear_runtime_hardware, True)
        ok, result = _inspection.scan_hardware(
            cancel_event=self._operation_cancel_event
        )
        if not ok:
            msg = str(result)
            if "cancelad" in msg.lower():
                self.call_from_thread(
                    self._cw,
                    "[yellow]Varredura inicial cancelada.[/yellow]",
                )
            else:
                self.call_from_thread(
                    self._cw,
                    f"[red]Falha na varredura inicial:[/red] {msg}",
                )
            return
        entries = self._build_hardware_entries(result)
        self.call_from_thread(self._apply_boot_scan, entries)

    def _apply_boot_scan(
        self, entries: dict[str, dict[str, Any]]
    ) -> None:
        """Aplica a varredura do boot: persiste conexão, auto-conecta pela
        placa do projeto ativo (sem 2º reset) e informa. Sem modal."""
        self._hardware_por_porta = dict(entries)
        self._hardware_scan_performed = True
        self._porta_ativa = None
        self._mac_porta_ativa = None

        # Persiste 'connected' para toda placa identificada com perfil.
        for entry in self._hardware_por_porta.values():
            mac = str(entry.get("mac") or "").strip().lower()
            if mac and entry.get("profile"):
                _boards.set_connection_status(
                    mac, _boards.CONNECTION_CONNECTED
                )
                entry["connection_status"] = _boards.CONNECTION_CONNECTED

        # MAC esperado pelo projeto ativo (sem sondar; via context.resolve).
        expected_mac = ""
        if self._projeto_ativo:
            ok_ctx, ctx = self._current_hardware_context()
            if ok_ctx:
                expected_mac = str(
                    ctx.get("expected_mac") or ""
                ).strip().lower()

        # Auto-conexão quando a placa do projeto está presente e válida.
        if expected_mac:
            match = next(
                (
                    e for e in self._hardware_por_porta.values()
                    if str(e.get("mac") or "").strip().lower()
                    == expected_mac and e.get("selectable")
                ),
                None,
            )
            if match is not None:
                self._porta_ativa = match.get("port") or None
                self._mac_porta_ativa = match.get("mac") or None
            else:
                # Placa do projeto ausente: rebaixa o status no arquivo.
                _boards.set_connection_status(
                    expected_mac, _boards.CONNECTION_NOT_FOUND
                )

        self._refresh_hardware_panel()
        self._cw(self._boot_scan_summary(expected_mac))

    def _boot_scan_summary(self, expected_mac: str = "") -> str:
        total = len(self._hardware_por_porta)
        selecionaveis = sum(
            1 for e in self._hardware_por_porta.values()
            if isinstance(e, dict) and e.get("selectable")
        )
        lines = [
            "[b]Varredura inicial de hardware[/b]",
            "",
            f"Dispositivos identificados: {total} · "
            f"Selecionáveis: {selecionaveis}",
        ]
        if self._porta_ativa:
            lines.extend([
                "",
                "[green]Placa do projeto conectada automaticamente "
                "(sem novo reset).[/green]",
                f"Porta: {self._porta_ativa}",
                f"MAC:   {self._mac_porta_ativa or 'Não informado'}",
            ])
        elif expected_mac:
            lines.extend([
                "",
                "[yellow]A placa do projeto ativo não foi encontrada "
                "nesta varredura.[/yellow]",
                f"[dim]MAC esperado: {expected_mac} · status atualizado "
                "para 'Não conectada'.[/dim]",
            ])
        elif self._projeto_ativo:
            lines.extend([
                "",
                "[dim]Projeto ativo sem placa associada; nenhuma porta "
                "foi selecionada.[/dim]",
            ])
        else:
            lines.extend([
                "",
                "[dim]Nenhum projeto ativo; portas apenas "
                "identificadas.[/dim]",
            ])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Navegacao
    # ------------------------------------------------------------------

    def _current(self) -> Dict[str, Any]:
        return self._stack[-1]

    def _breadcrumb_text(self) -> str:
        nos = [n["title"] for n in self._stack if n["title"] != "Principal"]
        return " > ".join(nos) if nos else "Principal"

    def _is_root(self) -> bool:
        return len(self._stack) == 1

    def _render_menu(self) -> None:
        node = self._current()
        self.query_one("#breadcrumb", Static).update(self._breadcrumb_text())
        lines: List[str] = []
        raiz = self._is_root()
        for i, item in enumerate(node["items"], start=1):
            label = item["label"]
            # Indicador de submenu (">") a partir do segundo nivel — o
            # menu raiz ja e implicitamente todo composto de categorias,
            # entao o indicador so ajuda a partir de um submenu em diante.
            if not raiz and item.get("node") is not None:
                label = f"{label} >"
            lines.append(f"[b]{i}[/b]. {label}")
        if raiz:
            lines.append("[b]0[/b]. [yellow]Sair[/yellow]")
        else:
            lines.append("[b]9[/b] ou [b]ESC[/b]. [yellow]Voltar[/yellow]")
        self.query_one("#menu", Static).update("\n".join(lines))
        c = self.query_one("#content", RichLog)
        c.clear()
        c.write("[dim]Digite o numero de uma opcao.[/dim]")


    def _set_status(self, msg: str) -> None:
        """
        Exibe status na barra fixa abaixo do header, com os pontinhos
        finais animados (. -> .. -> ... -> .) enquanto durar. msg pode
        vir com "..." embutido (call sites existentes) ou sem -- os
        pontos finais sao sempre removidos e a animacao assume dali.
        """
        bar = self.query_one("#statusbar", Static)
        base = msg.rstrip(".").rstrip() if msg else ""
        self._status_base = base
        if base:
            self._status_dots = 0
            bar.update(f"⟳  {base}{'':<3}")
            bar.add_class("ativo")
            if self._status_timer is None:
                self._status_timer = self.set_interval(0.5, self._tick_status_dots)
        else:
            if self._status_timer is not None:
                self._status_timer.stop()
                self._status_timer = None
            bar.update("")
            bar.remove_class("ativo")

    def _tick_status_dots(self) -> None:
        """Callback do timer: avanca a animacao dos pontinhos."""
        if not self._status_base:
            return
        self._status_dots = (self._status_dots + 1) % 4
        bar = self.query_one("#statusbar", Static)
        bar.update(f"⟳  {self._status_base}{('.' * self._status_dots):<3}")

    def _content_scroll_rule(self, c: "RichLog | None" = None) -> None:
        """Acima de 50 linhas renderizadas, liga o scroll interno do #content;
        abaixo, desliga (sem barra e sem o rastro do scrollbar padrao do
        RichLog). Chamado apos cada escrita."""
        c = c if c is not None else self._content()
        try:
            n = len(c.lines)
        except Exception:
            n = 0
        if n > 50:
            c.styles.max_height = 50
            c.styles.overflow_y = "auto"
        else:
            c.styles.max_height = None
            c.styles.overflow_y = "hidden"

    def _cw(self, texto: str) -> None:
        """Limpa e escreve no RichLog de conteudo (thread principal)."""
        c = self._content()
        c.clear()
        c.write(texto)
        self._content_scroll_rule(c)

    def _cw_append(self, texto: str) -> None:
        """Adiciona linha ao RichLog sem limpar (para progresso)."""
        c = self._content()
        c.write(texto)
        self._content_scroll_rule(c)

    def _cw_iniciar_stream(self, cabecalho: str) -> None:
        """
        Inicia uma tela de stream com suporte a "mesma linha" (progresso
        tipo git --progress, ex. Instalar/Reparar/Atualizar ESP-IDF).
        Usar com _cw_stream_linha() daqui em diante nessa tela -- nao
        misturar com _cw_append() no mesmo fluxo.
        """
        self._stream_historico = [cabecalho]
        c = self._content()
        c.clear()
        c.write(cabecalho)
        self._content_scroll_rule(c)

    def _cw_stream_linha(self, texto: str, mesma_linha: bool) -> None:
        """
        Adiciona linha ao stream iniciado por _cw_iniciar_stream().
        mesma_linha=True: atualizacao de progresso (ex. percentual do
        git) -- sobrescreve a ultima atualizacao, nunca vira linha
        permanente. mesma_linha=False: linha definitiva -- fica
        gravada no historico e nunca mais e sobrescrita.
        """
        c = self._content()
        if not mesma_linha:
            self._stream_historico.append(texto)
        c.clear()
        for linha in self._stream_historico:
            c.write(linha)
        if mesma_linha:
            c.write(texto)
        self._content_scroll_rule(c)

    def _content(self) -> RichLog:
        """Atalho para o widget de conteudo."""
        return self.query_one("#content", RichLog)

    def _operation_busy(self) -> bool:
        """True enquanto existe worker/flash executando ou cancelando."""
        return (
            self._operation_state != _OPERATION_IDLE
            or self._worker_ativo
            or self._flash_em_andamento
        )

    def _start_operation(self, name: str, *, cancelable: bool = False) -> int:
        """
        Registra uma operacao antes de agendar seu worker.

        Deve ser chamado na thread principal ANTES de _run_*_worker(), para
        eliminar a janela em que uma tecla poderia entrar entre o agendamento
        e o inicio efetivo da thread.
        """
        self._operation_id += 1
        self._operation_name = name.strip() or "Operacao"
        self._operation_cancelable = cancelable
        self._operation_cancel_event.clear()
        self._operation_state = _OPERATION_RUNNING
        self._worker_ativo = True
        return self._operation_id

    def _finish_operation(self, expected_id: int | None = None) -> None:
        """
        Devolve o teclado ao estado ocioso somente depois que o worker real
        retornou. Teclas descartadas durante EXECUTANDO/CANCELANDO nao sao
        reaplicadas nem armazenadas.
        """
        # Um worker antigo nao pode liberar o teclado de uma operacao
        # mais nova iniciada por callback/modal antes de seu finally rodar.
        if expected_id is not None and expected_id != self._operation_id:
            return
        self._worker_ativo = False
        self._operation_state = _OPERATION_IDLE
        self._operation_name = ""
        self._operation_cancelable = False
        self._operation_cancel_event.clear()
        # Ctrl+C em backend ainda nao conectado pode ter exibido um status
        # informativo. Ele deve desaparecer quando o worker realmente termina.
        self.call_from_thread(self._set_status, "")

    def _request_cancel_current(self) -> None:
        """Solicita cancelamento sem encadear saida da aplicacao."""
        if not self._operation_busy():
            return
        if self._operation_state == _OPERATION_CANCELLING:
            return
        if not self._operation_cancelable:
            # Fase 1: consome Ctrl+C, mas nao finge cancelar um backend que
            # ainda nao recebeu cancel_event. O processo continua protegido
            # contra q/Ctrl+q/0 ate terminar de verdade.
            self._set_status(
                f"{self._operation_name}: cancelamento ainda nao conectado"
            )
            return

        # Confirmacao antes de cancelar: qualquer interrupcao de operacao
        # pede confirmacao (como a saida do app e o fechar projeto ja fazem).
        op_id = self._operation_id
        nome = self._operation_name

        def _on_confirmar_cancelamento(confirmado: bool) -> None:
            if not confirmado:
                return
            if not self._operation_busy() or self._operation_id != op_id:
                return
            if self._operation_state == _OPERATION_CANCELLING:
                return
            self._operation_state = _OPERATION_CANCELLING
            self._operation_cancel_event.set()
            self._set_status(f"cancelando {nome}")

        _confirmar(
            self,
            titulo="Cancelar operação",
            mensagem="Cancelar a operação em andamento?",
            on_confirm=_on_confirmar_cancelamento,
        )

    def _enter_item(self, index: int) -> None:
        if self._operation_busy():
            return
        node = self._current()
        items = node["items"]
        if index < 1 or index > len(items):
            return
        item = items[index - 1]
        sub = item.get("node")
        if sub is not None:
            # Submenu — navegacao instantanea, sem worker
            self._stack.append(sub)
            self._render_menu()
            return

        action = item.get("action", "")
        action_name, sep, action_arg = action.partition(":")
        method_name = f"_action_{action_name}"

        if action_name in _ACOES_LENTAS:
            # Mostra placeholder imediatamente; worker atualiza quando terminar
            self._cw("[dim]Aguarde...[/dim]")
            # Trava ANTES do dispatch (thread principal) — evita janela de
            # corrida em que uma segunda tecla dispara outra acao antes do
            # worker ter chance de marcar _worker_ativo internamente.
            self._start_operation(
                method_name.removeprefix("_action_"),
                cancelable=action_name in _CANCELABLE_ACTIONS,
            )
            # Barra laranja informa, com pontinhos animados, o que roda.
            self._set_status(item.get("label") or "Executando")
            self._run_action_worker(method_name)
        else:
            # Acao instantanea (thread principal): mostra "Aguarde..." na hora
            # para nao deixar dados do menu anterior enquanto a acao prepara o
            # proprio andamento. Sem barra laranja (so tarefas lentas a usam).
            self._cw("[dim]Aguarde...[/dim]")
            if hasattr(self, method_name):
                method = getattr(self, method_name)
                result = method(action_arg) if sep else method()
                if result is not None:
                    self._cw(result)
            else:
                self._cw(
                    f"[b]{item['label']}[/b]\n\n"
                    "[dim]Em construcao. Digite 9 para voltar.[/dim]")

    def _stop_monitor_runtime(self) -> tuple[bool, Any]:
        """
        Encerra os daemons de monitor e confirma a liberacao das portas.

        O projeto so pode ser fechado depois deste metodo retornar sucesso.
        A leitura agora vive nos daemons (nao mais em self._monitor); a
        parada usa as tres camadas de _encerrar_daemons_monitor (shutdown
        educado -> SIGTERM -> vigia do pai), sem bloquear a espera. O log
        e do daemon: ele o fecha ao encerrar.
        """
        ok, detalhe = self._encerrar_daemons_monitor()
        # Camada 3 (o _parent_watch_loop mata o daemon ao sair da TUI)
        # cobre qualquer 'restante'; nao bloqueamos o fechamento por isso.
        return (True, {
            "monitor_stopped": True,
            "log_closed": True,
            "port_released": True,
            "detalhe": detalhe,
        })


    def _go_back(self) -> None:
        if self._operation_busy():
            return
        # A leitura vive nos daemons; encerra-os ao sair da tela. O log
        # e fechado pelo proprio daemon. self._monitor* seguem inertes.
        self._encerrar_daemons_monitor()
        if not self._is_root():
            self._stack.pop()
            self._render_menu()
            self._refresh_software_panel()

    def on_key(self, event: events.Key) -> None:
        # ModalScreen impede os bindings do App; esta guarda tambem evita que
        # os numeros do menu sejam tratados pelo fundo.
        if len(self.screen_stack) > 1:
            return

        key = event.key.lower()

        if self._operation_busy():
            # Durante EXECUTANDO/CANCELANDO nenhuma tecla de saida ou
            # navegacao e enfileirada. O usuario precisara pressionar de novo
            # depois que o estado voltar explicitamente para OCIOSO.
            if key == "ctrl+c":
                self._request_cancel_current()
            if key in {"ctrl+c", "q", "ctrl+q", "0", "9", "escape"} or key.isdigit():
                event.prevent_default()
                event.stop()
            return

        if key == "ctrl+c":
            # Ctrl+C ocioso nao encerra a aplicacao.
            event.prevent_default()
            event.stop()
            return
        if key == "0":
            if self._is_root():
                self._tentar_sair()
            return
        if key == "escape":
            # Prioridade: se o painel de ajuda (HelpPanel) estiver
            # aberto, o 1o ESC fecha SO o painel e consome o evento;
            # o menu so reage ao 2o ESC.
            if self.screen.query("HelpPanel"):
                self.action_hide_help_panel()
                event.prevent_default()
                event.stop()
                return
            # ESC equivale ao 9 somente quando a opcao Voltar existe.
            if not self._is_root():
                self._go_back()
            event.prevent_default()
            event.stop()
            return
        if key == "9":
            self._go_back()
            return
        if key.isdigit():
            self._enter_item(int(key))

    def action_cancel_current(self) -> None:
        """Binding de Ctrl+C: cancela a operacao, nunca a aplicacao."""
        self._request_cancel_current()

    def action_quit(self) -> None:
        """
        q/Ctrl+q so abrem a saida quando a aplicacao esta OCIOSA.
        Durante EXECUTANDO/CANCELANDO a tecla e descartada; nao existe
        intencao de saida pendente para executar depois.
        """
        if self._operation_busy():
            return
        self._tentar_sair()

    def _tentar_sair(self) -> None:
        """Ponto unico de saida, disponivel somente no estado OCIOSO."""
        if self._operation_busy():
            return

        def _confirmar_sair_normal(confirmado: bool) -> None:
            if confirmado:
                self._finalizar_e_sair()

        aviso_monitor = (
            "\n\n[dim]Os monitores ativos serao encerrados.[/dim]"
            if self._monitor_ativos() else ""
        )
        _confirmar(
            self,
            titulo="Sair do ESP Lab",
            mensagem=f"Deseja sair da aplicacao?{aviso_monitor}",
            on_confirm=_confirmar_sair_normal,
        )

    def _finalizar_e_sair(self) -> None:
        """Limpeza final: encerra os daemons de monitor antes de sair."""
        self._encerrar_daemons_monitor()
        self.exit()

    # ------------------------------------------------------------------
    # Worker generico para acoes lentas
    # ------------------------------------------------------------------

    @work(thread=True)
    def _run_action_worker(self, method_name: str) -> None:
        """Executa uma _action_* em thread separada e atualiza #content ao fim."""
        operation_id = self._operation_id
        method = getattr(self, method_name, None)
        if method is None:
            self.call_from_thread(self._cw, "[red]Acao nao implementada.[/red]"
            )
            self._finish_operation(operation_id)
            return
        try:
            result = method()
            if result is not None:
                def _upd(r=result):
                    self._content().clear()
                    self._content().write(r)
                self.call_from_thread(_upd)
        except Exception as exc:
            def _upd_exc(e=str(exc)):
                self._content().clear()
                self._content().write(f"[red]Erro inesperado:[/red] {e}")
            self.call_from_thread(_upd_exc)
        finally:
            self._finish_operation(operation_id)
    # ==================================================================
    # ===  [PANEIS] PAINEIS DA TELA INICIAL
    # ===  Software / Hardware / Locais
    # ===  usa: _scanner, _sysinfo
    # ==================================================================

    # ------------------------------------------------------------------
    # Secoes fixas da tela inicial
    # ------------------------------------------------------------------

    def _software_text(self) -> str:
        """
        Monta o painel SOFTWARE da tela inicial.

        collect() fornece os dados leves do sistema. As versoes do esptool
        da ESP-IDF ativa e das dependencias do app-venv sao consultadas
        pelas funcoes especificas de system_info.
        """
        ok, info = _sysinfo.collect()
        if not ok:
            return "[red]Falha ao coletar informacoes do sistema.[/red]"

        esptool_version = _sysinfo.detect_esptool()
        dependencies = _sysinfo.detect_dependencies()

        deps = "\n".join(
            f"    {str(d.get('name') or 'desconhecida'):<10} "
            f"{d.get('version') or 'Não detectado'}"
            for d in dependencies
        )
        if not deps:
            deps = "    Não detectado"

        os_name = info.get("os") or "Não detectado"
        kernel = info.get("kernel") or "Não detectado"
        python_version = info.get("python") or "Não detectado"
        editor = info.get("editor") or "Não detectado"
        idf_version = (
            info.get("esp_idf")
            or info.get("idf")
            or "Não detectado"
        )

        return (
            f"[b]Sistema:[/b]\n"
            f"    [b]OS[/b]        {os_name}\n"
            f"    [b]Kernel[/b]    {kernel}\n"
            f"\n"
            f"[b]Aplicação (app-venv):[/b]\n"
            f"    [b]Python[/b]    {python_version}\n"
            f"    [b]Editor[/b]    {editor}\n"
            f"\n"
            f"[b]ESP-IDF ativa:[/b]\n"
            f"    [b]Versão[/b]    {idf_version}\n"
            f"    [b]esptool[/b]   {esptool_version}\n"
            f"\n"
            f"[b]Dependências:[/b]\n"
            f"{deps}"
        )


    def _compute_software_text(self) -> str:
        """Calcula o texto do painel SOFTWARE (dispara subprocess via
        system_info.collect()). Seguro em worker thread; NAO toca widgets."""
        try:
            return self._software_text()
        except Exception:
            return "[dim]Falha ao carregar SOFTWARE.[/dim]"

    def _apply_software_text(self, texto: str) -> None:
        """Aplica texto ja calculado ao widget. Apenas main thread."""
        try:
            self.query_one("#software-panel", Static).update(texto)
        except Exception:
            # Nao derruba a TUI por falha de refresh lateral.
            pass

    def _refresh_software_panel(self) -> None:
        """Recarrega o painel SOFTWARE, sincrono (main thread).
        Mantido para call sites ja na thread principal (ex.: _go_back).
        De dentro de worker thread, usar _compute_software_text() +
        call_from_thread(_apply_software_text, ...) para nao bloquear a UI."""
        self._apply_software_text(self._compute_software_text())


    @staticmethod
    def _profile_readiness_text(profile: dict | None) -> str:
        if not profile:
            return "[dim]Não cadastrado[/dim]"
        if profile.get("profile_ready"):
            return "[green]Pronto[/green]"
        return "[yellow]Incompleto[/yellow]"


    @staticmethod
    def _profile_readiness_reasons(profile: dict | None) -> list[str]:
        if not profile:
            return ["perfil não cadastrado"]
        return [
            str(item) for item in (
                profile.get("profile_readiness_reasons") or []
            ) if str(item).strip()
        ]


    @staticmethod
    def _connection_status_display(status: Any) -> str:
        """Mapeia o status de conexão persistido para exibição PT-BR."""
        return {
            "connected": "[green]Conectada[/green]",
            "not_found": "[red]Não conectada[/red]",
            "unchecked": "[dim]Não verificada[/dim]",
        }.get(str(status or ""), "")


    def _active_hardware_entry(self) -> "dict[str, Any] | None":
        """Retorna o entry da varredura correspondente à porta/placa ativa,
        ou None. Casamento por porta primeiro, depois por MAC vivo."""
        if not self._porta_ativa and not self._mac_porta_ativa:
            return None
        direto = self._hardware_por_porta.get(self._porta_ativa)
        if isinstance(direto, dict):
            return direto
        mac_alvo = str(self._mac_porta_ativa or "").strip().lower()
        for entry in self._hardware_por_porta.values():
            if not isinstance(entry, dict):
                continue
            if self._porta_ativa and entry.get("port") == self._porta_ativa:
                return entry
            if mac_alvo and str(entry.get("mac") or "").strip().lower() == mac_alvo:
                return entry
        return None


    def _hardware_text(self) -> str:
        """Retrato do dispositivo físico presente e da configuração de build
        que o descreve. Território de hardware apenas — identidade de projeto
        (associação, target/MAC esperado, reconciliação) pertence ao projeto e
        não aparece aqui. Não inicia varredura."""

        def _val(v: Any, vazio: str = "—") -> str:
            s = str(v or "").strip()
            if not s or s in ("Desconhecido", "Nenhum", "Não informado"):
                return vazio
            return s

        entry = self._active_hardware_entry()
        lines: list[str] = ["[b]Dispositivo ativo[/b]"]

        if entry is None:
            lines.append("  [dim]Nenhuma placa conectada.[/dim]")
        else:
            prof = entry.get("profile") or {}
            chip = entry.get("chip") or {}

            def _fis(*keys: str) -> str:
                for src in (prof, chip):
                    for k in keys:
                        s = str(src.get(k) or "").strip()
                        if s and s not in ("Desconhecido", "Nenhum"):
                            return s
                return ""

            # Facetas de build (sdkconfig) — só com projeto ativo.
            cpu_freq = flash_mode = psram_mode = ""
            if self._projeto_ativo:
                cpu_freq = _sdk.get_cpu_freq(self._projeto_ativo)
                flash_mode = _sdk.get_flash_mode(self._projeto_ativo)
                psram_mode = _sdk.get_psram_mode(self._projeto_ativo)

            porta = _val(self._porta_ativa)
            conn = (self._connection_status_display(entry.get("connection_status"))
                    or "[dim]Não verificada[/dim]")
            placa = _val(_fis("board_name"))
            mac = _val(self._mac_porta_ativa or _fis("mac"))

            chip_type = _fis("chip_type", "chip_family")
            rev = _fis("chip_revision")
            cpu_parts = [p for p in (chip_type, f"rev {rev}" if rev else "",
                                     cpu_freq) if p]
            cpu_line = " · ".join(cpu_parts) if cpu_parts else "—"

            flash_fis = _fis("flash_size_mb", "flash_size")
            flash_mfr = _fis("flash_manufacturer")
            flash_dev = _fis("flash_device")
            flash_parts = []
            if flash_fis:
                flash_parts.append(flash_fis)
            if flash_mode:
                flash_parts.append(flash_mode)
            if flash_mfr and flash_dev:
                flash_parts.append(f"{flash_mfr}/{flash_dev}")
            flash_line = " · ".join(flash_parts) if flash_parts else "—"

            psram_fis = _fis("psram_enabled", "psram")
            psram_parts = [f"{psram_fis} presente" if psram_fis
                           else "não detectada"]
            if psram_mode:
                psram_parts.append(psram_mode)
            psram_line = " · ".join(psram_parts)

            lines.extend([
                f"  [b]Porta[/b]     {porta} · {conn}",
                f"  [b]Placa[/b]     {placa}",
                f"  [b]MAC[/b]       {mac}",
                f"  [b]CPU[/b]       {cpu_line}",
                f"  [b]Flash[/b]     {flash_line}",
                f"  [b]PSRAM[/b]     {psram_line}",
                f"  [b]Cristal[/b]   {_val(_fis('crystal'))}",
                f"  [b]USB[/b]       {_val(_fis('usb_mode'))}",
                f"  [b]Perfil[/b]    {self._profile_readiness_text(prof)}",
            ])

            # Recursos da placa (contagem por função do perfil + USB).
            caps: dict[str, int] = {}
            for pin in (prof.get("pinout_mapping") or []):
                if not isinstance(pin, dict):
                    continue
                letras = [str(v) for v in (pin.get("functions") or [])
                          if str(v) in _board_ascii.LEGEND]
                if not letras:
                    c = _board_ascii.CAT.get(str(pin.get("category") or ""))
                    if c:
                        letras = [c]
                for L in set(letras):
                    caps[L] = caps.get(L, 0) + 1
            recursos = []
            for L in sorted(caps):
                # GPIO (~todos os pinos) e USB (coberto por Portas USB) fora.
                if L in ("A", "F"):
                    continue
                recursos.append(f"  {caps[L]} - {_board_ascii.LEGEND[L]}")
            usb_ports = prof.get("usb_ports") or []
            if usb_ports:
                nomes = ", ".join(
                    str(u.get("nome") or u.get("name") or f"USB {i}")
                    for i, u in enumerate(usb_ports, 1)
                )
                recursos.append(
                    f"  {len(usb_ports)} - Portas USB ({nomes})"
                )
            if recursos:
                lines.extend(["", "[b]Recursos da placa[/b]"] + recursos)

        # Build (sdkconfig): partição e depuração são do projeto ativo.
        lines.extend(["", "[b]Build (sdkconfig)[/b]"])
        if self._projeto_ativo:
            nome, tam = _sdk.get_partition_scheme_info(self._projeto_ativo)
            particao = (f"{nome} ({tam})" if nome and tam
                        else _sdk.get_partition_scheme_name(self._projeto_ativo))
            lines.append(f"  [b]Partição[/b]  {particao}")
            lines.append(f"  [b]Depuração[/b] {_sdk.get_log_level(self._projeto_ativo)}")
        else:
            lines.append("  [dim]— sem projeto ativo[/dim]")

        # Detectados nesta varredura (lista física completa).
        detected = []
        for key, entry in self._hardware_por_porta.items():
            if not isinstance(entry, dict):
                continue
            label = entry.get("label") or key
            chip = entry.get("chip") or {}
            family = chip.get("chip_family") or "Desconhecido"
            mac = chip.get("mac") or "Não informado"
            selectable = entry.get("selectable", False)
            suffix = "" if selectable else " [dim](não selecionável)[/dim]"
            conn = self._connection_status_display(entry.get("connection_status"))
            conn_txt = f" · {conn}" if conn else ""
            detected.append(f"  {label}: {family} · {mac}{conn_txt}{suffix}")
        if detected:
            lines.extend(["", "[b]Detectados nesta varredura[/b]"] + detected)

        return "\n".join(lines)


    def _refresh_hardware_panel(self) -> None:
        try:
            self.query_one("#hardware-panel", Static).update(
                self._hardware_text()
            )
        except Exception:
            pass
        self._refresh_projetos_panel()

    def _projetos_text(self) -> str:
        """Retrato do projeto ativo: perfil/placa associada, target, prontidão
        e reconciliação com o dispositivo vivo. Território de projeto — a parte
        física fica no painel HARDWARE; os caminhos, em LOCAIS. Não sonda."""
        if not self._projeto_ativo:
            return (
                "[dim]Nenhum projeto ativo.[/dim]\n\n"
                "[dim]Abra ou crie um projeto para ver a associação de placa, "
                "target e prontidão.[/dim]"
            )
        ok, context = _hardware_context.resolve(
            self._projeto_ativo,
            current_port=self._porta_ativa,
            current_mac=self._mac_porta_ativa,
            hardware_by_port=self._hardware_por_porta,
            scan_performed=self._hardware_scan_performed,
        )
        if not ok:
            return "[dim]Contexto de projeto indisponível.[/dim]"

        match = context.get("live_matches_expected")
        if context.get("association_exists") and not context.get(
            "expected_profile_ready"
        ):
            state = "[yellow]Perfil do projeto incompleto[/yellow]"
        elif match is True and context.get("ready_for_flash"):
            state = "[green]Dispositivo e perfil conferem[/green]"
        elif match is True:
            state = "[yellow]MAC confere; perfil ainda não está pronto[/yellow]"
        elif match is False:
            state = "[red]Dispositivo diferente do perfil do projeto[/red]"
        elif context.get("association_exists"):
            state = "[yellow]Perfil pronto ainda não verificado ao vivo[/yellow]"
        else:
            state = "[dim]Projeto sem perfil associado[/dim]"

        expected_profile = context.get("expected_profile")
        lines = [
            f"[b]Projeto[/b]       {context['project_name']}",
            f"[b]Perfil[/b]        {context['profile_name']}",
            f"[b]Placa[/b]         {context['board_name']}",
            f"[b]MAC esperado[/b]  {context['expected_mac_display']}",
            f"[b]Target[/b]        {context['target_display']}",
            f"[b]Prontidão[/b]     "
            f"{self._profile_readiness_text(expected_profile)}",
            f"[b]Última porta[/b]  {context['last_port_display']}",
            f"[b]Estado[/b]        {state}",
        ]

        ok_libs, libs = _libmgr.list_libs(_Path(self._projeto_ativo))
        if ok_libs and isinstance(libs, list) and libs:
            nomes = [str(lib.get("name") or "?") for lib in libs]
            travadas = sum(1 for lib in libs if lib.get("locked"))
            amostra = ", ".join(nomes[:4])
            if len(nomes) > 4:
                amostra += f", +{len(nomes) - 4}"
            trav = f" · {travadas} travada(s)" if travadas else ""
            dep_line = f"{len(nomes)} ({amostra}){trav}"
        elif ok_libs:
            dep_line = "nenhuma declarada"
        else:
            dep_line = "—"
        ok_req, req = _libmgr.get_idf_requirement(_Path(self._projeto_ativo))
        req_txt = req if (ok_req and req) else "(não definido)"
        lines.append(f"[b]Requisito IDF[/b] {req_txt}")
        lines.append(f"[b]Dependências[/b]  {dep_line}")

        if expected_profile and not context.get("expected_profile_ready"):
            lines.append("")
            lines.append("[b]Pendências do perfil do projeto[/b]")
            lines.extend(
                f"  [yellow]• {reason}[/yellow]"
                for reason in context.get(
                    "expected_profile_readiness_reasons", []
                )
            )
        return "\n".join(lines)

    def _refresh_projetos_panel(self) -> None:
        try:
            self.query_one("#projetos-panel", Static).update(
                self._projetos_text()
            )
        except Exception:
            pass


    def _clear_runtime_hardware(self, scan_performed: bool = False) -> None:
        self._porta_ativa = None
        self._mac_porta_ativa = None
        self._hardware_por_porta = {}
        self._hardware_scan_performed = bool(scan_performed)
        self._refresh_hardware_panel()


    def _update_runtime_chip(self, port: str, chip: dict) -> None:
        entry = dict(self._hardware_por_porta.get(port, {}))
        old_chip = dict(entry.get("chip") or {})
        old_chip.update(chip or {})
        entry["chip"] = old_chip
        entry["mac"] = str(old_chip.get("mac") or "").lower()
        self._hardware_por_porta[port] = entry
        if port == self._porta_ativa:
            self._mac_porta_ativa = entry["mac"] or None
        self._refresh_hardware_panel()


    def _current_hardware_context(self):
        return _hardware_context.resolve(
            self._projeto_ativo,
            current_port=self._porta_ativa,
            current_mac=self._mac_porta_ativa,
            hardware_by_port=self._hardware_por_porta,
            scan_performed=self._hardware_scan_performed,
        )

    def _paths_text(self) -> str:
        p = _paths.get_paths()
        short = _paths.ESPLabPaths.shorten
        ok_ws, state = _workspace.get_workspace_state()
        if ok_ws:
            workspace_path = short(state.get("path") or p.workspace_default)
            source = "padrão" if state.get("source") == "default" else "usuário"
            if state.get("usable"):
                workspace_line = f"{workspace_path} [dim]({source})[/dim]"
            else:
                workspace_line = (
                    f"[red]{workspace_path}[/red] [dim](indisponível)[/dim]"
                )
        else:
            workspace_line = "[red]configuração inválida[/red]"
        return (
            f"[b]Projetos[/b]  {workspace_line}\n"
            f"[b]Config[/b]    {short(p.config_home)}\n"
            f"[b]Dados[/b]     {short(p.data_home)}\n"
            f"[b]Logs[/b]      {short(p.logs)}\n"
            f"[b]Backup[/b]    {short(p.backups)}\n"
            f"[b]Bancada[/b]   {short(p.workbench)}"
        )

    def _refresh_paths_panel(self) -> None:
        try:
            self.query_one("#paths-panel", Static).update(self._paths_text())
        except Exception:
            pass
    # ==================================================================
    # ===  [HW] HARDWARE - portas / perfil / scan / layout
    # ===  menu: Hardware
    # ===  usa: _board_ascii, _boards
    # ==================================================================

    # ------------------------------------------------------------------
    # Acoes lentas (rodam via _run_action_worker em thread separada)
    # ------------------------------------------------------------------


    def _action_definir_portas(self) -> None:
        """Identifica portas; só serial_esptool pode ser selecionado."""
        from ..hardware.inspection import service as _inspection

        self.call_from_thread(self._clear_runtime_hardware, True)
        ok, result = _inspection.scan_hardware(
            cancel_event=self._operation_cancel_event
        )
        if not ok:
            if "cancelad" in str(result).lower():
                self.call_from_thread(
                    self._cw, "[yellow]Identificação cancelada.[/yellow]"
                )
            else:
                self.call_from_thread(
                    self._cw,
                    f"[red]Falha ao identificar portas:[/red] {result}",
                )
            return

        entries = self._build_hardware_entries(result)
        self.call_from_thread(self._show_hardware_port_selection, entries)


    def _build_hardware_entries(
        self, result: Any
    ) -> dict[str, dict[str, Any]]:
        """Monta identifier -> entry a partir da varredura.

        Lógica compartilhada entre o menu 'Identificar e selecionar portas'
        e a varredura inicial do boot, para os dois fluxos nunca
        divergirem. Puro: não toca a UI.
        """
        from ..hardware.inspection import service as _inspection

        entries: dict[str, dict[str, Any]] = {}
        for device in result:
            port = str(getattr(device, "porta", None) or "").strip()
            local_usb = str(getattr(device, "local_usb", None) or "").strip()
            identifier = port or local_usb
            if not identifier:
                continue

            if port.startswith("/dev/ttyS") and port != "/dev/ttyS4":
                continue

            device_class = getattr(device, "classe", "desconhecido")
            probe_ok = bool(getattr(device, "probe", {}).get("ok"))
            chip = (
                _inspection.device_to_chip_info(device)
                if device_class == "serial_esptool" and probe_ok
                else {}
            )
            mac = str(chip.get("mac") or "").lower()
            profile = None
            if mac:
                ok_profile, profile_or_error = _boards.get_profile(mac)
                if ok_profile:
                    profile = profile_or_error

            selectable = bool(
                port and device_class == "serial_esptool" and probe_ok
            )
            label = (
                getattr(device, "nome", None)
                or getattr(device, "descricao", None)
                or identifier
            )
            entries[identifier] = {
                "device": device,
                "identifier": identifier,
                "port": port,
                "label": label,
                "class": device_class,
                "state": _inspection.derive_state(device),
                "selectable": selectable,
                "chip": chip,
                "mac": mac,
                "profile": profile,
            }

        return entries


    def _show_hardware_port_selection(
        self,
        entries: dict[str, dict[str, Any]],
    ) -> None:
        self._hardware_por_porta = dict(entries)
        self._hardware_scan_performed = True
        self._porta_ativa = None
        self._mac_porta_ativa = None
        self._refresh_hardware_panel()

        selectable: list[dict[str, Any]] = []
        lines = ["[b]Dispositivos identificados[/b]\n"]
        for entry in entries.values():
            device_class = entry.get("class") or "desconhecido"
            chip = entry.get("chip") or {}
            profile = entry.get("profile") or {}

            if entry.get("selectable"):
                selectable.append(entry)
                prefix = f"[b]{len(selectable)}[/b]."
            else:
                prefix = "[dim]—[/dim]"

            lines.append(
                f"  {prefix} {entry.get('identifier')}  "
                f"{entry.get('label')}  [dim]{device_class}[/dim]"
            )

            if device_class == "serial_virtual":
                lines.append(
                    "      [cyan]Informação:[/cyan] porta serial virtual; "
                    "sondagem esptool e perfil não se aplicam."
                )
                continue
            if device_class == "gravador":
                lines.append(
                    "      [cyan]Informação:[/cyan] gravador USB detectado; "
                    "não possui porta serial nem perfil ESP."
                )
                continue
            if device_class != "serial_esptool":
                lines.append(
                    "      [cyan]Informação:[/cyan] dispositivo listado apenas "
                    "para inventário; não é selecionável."
                )
                continue

            family = chip.get("chip_family") or "Desconhecido"
            mac = chip.get("mac") or "Não informado"
            name = profile.get("board_name") or "Não cadastrado"
            readiness = self._profile_readiness_text(profile or None)
            lines.append(
                f"      Família: {family} · MAC: {mac} · Perfil: {name} · "
                f"{readiness}"
            )
            if entry.get("state") == "erro":
                device = entry.get("device")
                reason = (
                    getattr(device, "probe", {}).get("erro")
                    or getattr(device, "probe", {}).get("motivo")
                    or getattr(device, "motivo", "")
                    or "falha na sondagem esptool"
                )
                lines.append(f"      [yellow]Falha real:[/yellow] {reason}")

        if not entries:
            self._cw(
                "[b]Identificar e selecionar porta[/b]\n\n"
                "[yellow]Nenhum dispositivo encontrado.[/yellow]"
            )
            return
        if not selectable:
            lines.append(
                "\n[yellow]Nenhuma porta serial Espressif com chip-id válido "
                "pode ser selecionada.[/yellow]"
            )
            self._cw("\n".join(lines))
            return

        def _select(value: str | None) -> None:
            if value is None:
                self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                index = int(value.strip()) - 1
                if index < 0 or index >= len(selectable):
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Número inválido.[/red] "
                    f"Escolha entre 1 e {len(selectable)}"
                )
                return

            entry = selectable[index]
            self._porta_ativa = entry.get("port") or None
            self._mac_porta_ativa = entry.get("mac") or None
            self._refresh_hardware_panel()

            chip = entry.get("chip") or {}
            profile = entry.get("profile") or None
            base = [
                "[green]Porta selecionada para esta execução.[/green]",
                "",
                f"Porta:   {self._porta_ativa}",
                f"MAC:     {self._mac_porta_ativa or 'Não informado'}",
                f"Família: {chip.get('chip_family') or 'Desconhecido'}",
            ]

            if not profile:
                base.extend([
                    "Perfil:  Não cadastrado",
                    "",
                    "[yellow]Nenhum perfil existe para este MAC.[/yellow]",
                    "[dim]Use Hardware > Cadastrar / atualizar placa.[/dim]",
                ])
                self._cw("\n".join(base))
                return

            validation = _family_profiles.validate_profile_against_chip(
                profile, chip, require_ready=True
            )
            base.append(
                f"Perfil:  {profile.get('board_name') or 'Não identificada'}"
            )
            base.append(
                f"Estado:  {self._profile_readiness_text(profile)}"
            )

            if not validation.get("use_allowed"):
                base.extend([
                    "",
                    "[yellow]O perfil foi localizado, mas não foi aplicado "
                    "automaticamente.[/yellow]",
                ])
                base.extend(
                    f"  [yellow]• {reason}[/yellow]"
                    for reason in validation.get("reasons", [])
                )
                base.append(
                    "[dim]Revise o perfil em Cadastrar/atualizar ou "
                    "Gerenciar perfis.[/dim]"
                )
                self._cw("\n".join(base))
                return

            base.extend([
                "",
                "[green]Perfil pronto reconhecido automaticamente pelo MAC "
                "e conferido com a família viva.[/green]",
            ])
            ok_context, context = self._current_hardware_context()
            if ok_context and context.get("association_exists"):
                if context.get("expected_mac") == self._mac_porta_ativa:
                    base.append(
                        "[green]A associação do projeto também confere.[/green]"
                    )
                else:
                    base.append(
                        "[red]O projeto está associado a outro MAC; o vínculo "
                        "persistente não foi alterado.[/red]"
                    )
            elif self._projeto_ativo:
                base.append(
                    "[dim]O perfil já está ativo no runtime. Associá-lo ao "
                    "projeto continua sendo uma opção explícita no item 3.[/dim]"
                )
            else:
                base.append(
                    "[dim]Nenhum projeto ativo; o perfil vale somente para "
                    "esta execução.[/dim]"
                )
            self._cw("\n".join(base))

        _pedir_input(
            self,
            "Identificar e selecionar porta",
            f"Porta válida (1-{len(selectable)}):",
            _select,
            "1",
            lista=lines,
        )


    def _choose_database_profile(
        self,
        title: str,
        on_select,
        on_cancel=None,
    ) -> None:
        """Seleciona perfil; ESC retorna ao pai quando informado."""
        ok, profiles = _boards.list_profiles()
        if not ok:
            self._cw(f"[red]Falha ao listar perfis:[/red] {profiles}")
            return
        ordered = sorted(
            profiles,
            key=lambda item: (
                str(item.get("board_name") or "").lower(),
                str(item.get("mac") or ""),
            ),
        )
        if not ordered:
            self._cw("[yellow]O banco não possui perfis físicos.[/yellow]")
            return
        lines = []
        for index, profile in enumerate(ordered, 1):
            lines.append(
                f"  [b]{index}[/b]. "
                f"{profile.get('board_name') or 'Não identificada'} · "
                f"{profile.get('chip_family') or 'Desconhecido'} · "
                f"[dim]{profile.get('mac') or 'MAC ausente'}[/dim]"
            )

        def _choose(value: str | None) -> None:
            if value is None:
                if on_cancel is not None:
                    on_cancel()
                else:
                    self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                index = int(value.strip()) - 1
                if index < 0 or index >= len(ordered):
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Número inválido.[/red] "
                    f"Escolha entre 1 e {len(ordered)}"
                )
                self._choose_database_profile(
                    title,
                    on_select,
                    on_cancel=on_cancel,
                )
                return
            on_select(ordered[index])

        _pedir_input(
            self,
            title,
            f"Perfil (1-{len(ordered)}):",
            _choose,
            "",
            lista=lines,
        )


    def _clear_profile_from_runtime(self, mac: str) -> None:
        for key, raw_entry in list(self._hardware_por_porta.items()):
            if not isinstance(raw_entry, dict):
                continue
            entry_mac = str(
                raw_entry.get("mac")
                or (raw_entry.get("chip") or {}).get("mac")
                or ""
            ).lower()
            if entry_mac != mac.lower():
                continue
            entry = dict(raw_entry)
            entry["profile"] = None
            self._hardware_por_porta[key] = entry
        self._refresh_hardware_panel()


    def _clear_active_project_association_for(self, mac: str) -> bool:
        if not self._projeto_ativo:
            return False
        ok_assoc, association = _project_config.get_board_association(
            self._projeto_ativo
        )
        if not ok_assoc:
            return False
        if str(association.get("board_profile_mac") or "").lower() != mac.lower():
            return False
        ok_clear, _ = _project_config.clear_board_association(
            self._projeto_ativo
        )
        return bool(ok_clear)


    def _action_gerenciar_perfis(self) -> None:
        """Edita, audita, remove ou limpa os perfis físicos do banco."""
        options = [
            ("edit", "Editar ou revisar um perfil"),
            ("delete", "Excluir uma placa/perfil do banco [destrutivo]"),
            ("audit", "Exibir auditoria dos perfis"),
            ("reset", "Limpar todos os perfis físicos [destrutivo]"),
        ]
        lines = [
            "[b]Gerenciar perfis do banco[/b]\n",
            "[dim]Ações destrutivas exigem confirmação digitada e nunca são executadas imediatamente.[/dim]",
        ]
        for index, (_, label) in enumerate(options, 1):
            lines.append(f"  [b]{index}[/b]. {label}")

        def _choose(value: str | None) -> None:
            if value is None:
                self._cw("[dim]Gerenciamento cancelado.[/dim]")
                return
            try:
                index = int(value.strip()) - 1
                if index < 0 or index >= len(options):
                    raise ValueError
            except ValueError:
                self._cw("[red]Opção inválida.[/red]")
                return
            action = options[index][0]

            if action == "edit":
                def _edit(profile: dict) -> None:
                    mac = str(profile.get("mac") or "")
                    self._layout_review_menu(mac)
                self._choose_database_profile(
                    "Editar perfil do banco",
                    _edit,
                    on_cancel=self._action_gerenciar_perfis,
                )
                return

            if action == "delete":
                self._choose_profile_for_deletion()
                return

            if action == "audit":
                ok_audit, audit = _boards.audit_profiles()
                if not ok_audit:
                    self._cw(f"[red]Falha na auditoria:[/red] {audit}")
                    return
                if not audit:
                    self._cw("[green]O banco não possui perfis físicos.[/green]")
                    return
                output = ["[b]Auditoria dos perfis físicos[/b]\n"]
                for item in audit:
                    status = item.get("review_status") or "pending"
                    output.append(
                        f"[b]{item.get('board_name')}[/b] · "
                        f"{item.get('chip_family')} · "
                        f"[dim]{item.get('mac')}[/dim]"
                    )
                    readiness = (
                        "[green]pronto[/green]"
                        if item.get("profile_ready")
                        else "[yellow]incompleto[/yellow]"
                    )
                    output.append(f"  Layout: {status} · Perfil: {readiness}")
                    reasons = list(item.get("reasons") or [])
                    reasons.extend(
                        item.get("profile_readiness_reasons") or []
                    )
                    reasons = list(dict.fromkeys(reasons))
                    if reasons:
                        output.extend(
                            f"  [yellow]• {reason}[/yellow]"
                            for reason in reasons
                        )
                    else:
                        output.append(
                            "  [green]• Sem inconsistência estrutural[/green]"
                        )
                self._cw("\n".join(output))
                return

            ok_profiles, profiles = _boards.list_profiles()
            if not ok_profiles:
                self._cw(f"[red]Falha ao listar perfis:[/red] {profiles}")
                return
            count = len(profiles)
            if count == 0:
                self._cw("[green]O banco já está sem perfis físicos.[/green]")
                return

            confirmation_text = "LIMPAR BANCO"
            consequences = [
                "[bold red]AÇÃO DESTRUTIVA — LIMPEZA TOTAL[/bold red]",
                "",
                f"Serão removidos {count} perfil(is) físico(s), incluindo nomes, pinagens e portas USB cadastradas.",
                "",
                "[yellow]Consequências:[/yellow]",
                "  • todos os perfis físicos precisarão ser cadastrados novamente;",
                "  • mapeamentos manuais não podem ser reconstruídos pelo esptool;",
                "  • a associação do projeto ativo será limpa;",
                "  • projetos fechados podem continuar apontando para MACs removidos até nova associação;",
                "  • nenhuma memória ou configuração da placa física será apagada;",
                "  • um backup verificado do banco será criado antes da gravação.",
                "",
                f"Para confirmar, digite exatamente: [b]{confirmation_text}[/b]",
            ]

            def _reset_typed(value: str | None) -> None:
                if value is None:
                    self._cw(
                        "[dim]Limpeza cancelada; nada foi alterado.[/dim]"
                    )
                    self._action_gerenciar_perfis()
                    return
                if value.strip() != confirmation_text:
                    self._cw(
                        "[yellow]Confirmação incorreta.[/yellow] "
                        "A limpeza total foi cancelada e nada foi alterado."
                    )
                    self._action_gerenciar_perfis()
                    return

                ok_reset, result = _boards.reset_physical_profiles()
                if not ok_reset:
                    self._cw(f"[red]Falha ao limpar banco:[/red] {result}")
                    return
                if self._projeto_ativo:
                    _project_config.clear_board_association(
                        self._projeto_ativo
                    )
                for key, raw_entry in list(
                    self._hardware_por_porta.items()
                ):
                    if isinstance(raw_entry, dict):
                        entry = dict(raw_entry)
                        entry["profile"] = None
                        self._hardware_por_porta[key] = entry
                self._refresh_hardware_panel()
                self._cw(
                    "[green]Banco de perfis físicos limpo.[/green]\n\n"
                    f"Removidos: {result.get('removed', 0)}\n"
                    f"Backup: {result.get('backup') or 'não necessário'}\n\n"
                    "[dim]Somente a associação do projeto ativo foi limpa. "
                    "Projetos fechados com MAC antigo permanecem inalterados "
                    "até serem abertos e associados novamente.[/dim]"
                )

            _pedir_input(
                self,
                "Confirmar limpeza total do banco",
                f"Digite {confirmation_text} para executar:",
                _reset_typed,
                "",
                lista=consequences,
            )

        _pedir_input(
            self,
            "Gerenciar perfis do banco",
            "Opção (1-4):",
            _choose,
            "",
            lista=lines,
        )


    def _choose_profile_for_deletion(self) -> None:
        """Abre a seleção destrutiva com retorno ao gerenciamento."""
        self._choose_database_profile(
            "Excluir perfil do banco",
            self._confirm_delete_database_profile,
            on_cancel=self._action_gerenciar_perfis,
        )

    def _confirm_delete_database_profile(self, profile: dict) -> None:
        """Exige o MAC digitado antes de remover um perfil físico."""
        mac = str(profile.get("mac") or "").strip().lower()
        name = str(profile.get("board_name") or "Não identificada")
        family = str(profile.get("chip_family") or "Desconhecido")

        consequences = [
            "[bold red]AÇÃO DESTRUTIVA — EXCLUSÃO DE PERFIL[/bold red]",
            "",
            f"Placa: {name}",
            f"MAC: {mac}",
            f"Família: {family}",
            "",
            "[yellow]Consequências:[/yellow]",
            "  • o nome, a pinagem, as portas USB e os demais dados manuais deste perfil serão removidos;",
            "  • o perfil precisará ser cadastrado novamente para voltar a ser usado;",
            "  • a associação do projeto ativo será limpa quando apontar para este MAC;",
            "  • projetos fechados não serão reescritos e podem ficar apontando para um perfil ausente;",
            "  • nenhuma memória ou configuração da placa física será apagada;",
            "  • um backup verificado do banco será criado antes da exclusão.",
            "",
            "Para confirmar, digite exatamente o MAC exibido acima.",
        ]

        def _delete_typed(value: str | None) -> None:
            if value is None:
                self._cw(
                    "[dim]Exclusão cancelada; nada foi alterado.[/dim]"
                )
                self._choose_profile_for_deletion()
                return
            if value.strip().lower() != mac:
                self._cw(
                    "[yellow]MAC de confirmação incorreto.[/yellow] "
                    "A exclusão foi cancelada e nada foi alterado."
                )
                self._choose_profile_for_deletion()
                return

            ok_remove, result = _boards.key_json_manager("remove", mac)
            if not ok_remove:
                self._cw(f"[red]Falha ao excluir perfil:[/red] {result}")
                return
            active_cleared = self._clear_active_project_association_for(mac)
            self._clear_profile_from_runtime(mac)
            self._cw(
                "[green]Perfil removido do banco.[/green]\n\n"
                f"Placa: {name}\nMAC: {mac}\nFamília: {family}\n"
                f"Backup: {result.get('backup') or 'não necessário'}\n"
                f"Associação do projeto ativo limpa: "
                f"{'sim' if active_cleared else 'não aplicável'}\n\n"
                "[dim]Projetos fechados não foram modificados.[/dim]"
            )

        _pedir_input(
            self,
            "Confirmar exclusão de placa/perfil",
            "Digite o MAC completo para executar:",
            _delete_typed,
            "",
            lista=consequences,
        )


    def _action_cadastrar_placa(self) -> None:
        """Cadastra o MAC selecionado ou abre seu perfil existente para edição."""
        port = self._porta_ativa
        mac = str(self._mac_porta_ativa or "").lower()
        if not port or not mac:
            self.call_from_thread(
                self._cw,
                "[b]Cadastrar / atualizar placa[/b]\n\n"
                "[yellow]Nenhuma placa identificada e selecionada.[/yellow]\n\n"
                "[dim]Use primeiro Hardware > Identificar e selecionar porta.[/dim]",
            )
            return

        entry = self._hardware_por_porta.get(port, {})
        if entry.get("class") != "serial_esptool":
            self.call_from_thread(
                self._cw,
                "[yellow]A porta virtual não pode gerar um perfil físico.[/yellow]",
            )
            return

        ok_existing, profile_or_error = _boards.get_profile(mac)
        created = False
        if ok_existing:
            profile = profile_or_error
        else:
            ok_chip, chip_info = _chip.read_chip(
                port,
                cancel_event=self._operation_cancel_event,
            )
            if not ok_chip:
                self.call_from_thread(
                    self._cw,
                    f"[red]Falha na leitura mínima da placa:[/red] {chip_info}",
                )
                return
            live_mac = str(chip_info.get("mac") or "").lower()
            if live_mac != mac:
                self.call_from_thread(
                    self._clear_runtime_hardware, True
                )
                self.call_from_thread(
                    self._cw,
                    "[red]A identidade da porta mudou durante o cadastro.[/red]\n\n"
                    f"MAC inicial: {mac}\nMAC atual: {live_mac or 'Não informado'}\n\n"
                    "[dim]Repita a identificação antes de continuar.[/dim]",
                )
                return
            ok_create, result = _boards.find_or_create_by_mac(chip_info)
            if not ok_create:
                self.call_from_thread(
                    self._cw,
                    f"[red]Falha ao cadastrar perfil:[/red] {result}",
                )
                return
            profile = result["profile"]
            created = bool(result.get("created"))
            self.call_from_thread(self._update_runtime_chip, port, chip_info)

        self.call_from_thread(
            self._open_registered_profile_editor,
            mac,
            profile,
            created,
        )


    def _open_registered_profile_editor(
        self,
        mac: str,
        profile: dict,
        created: bool,
    ) -> None:
        status = "cadastrado" if created else "localizado"
        reasons = profile.get("layout_review_reasons") or []
        notes = ""
        if reasons:
            notes = "\n".join(
                f"  [yellow]• {item}[/yellow]" for item in reasons
            )

        ok_layout, layout_or_error = _board_ascii.render(profile)
        if ok_layout:
            layout_section = f"\n\n{layout_or_error}"
        else:
            layout_section = (
                "\n\n[yellow]Layout físico indisponível:[/yellow] "
                f"{layout_or_error}"
            )

        self._cw(
            f"[green]Perfil {status}:[/green] "
            f"{profile.get('board_name') or 'Não identificada'}\n"
            f"MAC: {mac}\n"
            f"Família: {profile.get('chip_family') or 'Desconhecido'}\n"
            f"Target candidato: {profile.get('target') or 'Não definido'}\n"
            f"Prontidão: {self._profile_readiness_text(profile)}\n"
            f"Revisão do layout: "
            f"{self._layout_review_status_text(profile)}"
            + (f"\n\n{notes}" if notes else "")
            + layout_section
        )
        if profile.get("layout_review_required"):
            self._layout_review_menu(mac)
        else:
            self._editar_perfil_campo_menu(mac)


    def _layout_review_status_text(self, profile: dict) -> str:
        status = str(profile.get("layout_review_status") or "pending")
        labels = {
            _family_profiles.LAYOUT_REVIEW_PENDING: (
                "[yellow]Pendente[/yellow]"
            ),
            _family_profiles.LAYOUT_REVIEW_CONFIRMED: (
                "[green]Confirmado[/green]"
            ),
            _family_profiles.LAYOUT_REVIEW_NOT_DEFINED: (
                "[dim]Sem layout físico[/dim]"
            ),
        }
        return labels.get(status, "[yellow]Pendente[/yellow]")


    def _sync_profile_runtime_and_project(self, mac: str) -> None:
        """Atualiza caches e nome associado sem restaurar porta alguma."""
        ok_profile, profile = _boards.get_profile(mac)
        if not ok_profile:
            self._refresh_hardware_panel()
            return

        for key, raw_entry in list(self._hardware_por_porta.items()):
            if not isinstance(raw_entry, dict):
                continue
            entry_mac = str(
                raw_entry.get("mac")
                or (raw_entry.get("chip") or {}).get("mac")
                or ""
            ).lower()
            if entry_mac != mac.lower():
                continue
            entry = dict(raw_entry)
            entry["profile"] = profile
            self._hardware_por_porta[key] = entry

        if self._projeto_ativo:
            ok_assoc, association = _project_config.get_board_association(
                self._projeto_ativo
            )
            if (
                ok_assoc
                and str(association.get("board_profile_mac") or "").lower()
                == mac.lower()
            ):
                board_name = str(
                    profile.get("board_name") or "Não identificada"
                )
                last_port = str(association.get("last_port") or "")
                if board_name != association.get("board_name"):
                    _project_config.set_board_association(
                        self._projeto_ativo,
                        mac,
                        board_name,
                        last_port,
                    )
        self._refresh_hardware_panel()


    def _layout_review_menu(self, mac: str) -> None:
        """Revisão explícita: nada é confirmado ou substituído sozinho."""
        ok_profile, profile = _boards.get_profile(mac)
        if not ok_profile:
            self._cw(f"[red]Erro ao ler perfil:[/red] {profile}")
            return

        family = profile.get("chip_family") or "Desconhecido"
        ok_reference, reference = _family_profiles.get_reference_layout(family)
        reasons = profile.get("layout_review_reasons") or []
        lines = [
            f"[b]Perfil:[/b] {profile.get('board_name') or 'Não identificada'}",
            f"[b]MAC:[/b] {mac}",
            f"[b]Família:[/b] {family}",
            f"[b]Estado:[/b] {self._layout_review_status_text(profile)}",
        ]
        if profile.get("reference_board_name"):
            lines.append(
                "[b]Referência atual:[/b] "
                f"{profile.get('reference_board_name')}"
            )
        if reasons:
            lines.append("\n[b]Motivos:[/b]")
            lines.extend(f"  [yellow]• {item}[/yellow]" for item in reasons)

        actions: list[tuple[str, str]] = [
            ("edit", "Editar o perfil manualmente"),
        ]
        if ok_reference:
            actions.append((
                "reference",
                "Aplicar layout oficial de referência "
                f"({reference.get('reference_board_name')})",
            ))
        actions.extend([
            ("confirm", "Confirmar o layout atual"),
            ("clear", "Manter este perfil sem layout físico"),
        ])

        lines.append("\n[b]Ações explícitas:[/b]")
        for index, (_, label) in enumerate(actions, 1):
            lines.append(f"  [b]{index}[/b]. {label}")

        def _choose(value: str | None) -> None:
            if value is None:
                self._cw("[dim]Revisão cancelada; nada foi alterado.[/dim]")
                return
            try:
                index = int(value.strip()) - 1
                if index < 0 or index >= len(actions):
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Número inválido.[/red] "
                    f"Escolha entre 1 e {len(actions)}"
                )
                return

            action = actions[index][0]
            if action == "edit":
                self._editar_perfil_campo_menu(mac)
                return

            if action == "reference":
                def _apply(confirmed: bool) -> None:
                    if not confirmed:
                        self._cw(
                            "[dim]Aplicação da referência cancelada; "
                            "nada foi alterado.[/dim]"
                        )
                        self._layout_review_menu(mac)
                        return
                    ok_apply, result = _boards.apply_family_reference_layout(mac)
                    if not ok_apply:
                        self._cw(
                            f"[red]Falha ao aplicar referência:[/red] {result}"
                        )
                        self._layout_review_menu(mac)
                        return
                    self._sync_profile_runtime_and_project(mac)
                    self._cw(
                        "[green]Layout oficial aplicado.[/green]\n\n"
                        "Ele continua pendente até você confirmar que a "
                        "placa física corresponde à referência."
                    )
                    self._layout_review_menu(mac)

                _confirmar(
                    self,
                    titulo="Aplicar layout oficial",
                    mensagem=(
                        f"Perfil: {profile.get('board_name')}\n"
                        f"Família: {family}\n"
                        f"Referência: {reference.get('reference_board_name')}\n\n"
                        "A pinagem e as portas USB atuais serão substituídas.\n"
                        "Nome da placa e dados detectados do chip serão preservados.\n\n"
                        "Confirma?"
                    ),
                    on_confirm=_apply,
                )
                return

            if action == "confirm":
                def _confirm_current(confirmed: bool) -> None:
                    if not confirmed:
                        self._cw(
                            "[dim]Confirmação cancelada; nada foi alterado.[/dim]"
                        )
                        self._layout_review_menu(mac)
                        return
                    ok_confirm, result = _boards.confirm_profile_layout(mac)
                    if not ok_confirm:
                        self._cw(
                            f"[red]Layout não confirmado:[/red]\n{result}\n\n"
                            "[dim]Corrija o perfil ou escolha mantê-lo sem layout.[/dim]"
                        )
                        self._layout_review_menu(mac)
                        return
                    self._sync_profile_runtime_and_project(mac)
                    self._cw(
                        "[green]✔ Layout confirmado explicitamente.[/green]\n\n"
                        f"Perfil: {result.get('board_name')}\n"
                        f"MAC: {mac}"
                    )
                    self._editar_perfil_campo_menu(mac)

                _confirmar(
                    self,
                    titulo="Confirmar layout atual",
                    mensagem=(
                        f"Perfil: {profile.get('board_name')}\n"
                        f"MAC: {mac}\n"
                        f"Total físico: {profile.get('total_pins', 0)}\n"
                        f"Referência/origem: "
                        f"{profile.get('reference_board_name') or profile.get('layout_source_type') or 'manual'}\n\n"
                        "Ao confirmar, você declara que revisou a geometria, "
                        "a pinagem e as portas USB desta placa física.\n\n"
                        "Confirma?"
                    ),
                    on_confirm=_confirm_current,
                )
                return

            def _clear(confirmed: bool) -> None:
                if not confirmed:
                    self._cw(
                        "[dim]Limpeza cancelada; nada foi alterado.[/dim]"
                    )
                    self._layout_review_menu(mac)
                    return
                ok_clear, result = _boards.clear_profile_layout(mac)
                if not ok_clear:
                    self._cw(f"[red]Falha ao limpar layout:[/red] {result}")
                    self._layout_review_menu(mac)
                    return
                self._sync_profile_runtime_and_project(mac)
                self._cw(
                    "[green]Perfil mantido sem layout físico.[/green]\n\n"
                    "Pinagem e portas USB foram removidas explicitamente.\n"
                    "Os dados de identidade, memória e target foram preservados."
                )
                self._editar_perfil_campo_menu(mac)

            _confirmar(
                self,
                titulo="Manter sem layout físico",
                mensagem=(
                    f"Perfil: {profile.get('board_name')}\n"
                    f"MAC: {mac}\n\n"
                    "Esta ação removerá total de pinos, pinagem e portas USB.\n"
                    "Ela não remove o perfil nem os dados detectados do chip.\n\n"
                    "Confirma?"
                ),
                on_confirm=_clear,
            )

        _pedir_input(
            self,
            "Revisar layout do perfil",
            f"Ação (1-{len(actions)}):",
            _choose,
            "1",
            lista=lines,
        )

    def _action_associar_perfil(self) -> None:
        """Associa somente perfil pronto; a operação continua offline."""
        if not self._projeto_ativo:
            self._cw(self._msg_sem_projeto())
            return
        ok_profiles, profiles = _boards.list_profiles()
        if not ok_profiles:
            self._cw(f"[red]Falha ao ler perfis:[/red] {profiles}")
            return
        if not profiles:
            self._cw(
                "[yellow]Nenhum perfil cadastrado.[/yellow]\n\n"
                "[dim]Identifique uma porta e cadastre a placa primeiro.[/dim]"
            )
            return

        ok_assoc, association = _project_config.get_board_association(
            self._projeto_ativo
        )
        current_mac = association.get("board_profile_mac", "") if ok_assoc else ""
        lines = []
        for index, profile in enumerate(profiles, 1):
            mac = str(profile.get("mac") or "")
            mark = " [green]► projeto[/green]" if mac == current_mac else ""
            live = " [cyan]conectada[/cyan]" if mac == self._mac_porta_ativa else ""
            ready = (
                " [green]pronto[/green]" if profile.get("profile_ready")
                else " [yellow]incompleto[/yellow]"
            )
            lines.append(
                f"  [b]{index}[/b]. "
                f"{profile.get('board_name') or 'Não identificada'} "
                f"[dim]({mac}) · {profile.get('chip_family') or 'Desconhecido'}[/dim]"
                f"{ready}{mark}{live}"
            )

        def _associate(value: str | None) -> None:
            if value is None:
                self._cw("[dim]Associação cancelada.[/dim]")
                return
            try:
                index = int(value.strip()) - 1
                if index < 0 or index >= len(profiles):
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Número inválido.[/red] Escolha entre 1 e {len(profiles)}"
                )
                return

            profile = profiles[index]
            mac = str(profile.get("mac") or "")
            if not profile.get("profile_ready"):
                reasons = self._profile_readiness_reasons(profile)
                self._cw(
                    "[yellow]Este perfil ainda não está pronto e não foi "
                    "associado.[/yellow]\n\n"
                    + "\n".join(f"  • {reason}" for reason in reasons)
                    + "\n\n[dim]Revise-o em Cadastrar/atualizar ou "
                      "Gerenciar perfis.[/dim]"
                )
                return

            last_port = (
                self._porta_ativa
                if mac and mac == self._mac_porta_ativa and self._porta_ativa
                else ""
            )
            ok_set, result = _project_config.set_board_association(
                self._projeto_ativo,
                mac,
                profile.get("board_name") or "Não identificada",
                last_port=last_port,
            )
            if not ok_set:
                self._cw(f"[red]Falha ao associar perfil:[/red] {result}")
                return
            self._refresh_hardware_panel()
            live_note = (
                "Identidade viva conferida agora."
                if mac == self._mac_porta_ativa and self._porta_ativa
                else "Associação feita offline; a identidade será conferida "
                     "antes de qualquer operação física."
            )
            self._cw(
                "[green]Perfil pronto associado ao projeto.[/green]\n\n"
                f"Placa: {profile.get('board_name') or 'Não identificada'}\n"
                f"MAC: {mac}\n"
                f"Família: {profile.get('chip_family') or 'Desconhecido'}\n"
                f"Última porta: {last_port or 'Nenhuma'}\n\n"
                f"[dim]{live_note}\nO target não foi alterado.[/dim]"
            )

        _pedir_input(
            self,
            "Associar perfil ao projeto",
            f"Perfil (1-{len(profiles)}):",
            _associate,
            "1",
            lista=lines,
        )


    def _action_configurar_target(self) -> None:
        """Valida o target do perfil na versão ESP-IDF do projeto."""
        ok_context, context = self._current_hardware_context()
        if not ok_context:
            self.call_from_thread(
                self._cw,
                f"[red]Falha ao resolver contexto:[/red] {context}",
            )
            return
        if not context.get("project_active"):
            self.call_from_thread(self._cw, self._msg_sem_projeto())
            return
        profile = context.get("expected_profile")
        if not profile:
            self.call_from_thread(
                self._cw,
                "[yellow]Projeto sem perfil associado.[/yellow]\n\n"
                "[dim]Use Hardware > Associar perfil ao projeto.[/dim]",
            )
            return

        if not context.get("expected_profile_ready"):
            reasons = context.get("expected_profile_readiness_reasons") or []
            self.call_from_thread(
                self._cw,
                "[yellow]O perfil associado ainda não está pronto.[/yellow]\n\n"
                + "\n".join(f"  • {reason}" for reason in reasons)
                + "\n\n[dim]Revise o perfil antes de aplicar seu target.[/dim]",
            )
            return

        cfg = context.get("config") or {}
        idf_version = str(cfg.get("idf_version") or "").strip()
        candidate = str(
            profile.get("target")
            or _family_profiles.target_for_family(profile.get("chip_family"))
            or ""
        ).strip()
        if not candidate:
            self.call_from_thread(
                self._cw,
                "[red]O perfil não possui target candidato.[/red]",
            )
            return

        ok_targets, targets = _builder.list_supported_targets(
            idf_version,
            cancel_event=self._operation_cancel_event,
        )
        if not ok_targets:
            self.call_from_thread(
                self._cw,
                f"[red]Não foi possível consultar targets do {idf_version}:[/red] "
                f"{targets}",
            )
            return
        if candidate not in targets:
            self.call_from_thread(
                self._cw,
                f"[red]Target '{candidate}' não é suportado pelo "
                f"ESP-IDF {idf_version}.[/red]\n\n"
                f"[dim]Disponíveis: {', '.join(targets)}[/dim]",
            )
            return

        current = str(cfg.get("target") or "").strip()
        if current == candidate:
            self.call_from_thread(
                self._cw,
                "[green]O target do projeto já confere com o perfil.[/green]\n\n"
                f"Target: {candidate}\nESP-IDF: {idf_version}",
            )
            return

        self.call_from_thread(
            self._confirm_project_target,
            context,
            candidate,
            targets,
        )


    def _confirm_project_target(
        self,
        context: dict,
        candidate: str,
        targets: list[str],
    ) -> None:
        cfg = context.get("config") or {}
        project_dir = context.get("project_dir") or ""
        idf_version = str(cfg.get("idf_version") or "")
        current = str(cfg.get("target") or "Não definido")

        def _apply(confirmed: bool) -> None:
            if not confirmed:
                self._cw("[dim]Configuração do target cancelada.[/dim]")
                return
            self._start_operation(
                f"Definição do target {candidate}",
                cancelable=True,
            )
            self._run_set_target_worker(
                project_dir,
                candidate,
                idf_version,
            )

        _confirmar(
            self,
            titulo="Configurar target do projeto",
            mensagem=(
                f"Projeto: {context.get('project_name')}\n"
                f"Perfil:  {context.get('profile_name')}\n"
                f"MAC:     {context.get('expected_mac_display')}\n"
                f"IDF:     {idf_version}\n"
                f"Atual:   {current}\n"
                f"Novo:    {candidate}\n\n"
                "O ESP-IDF apagará o build e recriará sdkconfig.\n"
                "O ESP Lab preserva e restaura o estado anterior em falha "
                "ou cancelamento.\n\n"
                "Confirma?"
            ),
            on_confirm=_apply,
        )


    def _action_definir_perfil(self) -> None:
        """Compatibilidade: o estado global foi substituído pela associação."""
        self.call_from_thread(self._action_associar_perfil)

    def _action_rescan(self) -> None:
        """Hardware > Buscar placas: confirmacao modal antes de varrer.
        Usa inspection.service (nao os modulos antigos scanner/chip_info)."""
        def _executar(confirmado: bool) -> None:
            if not confirmado:
                self._cw("[dim]Busca cancelada.[/dim]")
                return
            # Placeholder imediato: coleta completa pode levar minutos
            # (espefuse por porta). Sem isso a tela fica parada, parecendo
            # travada, entre a confirmacao e o primeiro resultado.
            self._content().clear()
            self._content().write(
                "[dim]Aguarde... interrogando placas "
                "(pode levar alguns minutos por porta)...[/dim]"
            )
            # Rescan e I/O pesado: roda em worker para nao bloquear
            self._start_operation("Busca de placas")
            self._run_rescan_worker()
        _confirmar(
            self,
            titulo="Buscar placas",
            mensagem=("Esta operacao interroga todas as portas ESP.\n"
                      "Processos ativos na porta serao interrompidos.\n\n"
                      "Deseja continuar?"),
            on_confirm=_executar,
        )

    @work(thread=True)
    def _run_rescan_worker(self) -> None:
        """Executa o rescan completo em background apos confirmacao.
        Para cada dispositivo compativel com esptool: sonda (chip-id),
        coleta completo (flash-id/seguranca/efuse/particoes/boot) via
        inspection.service.collect_full, atualiza/cria perfil no
        boards_db e reporta divergencias."""
        from ..hardware.inspection import service as _inspection

        try:
            ok, dispositivos = _inspection.scan_hardware()
            if not ok:
                self.call_from_thread(
                    self._cw, f"[red]Busca falhou:[/red] {dispositivos}"
                )
                return

            alvos = [
                d for d in dispositivos
                if d.classe == "serial_esptool" and d.probe.get("ok")
            ]
            if not alvos:
                self.call_from_thread(
                    self._cw, "[dim]Nenhuma placa ESP encontrada.[/dim]"
                )
                return

            linhas = ["[b]Busca de placas concluida:[/b]\n"]
            for d in alvos:
                ok2, relatorio = _inspection.collect_full(d)
                if not ok2:
                    linhas.append(f"[yellow]{d.porta}: {relatorio}[/yellow]")
                    continue

                chip_info = _inspection.relatorio_to_chip_info(relatorio)
                ok3, res = _boards.find_or_create_by_mac(chip_info)
                if not ok3:
                    linhas.append(
                        f"[yellow]{d.porta}: perfil nao resolvido: "
                        f"{res}[/yellow]"
                    )
                    continue

                perfil = res["profile"]
                modelo = perfil.get("board_name") or perfil.get("mac")
                linhas.append(
                    "[b]{}[/b]  {}  Flash {}  PSRAM {}".format(
                        d.porta, chip_info["chip_family"],
                        chip_info["flash_size"], chip_info["psram"],
                    )
                )
                linhas.append(
                    "  Modelo: {}  MAC: {}".format(modelo, chip_info["mac"])
                )

                comparison = res.get("comparison") or {}
                for item in comparison.get("divergencias") or []:
                    if item.get("locked"):
                        linhas.append(
                            "  [red]! FIXO preservado — {}: "
                            "chip={} perfil={}[/red]".format(
                                item["campo"], item["no_chip"],
                                item["no_perfil"],
                            )
                        )
                    else:
                        linhas.append(
                            "  [yellow]! Observado antes da atualização — {}: "
                            "chip={} perfil={}[/yellow]".format(
                                item["campo"], item["no_chip"],
                                item["no_perfil"],
                            )
                        )

                completed = res.get("enriched_locked_fields") or []
                if completed:
                    linhas.append(
                        "  [cyan]i Dados fixos ausentes completados: {}[/cyan]"
                        .format(", ".join(completed))
                    )

                updated = res.get("updated_fields") or []
                if updated:
                    linhas.append(
                        "  [dim]Dados observáveis atualizados após comparação: {}[/dim]"
                        .format(", ".join(updated))
                    )

                unavailable = [
                    item["campo"]
                    for item in comparison.get("dados_ausentes") or []
                    if item.get("lado") == "chip"
                ]
                if unavailable:
                    linhas.append(
                        "  [dim]Sem leitura viva para comparar: {}[/dim]"
                        .format(", ".join(unavailable))
                    )

            self.call_from_thread(self._cw, "\n".join(linhas))
        finally:
            self._finish_operation()


    def _action_layout(self) -> None:
        """Compatibilidade interna: renderiza o perfil vivo ou o do projeto."""
        ok_context, context = self._current_hardware_context()
        if not ok_context:
            self._cw(f"[red]Falha ao resolver contexto:[/red] {context}")
            return
        profile = (
            context.get("current_profile")
            or context.get("expected_profile")
        )
        mac = (
            context.get("current_mac")
            or context.get("expected_mac")
            or ""
        )
        if not profile:
            self._cw(
                "[yellow]Nenhum perfil disponível para layout.[/yellow]\n\n"
                "[dim]Cadastre uma placa ou associe um perfil ao projeto.[/dim]"
            )
            return
        ok_render, drawing = _board_ascii.render(profile)
        if not ok_render:
            self._cw(
                f"[yellow]Layout indisponível:[/yellow] {drawing}\n\n"
                "[dim]Revise total_pins e pinout_mapping no perfil.[/dim]"
            )
            return
        self._cw(
            f"[b]Layout — {profile.get('board_name') or 'Não identificada'}[/b] "
            f"[dim]({mac})[/dim]\n\n{drawing}"
        )
    # ==================================================================
    # ===  [IDF] SOFTWARE / ESP-IDF
    # ===  menu: Software
    # ===  usa: _idf_mgr, _updates
    # ==================================================================

    def _action_updates(self) -> str:
        """
        Software > Estado do ambiente: raio-X completo do ambiente —
        todos os 4 slots ESP-IDF (fixa/atualizavel, EOL, instalada,
        ativa, reversao) com o esptool de CADA um, mais as dependencias
        da propria aplicacao (app-venv). Absorve o que antes era a tela
        separada "ESP-IDF (versoes)" — eram redundantes com esta.
        """
        ok, status = _idf_mgr.list_slots_status()
        if not ok:
            return f"[red]Matriz de compatibilidade indisponivel:[/red] {status}"

        PAPEL_LABEL = {"fixed": "fixa", "updatable": "atualizavel"}
        chaves = sorted(status.keys(), key=lambda v: [int(x) for x in v.split(".")])

        linhas = ["[b]Estado do ambiente[/b]\n"]
        linhas.append("[b]ESP-IDF — slots:[/b]\n")
        for key in chaves:
            s = status[key]
            papel = PAPEL_LABEL.get(s["role"], s["role"])
            if s["release"] and s["installed"]:
                estado = f"[green]{s['release']}[/green]"
                if s["active"]:
                    estado += "  [black on green] ativa [/black on green]"
                esptool_ver = _sysinfo.detect_esptool_for(s["release"])
                estado += f"\n    [dim]esptool: {esptool_ver}[/dim]"
            elif s["release"] and not s["installed"]:
                estado = f"[red]{s['release']} (ausente em disco — use Instalar/Reparar)[/red]"
            else:
                estado = "[dim]nao instalada[/dim]"
            eol_tag = ""
            if s["role"] == "fixed":
                eol_tag = ("  [dim](EOL — congelada)[/dim]" if s["eol"]
                           else "  [dim](fixa por escolha do ESP Lab)[/dim]")
            linhas.append(f"  [b]{key}[/b] ({papel}){eol_tag}\n    {estado}")
            if s["rollback"]:
                linhas.append(f"    [dim]reversao disponivel: {s['rollback']}[/dim]")

        # Dependencias da APLICACAO (app-venv) — nao tem relacao com
        # ESP-IDF; esptool nunca aparece aqui (nao vive no app-venv).
        ok2, resumo = _updates.get_update_summary()
        linhas.append("\n[b]Dependencias da aplicacao (app-venv):[/b]")
        if ok2:
            pkgs = resumo.get("python_packages", [])
            if pkgs:
                for p in pkgs:
                    crit = " [red][critico][/red]" if p.get("critical") else ""
                    linhas.append(f"  {p['name']:<20} {p['installed']} -> {p['available']}{crit}")
            else:
                linhas.append("  [green]Todas atualizadas.[/green]")
        else:
            linhas.append("  [dim]Nao foi possivel verificar.[/dim]")

        return "\n".join(linhas)

    def _action_idf_install_repair(self) -> None:
        """Lista os slots e inicia Instalacao ou Reparo cancelavel."""
        ok, status = _idf_mgr.list_slots_status()
        if not ok:
            self.call_from_thread(
                self._cw,
                f"[red]Matriz de compatibilidade indisponivel:[/red] {status}",
            )
            return
        if self._operation_cancel_event.is_set():
            self.call_from_thread(
                self._cw, "[yellow]Operacao cancelada.[/yellow]")
            return

        keys = sorted(
            status.keys(),
            key=lambda value: [int(part) for part in value.split(".")],
        )
        lines = ["[b]Instalar / Reparar[/b]\n"]
        options: list[tuple[str, str, str | None]] = []
        for key in keys:
            item = status[key]
            if not item["release"]:
                options.append((key, "instalar", None))
                lines.append(
                    f"  [b]{len(options)}[/b]. {key} — "
                    "[cyan]Instalar[/cyan]")
            else:
                options.append((key, "reparar", item["release"]))
                marker = (
                    ""
                    if item["installed"]
                    else "  [red](ausente em disco!)[/red]"
                )
                lines.append(
                    f"  [b]{len(options)}[/b]. {key} — "
                    f"[yellow]Reparar[/yellow] ({item['release']}){marker}"
                )

        self.call_from_thread(
            self._cw, "[dim]Selecione o slot no dialogo...[/dim]")

        def _choose(value):
            if value is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                index = int(value.strip()) - 1
                if index < 0 or index >= len(options):
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Numero invalido.[/red] "
                    f"Escolha entre 1 e {len(options)}")
                return

            slot_key, operation, current_tag = options[index]
            if operation == "instalar":
                self._cw(
                    f"[dim]Instalando slot {slot_key}...\n"
                    "Isso pode demorar varios minutos.[/dim]")
                self._start_operation(
                    f"Instalacao ESP-IDF {slot_key}",
                    cancelable=True,
                )
                self._run_idf_install_worker(slot_key)
                return

            def _confirm_repair(confirmed):
                if not confirmed:
                    self._cw("[dim]Reparo cancelado.[/dim]")
                    return
                self._cw(
                    f"[dim]Reparando slot {slot_key} ({current_tag})...\n"
                    "A instalacao atual sera preservada ate a nova copia "
                    "ser validada.[/dim]")
                self._start_operation(
                    f"Reparo ESP-IDF {slot_key}",
                    cancelable=True,
                )
                self._run_idf_repair_worker(slot_key)

            _confirmar(
                self,
                titulo="Reparar ESP-IDF",
                mensagem=(
                    f"Prepara uma nova copia de {current_tag} "
                    f"no slot {slot_key}.\n"
                    "A instalacao atual permanece intacta durante clone, "
                    "instalacao e validacao. Ela so e substituida depois "
                    "da nova copia estar integra.\n\n"
                    "Confirma?"
                ),
                on_confirm=_confirm_repair,
            )

        self.call_from_thread(
            _pedir_input,
            self,
            "Instalar / Reparar",
            f"Digite o numero (1-{len(options)}):",
            _choose,
            "1",
            lista=lines[1:],
        )

    @work(thread=True)
    def _run_idf_install_worker(self, slot_key: str) -> None:
        self.call_from_thread(
            self._cw_iniciar_stream,
            f"[b]Instalando slot {slot_key}[/b]\n"
            "[dim]Aguarde — Ctrl+C cancela com limpeza confirmada.[/dim]\n",
        )
        self.call_from_thread(
            self._set_status, f"instalando {slot_key}...")

        def _progress(
            kind: str, message: str, same_line: bool = False
        ) -> None:
            cancelled = (
                kind == "cancelado"
                or "cancelado" in message.lower()
            )
            color = (
                "[yellow]" if cancelled
                else "[red]" if kind == "erro"
                else "[dim]"
            )
            end = (
                "[/yellow]" if cancelled
                else "[/red]" if kind == "erro"
                else "[/dim]"
            )
            self.call_from_thread(
                self._cw_stream_linha,
                f"{color}{message}{end}",
                same_line,
            )

        try:
            ok, result = _idf_mgr.install_slot(
                slot_key,
                progress_cb=_progress,
                background=False,
                cancel_event=self._operation_cancel_event,
            )
            cancelled = (
                self._operation_cancel_event.is_set()
                or "cancelado" in str(result).lower()
            )
            if ok:
                self.call_from_thread(
                    self._cw_stream_linha,
                    f"\n[green]✔ Slot {slot_key} instalado "
                    f"({result['tag']}).[/green]\n"
                    "[dim]Use 'Ativar versao' para torna-la ativa.[/dim]",
                    False,
                )
            elif cancelled:
                self.call_from_thread(
                    self._cw_stream_linha,
                    "\n[yellow]Cancelamento concluido. "
                    "Nenhuma instalacao incompleta foi registrada.[/yellow]",
                    False,
                )
            else:
                self.call_from_thread(
                    self._cw_stream_linha,
                    f"\n[red]✘ Falha na instalacao:[/red] {result}",
                    False,
                )
        finally:
            self._finish_operation()

    @work(thread=True)
    def _run_idf_repair_worker(self, slot_key: str) -> None:
        self.call_from_thread(
            self._cw_iniciar_stream,
            f"[b]Reparando slot {slot_key}[/b]\n"
            "[dim]A instalacao atual permanece ativa ate a nova "
            "ser validada.[/dim]\n",
        )
        self.call_from_thread(
            self._set_status, f"reparando {slot_key}...")

        def _progress(
            kind: str, message: str, same_line: bool = False
        ) -> None:
            cancelled = (
                kind == "cancelado"
                or "cancelado" in message.lower()
            )
            color = (
                "[yellow]" if cancelled
                else "[red]" if kind == "erro"
                else "[dim]"
            )
            end = (
                "[/yellow]" if cancelled
                else "[/red]" if kind == "erro"
                else "[/dim]"
            )
            self.call_from_thread(
                self._cw_stream_linha,
                f"{color}{message}{end}",
                same_line,
            )

        try:
            ok, result = _idf_mgr.repair_slot(
                slot_key,
                progress_cb=_progress,
                background=False,
                cancel_event=self._operation_cancel_event,
            )
            cancelled = (
                self._operation_cancel_event.is_set()
                or "cancelado" in str(result).lower()
            )
            if ok:
                self.call_from_thread(
                    self._cw_stream_linha,
                    f"\n[green]✔ Slot {slot_key} reparado e validado "
                    f"({result['tag']}).[/green]",
                    False,
                )
            elif cancelled:
                self.call_from_thread(
                    self._cw_stream_linha,
                    "\n[yellow]Cancelamento concluido. "
                    "A instalacao anterior foi preservada.[/yellow]",
                    False,
                )
            else:
                self.call_from_thread(
                    self._cw_stream_linha,
                    f"\n[red]✘ Falha no reparo:[/red] {result}",
                    False,
                )
        finally:
            self._finish_operation()

    def _action_idf_ativar(self) -> None:
        """Software > Ativar versao: lista releases instaladas (dos 4
        slots) e ativa a escolhida."""
        ok, status = _idf_mgr.list_slots_status()
        if not ok:
            self.call_from_thread(self._cw, f"[red]Matriz de compatibilidade indisponivel:[/red] {status}")
            return

        chaves = sorted(status.keys(), key=lambda v: [int(x) for x in v.split(".")])
        instaladas = [(k, status[k]) for k in chaves if status[k]["installed"]]

        if not instaladas:
            self.call_from_thread(self._cw,
                "[yellow]Nenhuma versao instalada.[/yellow]\n\n"
                "[dim]Use 'Instalar / Reparar' primeiro.[/dim]")
            return

        linhas = ["[b]Ativar versao ESP-IDF[/b]\n"]
        for i, (key, s) in enumerate(instaladas, start=1):
            ativa = "  [black on green] ATIVA [/black on green]" if s["active"] else ""
            linhas.append(f"  [b]{i}[/b]. {s['release']}  [dim](slot {key})[/dim]{ativa}")

        self.call_from_thread(self._cw, "[dim]Selecione a versao no dialogo...[/dim]")

        def _escolher(valor):
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(instaladas):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(instaladas)}")
                return
            key, s = instaladas[idx]
            if s["active"]:
                self._cw(f"[yellow]{s['release']} ja e a versao ativa.[/yellow]")
                return
            self._cw(f"[dim]Ativando {s['release']}...[/dim]")
            self._start_operation(
                f"Ativacao ESP-IDF {s['release']}", cancelable=True)
            self._run_idf_activate_worker(s["release"])

        self.call_from_thread(
            _pedir_input, self,
            "Ativar versao",
            f"Digite o numero (1-{len(instaladas)}):",
            _escolher, "1",
            lista=linhas[1:])

    @work(thread=True)
    def _run_idf_activate_worker(self, versao: str) -> None:
        """Valida e ativa uma versao em worker cancelavel."""
        self.call_from_thread(
            self._set_status, f"ativando {versao}...")
        try:
            ok, result = _idf_mgr.activate(
                versao,
                cancel_event=self._operation_cancel_event,
            )
            cancelled = (
                self._operation_cancel_event.is_set()
                or "cancelado" in str(result).lower()
            )
            if ok:
                self.call_from_thread(
                    self._cw,
                    f"[green]✔ ESP-IDF {versao} ativado.[/green]",
                )
            elif cancelled:
                self.call_from_thread(
                    self._cw,
                    "[yellow]Cancelamento concluido. "
                    "A versao ativa nao foi alterada.[/yellow]",
                )
            else:
                self.call_from_thread(
                    self._cw,
                    f"[red]✘ Falha ao ativar:[/red] {result}",
                )

            if not cancelled:
                text = self._compute_software_text()
                self.call_from_thread(
                    self._apply_software_text, text)
        finally:
            self._finish_operation()

    def _action_idf_atualizar(self) -> None:
        """Consulta e aplica atualizacao do slot atualizavel."""
        ok_slot, slot_key = _idf_mgr.updatable_slot_key()
        if not ok_slot:
            self.call_from_thread(
                self._cw,
                f"[red]Matriz de compatibilidade indisponivel:[/red] "
                f"{slot_key}",
            )
            return

        self.call_from_thread(
            self._cw,
            "[dim]Consultando releases do ESP-IDF...[/dim]",
        )
        ok, info = _idf_mgr.check_update(
            slot_key,
            cancel_event=self._operation_cancel_event,
        )
        cancelled = (
            self._operation_cancel_event.is_set()
            or "cancelado" in str(info).lower()
        )
        if cancelled:
            self.call_from_thread(
                self._cw,
                "[yellow]Consulta de atualizacao cancelada.[/yellow]",
            )
            return
        if not ok:
            self.call_from_thread(
                self._cw,
                f"[red]Nao foi possivel verificar atualizacao:[/red] "
                f"{info}",
            )
            return
        if not info["update_disponivel"]:
            self.call_from_thread(
                self._cw,
                f"[green]Slot {slot_key} ja esta na versao mais recente "
                f"({info['current']}).[/green]",
            )
            return

        def _confirm_update(confirmed):
            if not confirmed:
                self._cw("[dim]Atualizacao cancelada.[/dim]")
                return
            self._cw_iniciar_stream(
                f"[dim]Atualizando {info['current']} -> "
                f"{info['latest']}...\n"
                "A versao atual permanece intacta ate a nova "
                "ser validada.[/dim]"
            )
            self._start_operation(
                f"Atualizacao ESP-IDF {slot_key}",
                cancelable=True,
            )
            self._run_idf_update_worker(slot_key)

        self.call_from_thread(
            _confirmar,
            self,
            titulo="Atualizar ESP-IDF",
            mensagem=(
                f"Slot {slot_key}: {info['current']} -> "
                f"{info['latest']}\n\n"
                "A versao atual e mantida como reversao.\n\n"
                "Confirma?"
            ),
            on_confirm=_confirm_update,
        )

    @work(thread=True)
    def _run_idf_update_worker(self, slot_key: str) -> None:
        self.call_from_thread(
            self._set_status, f"atualizando {slot_key}...")

        def _progress(
            kind: str, message: str, same_line: bool = False
        ) -> None:
            cancelled = (
                kind == "cancelado"
                or "cancelado" in message.lower()
            )
            color = (
                "[yellow]" if cancelled
                else "[red]" if kind == "erro"
                else "[dim]"
            )
            end = (
                "[/yellow]" if cancelled
                else "[/red]" if kind == "erro"
                else "[/dim]"
            )
            self.call_from_thread(
                self._cw_stream_linha,
                f"{color}{message}{end}",
                same_line,
            )

        try:
            ok, result = _idf_mgr.apply_update(
                slot_key,
                progress_cb=_progress,
                background=False,
                cancel_event=self._operation_cancel_event,
            )
            cancelled = (
                self._operation_cancel_event.is_set()
                or "cancelado" in str(result).lower()
            )
            if ok and result.get("status") == "ja_atualizado":
                self.call_from_thread(
                    self._cw,
                    f"[green]Slot {slot_key} ja esta atualizado "
                    f"({result['release']}).[/green]",
                )
            elif ok:
                self.call_from_thread(
                    self._cw_stream_linha,
                    f"\n[green]✔ Slot {slot_key} atualizado: "
                    f"{result['de']} -> {result['para']}.[/green]\n"
                    "[dim]Use 'Ativar versao' se quiser torna-la "
                    "ativa.[/dim]",
                    False,
                )
                text = self._compute_software_text()
                self.call_from_thread(
                    self._apply_software_text, text)
            elif cancelled:
                self.call_from_thread(
                    self._cw_stream_linha,
                    "\n[yellow]Cancelamento concluido. "
                    "A versao anterior continua registrada.[/yellow]",
                    False,
                )
            else:
                self.call_from_thread(
                    self._cw_stream_linha,
                    f"\n[red]✘ Falha na atualizacao:[/red] {result}",
                    False,
                )
        finally:
            self._finish_operation()

    def _action_idf_reverter(self) -> None:
        """Confirma e executa a reversao em worker cancelavel."""
        ok_slot, slot_key = _idf_mgr.updatable_slot_key()
        if not ok_slot:
            self.call_from_thread(
                self._cw,
                f"[red]Matriz de compatibilidade indisponivel:[/red] "
                f"{slot_key}",
            )
            return

        ok, status = _idf_mgr.list_slots_status()
        if not ok:
            self.call_from_thread(
                self._cw,
                f"[red]Matriz de compatibilidade indisponivel:[/red] "
                f"{status}",
            )
            return
        if self._operation_cancel_event.is_set():
            self.call_from_thread(
                self._cw,
                "[yellow]Reversao cancelada.[/yellow]",
            )
            return

        slot_status = status.get(slot_key, {})
        rollback = slot_status.get("rollback")
        if not rollback:
            self.call_from_thread(
                self._cw,
                "[yellow]Nao ha atualizacao recente para "
                "reverter.[/yellow]",
            )
            return

        def _confirm_revert(confirmed):
            if not confirmed:
                self._cw("[dim]Reversao cancelada.[/dim]")
                return
            self._start_operation(
                f"Reversao ESP-IDF {slot_key}",
                cancelable=True,
            )
            self._run_idf_revert_worker(slot_key)

        self.call_from_thread(
            _confirmar,
            self,
            titulo="Reverter atualizacao",
            mensagem=(
                f"Slot {slot_key}: volta de "
                f"{slot_status['release']} para {rollback}.\n\n"
                "Confirma?"
            ),
            on_confirm=_confirm_revert,
        )

    @work(thread=True)
    def _run_idf_revert_worker(self, slot_key: str) -> None:
        self.call_from_thread(
            self._set_status, f"revertendo {slot_key}...")
        try:
            ok, result = _idf_mgr.revert_slot(
                slot_key,
                cancel_event=self._operation_cancel_event,
            )
            cancelled = (
                self._operation_cancel_event.is_set()
                or "cancelado" in str(result).lower()
            )
            if ok:
                self.call_from_thread(
                    self._cw,
                    f"[green]✔ Slot {slot_key} revertido: "
                    f"{result['de']} -> {result['para']}.[/green]",
                )
                text = self._compute_software_text()
                self.call_from_thread(
                    self._apply_software_text, text)
            elif cancelled:
                self.call_from_thread(
                    self._cw,
                    "[yellow]Cancelamento concluido. "
                    "O registro nao foi alterado.[/yellow]",
                )
            else:
                self.call_from_thread(
                    self._cw,
                    f"[red]✘ Falha ao reverter:[/red] {result}",
                )
        finally:
            self._finish_operation()

    # ==================================================================
    # ===  [MON] MONITOR (daemon multi-porta @E10)
    # ===  usa: _paths, _ports, _pedir_input, _confirmar, subprocess
    # ==================================================================
    #
    # Arquitetura: a leitura NAO roda na TUI. Um daemon por porta e dono
    # exclusivo da serial, grava log e distribui o stream por socket Unix.
    # A TUI apenas sobe/derruba daemons e abre o visualizador via suspend().
    # Detalhes de implementacao (daemon/socket/viewer) nao aparecem no menu.

    _MONITOR_SHUTDOWN_TIMEOUT = 0.5   # s por daemon no shutdown educado

    def _monitor_run_dir(self) -> _Path:
        """Diretorio dos sockets do monitor (via paths, nunca fixo)."""
        return _paths.get_paths().run_dir

    def _monitor_logs_dir(self) -> _Path:
        """Diretorio dos logs do monitor (via paths, nunca fixo)."""
        return _paths.get_paths().monitor_logs

    def _monitor_sock_para_porta(self, port: str) -> _Path:
        """Caminho do socket de uma porta (mesma regra do daemon)."""
        nome = _Path(port).name
        return self._monitor_run_dir() / "monitor-{}.sock".format(nome)

    def _monitor_porta_de_sock(self, sock_path: _Path) -> str:
        """Extrai o nome da porta a partir do nome do socket."""
        nome = sock_path.name
        if nome.startswith("monitor-") and nome.endswith(".sock"):
            return nome[len("monitor-"):-len(".sock")]
        return nome

    def _monitor_ctrl(self, sock_path: _Path, msg: dict,
                      timeout: float = 1.0):
        """
        Fala com um daemon como cliente 'control' transiente: conecta,
        envia uma mensagem, le uma resposta, desconecta. O slot de control
        e liberado ao desconectar (confirmado no daemon). Nunca lanca:
        devolve o dict de resposta ou None.
        """
        s = None
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(str(sock_path))
            s.sendall((json.dumps({"t": "hello", "role": "control"})
                       + "\n").encode("utf-8"))
            s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            alvo = msg.get("t", "")
            buf = b""
            fim = time.time() + timeout
            while time.time() < fim:
                try:
                    chunk = s.recv(4096)
                except (socket.timeout, OSError):
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    linha, buf = buf.split(b"\n", 1)
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        resp = json.loads(linha.decode("utf-8"))
                    except Exception:
                        continue
                    # Ignora a confirmacao do hello (re="hello"). Aceita a
                    # resposta do comando enviado (re == alvo) ou um erro.
                    re = resp.get("re")
                    if re == "hello":
                        continue
                    if resp.get("t") == "error" or re == alvo:
                        return resp
            return None
        except Exception:
            return None
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass

    def _monitor_ativos(self) -> list:
        """
        Varre o run_dir por sockets e sonda cada um. Disco e a verdade:
        sobrevive a reinicio da TUI e ve daemons subidos pelo terminal.
        Socket orfao (daemon morto) nao responde e e ignorado.
        Retorna lista de dicts: porta, socket, conectada, estado.
        """
        ativos = []
        run_dir = self._monitor_run_dir()
        for sock in sorted(run_dir.glob("monitor-*.sock")):
            resp = self._monitor_ctrl(sock, {"t": "status"}, timeout=1.0)
            if resp is None:
                continue  # socket orfao ou daemon mudo
            ativos.append({
                "porta": self._monitor_porta_de_sock(sock),
                "socket": sock,
                "conectada": bool(resp.get("connected")),
                "estado": resp,
            })
        return ativos

    def _monitor_daemon_vivo(self, port: str) -> bool:
        """True se ha um daemon respondendo para esta porta."""
        sock = self._monitor_sock_para_porta(port)
        if not sock.exists():
            return False
        return self._monitor_ctrl(sock, {"t": "status"}, timeout=1.0) is not None

    def _monitor_subir_daemon(self, port: str, baud: int | None = None) -> tuple:
        """
        Sobe o daemon da porta como subprocess FILHO da TUI, mudo
        (verbose desligado, stdout/stderr descartados — senao ele escreve
        por cima do Textual). O daemon morre junto com a TUI pelo proprio
        _parent_watch_loop. Guarda o Popen para o SIGTERM na parada.
        baud: velocidade do monitor (P5); None usa o default do daemon.
        Retorna (ok, msg).
        """
        if self._monitor_daemon_vivo(port):
            return (True, "daemon ja ativo")
        cmd = [sys.executable, "-m", "esplab.monitor.run_daemon",
               port, "--quiet"]
        if baud:
            cmd += ["-b", str(baud)]
        env = dict(os.environ)
        src = str(_paths.get_paths().app_root / "src")
        env["PYTHONPATH"] = (src + os.pathsep + env["PYTHONPATH"]
                             if env.get("PYTHONPATH") else src)
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(_paths.get_paths().app_root), env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=False,   # filho: morre com o pai
            )
        except Exception as exc:
            return (False, "falha ao subir o monitor: {}".format(exc))
        self._monitor_procs[port] = proc
        # Espera curta ate o socket aparecer (o daemon cria ao abrir).
        sock = self._monitor_sock_para_porta(port)
        fim = time.time() + 5.0
        while time.time() < fim:
            if sock.exists() and self._monitor_daemon_vivo(port):
                return (True, "daemon no ar")
            if proc.poll() is not None:
                return (False, "o monitor encerrou antes de abrir a porta "
                               "(porta em uso, ou terminal protegido?)")
            time.sleep(0.15)
        return (False, "o monitor nao respondeu a tempo")

    def _encerrar_daemons_monitor(self) -> tuple:
        """
        Encerra TODOS os daemons de monitor, em tres camadas:
          1. shutdown educado pelo socket (teto curto por daemon);
          2. SIGTERM no processo filho, se conhecido e ainda vivo;
          3. rede final: o _parent_watch_loop do daemon o mata quando a
             TUI sair, caso 1 e 2 falhem.
        Nunca bloqueia esperando resposta: o SIGTERM e o plano B imediato.
        Confirma pela ausencia do socket. Retorna (ok, detalhe).
        """
        restantes = []
        # 1. shutdown educado a todos os sockets vivos
        run_dir = self._monitor_run_dir()
        socks = list(run_dir.glob("monitor-*.sock")) if run_dir.exists() else []
        for sock in socks:
            self._monitor_ctrl(sock, {"t": "shutdown"},
                               timeout=self._MONITOR_SHUTDOWN_TIMEOUT)
        # 2. SIGTERM nos filhos que ainda respiram
        for port, proc in list(self._monitor_procs.items()):
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        # pequena espera para o socket sumir
        fim = time.time() + 1.0
        while time.time() < fim:
            vivos = [s for s in socks if s.exists()]
            if not vivos:
                break
            time.sleep(0.1)
        self._monitor_procs.clear()
        vivos = [s for s in socks if s.exists()]
        if vivos:
            # 3. deixa a rede do _parent_watch_loop resolver ao sair.
            restantes = [self._monitor_porta_de_sock(s) for s in vivos]
            return (True, {"encerrados": len(socks) - len(vivos),
                           "restantes": restantes})
        return (True, {"encerrados": len(socks), "restantes": []})

    # ---- prioridade do chip no flash (@E10 P7 / §10.6) ---------------

    def _monitor_release_para_flash(self, port: str) -> tuple:
        """
        Se ha um daemon na porta que sera gravada, pede que ele libere a
        porta (release_port e sincrono: so responde apos fechar). Devolve
        (havia_daemon, ok, msg). Sem daemon: (False, True, "") — nada a
        fazer, segue o flash normal.
        """
        if not self._monitor_daemon_vivo(port):
            return (False, True, "")
        sock = self._monitor_sock_para_porta(port)
        resp = self._monitor_ctrl(
            sock, {"t": "release_port", "reason": "flash"}, timeout=8.0)
        if resp is None:
            return (True, False, "o monitor nao respondeu ao pedido de "
                                 "liberar a porta")
        if resp.get("t") == "error":
            return (True, False, str(resp.get("msg", "erro ao liberar porta")))
        return (True, True, "")

    def _monitor_reacquire_apos_flash(self, port: str) -> None:
        """
        Reabre a porta no daemon apos o flash (best-effort). Silencioso:
        se o daemon sumiu nesse meio-tempo, nao ha o que readquirir.
        """
        if not self._monitor_daemon_vivo(port):
            return
        sock = self._monitor_sock_para_porta(port)
        self._monitor_ctrl(sock, {"t": "acquire_port"}, timeout=8.0)

    # ---- seletor de porta leve (sem sondagem esptool) ----------------

    def _monitor_lista_portas(self) -> list:
        """
        Portas para o menu do monitor: lista ja tratada pela camada de
        inspecao (discovery + classificacao, SEM sondar o chip). Nao
        enumera o sistema por conta propria e nao reseta a placa. As
        ttyS fantasmas ja saem (exibir=False no discovery); gravadores
        saem (sem porta). fake_esp (/dev/pts/N) vem pela entrada manual.
        Devolve dicts: device (porta), classe, descricao.
        """
        from ..hardware.inspection import service as _inspection
        ok, devices = _inspection.list_display_ports()
        if not ok:
            return []
        return [
            {
                "device": d.porta,
                "classe": d.classe,
                "descricao": d.descricao or d.produto or "",
            }
            for d in devices
        ]

    def _action_monitor_start(self) -> None:
        """Busca portas (worker, status animado) e mostra o menu."""
        self.call_from_thread(self._set_status, "Buscando portas")
        try:
            portas = self._monitor_lista_portas()
        finally:
            self.call_from_thread(self._set_status, "")
        self.call_from_thread(self._monitor_mostrar_selecao, portas)

    def _monitor_mostrar_selecao(self, portas: list) -> None:
        """Mostra o menu de selecao de porta (thread principal)."""
        selectable = list(portas)
        linhas = ["[b]Monitorar porta[/b]\n"]
        _CLASSE_LABEL = {
            "serial_esptool": "[green]ESP[/green]",
            "serial_virtual": "[cyan]virtual[/cyan]",
        }
        for i, p in enumerate(selectable, 1):
            marca = _CLASSE_LABEL.get(p.get("classe"), "[dim]serial[/dim]")
            linhas.append("  [b]{}[/b]. {}  {}  [dim]{}[/dim]".format(
                i, p.get("device"), marca, p.get("descricao") or ""))
        n = len(selectable)
        linhas.append("  [b]{}[/b]. [cyan]Digitar outra porta[/cyan] "
                      "[dim](ex.: /dev/pts/10 do fake_esp)[/dim]".format(n + 1))
        default = ""
        if self._porta_ativa:
            for i, p in enumerate(selectable, 1):
                if p.get("device") == self._porta_ativa:
                    default = str(i)
                    break

        def _abrir(port: str) -> None:
            # baud por porta (P5); default se nao configurado
            baud = _port_config.get_monitor_baudrate(port)
            ok, msg = self._monitor_subir_daemon(port, baud=baud)
            if not ok:
                self._cw("[b]Monitor — {}[/b]\n\n[red]{}[/red]".format(
                    port, msg))
                return
            # prefs globais de leitura (P5): carimbo e tamanho do buffer
            prefs = _monitor_prefs.get_monitor_prefs()
            # visualizador na propria TTY via suspend()
            src = str(_paths.get_paths().app_root / "src")
            cmd = [sys.executable, "-P", "-m",
                   "esplab.monitor.esplab_monitor", port,
                   "--backlog", str(prefs["buffer_lines"])]
            if not prefs["timestamp"]:
                cmd.append("--no-timestamp")
            # Abre o visualizador numa JANELA nova; a TUI continua viva.
            from ..monitor import terminal_launcher as _terminal_launcher
            ok_term, info = _terminal_launcher.open_in_terminal(
                cmd, cwd=str(_paths.get_paths().app_root),
                env={"PYTHONPATH": src},
                title="{} @ {}".format(port, baud))
            if ok_term:
                self._cw(
                    "[b]Monitor — {}[/b]\n\n"
                    "[green]Visualizador aberto em nova janela "
                    "({}).[/green]\n\n"
                    "[dim]A aplicacao continua ativa. Feche o visualizador "
                    "com Ctrl+] — o monitor segue no ar (leitura e "
                    "log).[/dim]".format(port, info))
                return
            # Sem ambiente grafico (SSH puro): fallback para suspend() na TTY.
            env = dict(os.environ)
            env["PYTHONPATH"] = (src + os.pathsep + env["PYTHONPATH"]
                                 if env.get("PYTHONPATH") else src)
            try:
                with self.suspend():
                    subprocess.run(cmd, cwd=str(_paths.get_paths().app_root),
                                   env=env)
            except SuspendNotSupported:
                self._cw(
                    "[b]Monitor — {}[/b]\n\n"
                    "[red]Sem ambiente grafico e sem TTY para "
                    "suspender.[/red]\n\n[dim]{}[/dim]".format(port, info))
                return
            self._cw(
                "[b]Monitor — {}[/b]\n\n"
                "[green]Visualizador fechado.[/green] "
                "[dim]O monitor continua no ar (leitura e log).[/dim]\n\n"
                "[dim]Reabra por 'Monitorar porta' ou veja em "
                "'Monitores ativos'.[/dim]".format(port))

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip())
            except ValueError:
                self._cw("[red]Numero invalido.[/red]")
                return
            if idx == n + 1:
                # entrada manual (fake_esp e portas fora do list_ports)
                def _manual(caminho: str | None) -> None:
                    if not caminho or not caminho.strip():
                        self._cw("[dim]Operacao cancelada.[/dim]")
                        return
                    _abrir(caminho.strip())
                _pedir_input(
                    self, "Digitar porta",
                    "Caminho da porta (ex.: /dev/ttyUSB0, /dev/pts/10):",
                    _manual, "/dev/")
                return
            if idx < 1 or idx > n:
                self._cw("[red]Numero invalido.[/red] Escolha entre 1 e "
                         "{}.".format(n + 1))
                return
            _abrir(selectable[idx - 1]["device"])

        _pedir_input(
            self, "Monitorar porta",
            "Porta (1-{}):".format(n + 1),
            _escolher, default, lista=linhas)

    def _action_monitor_active(self) -> None:
        """Lista os monitores ativos; encerra o escolhido."""
        ativos = self._monitor_ativos()
        if not ativos:
            self._cw("[b]Monitores ativos[/b]\n\n"
                     "[dim]Nenhum monitor em execucao.[/dim]\n\n"
                     "[dim]Use 'Monitorar porta' para iniciar um.[/dim]")
            return
        linhas = ["[b]Monitores ativos[/b]\n"]
        for i, a in enumerate(ativos, 1):
            estado = ("[green]conectada[/green]" if a["conectada"]
                      else "[yellow]reconectando[/yellow]")
            linhas.append("  [b]{}[/b]. {}  {}".format(
                i, a["porta"], estado))
        linhas.append("\n[dim]Escolha o monitor a encerrar, "
                      "ou 9 para voltar.[/dim]")

        def _sobre(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(ativos):
                    raise ValueError
            except ValueError:
                self._cw("[red]Numero invalido.[/red]")
                return
            alvo = ativos[idx]
            port = alvo["porta"]
            self._monitor_ctrl(alvo["socket"], {"t": "shutdown"}, timeout=1.0)
            self._monitor_procs.pop(port, None)
            self._cw("[b]Monitores ativos[/b]\n\n"
                     "[green]Monitor da porta {} encerrado.[/green]\n\n"
                     "[dim]A leitura e o log desta porta foram parados.[/dim]"
                     .format(port))

        _pedir_input(
            self, "Monitores ativos",
            "Monitor (1-{}):".format(len(ativos)),
            _sobre, "", lista=linhas)

    def _action_monitor_prefs(self) -> None:
        """Preferencias do monitor: baud por porta, carimbo e buffer."""
        prefs = _monitor_prefs.get_monitor_prefs()
        carimbo = "ligado" if prefs["timestamp"] else "desligado"
        linhas = [
            "[b]Preferencias do monitor[/b]\n",
            "  [b]1[/b]. Baud de uma porta  [dim](velocidade de leitura)[/dim]",
            "  [b]2[/b]. Carimbo de hora  [dim](atual: {})[/dim]".format(carimbo),
            "  [b]3[/b]. Tamanho do buffer  [dim](atual: {} linhas)[/dim]".format(
                prefs["buffer_lines"]),
            "\n[dim]Escolha 1-3, ou 9 para voltar.[/dim]",
        ]

        def _escolha(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            v = valor.strip()
            if v == "1":
                self._prefs_baud_porta()
            elif v == "2":
                self._prefs_carimbo()
            elif v == "3":
                self._prefs_buffer()
            else:
                self._cw("[red]Opcao invalida.[/red]")

        _pedir_input(self, "Preferencias do monitor", "Opcao (1-3):",
                     _escolha, "", lista=linhas)

    def _prefs_baud_porta(self) -> None:
        """Escolhe uma porta e define o baud de leitura dela."""
        portas = self._monitor_lista_portas()
        linhas = ["[b]Baud de leitura — escolha a porta[/b]\n"]
        for i, p in enumerate(portas, 1):
            atual = _port_config.get_monitor_baudrate(p["device"])
            linhas.append("  [b]{}[/b]. {}  [dim]({} baud)[/dim]".format(
                i, p["device"], atual))
        n = len(portas)
        linhas.append("  [b]{}[/b]. [cyan]Digitar outra porta[/cyan]".format(n + 1))

        def _com_porta(port: str) -> None:
            bauds = _port_config.BAUDRATES
            atual = _port_config.get_monitor_baudrate(port)
            blinhas = ["[b]Baud de leitura — {}[/b]\n".format(port)]
            for i, b in enumerate(bauds, 1):
                marca = "  [green]* atual[/green]" if b == atual else ""
                blinhas.append("  [b]{}[/b]. {}{}".format(i, b, marca))

            def _grava(valor: str | None) -> None:
                if valor is None:
                    self._cw("[dim]Operacao cancelada.[/dim]")
                    return
                try:
                    idx = int(valor.strip()) - 1
                    if idx < 0 or idx >= len(bauds):
                        raise ValueError
                except ValueError:
                    self._cw("[red]Numero invalido.[/red]")
                    return
                ok, res = _port_config.set_monitor_baudrate(port, bauds[idx])
                if ok:
                    self._cw("[b]Preferencias do monitor[/b]\n\n"
                             "[green]Baud de {} definido em {}.[/green]".format(
                                 port, bauds[idx]))
                else:
                    self._cw("[red]{}[/red]".format(res))

            _pedir_input(self, "Baud de leitura",
                         "Baud (1-{}):".format(len(bauds)),
                         _grava, "", lista=blinhas)

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip())
            except ValueError:
                self._cw("[red]Numero invalido.[/red]")
                return
            if idx == n + 1:
                def _manual(caminho: str | None) -> None:
                    if not caminho or not caminho.strip():
                        self._cw("[dim]Operacao cancelada.[/dim]")
                        return
                    _com_porta(caminho.strip())
                _pedir_input(self, "Digitar porta",
                             "Caminho da porta (ex.: /dev/ttyUSB0):",
                             _manual, "/dev/")
                return
            if idx < 1 or idx > n:
                self._cw("[red]Numero invalido.[/red]")
                return
            _com_porta(portas[idx - 1]["device"])

        _pedir_input(self, "Baud de leitura", "Porta (1-{}):".format(n + 1),
                     _escolher, "", lista=linhas)

    def _prefs_carimbo(self) -> None:
        """Liga/desliga o carimbo de hora na exibicao."""
        prefs = _monitor_prefs.get_monitor_prefs()
        atual = prefs["timestamp"]

        def _grava(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            v = valor.strip()
            if v not in ("1", "2"):
                self._cw("[red]Opcao invalida.[/red]")
                return
            novo = (v == "1")
            ok, res = _monitor_prefs.set_monitor_pref("timestamp", novo)
            if ok:
                self._cw("[b]Preferencias do monitor[/b]\n\n"
                         "[green]Carimbo de hora {}.[/green]".format(
                             "ligado" if novo else "desligado"))
            else:
                self._cw("[red]{}[/red]".format(res))

        _pedir_input(
            self, "Carimbo de hora",
            "1 = ligado   ·   2 = desligado:",
            _grava, "1" if atual else "2",
            lista=["[dim]Estado atual: {}[/dim]".format(
                       "ligado" if atual else "desligado"),
                   "[b]1[/b] ligar    [b]2[/b] desligar"])

    def _prefs_buffer(self) -> None:
        """Define o tamanho do buffer de exibicao (linhas)."""
        prefs = _monitor_prefs.get_monitor_prefs()

        def _grava(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                n = int(valor.strip())
            except ValueError:
                self._cw("[red]Digite um numero inteiro.[/red]")
                return
            ok, res = _monitor_prefs.set_monitor_pref("buffer_lines", n)
            if ok:
                self._cw("[b]Preferencias do monitor[/b]\n\n"
                         "[green]Buffer definido em {} linhas.[/green]".format(n))
            else:
                self._cw("[red]{}[/red]".format(res))

        _pedir_input(
            self, "Tamanho do buffer",
            "Linhas ({}-{}):".format(
                _monitor_prefs.BUFFER_MIN, _monitor_prefs.BUFFER_MAX),
            _grava, str(prefs["buffer_lines"]))

    def _action_monitor_log(self) -> None:
        """Escolhe um log gravado e exibe no visualizador (--file | less)."""
        logs_dir = self._monitor_logs_dir()
        arquivos = []
        if logs_dir.exists():
            # log atual e rotacoes (.1/.2/.3), mais recentes primeiro
            for p in sorted(logs_dir.glob("*.monitor.log*")):
                try:
                    st = p.stat()
                except OSError:
                    continue
                arquivos.append({"path": p, "size": st.st_size,
                                 "mtime": st.st_mtime})
        arquivos.sort(key=lambda a: a["mtime"], reverse=True)
        if not arquivos:
            self._cw("[b]Abrir log gravado[/b]\n\n"
                     "[dim]Nenhum log de monitor encontrado em[/dim]\n"
                     "  [dim]{}[/dim]".format(logs_dir))
            return
        linhas = ["[b]Abrir log gravado[/b]\n"]
        for i, a in enumerate(arquivos, 1):
            kb = a["size"] / 1024.0
            quando = time.strftime("%d/%m %H:%M", time.localtime(a["mtime"]))
            linhas.append("  [b]{}[/b]. {}  [dim]{:.0f} KB · {}[/dim]".format(
                i, a["path"].name, kb, quando))

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(arquivos):
                    raise ValueError
            except ValueError:
                self._cw("[red]Numero invalido.[/red]")
                return
            log_path = arquivos[idx]["path"]
            src = str(_paths.get_paths().app_root / "src")
            # Abre o log numa JANELA nova (igual "Monitorar porta"): o
            # viewer --file (que sai sozinho no EOF) alimenta o less -R por
            # pipe. TUI viva; less navega (rola, / busca, q sai). O
            # PYTHONPATH vai explicito no bash (o server do terminal nao
            # herda o env deste processo).
            viewer_cmd = ("{} -P -m esplab.monitor.esplab_monitor "
                          "--file {}").format(
                              shlex.quote(sys.executable),
                              shlex.quote(str(log_path)))
            pipe = ["bash", "-c", "{} | less -R".format(viewer_cmd)]
            from ..monitor import terminal_launcher as _terminal_launcher
            ok_term, info = _terminal_launcher.open_in_terminal(
                pipe, cwd=str(_paths.get_paths().app_root),
                env={"PYTHONPATH": src}, hold_on_error=False,
                title="log: {}".format(log_path.name))
            if ok_term:
                self._cw(
                    "[b]Abrir log gravado[/b]\n\n"
                    "[green]Log aberto em nova janela ({}).[/green]\n\n"
                    "[dim]{}[/dim]\n\n"
                    "[dim]Na janela: rolar com as setas, buscar com /, "
                    "sair com q. A aplicacao continua ativa.[/dim]".format(
                        info, log_path.name))
                return
            # Sem ambiente grafico (SSH puro): fallback para o less na
            # propria TTY, via suspend.
            env = dict(os.environ)
            env["PYTHONPATH"] = (src + os.pathsep + env["PYTHONPATH"]
                                 if env.get("PYTHONPATH") else src)
            viewer = [sys.executable, "-P", "-m",
                      "esplab.monitor.esplab_monitor", "--file", str(log_path)]
            try:
                with self.suspend():
                    p1 = subprocess.Popen(
                        viewer, cwd=str(_paths.get_paths().app_root), env=env,
                        stdout=subprocess.PIPE)
                    try:
                        subprocess.run(["less", "-R"], stdin=p1.stdout)
                    except FileNotFoundError:
                        if p1.stdout is not None:
                            sys.stdout.write(
                                p1.stdout.read().decode("utf-8", "replace"))
                    finally:
                        if p1.stdout is not None:
                            p1.stdout.close()
                        p1.wait()
            except SuspendNotSupported:
                self._cw(
                    "[b]Abrir log gravado[/b]\n\n"
                    "[red]Sem ambiente grafico e sem TTY para "
                    "suspender.[/red]\n\n[dim]{}[/dim]".format(info))
                return
            self._cw("[b]Abrir log gravado[/b]\n\n"
                     "[green]Leitura encerrada.[/green]  [dim]{}[/dim]".format(
                         log_path.name))

        _pedir_input(
            self, "Abrir log gravado",
            "Log (1-{}):".format(len(arquivos)),
            _escolher, "1", lista=linhas)

    # ==================================================================
    # ===  [VER] VERSIONAMENTO
    # ===  menu: Versionamento
    # ===  usa: _git
    # ==================================================================

    def _action_versioning_status(self) -> str:
        """Versionamento > Estado (do projeto ativo)."""
        if not self._projeto_ativo:
            return self._msg_sem_projeto()
        ok, res = _git.status(self._projeto_ativo)
        if not ok:
            if "sem versionamento" in str(res):
                return (
                    "[yellow]Este projeto ainda nao tem versionamento.[/yellow]\n\n"
                    "[dim]Use 'Preparar versionamento' para iniciar.[/dim]"
                )
            return f"[red]Erro ao verificar status:[/red] {res}"
        return self._formatar_status_git(str(res))

    @staticmethod
    def _formatar_status_git(porcelain: str) -> str:
        """Traduz o porcelain do git (M, ??, A, D...) para rotulos PT-BR."""
        from rich.markup import escape
        rotulos = {
            "??": ("Novo", "cyan"),
            " M": ("Modificado", "yellow"), "M ": ("Modificado", "yellow"),
            "MM": ("Modificado", "yellow"),
            "A ": ("Adicionado", "green"), " A": ("Adicionado", "green"),
            " D": ("Removido", "red"), "D ": ("Removido", "red"),
            "R ": ("Renomeado", "magenta"), "C ": ("Copiado", "magenta"),
            "!!": ("Ignorado", "bright_black"),
        }
        ramo = ""
        itens: list[str] = []
        for linha in porcelain.splitlines():
            if not linha.strip():
                continue
            if linha.startswith("##"):
                ramo = linha[2:].strip().split("...")[0].strip()
                continue
            codigo = linha[:2]
            arquivo = escape(linha[3:].strip())
            rotulo, cor = rotulos.get(codigo, ("Alterado", "yellow"))
            itens.append(f"  [{cor}]{rotulo}[/{cor}]: {arquivo}")
        cabecalho = "[b]Estado do repositorio[/b]"
        if ramo:
            cabecalho += f"  [dim](ramo {escape(ramo)})[/dim]"
        if not itens:
            return cabecalho + "\n\n  [green]Nada a versionar — tudo em dia.[/green]"
        return cabecalho + "\n\n" + "\n".join(itens)

    def _action_versioning_prepare(self) -> None:
        """Versionamento > Preparar (do projeto ativo). Se ja existe .git,
        pergunta antes de excluir e recriar."""
        if not self._projeto_ativo:
            self._cw(self._msg_sem_projeto())
            return
        projeto = self._projeto_ativo

        def _disparar() -> None:
            self._cw("[dim]Aguarde...[/dim]")
            self._start_operation("preparar versionamento", cancelable=False)
            self._set_status("Preparar versionamento")
            self._run_action_worker("_action_versioning_prepare_do")

        if _git.is_repo(projeto):
            def _on_confirmar(confirmado: bool) -> None:
                if not confirmado:
                    self._cw(
                        "[dim]Preparacao cancelada. O versionamento atual "
                        "foi mantido.[/dim]"
                    )
                    return
                import shutil
                git_dir = _Path(projeto) / ".git"
                try:
                    if git_dir.exists():
                        shutil.rmtree(git_dir)
                except Exception as exc:
                    self._cw(f"[red]✘ Nao removi o .git:[/red] {exc}")
                    return
                _disparar()

            _confirmar(
                self,
                titulo="Recriar versionamento",
                mensagem=(
                    "Ja existe um repositorio (.git) neste projeto. "
                    "Excluir o .git atual e recriar do zero, com os "
                    "arquivos atuais? O historico de commits sera perdido."
                ),
                on_confirm=_on_confirmar,
            )
            return

        _disparar()

    def _action_versioning_prepare_do(self) -> str:
        """Trabalho de preparar (git init + add), em worker."""
        ok, res = _git.prepare(self._projeto_ativo)
        if ok:
            return f"[green]✔ {res}[/green]"
        if "ja possui versionamento" in str(res):
            return f"[yellow]{res}[/yellow]"
        return f"[red]✘ Falha ao preparar:[/red] {res}"

    def _action_versioning_commit(self) -> None:
        """Versionamento > Commit (do projeto ativo): pede mensagem e commita."""
        if not self._projeto_ativo:
            self._cw(self._msg_sem_projeto())
            return
        projeto = self._projeto_ativo
        if not _git.is_repo(projeto):
            self._cw(
                "[yellow]Este projeto ainda nao tem versionamento.[/yellow]\n\n"
                "[dim]Use 'Preparar versionamento' antes de commitar.[/dim]"
            )
            return

        def _fazer_commit(mensagem: str | None) -> None:
            if mensagem is None:
                self._cw("[dim]Commit cancelado.[/dim]")
                return
            ok, res = _git.commit(projeto, mensagem)
            if ok:
                self._cw(f"[green]✔ {res}[/green]")
            elif "nada a commitar" in str(res):
                self._cw(f"[yellow]{res}[/yellow]")
            else:
                self._cw(f"[red]✘ Falha ao commitar:[/red] {res}")

        _pedir_input(
            self,
            "Commit",
            "Mensagem do commit:",
            _fazer_commit,
            placeholder="Descreva a alteracao",
        )
    # ==================================================================
    # ===  [PERFIL] HARDWARE - editar perfil
    # ===  menu: Hardware > Editar perfil
    # ===  usa: _boards, _partitions
    # ==================================================================


    def _action_editar_perfil(self) -> None:
        """Abre o perfil vivo; sem placa viva, usa o perfil do projeto."""
        ok_context, context = self._current_hardware_context()
        if not ok_context:
            self._cw(f"[red]Falha ao resolver contexto:[/red] {context}")
            return
        mac = context.get("current_mac") or context.get("expected_mac") or ""
        if not mac:
            self._cw(
                "[yellow]Nenhum perfil disponível para edição.[/yellow]\n\n"
                "[dim]Cadastre uma placa ou associe um perfil ao projeto.[/dim]"
            )
            return
        ok_profile, profile = _boards.get_profile(mac)
        if not ok_profile:
            self._cw(f"[red]Perfil não encontrado:[/red] {profile}")
            return
        if profile.get("layout_review_required"):
            self._layout_review_menu(mac)
        else:
            self._editar_perfil_campo_menu(mac)


    def _editar_perfil_campo_menu(self, mac: str) -> None:
        """Menu de edição do perfil físico por MAC."""
        ok, profile = _boards.get_profile(mac)
        if not ok:
            self._cw(f"[red]Erro ao ler perfil:[/red] {profile}")
            return

        name = profile.get("board_name") or profile.get("chip_family") or "?"
        lines = []
        for index, field in enumerate(_EDITAR_PERFIL_CAMPOS, start=1):
            value = profile.get(field["key"], "Desconhecido")
            if field["tipo"] == "pinos":
                value = (
                    f"{len(value or [])} posições mapeadas "
                    f"de {profile.get('total_pins', 0)}"
                )
            elif field["tipo"] == "portas_usb":
                value = (
                    f"{profile.get('usb_port_count', len(value or []))} "
                    "porta(s) cadastrada(s)"
                )
            lines.append(
                f"  [b]{index}[/b]. {field['label']}: [dim]{value}[/dim]"
            )

        source_label = (
            "porta viva"
            if mac == self._mac_porta_ativa else
            "perfil associado/selecionado"
        )
        header = (
            f"[b]Editar perfil[/b] — {name} [dim]({mac})[/dim]\n"
            f"[b]Origem da seleção:[/b] {source_label}\n"
            f"[b]Família:[/b] {profile.get('chip_family') or 'Desconhecido'}\n"
            f"[b]Revisão do layout:[/b] "
            f"{self._layout_review_status_text(profile)}\n"
        )
        if profile.get("layout_review_required"):
            header += (
                "[yellow]Alterações de pinos ou USB permanecem pendentes "
                "até confirmação explícita.[/yellow]\n"
            )

        def _choose(value: str | None) -> None:
            if value is None:
                if profile.get("layout_review_required"):
                    self._layout_review_menu(mac)
                else:
                    self._cw("[dim]Edição cancelada.[/dim]")
                return
            try:
                index = int(value.strip()) - 1
                if index < 0 or index >= len(_EDITAR_PERFIL_CAMPOS):
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Número inválido.[/red] "
                    f"Escolha entre 1 e {len(_EDITAR_PERFIL_CAMPOS)}"
                )
                return
            self._editar_perfil_ir_para_campo(mac, index)

        _pedir_input(
            self,
            "Editar perfil",
            f"Campo (1-{len(_EDITAR_PERFIL_CAMPOS)}):",
            _choose,
            "1",
            lista=[header] + lines,
        )

    def _editar_perfil_pino_editar(self, mac: str, idx: int) -> None:
        """Edita um pino com ESC voltando exatamente um nível."""
        ok, perfil = _boards.get_profile(mac)
        if not ok:
            self._cw(f"[red]Erro ao ler perfil:[/red] {perfil}")
            return
        pinos = list(perfil.get("pinout_mapping") or [])
        if idx >= len(pinos):
            self._cw("[red]Pino não existe mais neste perfil.[/red]")
            return
        pino_atual = dict(pinos[idx])
        legenda_txt = ", ".join(
            f"{key}={value}" for key, value in _LEGENDA_CATEGORIAS.items()
        )
        categorias = pino_atual.get("functions") or []
        categorias_texto = (
            ",".join(categorias)
            if isinstance(categorias, list)
            else str(categorias or "")
        )

        def _pedir_nome(valor_inicial: str) -> None:
            def _novo_label(valor: str | None) -> None:
                if valor is None:
                    self._editar_perfil_pinos_menu(mac)
                    return
                label = valor.strip() or str(pino_atual.get("label") or "")
                _pedir_categorias(label, categorias_texto)

            _pedir_input(
                self,
                "Editar perfil > Pino > Nome",
                (
                    "Novo nome/label "
                    f"(atual: '{pino_atual.get('label', '?')}'):"
                ),
                _novo_label,
                valor_inicial,
            )

        def _pedir_categorias(label: str, valor_inicial: str) -> None:
            def _novas_categorias(valor: str | None) -> None:
                if valor is None:
                    _pedir_nome(label)
                    return
                letras = [
                    item.strip().upper()
                    for item in valor.split(",")
                    if item.strip()
                ]
                invalidas = [
                    item for item in letras
                    if item not in _LEGENDA_CATEGORIAS
                ]
                if invalidas:
                    self._cw(
                        f"[red]Categoria(s) inválida(s):[/red] "
                        f"{', '.join(invalidas)}\n[dim]{legenda_txt}[/dim]"
                    )
                    _pedir_categorias(label, valor)
                    return
                pinos[idx] = {
                    **pino_atual,
                    "label": label,
                    "functions": letras,
                }
                ok_save, result = _boards.key_json_manager(
                    "edit",
                    mac,
                    {"pinout_mapping": pinos},
                )
                if not ok_save:
                    self._cw(f"[red]Falha ao salvar:[/red] {result}")
                    _pedir_categorias(label, valor)
                    return
                self._sync_profile_runtime_and_project(mac)
                self._cw(
                    f"[green]✔ Pino atualizado:[/green] {label} "
                    f"[{','.join(letras)}]"
                )
                self._editar_perfil_pinos_menu(mac)

            _pedir_input(
                self,
                "Editar perfil > Pino > Categorias",
                f"Categorias separadas por vírgula ({legenda_txt}):",
                _novas_categorias,
                valor_inicial,
            )

        _pedir_nome(str(pino_atual.get("label") or ""))

    def _editar_perfil_texto(self, mac: str, campo: dict, perfil: dict) -> None:
        """Campo de texto livre (ex.: nome da placa)."""
        atual = perfil.get(campo["key"], "") or ""
        def _salvar(valor: str | None) -> None:
            if valor is None:
                self._editar_perfil_campo_menu(mac)
                return
            valor = valor.strip()
            if not valor:
                self._cw("[red]Valor vazio; nada foi salvo.[/red]")
                return
            ok, res = _boards.key_json_manager("edit", mac, {campo["key"]: valor})
            if not ok:
                self._cw(f"[red]Falha ao salvar:[/red] {res}")
                return
            self._editar_perfil_pos_acao(
                f"[green]✔ {campo['label']} atualizado:[/green] {valor}\n"
                "[dim]Perfil confirmado — releitura de hardware não "
                "sobrescreve mais os campos fixos.[/dim]")

        _pedir_input(self, f"Editar perfil > {campo['label']}",
                    f"Novo valor para '{campo['label']}' (atual: '{atual}'):",
                    _salvar, str(atual))


    def _editar_perfil_numero(
        self,
        mac: str,
        campo: dict,
        perfil: dict,
    ) -> None:
        """Redimensiona o mapa; reduções exigem confirmação explícita."""
        current = perfil.get(campo["key"], "")

        def _open_again() -> None:
            ok_current, current_profile = _boards.get_profile(mac)
            if ok_current:
                self._editar_perfil_numero(mac, campo, current_profile)
            else:
                self._cw(f"[red]Erro ao reler perfil:[/red] {current_profile}")

        def _save(value: str | None) -> None:
            if value is None:
                self._editar_perfil_campo_menu(mac)
                return
            try:
                number = int(value.strip())
                if number < 0 or (number and number % 2):
                    raise ValueError
            except ValueError:
                self._cw(
                    "[red]Use zero ou um número inteiro positivo e par.[/red]"
                )
                _open_again()
                return

            ok_resize, resized = _family_profiles.resize_pinout_mapping(
                perfil.get("pinout_mapping") or [],
                number,
            )
            if not ok_resize:
                self._cw(f"[red]Falha ao redimensionar:[/red] {resized}")
                _open_again()
                return

            changes = {
                "total_pins": number,
                "pinout_mapping": resized["pinout_mapping"],
            }
            if number == 0:
                changes.update({"usb_port_count": 0, "usb_ports": []})

            def _commit() -> None:
                ok_save, result = _boards.key_json_manager(
                    "edit",
                    mac,
                    changes,
                )
                if not ok_save:
                    self._cw(f"[red]Falha ao salvar:[/red] {result}")
                    _open_again()
                    return
                legacy = (
                    " Numeração legada convertida."
                    if resized.get("legacy_converted") else ""
                )
                self._editar_perfil_pos_acao(
                    f"[green]✔ Total de pinos atualizado:[/green] {number}\n"
                    f"Preservados: {resized['preserved']} · "
                    f"Adicionados: {resized['added']} · "
                    f"Removidos: {resized['removed']}.{legacy}"
                )

            destructive = bool(
                resized.get("removed")
                or (
                    number == 0
                    and (
                        perfil.get("usb_ports")
                        or perfil.get("usb_port_count")
                    )
                )
            )
            if not destructive:
                _commit()
                return

            def _confirm_resize(confirmed: bool) -> None:
                if confirmed:
                    _commit()
                else:
                    _open_again()

            usb_warning = (
                "\nAs portas USB cadastradas também serão removidas."
                if number == 0 and (
                    perfil.get("usb_ports")
                    or perfil.get("usb_port_count")
                ) else ""
            )
            _confirmar(
                self,
                titulo="Confirmar redução do mapa físico",
                mensagem=(
                    f"Perfil: {perfil.get('board_name') or 'Não identificada'}\n"
                    f"Total atual: {current}\n"
                    f"Novo total: {number}\n"
                    f"Posições removidas: {resized.get('removed', 0)}\n\n"
                    "Os labels, GPIOs e categorias das posições removidas "
                    "serão perdidos e não podem ser recuperados pelo esptool."
                    f"{usb_warning}\n\n"
                    "Nenhum dado será gravado no chip físico."
                ),
                on_confirm=_confirm_resize,
            )

        _pedir_input(
            self,
            f"Editar perfil > {campo['label']}",
            (
                f"Novo total (atual: {current}). "
                "Use número par; zero remove o layout:"
            ),
            _save,
            str(current) if current not in (None, "", "Desconhecido") else "",
        )

    def _editar_perfil_lista(self, mac: str, campo: dict, perfil: dict) -> None:
        """Campo Selecionavel: opcoes fixas, nunca digitacao livre."""
        opcoes = campo["opcoes"]
        atual = perfil.get(campo["key"])
        linhas = []
        for i, op in enumerate(opcoes, start=1):
            marca = " [green]►[/green]" if op == atual else ""
            linhas.append(f"  [b]{i}[/b]. {op}{marca}")

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._editar_perfil_campo_menu(mac)
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(opcoes):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(opcoes)}")
                return
            escolhido = opcoes[idx]
            ok, res = _boards.key_json_manager("edit", mac, {campo["key"]: escolhido})
            if not ok:
                self._cw(f"[red]Falha ao salvar:[/red] {res}")
                return
            self._editar_perfil_pos_acao(
                f"[green]✔ {campo['label']} atualizado:[/green] {escolhido}")

        _pedir_input(self, f"Editar perfil > {campo['label']}",
                    f"Número da opção (atual: {atual}):",
                    _escolher, "1", lista=linhas)

    def _editar_perfil_particao(self, mac: str, perfil: dict) -> None:
        """Tabela de particao: reusa o MESMO catalogo (partition_tables.py)
        que Configuracoes > Particao usa, so muda o destino da gravacao
        (perfil da placa, nao sdkconfig.defaults do projeto). Depende do
        flash_size_mb ja estar definido neste perfil."""
        flash = perfil.get("flash_size_mb", "")
        if not flash or flash == "Desconhecido":
            self._cw("[b]Tabela de partição[/b]\n\n"
                     "[yellow]Defina 'Tamanho da flash' neste perfil "
                     "primeiro.[/yellow]")
            return
        ok, variacoes = _partitions.list_variations(flash)
        if not ok or not variacoes:
            self._cw(f"[b]Tabela de partição[/b]\n\n"
                     f"[yellow]Catálogo sem esquema para {flash}.[/yellow]")
            return
        atual = perfil.get("partition_table", "")
        linhas = []
        for i, v in enumerate(variacoes, start=1):
            nome = v.get("nome", "?")
            marca = " [green]►[/green]" if nome == atual else ""
            linhas.append(f"  [b]{i}[/b]. {nome}{marca}")

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._editar_perfil_campo_menu(mac)
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(variacoes):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(variacoes)}")
                return
            nome = variacoes[idx].get("nome", "?")
            ok2, res2 = _boards.key_json_manager(
                "edit", mac, {"partition_table": nome})
            if not ok2:
                self._cw(f"[red]Falha ao salvar:[/red] {res2}")
                return
            self._editar_perfil_pos_acao(
                f"[green]✔ Tabela de partição atualizada:[/green] {nome}")

        _pedir_input(self, "Editar perfil > Tabela de partição",
                    f"Número do esquema ({flash}):", _escolher, "1",
                    lista=linhas)

    def _editar_perfil_pinos_menu(self, mac: str) -> None:
        """Lista pinos numerados. Recarrega a cada chamada - permite
        editar varios pinos em sequencia, voltando aqui apos cada um."""
        ok, perfil = _boards.get_profile(mac)
        if not ok:
            self._cw(f"[red]Erro ao ler perfil:[/red] {perfil}")
            return
        pinos = perfil.get("pinout_mapping") or []
        if not pinos:
            self._cw("[b]Mapeamento de pinos[/b]\n\n"
                     "[yellow]Este perfil não tem pinos cadastrados.[/yellow]")
            return

        ordered = sorted(
            enumerate(pinos),
            key=lambda item: (
                item[1].get("physical")
                if isinstance(item[1].get("physical"), int)
                else 10**9
            ),
        )
        linhas = []
        for option, (_original_index, pin) in enumerate(ordered, start=1):
            gpio = pin.get("gpio")
            gpio_txt = f"GPIO{gpio}" if gpio is not None else "-"
            functions = pin.get("functions") or []
            functions_txt = (
                ",".join(str(item) for item in functions)
                if isinstance(functions, list) else str(functions or "-")
            )
            linhas.append(
                f"  [b]{option}[/b]. Pino {pin.get('physical','?')!s:<3} "
                f"{gpio_txt:<7} '{pin.get('label','?')}' "
                f"[dim][{functions_txt or '-'}][/dim]"
            )

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._editar_perfil_campo_menu(mac)
                return
            try:
                option = int(valor.strip()) - 1
                if option < 0 or option >= len(ordered):
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Número inválido.[/red] "
                    f"Escolha entre 1 e {len(ordered)}"
                )
                return
            original_index = ordered[option][0]
            self._editar_perfil_pino_editar(mac, original_index)

        _pedir_input(self, "Editar perfil > Mapeamento de pinos",
                    f"Qual pino editar (1-{len(pinos)}):",
                    _escolher, "", lista=linhas)


    def _save_profile_usb_ports(
        self,
        mac: str,
        ports: list,
    ):
        if not isinstance(ports, list):
            return (False, "lista de portas USB inválida")
        if len(ports) > 2:
            return (False, "o perfil suporta no máximo duas portas USB")
        return _boards.key_json_manager(
            "edit",
            mac,
            {
                "usb_ports": ports,
                "usb_port_count": len(ports),
            },
        )


    def _editar_perfil_portas_usb_menu(self, mac: str) -> None:
        """Lista 0, 1 ou 2 portas USB e mantém a contagem sincronizada."""
        ok, profile = _boards.get_profile(mac)
        if not ok:
            self._cw(f"[red]Erro ao ler perfil:[/red] {profile}")
            return
        ports = list(profile.get("usb_ports") or [])
        if len(ports) > 2:
            self._cw(
                "[red]Perfil inválido: há mais de duas portas USB.[/red]\n\n"
                "[dim]Corrija o JSON por uma migração explícita antes de editar.[/dim]"
            )
            return

        lines = []
        for index, port in enumerate(ports, start=1):
            gpios = ",".join(str(item) for item in port.get("gpios", []))
            lines.append(
                f"  [b]{index}[/b]. {port.get('nome','?')} "
                f"[dim](GPIO {gpios or 'não informado'})[/dim]"
            )

        add_index = len(ports) + 1
        if len(ports) < 2:
            lines.append(
                f"  [b]{add_index}[/b]. [green]+ Adicionar porta USB[/green]"
            )

        maximum = len(ports) + (1 if len(ports) < 2 else 0)
        if maximum == 0:
            self._cw("[yellow]Nenhuma opção disponível.[/yellow]")
            return

        def _choose(value: str | None) -> None:
            if value is None:
                self._editar_perfil_campo_menu(mac)
                return
            try:
                index = int(value.strip()) - 1
                if index < 0 or index >= maximum:
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Número inválido.[/red] Escolha entre 1 e {maximum}"
                )
                return
            if index == len(ports):
                self._editar_perfil_porta_usb_nova(mac, ports)
            else:
                self._editar_perfil_porta_usb_editar(mac, ports, index)

        _pedir_input(
            self,
            "Editar perfil > Portas USB",
            f"Porta/opção (1-{maximum}):",
            _choose,
            "",
            lista=lines,
        )


    def _editar_perfil_porta_usb_nova(self, mac: str, portas: list) -> None:
        """Adiciona USB com ESC retornando um nível e sem gravação parcial."""
        if len(portas) >= 2:
            self._cw("[yellow]O limite de duas portas USB já foi atingido.[/yellow]")
            self._editar_perfil_portas_usb_menu(mac)
            return

        def _pedir_nome(valor_inicial: str = "") -> None:
            def _name(value: str | None) -> None:
                if value is None:
                    self._editar_perfil_portas_usb_menu(mac)
                    return
                name = value.strip()
                if not name:
                    self._cw("[red]Nome vazio; nada foi gravado.[/red]")
                    _pedir_nome(value)
                    return
                _pedir_gpios(name, "")

            _pedir_input(
                self,
                "Editar perfil > Nova porta USB",
                "Nome da porta:",
                _name,
                valor_inicial,
            )

        def _pedir_gpios(name: str, valor_inicial: str) -> None:
            def _gpios(value: str | None) -> None:
                if value is None:
                    _pedir_nome(name)
                    return
                try:
                    gpios = [
                        int(item.strip())
                        for item in value.split(",")
                        if item.strip()
                    ]
                    if not gpios or any(item < 0 for item in gpios):
                        raise ValueError
                except ValueError:
                    self._cw(
                        "[red]GPIOs inválidos. Use números separados por vírgula.[/red]"
                    )
                    _pedir_gpios(name, value)
                    return

                new_ports = portas + [{"nome": name, "gpios": gpios}]
                ok_save, result = self._save_profile_usb_ports(mac, new_ports)
                if not ok_save:
                    self._cw(f"[red]Falha ao salvar:[/red] {result}")
                    _pedir_gpios(name, value)
                    return
                self._sync_profile_runtime_and_project(mac)
                self._cw(
                    f"[green]✔ Porta USB adicionada:[/green] {name} "
                    f"(GPIO {', '.join(str(item) for item in gpios)})"
                )
                self._editar_perfil_portas_usb_menu(mac)

            _pedir_input(
                self,
                "Editar perfil > Nova porta USB",
                "GPIOs separados por vírgula:",
                _gpios,
                valor_inicial,
            )

        _pedir_nome()


    def _editar_perfil_porta_usb_editar(
        self,
        mac: str,
        portas: list,
        idx: int,
    ) -> None:
        """Edita USB com retorno hierárquico e confirmação para remoção."""
        port = dict(portas[idx])
        gpios_text = ",".join(str(item) for item in port.get("gpios", []))
        header = (
            f"[b]Porta USB[/b]: {port.get('nome', '?')} "
            f"[dim](GPIO {gpios_text or 'não informado'})[/dim]\n"
        )
        lines = [
            "  [b]1[/b]. Renomear",
            "  [b]2[/b]. Editar GPIOs",
            "  [b]3[/b]. [red]Remover esta porta[/red]",
        ]

        def _open_actions() -> None:
            self._editar_perfil_porta_usb_editar(mac, portas, idx)

        def _choose(value: str | None) -> None:
            if value is None:
                self._editar_perfil_portas_usb_menu(mac)
                return
            option = value.strip()

            if option == "1":
                def _rename(new_value: str | None) -> None:
                    if new_value is None:
                        _open_actions()
                        return
                    name = new_value.strip()
                    if not name:
                        self._cw("[red]Nome vazio; nada foi gravado.[/red]")
                        _pedir_input(
                            self,
                            "Editar perfil > Porta USB > Renomear",
                            "Novo nome:",
                            _rename,
                            new_value,
                        )
                        return
                    updated = list(portas)
                    updated[idx] = {**port, "nome": name}
                    ok_save, result = self._save_profile_usb_ports(mac, updated)
                    if not ok_save:
                        self._cw(f"[red]Falha ao salvar:[/red] {result}")
                        _open_actions()
                        return
                    self._sync_profile_runtime_and_project(mac)
                    self._cw(f"[green]✔ Porta renomeada:[/green] {name}")
                    self._editar_perfil_portas_usb_menu(mac)

                _pedir_input(
                    self,
                    "Editar perfil > Porta USB > Renomear",
                    "Novo nome:",
                    _rename,
                    str(port.get("nome") or ""),
                )
                return

            if option == "2":
                def _edit_gpios(new_value: str | None) -> None:
                    if new_value is None:
                        _open_actions()
                        return
                    try:
                        gpios = [
                            int(item.strip())
                            for item in new_value.split(",")
                            if item.strip()
                        ]
                        if not gpios or any(item < 0 for item in gpios):
                            raise ValueError
                    except ValueError:
                        self._cw("[red]Lista de GPIOs inválida.[/red]")
                        _pedir_input(
                            self,
                            "Editar perfil > Porta USB > GPIOs",
                            "GPIOs separados por vírgula:",
                            _edit_gpios,
                            new_value,
                        )
                        return
                    updated = list(portas)
                    updated[idx] = {**port, "gpios": gpios}
                    ok_save, result = self._save_profile_usb_ports(mac, updated)
                    if not ok_save:
                        self._cw(f"[red]Falha ao salvar:[/red] {result}")
                        _open_actions()
                        return
                    self._sync_profile_runtime_and_project(mac)
                    self._cw("[green]✔ GPIOs atualizados.[/green]")
                    self._editar_perfil_portas_usb_menu(mac)

                _pedir_input(
                    self,
                    "Editar perfil > Porta USB > GPIOs",
                    "GPIOs separados por vírgula:",
                    _edit_gpios,
                    gpios_text,
                )
                return

            if option == "3":
                def _remove(confirmed: bool) -> None:
                    if not confirmed:
                        _open_actions()
                        return
                    updated = portas[:idx] + portas[idx + 1:]
                    ok_save, result = self._save_profile_usb_ports(mac, updated)
                    if not ok_save:
                        self._cw(f"[red]Falha ao remover:[/red] {result}")
                        _open_actions()
                        return
                    self._sync_profile_runtime_and_project(mac)
                    self._cw(
                        f"[green]✔ Porta removida:[/green] "
                        f"{port.get('nome', '?')}"
                    )
                    self._editar_perfil_portas_usb_menu(mac)

                _confirmar(
                    self,
                    titulo="Remover porta USB do perfil",
                    mensagem=(
                        f"Perfil MAC: {mac}\n"
                        f"Porta: {port.get('nome', '?')}\n"
                        f"GPIOs: {gpios_text or 'não informados'}\n\n"
                        "Consequência: este conector e seu mapeamento de GPIOs "
                        "serão removidos somente do perfil. "
                        "Nada será gravado ou apagado na placa física."
                    ),
                    on_confirm=_remove,
                )
                return

            self._cw("[red]Opção inválida.[/red]")
            _open_actions()

        _pedir_input(
            self,
            "Editar perfil > Porta USB",
            "Escolha (1-3):",
            _choose,
            "",
            lista=[header] + lines,
        )

    def _editar_perfil_ir_para_campo(self, mac: str, idx_campo: int) -> None:
        """Abre o editor do campo pelo indice, sem perguntar de novo.
        Usado tanto pela primeira escolha quanto pela navegacao
        Avancar/Voltar. Guarda o estado (mac, idx_campo) para que o
        editor consiga voltar aqui ao terminar."""
        idx_campo = max(0, min(idx_campo, len(_EDITAR_PERFIL_CAMPOS) - 1))
        self._editar_perfil_estado = {"mac": mac, "idx_campo": idx_campo}
        ok, perfil = _boards.get_profile(mac)
        if not ok:
            self._cw(f"[red]Erro ao ler perfil:[/red] {perfil}")
            return
        campo = _EDITAR_PERFIL_CAMPOS[idx_campo]
        tipo = campo["tipo"]
        if tipo == "texto":
            self._editar_perfil_texto(mac, campo, perfil)
        elif tipo == "numero":
            self._editar_perfil_numero(mac, campo, perfil)
        elif tipo == "lista":
            self._editar_perfil_lista(mac, campo, perfil)
        elif tipo == "particao":
            self._editar_perfil_particao(mac, perfil)
        elif tipo == "pinos":
            self._editar_perfil_pinos_menu(mac)
        elif tipo == "portas_usb":
            self._editar_perfil_portas_usb_menu(mac)

    def _editar_perfil_pos_acao(self, mensagem: str) -> None:
        """Navega entre campos e retorna à revisão quando necessário."""
        estado = self._editar_perfil_estado
        mac = estado.get("mac")
        idx_campo = estado.get("idx_campo", 0)
        if not mac:
            self._cw(mensagem)
            return

        self._sync_profile_runtime_and_project(mac)
        linhas = [
            "  [b]1[/b]. Avançar (próximo campo)",
            "  [b]2[/b]. Voltar (campo anterior)",
            "  [b]3[/b]. Fechar edição",
        ]

        def _escolher(valor: str | None) -> None:
            opc = (valor or "3").strip()
            if opc == "1":
                self._editar_perfil_ir_para_campo(mac, idx_campo + 1)
            elif opc == "2":
                self._editar_perfil_ir_para_campo(mac, idx_campo - 1)
            else:
                ok_profile, profile = _boards.get_profile(mac)
                if ok_profile and profile.get("layout_review_required"):
                    self._layout_review_menu(mac)
                else:
                    self._cw("[dim]Edição encerrada.[/dim]")

        _pedir_input(
            self,
            "Editar perfil",
            f"{mensagem}\n\nO que fazer agora?",
            _escolher,
            "1",
            lista=linhas,
        )
    # ==================================================================
    # ===  [AJUDA] AJUDA / MENSAGENS
    # ===  menu: Ajuda + helpers de mensagem
    # ===  usa: (nenhum modulo de dominio)
    # ==================================================================

    def _action_shortcuts(self) -> str:
        return (
            "[b]Atalhos de teclado[/b]\n\n"

            "[b]Menu principal e submenus[/b]\n"
            "  [b]0[/b]        Sair (so no menu principal)\n"
            "  [b]9[/b]        Voltar (dentro de submenus)\n"
            "  [b]1-8[/b]      Selecionar opcao do menu\n"
            "  [b]q / Ctrl+q[/b]  Sair (somente sem operacao em andamento)\n"
            "  [b]Ctrl+C[/b]      Cancelar a operacao atual; nunca sai da aplicacao\n\n"

            "[b]Dialogos de confirmacao[/b] [dim](ex.: Excluir, Reparar ESP-IDF, "
            "Compilar, Flash)[/dim]\n"
            "  [b]← / →[/b]    Alternar entre Confirmar e Cancelar\n"
            "  [b]Enter[/b]    Executar o botao selecionado\n"
            "  [b]Esc[/b]      Cancelar\n"
            "  [b]S / N[/b]    Confirmar / Cancelar diretamente\n"
            "  [dim]Tambem da para clicar nos botoes com o mouse.[/dim]\n\n"

            "[b]Dialogos de entrada de texto[/b] [dim](ex.: Renomear, Commit, "
            "Novo projeto, Definir placa)[/dim]\n"
            "  [b]Tab[/b]      Mover o foco do campo para os botoes\n"
            "  [b]← / →[/b]    Alternar entre Confirmar e Cancelar\n"
            "  [b]Enter[/b]    Confirmar o texto ou executar o botao selecionado\n"
            "  [b]Esc[/b]      Cancelar\n"
            "  [b]Ctrl+Shift+V[/b]  Colar texto\n"
            "  [dim]Com o campo focado, ← / → continuam movendo o cursor.[/dim]\n\n"

            "[dim]Nota: enquanto um dialogo estiver aberto, os numeros do menu "
            "(0, 1-8, 9) nao navegam — o teclado pertence ao dialogo ate ele "
            "fechar.[/dim]"
        )

    def _action_about(self) -> str:
        return (
            f"[b]ESP Lab[/b]  v{_version.get_version()}\n\n"
            "Gerenciador completo do ciclo de desenvolvimento de firmware\n"
            "ESP32 — o classico e as familias S2, S3, C2, C3, C5, C6,\n"
            "C61, H2, H4, H21 e P4 —, em terminal\n"
            "Linux.\n\n"

            "[b]O ciclo, por etapa[/b]\n"
            "  [b]Ambiente[/b]      ferramentas, ESP-IDF multi-versao,\n"
            "                dependencias isoladas.\n"
            "  [b]Hardware[/b]      reconhece a placa, le o chip real e\n"
            "                mantem um banco de perfis de placa.\n"
            "  [b]Programacao[/b]   organiza o projeto, gerencia\n"
            "                bibliotecas e gera a pinagem da placa.\n"
            "  [b]Flash[/b]         grava com validacao e confirmacao\n"
            "                em cada passo destrutivo.\n"
            "  [b]Monitor[/b]       saida serial em tempo real, com log\n"
            "                em disco.\n"
            "  [b]Versionamento[/b] prepara a estrutura Git local.\n\n"

            "[b]Filosofia: seguranca primeiro[/b]\n"
            "  Seguranca e a marca do produto e o criterio que decide os\n"
            "  empates de design:\n"
            "    - validacao em toda fronteira (nenhum dado externo\n"
            "      entra na logica sem ser validado);\n"
            "    - nada age sozinho: decisoes destrutivas sao sempre\n"
            "      suas, conscientes e explicitas;\n"
            "    - a falha vira mensagem de status, nunca derruba o app;\n"
            "    - persistencia atomica, resistente a queda de energia.\n"
            "  Na pratica: varredura de hardware so no boot, confirmacao\n"
            "  antes de apagar a Flash, monitor que nunca limpa sozinho,\n"
            "  recusa de gravar binario desatualizado.\n\n"

            "[b]O que nao e[/b]\n"
            "  Nao e um editor de codigo — a escrita e delegada ao editor\n"
            "  externo que voce ja usa.\n"
            "  Nao e um cliente Git completo — prepara o repositorio local;\n"
            "  o envio para a nuvem, se houver, e sempre manual, por sua\n"
            "  conta.\n\n"

            "[b]Repositorio[/b]  github.com/agaiautomacao-web/ESP-Lab "
            "[dim](publico)[/dim]\n\n"

            "[b]Isolamento e responsabilidade[/b]\n"
            "  O ESP Lab nao escreve nada fora da propria pasta em que\n"
            "  esta instalado e roda inteiramente dentro de ambientes\n"
            "  virtuais isolados — nao toca no Python do sistema nem em\n"
            "  pastas fora do projeto (salvo a regra sudoers opcional,\n"
            "  criada so com seu consentimento explicito).\n"
            "  Se tiver duvida sobre o que a aplicacao faz, nao instale.\n"
            "  O autor nao se responsabiliza por danos decorrentes de\n"
            "  uso incorreto, especialmente se os scripts forem\n"
            "  alterados em relacao ao original.\n\n"
            "[b]Contato[/b]\n"
            "  WhatsApp  +55 (11) 96595-2404\n"
            "  E-mail    ag.ai.automacao@gmail.com\n"
            "  Site      https://ag-ai-automacao.org\n\n"

            "[dim]Autor: Antonio Goncalves — AG AI Automacao.\n"
            "Desenvolvido com Python + Textual.[/dim]\n\n"

            "[dim]Nota: o design todo-terminal — sem depender de interface\n"
            "grafica, nem no editor externo — nao e uma limitacao tecnica.\n"
            "E o que garante que a aplicacao funcione igual num desktop ou\n"
            "direto do celular via SSH.[/dim]"
        )

    @staticmethod
    def _msg_sem_projeto() -> str:
        return (
            "[yellow]Nenhum projeto ativo.[/yellow]\n\n"
            "[dim]Abra um projeto em Workspace > Abrir projeto.[/dim]"
        )

    @staticmethod
    def _msg_sem_editor() -> str:
        return (
            "[yellow]Nenhum editor de terminal encontrado.[/yellow]\n\n"
            "[dim]Instale vim, nvim, nano, Helix ou Micro no PATH do\n"
            "sistema, ou rode 'python3 bundle_nano.py' na raiz do\n"
            "projeto (fora da aplicacao) para empacotar o nano dentro\n"
            "do proprio ambiente do ESP Lab. O ESP Lab so integra\n"
            "editores de terminal — eles rodam dentro do proprio\n"
            "terminal, sem sair do ambiente isolado da aplicacao.[/dim]"
        )
    # ==================================================================
    # ===  [PROG] PROGRAMACAO / BUILD
    # ===  menu: Programacao
    # ===  usa: _boards, _builder, _ports, _project_config, _scanner
    # ==================================================================

    @staticmethod
    def _format_code_chip_validation(report: dict) -> str:
        """Resumo Rich da validação offline de recursos do projeto."""
        declared = report.get("declared") or []
        labels = ", ".join(_code_chip.feature_label(item) for item in declared)
        if not labels:
            return "[dim]Recursos declarados: nenhum.[/dim]"

        status = str(report.get("status") or "")
        message = str(report.get("message") or "")
        lines = [f"Recursos declarados: {labels}"]
        if status == "warning":
            lines.append(f"[yellow]Aviso código × chip:[/yellow] {message}")
        elif status == "ok":
            lines.append("[green]Compatibilidade código × chip: OK[/green]")
        elif status == "not_declared":
            lines.append("[dim]Validação opcional sem requisitos declarados.[/dim]")
        return "\n".join(lines)

    def _guard_code_chip_build(self, project, title: str):
        """Valida antes do modal; ``builder.build`` repetirá na fronteira."""
        ok, result = _builder.validate_code_chip(project)
        if ok:
            return result
        message = (
            result.get("message", "validação indisponível")
            if isinstance(result, dict) else str(result)
        )
        self._cw(
            f"[b]{title}[/b]\n\n"
            "[red]Compilação bloqueada pela validação código × chip.[/red]\n\n"
            f"{message}\n\n"
            "[dim]Revise Programação > Recursos do projeto ou o perfil "
            "associado em Hardware.[/dim]"
        )
        return None

    def _action_programming_features(self) -> None:
        """Declara recursos opcionais usados pelo código do projeto."""
        from pathlib import Path

        if not self._projeto_ativo:
            self._cw("[b]Recursos do projeto[/b]\n\n" + self._msg_sem_projeto())
            return

        project = Path(self._projeto_ativo)
        ok_cfg, cfg = _project_config.read(project)
        if not ok_cfg:
            self._cw(f"[red]Erro ao ler config do projeto:[/red] {cfg}")
            return
        ok_catalog, catalog = _code_chip.get_feature_catalog()
        if not ok_catalog:
            self._cw(f"[red]Catálogo de recursos indisponível:[/red] {catalog}")
            return

        names = list(catalog.keys())
        current = [
            str(item).strip().lower()
            for item in (cfg.get("features") or [])
            if str(item).strip().lower() in catalog
        ]
        lines = [
            "[b]Recursos do projeto[/b]\n",
            "Declare somente recursos que o código realmente exige.",
            "Ausência confirmada bloqueia o build; dado desconhecido gera aviso.\n",
        ]
        selected_numbers = []
        for index, name in enumerate(names, start=1):
            mark = " [green]► ativo[/green]" if name in current else ""
            item = catalog[name]
            lines.append(
                f"  [b]{index}[/b]. {item.get('label', name)}{mark}\n"
                f"     [dim]{item.get('description', '')}[/dim]"
            )
            if name in current:
                selected_numbers.append(str(index))
        lines.append("\n  [b]0[/b]. Nenhum recurso opcional")

        def _save(value: str | None) -> None:
            if value is None:
                self._cw("[dim]Edição dos recursos cancelada.[/dim]")
                return
            raw = value.strip()
            if not raw:
                self._cw(
                    "[yellow]Nada foi alterado.[/yellow] "
                    "Digite 0 para limpar explicitamente."
                )
                return

            if raw == "0":
                selected = []
            else:
                tokens = [
                    token for token in raw.replace(";", ",").replace(" ", ",").split(",")
                    if token
                ]
                indexes = []
                try:
                    for token in tokens:
                        number = int(token)
                        if number < 1 or number > len(names):
                            raise ValueError
                        if number not in indexes:
                            indexes.append(number)
                except ValueError:
                    self._cw(
                        f"[red]Seleção inválida.[/red] Use números de 1 a "
                        f"{len(names)}, separados por vírgula, ou 0."
                    )
                    return
                selected = [names[number - 1] for number in indexes]

            ok_set, updated = _project_config.set_features(project, selected)
            if not ok_set:
                self._cw(f"[red]Falha ao salvar recursos:[/red] {updated}")
                return

            ok_validation, validation = _builder.validate_code_chip(project)
            labels = ", ".join(
                _code_chip.feature_label(item) for item in selected
            ) or "nenhum"
            if ok_validation:
                summary = self._format_code_chip_validation(validation)
                self._cw(
                    "[green]Recursos do projeto atualizados.[/green]\n\n"
                    f"Ativos: {labels}\n\n{summary}"
                )
                return

            message = (
                validation.get("message", "incompatibilidade")
                if isinstance(validation, dict) else str(validation)
            )
            self._cw(
                "[yellow]Recursos salvos, mas o próximo build será bloqueado.[/yellow]\n\n"
                f"Ativos: {labels}\n\n[red]{message}[/red]"
            )

        _pedir_input(
            self,
            "Recursos do projeto",
            "Números separados por vírgula; 0 limpa a seleção:",
            _save,
            placeholder="Ex.: 1,3,5 ou 0",
            valor_inicial=",".join(selected_numbers),
            lista=lines,
        )

    def _action_programming_status(self) -> str:
        """Programacao > Estado do build."""
        from pathlib import Path

        if not self._projeto_ativo:
            return (
                "[b]Estado do build[/b]\n\n"
                "[yellow]Nenhum projeto ativo.[/yellow]\n\n"
                "[dim]Abra um projeto em Workspace > Abrir projeto.[/dim]"
            )

        projeto = Path(self._projeto_ativo)
        ok, cfg = _project_config.read(projeto)
        if not ok:
            return f"[red]Erro ao ler config do projeto:[/red] {cfg}"

        linhas = [f"[b]Estado do build — {projeto.name}[/b]\n"]
        linhas.append(f"  ESP-IDF:  {cfg.get('idf_version', '?')}")
        linhas.append(f"  Target:   {cfg.get('target', '[dim]nao definido[/dim]')}")
        linhas.append(f"  Placa:    {cfg.get('board_name', '?')}")
        linhas.append("")

        ok_validation, validation = _builder.validate_code_chip(projeto)
        if ok_validation:
            linhas.append(self._format_code_chip_validation(validation))
        else:
            validation_message = (
                validation.get("message", "validação indisponível")
                if isinstance(validation, dict) else str(validation)
            )
            linhas.append(
                "[red]Validação código × chip bloqueada:[/red] "
                + validation_message
            )
        linhas.append("")

        ok2, check = _builder.check_build_valid(projeto)
        if not ok2:
            linhas.append(f"[red]Erro ao verificar build:[/red] {check}")
        elif check.get("valid"):
            bin_path = check.get("bin_path", "")
            linhas.append("[green]✔ Build valido[/green]")
            if bin_path:
                linhas.append(f"  Binario: [dim]{bin_path}[/dim]")
        else:
            razao = check.get("reason", "motivo desconhecido")
            linhas.append(f"[yellow]✘ Build invalido:[/yellow] {razao}")
            linhas.append("[dim]Use 'Compilar projeto' para gerar o binario.[/dim]")

        return "\n".join(linhas)

    @staticmethod

    @staticmethod
    def _family_to_target(chip_family: str) -> str:
        return _family_profiles.target_for_family(chip_family)


    def _guard_projeto_e_placa(
        self,
        titulo: str = "",
        via_thread: bool = False,
    ):
        """Exige projeto, versão ESP-IDF e target já configurado."""
        from pathlib import Path

        def _msg(text: str) -> None:
            if via_thread:
                self.call_from_thread(self._cw, text)
            else:
                self._cw(text)

        prefix = f"[b]{titulo}[/b]\n\n" if titulo else ""
        if not self._projeto_ativo:
            _msg(
                prefix
                + "[yellow]Nenhum projeto ativo.[/yellow]\n\n"
                + "[dim]Abra um projeto em Workspace > Abrir projeto.[/dim]"
            )
            return None, None

        project = Path(self._projeto_ativo)
        ok, cfg = _project_config.read(project)
        if not ok:
            _msg(f"{prefix}[red]Erro ao ler config do projeto:[/red] {cfg}")
            return None, None
        if not str(cfg.get("idf_version") or "").strip():
            _msg(f"{prefix}[red]Projeto sem versão ESP-IDF definida.[/red]")
            return None, None
        if not str(cfg.get("target") or "").strip():
            _msg(
                prefix
                + "[yellow]Target do projeto não definido.[/yellow]\n\n"
                + "[dim]Use Hardware > Associar perfil ao projeto e depois "
                  "Hardware > Configurar target do projeto.[/dim]"
            )
            return None, None
        return project, cfg


    def _action_programming_placa(self) -> None:
        """Compatibilidade: configuração de target agora pertence a Hardware."""
        self._cw(
            "[yellow]Esta ação foi movida.[/yellow]\n\n"
            "[dim]Use Hardware > Configurar target do projeto.[/dim]"
        )

    @work(thread=True)
    def _run_set_target_worker(
        self,
        project_dir: str,
        target: str,
        idf_version: str,
    ) -> None:
        """Executa o set-target transacional e atualiza o contexto visual."""
        lines: list[str] = [f"[dim]Configurando target '{target}'...[/dim]"]

        def _progress(kind: str, line: str) -> None:
            color = "yellow" if kind == "cancelado" else "dim"
            lines.append(f"[{color}]{line}[/{color}]")
            self.call_from_thread(self._cw, "\n".join(lines))

        try:
            ok, result = _builder.set_target(
                project_dir,
                target,
                idf_version,
                progress_cb=_progress,
                cancel_event=self._operation_cancel_event,
            )
            cancelled = (
                self._operation_cancel_event.is_set()
                or "cancelad" in str(result).lower()
            )
            if ok:
                warning = (
                    result.get("cleanup_warning")
                    if isinstance(result, dict) else None
                )
                suffix = (
                    f"\n[yellow]Aviso de limpeza:[/yellow] {warning}"
                    if warning else ""
                )
                self.call_from_thread(self._refresh_hardware_panel)
                self.call_from_thread(
                    self._cw,
                    "\n".join(lines)
                    + f"\n\n[green]✔ Target definido: {target}[/green]"
                    + suffix,
                )
            elif cancelled:
                self.call_from_thread(
                    self._cw,
                    "\n".join(lines)
                    + "\n\n[yellow]Cancelamento concluído. O estado anterior "
                      "do projeto foi restaurado.[/yellow]",
                )
            else:
                self.call_from_thread(
                    self._cw,
                    "\n".join(lines)
                    + f"\n\n[red]✘ Falha ao definir target:[/red] {result}",
                )
        finally:
            self._finish_operation()

    def _action_programming_carregar(self) -> None:
        """
        Programacao > Carregar (@E8-T8.11).
        Sempre builda de verdade (idf.py build) — e o ponto de entrada
        pra achar erro de codigo cedo. Mesma chamada por baixo que
        "Compilar" (PROJECT.md Adendo 2); o Ninja nao tenta linkar se a
        compilacao falhar, entao o que importa aqui e o erro de codigo.
        """
        projeto, cfg = self._guard_projeto_e_placa(titulo="Carregar")
        if projeto is None:
            return
        target = cfg.get("target", "").strip()
        idf_version = cfg.get("idf_version", "").strip()
        validation = self._guard_code_chip_build(projeto, "Carregar")
        if validation is None:
            return
        validation_summary = self._format_code_chip_validation(validation)

        def _executar(confirmado: bool) -> None:
            if not confirmado:
                self._cw("[dim]Carregamento cancelado.[/dim]")
                return
            self._start_operation(
                "Build do projeto", cancelable=True)
            self._run_build_worker(
                str(projeto),
                titulo_progresso="Carregando (compilando)...",
                msg_sucesso=(
                    "[green]✔ Compilacao concluida sem erros.[/green]\n"
                    "[dim]Use 'Compilar' para confirmar/gerar o binario.[/dim]"
                ),
            )

        _confirmar(
            self,
            titulo="Carregar",
            mensagem=(
                f"Projeto:  {projeto.name}\n"
                f"Target:   {target}\n"
                f"IDF:      {idf_version}\n\n"
                f"{validation_summary}\n\n"
                "Deseja iniciar o carregamento (compilacao)?"
            ),
            on_confirm=_executar,
        )

    def _action_programming_compilar(self) -> None:
        """
        Programacao > Compilar (@E8-T8.11).
        So dispara build() de verdade se check_build_valid() disser que
        precisa (binario ausente ou fonte mais novo que o binario);
        senao so confirma o que ja existe, sem recompilar. Mesma chamada
        de idf.py build que "Carregar" por baixo (PROJECT.md Adendo 2).
        """
        projeto, cfg = self._guard_projeto_e_placa(titulo="Compilar")
        if projeto is None:
            return
        target = cfg.get("target", "").strip()
        idf_version = cfg.get("idf_version", "").strip()
        validation = self._guard_code_chip_build(projeto, "Compilar")
        if validation is None:
            return
        validation_summary = self._format_code_chip_validation(validation)

        ok, check = _builder.check_build_valid(projeto)
        if ok and check.get("valid"):
            bin_path = check.get("bin_path", "")
            self._cw(
                "[b]Compilar[/b]\n\n"
                "[green]✔ Binario ja compilado e atualizado.[/green]\n"
                f"[dim]{bin_path}[/dim]\n\n"
                f"{validation_summary}\n\n"
                "[dim]Nada a fazer — use Gravar (Flash) para gravar na placa.[/dim]"
            )
            return

        razao = check.get("reason", "binario ausente ou desatualizado") if ok else str(check)

        def _executar(confirmado: bool) -> None:
            if not confirmado:
                self._cw("[dim]Compilacao cancelada.[/dim]")
                return
            self._start_operation(
                "Build do projeto", cancelable=True)
            self._run_build_worker(
                str(projeto),
                titulo_progresso="Compilando...",
                msg_sucesso=(
                    "[green]✔ Binario gerado com sucesso.[/green]\n"
                    "[dim]Use Gravar (Flash) para gravar na placa.[/dim]"
                ),
            )

        _confirmar(
            self,
            titulo="Compilar",
            mensagem=(
                f"Projeto:  {projeto.name}\n"
                f"Target:   {target}\n"
                f"IDF:      {idf_version}\n\n"
                f"{validation_summary}\n\n"
                f"[yellow]{razao}[/yellow]\n\n"
                "Deseja compilar agora?"
            ),
            on_confirm=_executar,
        )


    def _action_programming_gravar(self) -> None:
        """
        Grava somente quando o MAC vivo selecionado confere com o perfil
        associado ao projeto. Não varre todas as portas nem usa perfil global.
        """
        from pathlib import Path
        import datetime

        project, cfg = self._guard_projeto_e_placa(
            titulo="Gravar (Flash)",
            via_thread=True,
        )
        if project is None:
            return

        ok_context, context = self._current_hardware_context()
        if not ok_context:
            self.call_from_thread(
                self._cw,
                f"[red]Falha ao resolver contexto:[/red] {context}",
            )
            return
        if not context.get("association_exists"):
            self.call_from_thread(
                self._cw,
                "[b]Gravar (Flash)[/b]\n\n"
                "[yellow]Projeto sem perfil físico associado.[/yellow]\n\n"
                "[dim]Use Hardware > Associar perfil ao projeto.[/dim]",
            )
            return
        profile = context.get("expected_profile") or {}
        if not context.get("expected_profile_ready"):
            reasons = context.get("expected_profile_readiness_reasons") or []
            self.call_from_thread(
                self._cw,
                "[b]Gravar (Flash)[/b]\n\n"
                "[yellow]O perfil associado não está pronto para uso físico.[/yellow]\n\n"
                + "\n".join(f"  • {reason}" for reason in reasons)
                + "\n\n[dim]Revise o perfil antes de gravar.[/dim]",
            )
            return

        if not self._porta_ativa or not self._mac_porta_ativa:
            self.call_from_thread(
                self._cw,
                "[b]Gravar (Flash)[/b]\n\n"
                "[yellow]Nenhuma porta viva selecionada.[/yellow]\n\n"
                "[dim]Use Hardware > Identificar e selecionar porta.[/dim]",
            )
            return

        expected_mac = str(context.get("expected_mac") or "").lower()
        selected_mac = str(self._mac_porta_ativa or "").lower()
        if expected_mac != selected_mac:
            self.call_from_thread(
                self._cw,
                "[b]Gravar (Flash)[/b]\n\n"
                "[red]A placa conectada não é a placa esperada pelo projeto.[/red]\n\n"
                f"MAC esperado: {expected_mac or 'Não informado'}\n"
                f"MAC vivo:     {selected_mac or 'Não informado'}\n\n"
                "[dim]Selecione a placa correta ou altere a associação do projeto.[/dim]",
            )
            return

        entry = self._hardware_por_porta.get(self._porta_ativa, {})
        if entry.get("class") != "serial_esptool":
            self.call_from_thread(
                self._cw,
                "[red]A porta selecionada não é uma porta física compatível "
                "com esptool.[/red]",
            )
            return

        ok_build, build_check = _builder.check_build_valid(
            project,
            cancel_event=self._operation_cancel_event,
        )
        if not ok_build or not build_check.get("valid"):
            reason = (
                build_check.get("reason", "build inválido")
                if ok_build else str(build_check)
            )
            self.call_from_thread(
                self._cw,
                "[b]Gravar (Flash)[/b]\n\n"
                f"[yellow]Build inválido:[/yellow] {reason}\n\n"
                "[dim]Use Carregar/Compilar antes de gravar.[/dim]",
            )
            return
        bin_path = build_check.get("bin_path", "")

        ok_chip, chip = _chip.read_chip(
            self._porta_ativa,
            cancel_event=self._operation_cancel_event,
        )
        if not ok_chip:
            self.call_from_thread(
                self._cw,
                f"[red]Falha ao confirmar a placa antes do flash:[/red] {chip}",
            )
            return
        confirmed_mac = str(chip.get("mac") or "").lower()
        validation = _family_profiles.validate_profile_against_chip(
            profile, chip, require_ready=True
        )
        if not validation.get("use_allowed"):
            self.call_from_thread(self._clear_runtime_hardware, True)
            self.call_from_thread(
                self._cw,
                "[red]A placa viva não confere com o perfil pronto do projeto.[/red]\n\n"
                + "\n".join(
                    f"  • {reason}" for reason in validation.get("reasons", [])
                )
                + "\n\n[dim]Nenhuma escrita foi iniciada. "
                  "Identifique a porta e revise a associação.[/dim]",
            )
            return
        self.call_from_thread(
            self._update_runtime_chip,
            self._porta_ativa,
            chip,
        )

        project_target = str(cfg.get("target") or "").strip()
        profile_target = str(
            profile.get("target")
            or _family_profiles.target_for_family(profile.get("chip_family"))
            or ""
        ).strip()
        if profile_target and project_target != profile_target:
            self.call_from_thread(
                self._cw,
                "[red]Target do projeto incompatível com o perfil associado.[/red]\n\n"
                f"Projeto: {project_target or 'Não definido'}\n"
                f"Perfil:  {profile_target}\n\n"
                "[dim]Use Hardware > Configurar target do projeto.[/dim]",
            )
            return

        chip_family = validation.get("live_family") or (
            _family_profiles.normalize_family(
                chip.get("chip_family") or chip.get("chip_type")
            )
        )
        chip_flash_size = chip.get("flash_size", "")
        board_name = profile.get("board_name") or "Não identificada"
        try:
            timestamp = datetime.datetime.fromtimestamp(
                Path(bin_path).stat().st_mtime
            ).strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            timestamp = "desconhecido"

        def _after_erase(do_erase: bool) -> None:
            def _confirm_flash(confirmed: bool) -> None:
                if not confirmed:
                    self._cw("[dim]Gravação cancelada.[/dim]")
                    return
                self._start_operation(
                    "Gravação de firmware",
                    cancelable=True,
                )
                self._flash_em_andamento = True
                self._run_flash_worker(
                    str(project),
                    self._porta_ativa,
                    chip_family,
                    chip_flash_size,
                    do_erase=do_erase,
                    erase_confirmed=do_erase,
                    expected_mac=expected_mac,
                    confirmed_mac=confirmed_mac,
                    expected_family=validation.get("expected_family") or "",
                    confirmed_family=validation.get("live_family") or "",
                    profile_ready=True,
                )

            _confirmar(
                self,
                titulo="Confirmar gravação",
                mensagem=(
                    f"Perfil:      {board_name} ({expected_mac})\n"
                    f"Porta:       {self._porta_ativa}\n"
                    f"Target:      {project_target}\n"
                    f"Binário:     {timestamp}\n"
                    f"Velocidade:  {self._resolver_baud(self._porta_ativa)} bauds\n"
                    f"Erase:       {'SIM — apaga tudo antes' if do_erase else 'não'}\n\n"
                    "Confirma a gravação?"
                ),
                on_confirm=_confirm_flash,
            )

        self.call_from_thread(
            _confirmar,
            self,
            "Apagar flash antes?",
            "Apagar o flash remove TODOS os dados persistidos da placa.\n\n"
            "S = apagar antes    N = gravar direto",
            _after_erase,
        )

    @work(thread=True)
    def _run_build_worker(self, project_dir: str,
                          titulo_progresso: str = "Compilando projeto...",
                          msg_sucesso: str = (
                              "[green]✔ Build concluido com sucesso.[/green]\n"
                              "[dim]Use Flash para gravar na placa.[/dim]"
                          )) -> None:
        """Executa idf.py build em background com progresso linha a linha.
        titulo_progresso/msg_sucesso permitem @E8-T8.11 (Carregar/Compilar)
        reusar o mesmo worker com mensagens diferentes por cima da mesma
        chamada de build()."""
        content = self._content()
        linhas: list[str] = [f"[b]{titulo_progresso}[/b]\n"]
        erros: list[str] = []

        def _progresso(tipo: str, linha: str) -> None:
            if tipo == "cancelado":
                linhas.append(f"[yellow]{linha}[/yellow]")
            elif tipo == "error":
                erros.append(linha)
                linhas.append(f"[red]{linha}[/red]")
            elif tipo == "warning":
                linhas.append(f"[yellow]{linha}[/yellow]")
            else:
                linhas.append(f"[dim]{linha}[/dim]")
            self.call_from_thread(self._cw, "\n".join(linhas))

        try:
            ok, resultado = _builder.build(
                project_dir=project_dir,
                progress_cb=_progresso,
                cancel_event=self._operation_cancel_event,
                background=False,
            )
            cancelado = (
                self._operation_cancel_event.is_set()
                or "cancelad" in str(resultado).lower()
            )

            if ok:
                self.call_from_thread(self._cw, "\n".join(linhas) + "\n\n" + msg_sucesso)
            elif cancelado:
                self.call_from_thread(
                    self._cw,
                    "\n".join(linhas)
                    + "\n\n[yellow]Cancelamento do build concluido. "
                    "idf.py, CMake, Ninja e compiladores foram "
                    "encerrados.[/yellow]",
                )
            else:
                resumo_erros = "\n".join(erros[-5:]) if erros else str(resultado)
                self.call_from_thread(self._cw, "\n".join(linhas) + "\n\n"
                    f"[red]✘ Build falhou:[/red]\n{resumo_erros}"
                )
        finally:
            # Libera o teclado ao terminar (sucesso, falha ou excecao).
            self._finish_operation()
    # ==================================================================
    # ===  [FLASH] FLASH
    # ===  gravacao (Programacao > Gravar)
    # ===  usa: _builder, _flasher, _port_config, _ports, _project_config
    # ===       _scanner
    # ==================================================================

    def _action_flash(self) -> None:
        """
        ÓRFÃO desde a criação de "Configurações" (ex-menu Principal>Flash):
        nenhum item de MENU_TREE aponta mais pra este metodo. Substituido
        por _action_programming_gravar (Programacao > Gravar (Flash),
        @E9-T9.8/T9.9). Mantido por decisao explicita (sem preferencia
        entre remover agora ou depois) — _run_flash_worker abaixo CONTINUA
        em uso, chamado por _action_programming_gravar.

        Flash > Grava firmware na placa.
        Sequencia: sem projeto ativo -> aviso; sem porta ESP -> aviso;
        build invalido -> oferece compilar; confirma erase (opcional);
        grava com progresso linha a linha; verifica pos-gravacao.
        """
        from pathlib import Path

        content = self._content()

        # 1. Projeto ativo obrigatorio
        if not self._projeto_ativo:
            self.call_from_thread(self._cw, "[b]Flash[/b]\n\n"
                "[yellow]Nenhum projeto ativo.[/yellow]\n\n"
                "[dim]Abra um projeto em Workspace > Abrir projeto.[/dim]"
            )
            return

        projeto = Path(self._projeto_ativo)
        ok, cfg = _project_config.read(projeto)
        if not ok:
            self.call_from_thread(self._cw, f"[red]Erro ao ler config do projeto:[/red] {cfg}"
            )
            return

        idf_version = cfg.get("idf_version", "").strip()
        if not idf_version:
            self.call_from_thread(self._cw, "[red]Projeto sem versao de ESP-IDF definida.[/red]"
            )
            return

        # 2. Porta ESP obrigatoria
        ok2, esp_ports = _ports.probable_esp_ports()
        if not ok2 or not esp_ports:
            self.call_from_thread(self._cw, "[b]Flash[/b]\n\n"
                "[yellow]Nenhuma porta ESP detectada.[/yellow]\n\n"
                "[dim]Conecte a placa e use Hardware > Buscar placas.[/dim]"
            )
            return

        port_info = esp_ports[0]
        port      = port_info["device"]
        hint      = port_info.get("chip_hint", "")

        # 3. Chip info do scanner (para familia e flash size)
        ok3, scan_results = _scanner.scan()
        chip_family     = ""
        chip_flash_size = ""
        if ok3 and scan_results:
            for r in scan_results:
                if r["device"] == port and not r["error"]:
                    chip_family     = r["chip"].get("chip_family", "")
                    chip_flash_size = r["chip"].get("flash_size", "")
                    break

        # 4. Verifica build
        ok4, check = _builder.check_build_valid(projeto)
        build_valido = ok4 and check.get("valid", False)

        if not build_valido:
            razao = check.get("reason", "build invalido") if ok4 else str(check)
            self.call_from_thread(self._cw, f"[b]Flash — {projeto.name}[/b]\n\n"
                f"[yellow]Build invalido:[/yellow] {razao}\n\n"
                "[dim]Compile o projeto antes de gravar.[/dim]\n\n"
                f"Porta:  {port}  {hint}\n"
                f"Chip:   {chip_family or 'desconhecido'}\n"
                f"Flash:  {chip_flash_size or 'desconhecido'}"
            )
            return

        # 5. Confirmacao de erase (opcional, destrutiva)
        def _continuar_apos_erase(do_erase: bool) -> None:
            """Chamado na thread principal apos decisao de erase."""
            def _confirmar_flash(confirmado: bool) -> None:
                if not confirmado:
                    self._cw("[dim]Gravacao cancelada.[/dim]")
                    return
                self._start_operation(
                    "Gravacao de firmware", cancelable=True
                )
                self._flash_em_andamento = True
                self._run_flash_worker(
                    str(projeto), port, chip_family, chip_flash_size,
                    do_erase=do_erase, erase_confirmed=do_erase
                )

            _confirmar(
                self,
                titulo="Confirmar gravacao",
                mensagem=(
                    f"Projeto:  {projeto.name}\n"
                    f"Porta:    {port}  {hint}\n"
                    f"Chip:     {chip_family or 'desconhecido'}\n"
                    f"Flash:    {chip_flash_size or 'desconhecido'}\n"
                    f"Erase:    {'SIM — apaga tudo antes' if do_erase else 'nao'}\n\n"
                    "Confirma a gravacao?"
                ),
                on_confirm=_confirmar_flash,
            )

        def _perguntar_erase(confirmado_erase: bool) -> None:
            _continuar_apos_erase(confirmado_erase)

        self.call_from_thread(
            _confirmar,
            self,
            "Apagar flash antes?",
            "Apagar o flash antes da gravacao remove TODOS os dados\n"
            "(NVS, configuracoes salvas). Operacao irreversivel.\n\n"
            "S = apagar antes    N = gravar direto",
            _perguntar_erase,
        )

    def _resolver_baud(self, port: str) -> int:
        """Baud de upload da porta (@EC-T3a): le de port_config, valida
        contra BAUDRATES, fallback pro default se invalido. Nunca quebra."""
        try:
            pc = _port_config.get_port_config(port)
            baud = pc.get("baudrate", _port_config.DEFAULT_BAUDRATE)
            if baud in _port_config.BAUDRATES:
                return baud
        except Exception:
            pass
        return _port_config.DEFAULT_BAUDRATE

    @work(thread=True)
    def _run_flash_worker(
        self,
        project_dir: str,
        port: str,
        chip_family: str,
        chip_flash_size: str,
        do_erase: bool,
        erase_confirmed: bool,
        expected_mac: str = "",
        confirmed_mac: str = "",
        expected_family: str = "",
        confirmed_family: str = "",
        profile_ready: bool | None = None,
    ) -> None:
        """Executa a sequencia completa de flash em background."""
        content = self._content()
        linhas: list[str] = [f"[b]Gravando firmware...[/b]\n"]

        def _progresso(tipo: str, linha: str) -> None:
            cor = {
                "cancelado": "[yellow]",
                "error":   "[red]",
                "warning": "[yellow]",
                "info":    "[dim]",
            }.get(tipo, "[dim]")
            fim = {
                "cancelado": "[/yellow]",
                "error": "[/red]",
                "warning": "[/yellow]",
                "info": "[/dim]",
            }.get(tipo, "[/dim]")
            linhas.append(f"{cor}{linha}{fim}")
            self.call_from_thread(self._cw, "\n".join(linhas))

        # Prioridade do chip (§10.6): se um monitor estiver na mesma porta,
        # o daemon libera a serial antes do write e a readquire depois. O
        # flasher nao conhece o monitor; a coordenacao vive aqui.
        havia_daemon, rel_ok, rel_msg = self._monitor_release_para_flash(port)
        if havia_daemon and rel_ok:
            _progresso("info", "Monitor liberou a porta {} para a "
                               "gravacao.".format(port))
        elif havia_daemon and not rel_ok:
            _progresso("warning", "Nao foi possivel liberar a porta do "
                                  "monitor: {}. Gravacao abortada para nao "
                                  "disputar a serial.".format(rel_msg))
            self.call_from_thread(self._cw, "\n".join(linhas) + "\n\n"
                "[red]✘ Gravacao nao iniciada:[/red] a porta esta em uso "
                "pelo monitor e nao pode ser liberada.\n"
                "[dim]Encerre o monitor da porta {} e tente de novo.[/dim]"
                .format(port))
            self._flash_em_andamento = False
            self._finish_operation()
            return

        try:
            ok, resultado = _flasher.flash(
                project_dir=project_dir,
                port=port,
                chip_family=chip_family,
                chip_flash_size=chip_flash_size,
                baudrate=self._resolver_baud(port),
                do_erase=do_erase,
                erase_confirmed=erase_confirmed,
                progress_cb=_progresso,
                cancel_event=self._cancelar_flash,
                expected_mac=expected_mac,
                confirmed_mac=confirmed_mac,
                expected_chip_family=expected_family,
                confirmed_chip_family=confirmed_family,
                profile_ready=profile_ready,
                background=False,
            )

            if ok:
                self.call_from_thread(self._cw, "\n".join(linhas) + "\n\n"
                    "[green]✔ Firmware gravado e verificado com sucesso.[/green]\n"
                    f"[dim]Porta: {port}[/dim]"
                )
            elif "cancelad" in str(resultado).lower():
                self.call_from_thread(self._cw, "\n".join(linhas) + "\n\n"
                    "[yellow]Cancelamento da gravacao concluido.[/yellow]\n"
                    f"[dim]{resultado}[/dim]\n\n"
                    "[dim]Se a escrita ja havia iniciado, o firmware pode "
                    "estar incompleto ou sem verificacao. Grave novamente "
                    "antes de usar a placa.[/dim]"
                )
            else:
                self.call_from_thread(self._cw, "\n".join(linhas) + "\n\n"
                    f"[red]✘ Falha na gravacao:[/red] {resultado}"
                )
        finally:
            # Devolve a porta ao monitor mesmo se o flash falhou ou foi
            # cancelado — a leitura volta a acontecer.
            if havia_daemon:
                self._monitor_reacquire_apos_flash(port)
                _progresso("info", "Monitor readquiriu a porta {}."
                           .format(port))
            self._flash_em_andamento = False
            self._finish_operation()
    # ==================================================================
    # ===  [CONFIG] CONFIGURACOES
    # ===  menu: Configuracoes
    # ===  usa: _boards, _partitions, _port_config, _ports, _scanner, _sdk
    # ==================================================================

    # ---- Configurações (@EC-T2, casca visual) --------------------------
    # Estes 7 metodos SO EXIBEM listas com o item atual marcado (►). NAO
    # persistem escolha (decisao de Antonio: casca agora, gravacao depois —
    # @EC-T3). Campos que alimentam o build (Particao, Flash, CPU) usam
    # default FUNCIONAL, nunca placeholder. Ver PROJECT.md Adendo 4/5.

    @staticmethod
    def _render_config_list(titulo: str, opcoes: list, atual: str,
                            nota: str = "") -> str:
        """Renderiza uma lista de configuração com o item atual marcado (►).
        Nao grava nada — apenas exibe. Marca por comparacao case-insensitive;
        se 'atual' nao casa com nenhuma opcao, nada fica marcado (leitura
        honesta, sem forcar)."""
        linhas = [f"[b]{titulo}[/b]\n"]
        alvo = (atual or "").strip().lower()
        marcou = False
        for i, op in enumerate(opcoes, start=1):
            op_str = str(op)
            if op_str.strip().lower() == alvo:
                linhas.append(f"  [green]►[/green] [b]{i}. {op_str}[/b]")
                marcou = True
            else:
                linhas.append(f"    {i}. {op_str}")
        if atual and not marcou:
            linhas.append(f"\n[dim]Atual: {atual} "
                          f"(fora da lista de opções)[/dim]")
        elif not atual:
            linhas.append("\n[dim]Nenhum valor atual definido.[/dim]")
        if nota:
            linhas.append(f"\n[dim]{nota}[/dim]")
        linhas.append("\n[dim](Seleção e gravação chegam ao ligar "
                      "Configurações — @EC-T3.)[/dim]")
        return "\n".join(linhas)

    def _config_porta_ativa(self) -> str:
        """Melhor porta conhecida para ler config de Conexao.
        Prefere a porta escolhida pelo usuario em Hardware > Definir portas
        (self._porta_ativa). Se nao houver escolha explicita, cai no auto-
        detect: 1a porta ESP provavel detectada, senao vazio. So leitura."""
        if self._porta_ativa:
            return self._porta_ativa
        ok, esp = _ports.probable_esp_ports()
        if ok and esp:
            return esp[0].get("device", "")
        return ""

    def _action_config_conexao(self) -> None:
        """Configurações > Conexão (@EC-T3a): exibe estado e permite
        selecionar a velocidade de upload (grava em port_config, por porta).
        Seleção enumerada, sem digitação livre."""
        dev = self._config_porta_ativa()
        if not dev:
            self._cw("[b]Conexão[/b]\n\n"
                     "[yellow]Nenhuma porta ESP detectada.[/yellow]\n\n"
                     "[dim]Conecte a placa para configurar a velocidade.[/dim]")
            return
        baud_atual = self._resolver_baud(dev)
        usb_mode = "Desconhecido"
        ok_s, scan_res = _scanner.scan()
        if ok_s:
            for r in scan_res:
                if r.get("chip") and r.get("device") == dev:
                    usb_mode = r["chip"].get("usb_mode", "Desconhecido") or "Desconhecido"
                    break

        bauds = list(_port_config.BAUDRATES)
        linhas_lista = []
        for i, b in enumerate(bauds, start=1):
            marca = " [green]►[/green]" if b == baud_atual else ""
            linhas_lista.append(f"  [b]{i}[/b]. {b} bauds{marca}")

        cabecalho = (f"[b]Conexão[/b]\n\n"
                     f"Porta:     {dev}\n"
                     f"USB Modo:  {usb_mode}\n"
                     f"Atual:     {baud_atual} bauds\n")

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(bauds):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(bauds)}")
                return
            novo = bauds[idx]
            ok, res = _port_config.set_baudrate(dev, novo)
            if not ok:
                self._cw(f"[red]Falha ao gravar velocidade:[/red] {res}")
                return
            self._cw(f"[green]✔ Velocidade definida:[/green] {novo} bauds\n"
                     f"[dim]Porta: {dev}[/dim]")

        _pedir_input(
            self,
            "Velocidade (upload)",
            f"Número da velocidade (atual: {baud_atual}):",
            _escolher, "1",
            lista=[cabecalho] + linhas_lista)


    def _action_config_placa(self) -> None:
        """Configurações > Placa usa a associação do projeto, nunca sessão global."""
        self._action_associar_perfil()

    def _config_flash_guard(self):
        """Projeto ativo? Retorna Path ou None (com mensagem). Flash grava no
        sdkconfig.defaults do projeto — precisa de projeto aberto."""
        if not self._projeto_ativo:
            self._cw("[b]Flash[/b]\n\n"
                     "[yellow]Nenhum projeto ativo.[/yellow]\n\n"
                     "[dim]Abra um projeto em Workspace para configurar o "
                     "Flash (grava no sdkconfig.defaults do projeto).[/dim]")
            return None
        from pathlib import Path
        return Path(self._projeto_ativo)

    def _action_config_flash_modo(self) -> None:
        """Configurações > Flash > Modo (@EC-T3b). Lista amigavel, grava
        modo+freq no sdkconfig.defaults. Lista completa (§6.8); a checagem
        de suporte da placa e da funcao que executa, nao aqui."""
        projeto = self._config_flash_guard()
        if projeto is None:
            return
        opcoes = list(_sdk.FLASH_MODE_OPTIONS)
        atual = _sdk.get_flash_mode(projeto)
        linhas = []
        for i, op in enumerate(opcoes, start=1):
            marca = " [green]►[/green]" if op == atual else ""
            linhas.append(f"  [b]{i}[/b]. {op}{marca}")
        cabecalho = f"[b]Flash > Modo[/b]\n\nAtivo: {atual}\n"

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(opcoes):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(opcoes)}")
                return
            ok, res = _sdk.set_flash_mode(projeto, opcoes[idx])
            if not ok:
                self._cw(f"[red]Falha ao gravar modo:[/red] {res}")
                return
            self._cw(f"[green]✔ Modo definido:[/green] {opcoes[idx]}\n"
                     "[dim]Vale no próximo build (sdkconfig.defaults).[/dim]")

        _pedir_input(self, "Flash > Modo",
                     f"Número do modo (ativo: {atual}):",
                     _escolher, "1", lista=[cabecalho] + linhas)

    def _action_config_flash_tamanho(self) -> None:
        """Configurações > Flash > Tamanho (@EC-T3b). Lista completa; grava
        no sdkconfig.defaults. Default FUNCIONAL se ausente."""
        projeto = self._config_flash_guard()
        if projeto is None:
            return
        opcoes = list(_sdk.FLASH_SIZE_OPTIONS)
        atual = _sdk.get_flash_size(projeto)
        linhas = []
        for i, op in enumerate(opcoes, start=1):
            marca = " [green]►[/green]" if op == atual else ""
            linhas.append(f"  [b]{i}[/b]. {op}{marca}")
        cabecalho = (f"[b]Flash > Tamanho[/b]\n\nAtivo: {atual}\n"
                     "[dim]Lista completa (§6.8); a checagem de que cabe na "
                     "placa é feita ao gravar.[/dim]\n")

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(opcoes):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(opcoes)}")
                return
            ok, res = _sdk.set_flash_size(projeto, opcoes[idx])
            if not ok:
                self._cw(f"[red]Falha ao gravar tamanho:[/red] {res}")
                return
            self._cw(f"[green]✔ Tamanho definido:[/green] {opcoes[idx]}\n"
                     "[dim]Vale no próximo build (sdkconfig.defaults).[/dim]")

        _pedir_input(self, "Flash > Tamanho",
                     f"Número do tamanho (ativo: {atual}):",
                     _escolher, "1", lista=[cabecalho] + linhas)

    def _action_config_psram(self) -> None:
        """Configurações > PSRAM (@EC-T3b, Adendo 5): so "Modo"
        (Desabilitada/QSPI/OPI). Grava no sdkconfig.defaults. Nao ha
        "tamanho" de PSRAM no sdkconfig (auto-detectado pelo IDF)."""
        projeto = self._config_flash_guard()  # mesmo guard: projeto ativo
        if projeto is None:
            return
        opcoes = list(_sdk.PSRAM_MODE_OPTIONS)
        atual = _sdk.get_psram_mode(projeto)
        linhas = []
        for i, op in enumerate(opcoes, start=1):
            marca = " [green]►[/green]" if op == atual else ""
            linhas.append(f"  [b]{i}[/b]. {op}{marca}")
        cabecalho = (f"[b]PSRAM > Modo[/b]\n\nAtivo: {atual}\n"
                     "[dim]Tamanho é auto-detectado pelo IDF — sem seleção.[/dim]\n")

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(opcoes):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(opcoes)}")
                return
            ok, res = _sdk.set_psram_mode(projeto, opcoes[idx])
            if not ok:
                self._cw(f"[red]Falha ao gravar modo PSRAM:[/red] {res}")
                return
            self._cw(f"[green]✔ PSRAM definida:[/green] {opcoes[idx]}\n"
                     "[dim]Vale no próximo build (sdkconfig.defaults).[/dim]")

        _pedir_input(self, "PSRAM > Modo",
                     f"Número do modo (ativo: {atual}):",
                     _escolher, "1", lista=[cabecalho] + linhas)

    def _config_particao_para_tamanho(self, size_label: str) -> None:
        """
        Helper comum aos 4 subitens de Partição (4MB/8MB/16MB/32MB) —
        cada tamanho e seu proprio submenu, INDEPENDENTE de Flash > Tamanho
        (correcao pedida por Antonio; a versao anterior derivava do Flash
        e travava em "4MB" ate ele ser configurado). Lista dinamica do
        catalogo (partition_tables.yml) — crescer o catalogo aparece aqui
        sem mudanca de codigo. Grava sdkconfig.defaults + gera
        partitions.csv. Sem variacao no catalogo -> default FUNCIONAL
        (PARTITION_FALLBACK_VARIATION), nunca vazio.
        """
        projeto = self._config_flash_guard()
        if projeto is None:
            return
        ok, variacoes = _partitions.list_variations(size_label)
        if not ok or not variacoes:
            variacoes = [dict(_sdk.PARTITION_FALLBACK_VARIATION)]
            aviso = (f"[yellow]Catálogo sem esquema para {size_label}; "
                    "usando padrão funcional.[/yellow]\n")
        else:
            aviso = ""

        # nome E tamanho (nao so nome) -- o catalogo real repete nomes de
        # variacao entre tamanhos (ex. "Padrao" em 4/8/16/32MB); marcar so
        # por nome daria falso-positivo em todos os submenus ao mesmo tempo.
        nome_ativo, tamanho_ativo = _sdk.get_partition_scheme_info(projeto)
        nada_gravado_ainda = tamanho_ativo is None
        if nada_gravado_ainda:
            # Nenhum dos 4 tamanhos foi configurado ainda -- marca o
            # primeiro esquema desta lista como default, igualando o
            # comportamento de Flash/PSRAM (que sempre mostram algo
            # marcado, mesmo antes de qualquer selecao).
            nome_ativo = variacoes[0].get("nome", "?")
            tamanho_ativo = size_label
        linhas = []
        for i, v in enumerate(variacoes, start=1):
            nome = v.get("nome", "?")
            eh_ativo = (tamanho_ativo == size_label and nome == nome_ativo)
            marca = " [green]►[/green]" if eh_ativo else ""
            linhas.append(f"  [b]{i}[/b]. {nome}{marca}")
        nota_default = ("[dim]Nenhuma seleção gravada ainda — mostrando "
                       "padrão.[/dim]\n" if nada_gravado_ainda else "")
        cabecalho = f"[b]Partição > {size_label}[/b]\n\n{aviso}{nota_default}"

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(variacoes):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(variacoes)}")
                return
            variacao = variacoes[idx]
            ok2, res2 = _sdk.set_partition_scheme(projeto, size_label, variacao)
            if not ok2:
                self._cw(f"[red]Falha ao gravar partição:[/red] {res2}")
                return
            self._cw(f"[green]✔ Partição definida:[/green] {variacao.get('nome', '?')} "
                    f"({size_label})\n"
                    "[dim]Vale no próximo build (sdkconfig.defaults + "
                    "partitions.csv).[/dim]")

        _pedir_input(self, f"Partição > {size_label}",
                    "Número do esquema:",
                    _escolher, "1", lista=[cabecalho] + linhas)

    def _action_config_particao_4mb(self) -> None:
        """Configurações > Partição > 4MB (@EC-T3b)."""
        self._config_particao_para_tamanho("4MB")

    def _action_config_particao_8mb(self) -> None:
        """Configurações > Partição > 8MB (@EC-T3b)."""
        self._config_particao_para_tamanho("8MB")

    def _action_config_particao_16mb(self) -> None:
        """Configurações > Partição > 16MB (@EC-T3b)."""
        self._config_particao_para_tamanho("16MB")

    def _action_config_particao_32mb(self) -> None:
        """Configurações > Partição > 32MB (@EC-T3b)."""
        self._config_particao_para_tamanho("32MB")

    def _action_config_cpu(self) -> None:
        """Configurações > CPU (@EC-T3b): Frequência, seletor real. Grava
        choice + chave inteira companheira no sdkconfig.defaults."""
        projeto = self._config_flash_guard()
        if projeto is None:
            return
        opcoes = list(_sdk.CPU_FREQ_OPTIONS)
        atual = _sdk.get_cpu_freq(projeto)
        linhas = []
        for i, op in enumerate(opcoes, start=1):
            marca = " [green]►[/green]" if op == atual else ""
            linhas.append(f"  [b]{i}[/b]. {op}{marca}")
        cabecalho = f"[b]CPU > Frequência[/b]\n\nAtivo: {atual}\n"

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(opcoes):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(opcoes)}")
                return
            ok, res = _sdk.set_cpu_freq(projeto, opcoes[idx])
            if not ok:
                self._cw(f"[red]Falha ao gravar frequência:[/red] {res}")
                return
            self._cw(f"[green]✔ Frequência definida:[/green] {opcoes[idx]}\n"
                     "[dim]Vale no próximo build (sdkconfig.defaults).[/dim]")

        _pedir_input(self, "CPU > Frequência",
                     f"Número da frequência (ativo: {atual}):",
                     _escolher, "1", lista=[cabecalho] + linhas)

    def _action_config_depuracao(self) -> None:
        """Configurações > Depuração (@EC-T3b): Nível de log, seletor real.
        Grava no sdkconfig.defaults (CONFIG_LOG_DEFAULT_LEVEL_*)."""
        projeto = self._config_flash_guard()
        if projeto is None:
            return
        opcoes = list(_sdk.LOG_LEVEL_OPTIONS)
        atual = _sdk.get_log_level(projeto)
        linhas = []
        for i, op in enumerate(opcoes, start=1):
            marca = " [green]►[/green]" if op == atual else ""
            linhas.append(f"  [b]{i}[/b]. {op}{marca}")
        cabecalho = f"[b]Depuração > Nível[/b]\n\nAtivo: {atual}\n"

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Seleção cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(opcoes):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Número inválido.[/red] Escolha entre 1 e {len(opcoes)}")
                return
            ok, res = _sdk.set_log_level(projeto, opcoes[idx])
            if not ok:
                self._cw(f"[red]Falha ao gravar nível:[/red] {res}")
                return
            self._cw(f"[green]✔ Nível de log definido:[/green] {opcoes[idx]}\n"
                     "[dim]Vale no próximo build (sdkconfig.defaults).[/dim]")

        _pedir_input(self, "Depuração > Nível",
                     f"Número do nível (ativo: {atual}):",
                     _escolher, "1", lista=[cabecalho] + linhas)
    # ==================================================================
    # ===  [WS] WORKSPACE
    # ===  menu: Workspace
    # ===  usa: _idf_mgr, _project_config, _workspace
    # ==================================================================

    def _workspace_directory_change_blocked(self) -> bool:
        """Impede troca da raiz enquanto um projeto estiver ativo."""
        if not self._projeto_ativo:
            return False
        self._cw(
            "[b]Diretório do workspace[/b]\n\n"
            "[red]Alteração bloqueada: existe um projeto aberto.[/red]\n\n"
            f"Projeto ativo:\n  {self._projeto_ativo}\n\n"
            "[dim]Feche o projeto antes de alterar a raiz do workspace. "
            "Nenhum arquivo foi movido ou modificado.[/dim]"
        )
        return True

    def _action_workspace_diretorio_status(self) -> str:
        """Workspace > Diretório do workspace > Estado atual."""
        ok, state = _workspace.get_workspace_state()
        if not ok:
            return (
                "[b]Diretório do workspace[/b]\n\n"
                f"[red]Configuração inválida:[/red] {state}"
            )

        source = "padrão da aplicação" if state.get("source") == "default" else "escolhido pelo usuário"
        status = (
            "[green]disponível para leitura[/green]"
            if state.get("usable")
            else f"[red]indisponível[/red] — {state.get('error')}"
        )
        return (
            "[b]Diretório do workspace[/b]\n\n"
            f"[b]Ativo:[/b] {state.get('path')}\n"
            f"[b]Origem:[/b] {source}\n"
            f"[b]Estado:[/b] {status}\n\n"
            f"[b]Padrão:[/b] {state.get('default_path')}\n"
            f"[b]Preferência:[/b] {state.get('config_path')}\n\n"
            "[dim]A preferência é global. Os projetos existentes não são "
            "movidos automaticamente.[/dim]"
        )

    def _action_workspace_diretorio_alterar(self) -> None:
        """Escolhe e persiste uma nova raiz de workspace."""
        if self._workspace_directory_change_blocked():
            return

        ok_state, state = _workspace.get_workspace_state()
        current_path = (
            str(state.get("path"))
            if ok_state and isinstance(state, dict)
            else str(_workspace.default_workspace_dir())
        )

        def _preview(value: str) -> str:
            ok, normalized = _workspace.normalize_workspace_dir(value)
            if not ok:
                return f"[red]{normalized}[/red]"
            path = normalized
            if not path.exists():
                return f"[dim]{path}[/dim]  [red](inexistente)[/red]"
            if not path.is_dir():
                return f"[dim]{path}[/dim]  [red](não é diretório)[/red]"
            return f"[dim]{path}[/dim]"

        def _received(value: str | None) -> None:
            if value is None:
                self._cw("[dim]Alteração do workspace cancelada.[/dim]")
                return
            if self._workspace_directory_change_blocked():
                return

            ok, validation = _workspace.validate_workspace_dir(
                value,
                verify_write=True,
            )
            if not ok:
                self._cw(
                    "[b]Alterar diretório do workspace[/b]\n\n"
                    f"[red]Diretório recusado:[/red] {validation}\n\n"
                    "[dim]A preferência atual foi preservada.[/dim]"
                )
                return

            new_path = str(validation["path"])
            ok_now, state_now = _workspace.get_workspace_state()
            old_path = (
                str(state_now.get("path"))
                if ok_now and isinstance(state_now, dict)
                else current_path
            )
            if new_path == old_path:
                self._cw(
                    "[b]Alterar diretório do workspace[/b]\n\n"
                    "[dim]O diretório informado já é o workspace ativo.[/dim]\n\n"
                    f"{new_path}"
                )
                return

            def _apply(confirmed: bool) -> None:
                if not confirmed:
                    self._cw("[dim]Alteração do workspace cancelada.[/dim]")
                    return
                if self._workspace_directory_change_blocked():
                    return
                ok_set, result = _workspace.set_workspace_dir(new_path)
                if not ok_set:
                    self._cw(
                        "[b]Alterar diretório do workspace[/b]\n\n"
                        f"[red]Falha ao salvar a preferência:[/red] {result}\n\n"
                        "[dim]A configuração anterior foi preservada.[/dim]"
                    )
                    return
                self._refresh_paths_panel()
                self._cw(
                    "[green]Diretório do workspace atualizado.[/green]\n\n"
                    f"[b]Ativo:[/b] {result.get('path')}\n\n"
                    "[dim]Nenhum projeto foi movido, copiado ou excluído.[/dim]"
                )

            _confirmar(
                self,
                "Alterar diretório do workspace",
                "Confirme a alteração global:\n\n"
                f"Atual:\n  {old_path}\n\n"
                f"Novo:\n  {new_path}\n\n"
                "Consequências:\n"
                "  • projetos existentes não serão movidos nem copiados;\n"
                "  • Abrir projeto listará o novo diretório;\n"
                "  • novos projetos serão criados no novo diretório;\n"
                "  • o histórico de projetos recentes será preservado.",
                _apply,
            )

        _pedir_input(
            self,
            "Alterar diretório do workspace",
            "Diretório existente com permissão de leitura e escrita:",
            _received,
            placeholder="/caminho/absoluto/workspace",
            valor_inicial=current_path,
            on_change=_preview,
        )

    def _action_workspace_diretorio_padrao(self) -> None:
        """Restaura explicitamente a raiz padrão da aplicação."""
        if self._workspace_directory_change_blocked():
            return

        ok_state, state = _workspace.get_workspace_state()
        default_path = str(_workspace.default_workspace_dir())
        current_path = (
            str(state.get("path"))
            if ok_state and isinstance(state, dict)
            else "configuração inválida"
        )
        if ok_state and state.get("source") == "default":
            self._cw(
                "[b]Restaurar workspace padrão[/b]\n\n"
                "[dim]O workspace padrão já está ativo.[/dim]\n\n"
                f"{default_path}"
            )
            return

        def _apply(confirmed: bool) -> None:
            if not confirmed:
                self._cw("[dim]Restauração do workspace cancelada.[/dim]")
                return
            if self._workspace_directory_change_blocked():
                return
            ok_reset, result = _workspace.reset_workspace_dir()
            if not ok_reset:
                self._cw(
                    "[b]Restaurar workspace padrão[/b]\n\n"
                    f"[red]Falha ao restaurar:[/red] {result}"
                )
                return
            self._refresh_paths_panel()
            self._cw(
                "[green]Workspace padrão restaurado.[/green]\n\n"
                f"[b]Ativo:[/b] {result.get('path')}\n\n"
                "[dim]Nenhum projeto foi movido, copiado ou excluído.[/dim]"
            )

        _confirmar(
            self,
            "Restaurar workspace padrão",
            "Confirme a restauração global:\n\n"
            f"Atual:\n  {current_path}\n\n"
            f"Padrão:\n  {default_path}\n\n"
            "Consequências:\n"
            "  • projetos do diretório atual permanecerão onde estão;\n"
            "  • Abrir projeto voltará a listar o diretório padrão;\n"
            "  • novos projetos serão criados no diretório padrão;\n"
            "  • nenhum projeto será apagado.",
            _apply,
        )

    def _action_workspace_status(self) -> str:
        """Workspace > Estado atual."""
        from pathlib import Path

        ok_ws, ws_state = _workspace.get_workspace_state()
        ws_dir = Path(ws_state.get("path")) if ok_ws else None
        recentes = _session.get_recentes()

        linhas = ["[b]Workspace[/b]\n"]
        if ok_ws:
            source = "padrão" if ws_state.get("source") == "default" else "usuário"
            linhas.append(
                f"[b]Diretório ativo:[/b] {ws_state.get('path')} "
                f"[dim]({source})[/dim]"
            )
            if not ws_state.get("usable"):
                linhas.append(
                    f"[red]Workspace indisponível:[/red] {ws_state.get('error')}"
                )
            linhas.append("")
        else:
            linhas.append(f"[red]Configuração de workspace inválida:[/red] {ws_state}\n")
        if self._projeto_ativo:
            nome = Path(self._projeto_ativo).name
            ok, cfg = _project_config.read(self._projeto_ativo)
            idf = cfg.get("idf_version", "?") if ok else "?"
            linhas.append(f"[b]Projeto ativo:[/b] [green]{nome}[/green]  ESP-IDF {idf}")
            linhas.append(f"  [dim]{self._projeto_ativo}[/dim]\n")
        else:
            linhas.append("[dim]Nenhum projeto ativo.[/dim]\n")

        if recentes:
            linhas.append("[b]Recentes:[/b]")
            for i, caminho in enumerate(recentes, start=1):
                nome = Path(caminho).name
                ativo = " [green][ativo][/green]" if caminho == self._projeto_ativo else ""
                linhas.append(f"  {i}. [b]{nome}[/b]{ativo}")
                linhas.append(f"     [dim]{caminho}[/dim]")
        else:
            linhas.append("[dim]Nenhum projeto recente.[/dim]")

        if ws_dir is not None and ok_ws and ws_state.get("usable"):
            linhas.append(f"\n[b]Projetos em {ws_dir}:[/b]")
            try:
                projetos = sorted([
                    p for p in ws_dir.iterdir()
                    if p.is_dir() and (p / "project_config.json").is_file()
                ], key=lambda p: p.name)
                if projetos:
                    for p in projetos:
                        ok, cfg = _project_config.read(p)
                        idf = cfg.get("idf_version", "?") if ok else "?"
                        ativo = " [green][ativo][/green]" if str(p) == self._projeto_ativo else ""
                        linhas.append(f"  [b]{p.name}[/b]  ESP-IDF {idf}{ativo}")
                else:
                    linhas.append("  [dim]Nenhum projeto encontrado.[/dim]")
            except Exception as e:
                linhas.append(f"  [red]Erro ao listar workspace: {e}[/red]")
        else:
            linhas.append("\n[red]Listagem de projetos bloqueada até corrigir o workspace.[/red]")

        return "\n".join(linhas)

    def _action_workspace_abrir(self) -> None:
        """Workspace > Abrir projeto: lista projetos e abre pelo numero."""
        from pathlib import Path

        ok_ws, ws_result = _workspace.get_workspace_dir()
        if not ok_ws:
            self.call_from_thread(
                self._cw,
                "[b]Abrir projeto[/b]\n\n"
                f"[red]Workspace indisponível:[/red] {ws_result}",
            )
            return
        ws_dir = ws_result
        try:
            projetos = sorted([
                p for p in Path(ws_dir).iterdir()
                if p.is_dir() and (p / "project_config.json").is_file()
            ], key=lambda p: p.name)
        except Exception as e:
            self.call_from_thread(self._cw, f"[red]Erro ao listar workspace: {e}[/red]"
            )
            return

        if not projetos:
            self.call_from_thread(self._cw, "[b]Abrir projeto[/b]\n\n"
                "[dim]Nenhum projeto encontrado em:[/dim]\n"
                f"  {ws_dir}\n\n"
                "[dim]Use 'Novo projeto' para criar o primeiro.[/dim]"
            )
            return

        linhas_lista = []
        for i, p in enumerate(projetos, start=1):
            ok, cfg = _project_config.read(p)
            idf = cfg.get("idf_version", "?") if ok else "?"
            ativo = " [green][ativo][/green]" if str(p) == self._projeto_ativo else ""
            linhas_lista.append(f"  [b]{i}[/b]. {p.name}  [dim]ESP-IDF {idf}[/dim]{ativo}")

        def _preview(valor: str) -> str:
            """Mostra o caminho absoluto do projeto atualmente digitado."""
            valor = valor.strip()
            if not valor:
                return "[dim]Digite o numero de um projeto.[/dim]"
            try:
                idx = int(valor) - 1
                if idx < 0 or idx >= len(projetos):
                    raise ValueError
            except ValueError:
                return "[dim]Numero invalido.[/dim]"
            return f"[dim]{projetos[idx]}[/dim]"

        def _abrir(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Abertura cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(projetos):
                    raise ValueError
            except ValueError:
                self._cw(
                    f"[red]Numero invalido:[/red] '{valor}' "
                    f"— escolha entre 1 e {len(projetos)}"
                )
                return
            caminho = str(projetos[idx])
            self._set_projeto_ativo(caminho)
            nome = projetos[idx].name
            self._cw(
                f"[green]Projeto aberto:[/green] [b]{nome}[/b]\n\n"
                f"[dim]{caminho}[/dim]"
            )

        self.call_from_thread(
            _pedir_input,
            self,
            "Abrir projeto",
            f"Digite o numero do projeto (1-{len(projetos)}):",
            _abrir,
            "1",
            lista=linhas_lista,
            on_change=_preview,
        )

    def _action_workspace_novo(self) -> None:
        """Workspace > Novo projeto: pede nome e versao IDF, cria projeto."""
        content = self._content()
        ok_ws, ws_result = _workspace.get_workspace_dir()
        if not ok_ws:
            self._cw(
                "[b]Novo projeto[/b]\n\n"
                f"[red]Workspace indisponível:[/red] {ws_result}"
            )
            return
        ws_dir = ws_result

        def _preview_nome(valor: str) -> str:
            """Mostra o caminho onde o projeto sera criado, ao vivo."""
            valor = valor.strip()
            return f"[dim]{ws_dir}/{valor}[/dim]"

        def _pedir_nome(nome: str | None) -> None:
            if nome is None:
                self._cw("[dim]Criacao cancelada.[/dim]")
                return
            nome = nome.strip()
            if not nome:
                self._cw("[red]Nome invalido.[/red]")
                return

            caminho_final = ws_dir / nome

            def _pedir_idf(idf: str | None) -> None:
                if idf is None:
                    self._cw("[dim]Criacao cancelada.[/dim]")
                    return
                idf = idf.strip()
                if not idf:
                    self._cw("[red]Versao IDF invalida.[/red]")
                    return
                ok, res = _workspace.new(ws_dir, nome, idf)
                if not ok:
                    self._cw(f"[red]Erro ao criar projeto:[/red] {res}")
                    return
                caminho = res["project_dir"]
                self._set_projeto_ativo(caminho)
                self._cw(
                    f"[green]Projeto criado:[/green] [b]{nome}[/b]\n\n"
                    f"[dim]{caminho}[/dim]\n\n"
                    f"ESP-IDF: {idf}"
                )

            ok2, ativo = _idf_mgr.active_tag()
            placeholder_idf = ativo if (ok2 and ativo) else "v5.4.4"

            _pedir_input(
                self,
                "Novo projeto",
                "Versao do ESP-IDF:",
                _pedir_idf,
                placeholder=placeholder_idf,
                lista=[f"[dim]{caminho_final}[/dim]"],
            )

        _pedir_input(
            self,
            "Novo projeto",
            "Nome do projeto:",
            _pedir_nome,
            placeholder="meu_projeto",
            on_change=_preview_nome,
        )


    def _action_workspace_fechar(self) -> None:
        """
        Fecha o projeto com proteção de Flash e liberação confirmada da porta.
        """
        if not self._projeto_ativo:
            self._cw("[dim]Nenhum projeto ativo para fechar.[/dim]")
            return
        if self._flash_em_andamento:
            self._cw(
                "[b]Fechar projeto[/b]\n\n"
                "[red]Fechamento bloqueado: existe um Flash em andamento.[/red]\n\n"
                "[dim]Aguarde a gravação terminar ou conclua o cancelamento. "
                "Nenhum estado foi alterado.[/dim]"
            )
            return

        from pathlib import Path
        caminho = self._projeto_ativo
        nome = Path(caminho).name
        monitor_ativo = self._monitor is not None

        def _close(confirmed: bool) -> None:
            if not confirmed:
                self._cw("[dim]Fechamento cancelado.[/dim]")
                return

            # Segunda guarda dentro do callback evita fechar caso o estado
            # tenha mudado entre a abertura e a confirmação do modal.
            ok_guard, guard = _workspace.close_project({
                "flash_in_progress": self._flash_em_andamento,
                "monitor_connected": self._monitor is not None,
            })
            if not ok_guard:
                self._cw(
                    "[b]Fechar projeto[/b]\n\n"
                    f"[red]Fechamento bloqueado:[/red] {guard}\n\n"
                    "[dim]Nenhum estado foi alterado.[/dim]"
                )
                return

            ok_monitor, monitor_result = self._stop_monitor_runtime()
            if not ok_monitor:
                self._cw(
                    "[b]Fechar projeto[/b]\n\n"
                    f"[red]O monitor não pôde ser encerrado:[/red] "
                    f"{monitor_result}\n\n"
                    "[dim]O projeto permanece aberto para evitar perder o "
                    "contexto enquanto a porta pode estar ocupada.[/dim]"
                )
                return

            ok_session, session_result = _session.clear_projeto_ativo()
            if not ok_session:
                self._cw(
                    "[b]Fechar projeto[/b]\n\n"
                    "[red]Falha ao limpar a sessão persistente.[/red]\n"
                    f"{session_result}\n\n"
                    "[yellow]O monitor já foi encerrado e a porta liberada, "
                    "mas o projeto permanece aberto nesta execução.[/yellow]"
                )
                return

            self._projeto_ativo = None
            self._clear_runtime_hardware(scan_performed=False)
            self._stack = [MENU_TREE]
            self._render_menu()
            self.sub_title = f"v{_version.get_version()}"

            detalhes = []
            if monitor_result.get("monitor_stopped"):
                detalhes.append("monitor encerrado")
            if monitor_result.get("log_closed"):
                detalhes.append("log fechado")
            if monitor_result.get("port_released"):
                detalhes.append("porta liberada")
            resumo = ", ".join(detalhes) or "recursos já estavam livres"

            self._cw(
                f"[green]✔ Projeto fechado:[/green] [b]{nome}[/b]\n\n"
                f"[dim]{caminho}[/dim]\n\n"
                f"[green]✔ {resumo}.[/green]\n"
                "[dim]Nenhum arquivo do projeto foi apagado.[/dim]"
            )

        aviso_monitor = (
            "\n[yellow]O monitor ativo será encerrado e a porta serial "
            "será liberada.[/yellow]"
            if monitor_ativo else
            "\n[dim]Não há monitor ativo; a seleção de porta será descartada.[/dim]"
        )
        _confirmar(
            self,
            titulo="Fechar projeto",
            mensagem=(
                f"Fechar o projeto ativo?\n\n"
                f"[b]{nome}[/b]\n"
                f"[dim]{caminho}[/dim]\n"
                f"{aviso_monitor}\n\n"
                "Consequências:\n"
                "• o monitor e o log desta execução serão encerrados;\n"
                "• a porta e o contexto de hardware serão liberados;\n"
                "• a aplicação voltará ao menu principal;\n"
                "• nenhum arquivo ou perfil será apagado.\n\n"
                "Confirma?"
            ),
            on_confirm=_close,
        )


    def _set_projeto_ativo(self, caminho: str) -> None:
        """Ativa o projeto e exige nova verificação de hardware ao vivo."""
        from pathlib import Path
        self._projeto_ativo = caminho
        _session.set_projeto_ativo(caminho)
        self._clear_runtime_hardware(scan_performed=False)
        nome = Path(caminho).name
        self.sub_title = f"v{_version.get_version()} — {nome}"
        self._refresh_hardware_panel()
    # ==================================================================
    # ===  [EDIT] EDITORES DE TERMINAL
    # ===  menu: Software > Editores
    # ===  usa: _external_editor
    # ==================================================================


    # ------------------------------------------------------------------
    # Software > Editores de terminal
    # ------------------------------------------------------------------

    def _action_editor_status(self) -> str:
        """Software > Editores de terminal > Estado dos editores."""
        linhas = ["[b]Editores de terminal[/b]\n"]

        try:
            ok, info = _external_editor.active_editor_info()
        except Exception as exc:
            return f"[red]Erro ao consultar editor ativo:[/red] {exc}"

        linhas.append("[b]Editor ativo[/b]")
        if ok and info:
            linhas.append(
                f"  {info.get('label', '?')} {info.get('version', '')} "
                f"({info.get('origin', '?')})"
            )
            linhas.append(f"  [dim]{info.get('path', '')}[/dim]")
        else:
            linhas.append("  [yellow]Nenhum editor ativo detectado.[/yellow]")

        linhas.append("")
        linhas.append("[b]Editores detectados[/b]")
        try:
            ok2, editores = _external_editor.detect_editors()
        except Exception as exc:
            ok2, editores = False, str(exc)

        if ok2 and editores:
            for e in editores:
                label = e.get("label", "?")
                origem = e.get("origin", "sistema")
                path = e.get("path", e.get("bin", ""))
                linhas.append(f"  {label} ({origem})")
                linhas.append(f"    [dim]{path}[/dim]")
        else:
            linhas.append("  [dim]Nenhum editor detectado.[/dim]")

        linhas.append("")
        linhas.append("[b]Internos do ESP Lab[/b]")
        linhas.append("  Nano   instalavel agora")
        linhas.append("  Micro  planejado")
        linhas.append("  Helix  planejado")

        return "\n".join(linhas)

    def _action_editor_install(self) -> None:
        """Software > Editores de terminal > Instalar editor interno."""
        try:
            ok, editores = _external_editor.list_installable_editors()
        except Exception as exc:
            self.call_from_thread(
                self._cw,
                f"[red]Erro ao listar editores instalaveis:[/red] {exc}",
            )
            return

        if not ok:
            self.call_from_thread(
                self._cw,
                f"[red]Erro ao listar editores instalaveis:[/red] {editores}",
            )
            return

        linhas_lista = ["[b]Editores internos instalaveis:[/b]\n"]
        for i, item in enumerate(editores, start=1):
            estado = "[green]instalado[/green]" if item.get("installed") else "nao instalado"
            linhas_lista.append(f"  [b]{i}[/b]. {item['label']} — {estado}")

        def _preview(valor: str) -> str:
            valor = valor.strip()
            if not valor:
                return "[dim]Digite o numero do editor.[/dim]"
            try:
                idx = int(valor) - 1
                if idx < 0 or idx >= len(editores):
                    raise ValueError
            except ValueError:
                return "[dim]Numero invalido.[/dim]"

            item = editores[idx]
            return (
                f"[dim]Selecionado: {item['label']} "
                f"(pacote: {item['package']}, binario: {item['binary']}).[/dim]"
            )

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return

            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(editores):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(editores)}")
                return

            item = editores[idx]
            editor_id = item["id"]
            label = item["label"]

            def _confirmar_instalacao(confirmado: bool) -> None:
                if not confirmado:
                    self._cw("[dim]Instalacao cancelada.[/dim]")
                    return
                self._start_operation(f"Instalacao do editor {label}")
                self._run_bundle_editor_worker(editor_id, label)

            _confirmar(
                self,
                titulo=f"Instalar {label}",
                mensagem=(
                    f"Instalar {label} dentro do ambiente do ESP Lab?\n\n"
                    "Esta operacao pode usar rede e gravar arquivos em:\n"
                    "[dim]data/app-venv/bin[/dim]\n\n"
                    "Nada sera instalado no sistema e nao precisa de sudo.\n\n"
                    "Confirma?"
                ),
                on_confirm=_confirmar_instalacao,
            )

        self.call_from_thread(
            _pedir_input,
            self,
            "Instalar editor interno",
            f"Digite o numero do editor (1-{len(editores)}):",
            _escolher,
            "1",
            lista=linhas_lista,
            on_change=_preview,
        )

    @work(thread=True)
    def _run_bundle_editor_worker(self, editor_id: str, label: str) -> None:
        """Instala editor interno fixo: nano ou micro."""
        try:
            linhas: list[str] = [f"[b]Instalando {label} no ambiente...[/b]\n"]
            self.call_from_thread(self._cw, "\n".join(linhas))

            def _progresso(_tipo: str, linha: str) -> None:
                linhas.append(f"[dim]{linha}[/dim]")
                self.call_from_thread(self._cw, "\n".join(linhas))

            ok, res = _external_editor.install_editor(
                editor_id,
                progress_cb=_progresso,
                set_as_default=True,
            )

            if ok:
                self.call_from_thread(
                    self._cw,
                    "\n".join(linhas)
                    + "\n\n"
                    + f"[green]✔ {label} instalado em:[/green]\n"
                    + f"[dim]{res['path']}[/dim]\n\n"
                    + "[dim]Ele foi salvo como editor padrao do ESP Lab.[/dim]",
                )
            else:
                self.call_from_thread(
                    self._cw,
                    "\n".join(linhas)
                    + "\n\n"
                    + f"[red]✘ Falha ao instalar {label}:[/red] {res}",
                )
        finally:
            self._finish_operation()


    def _action_editor_choose(self) -> None:
        """Software > Editores de terminal > Escolher editor padrao."""
        try:
            ok, editores = _external_editor.detect_editors()
        except Exception as exc:
            self._cw(f"[red]Erro ao detectar editores:[/red] {exc}")
            return None

        if not ok:
            self._cw(f"[red]Erro ao detectar editores:[/red] {editores}")
            return None

        if not editores:
            self._cw(
                "[yellow]Nenhum editor de terminal detectado.[/yellow]\n\n"
                "[dim]Use Software > Editores de terminal > Instalar editor interno.[/dim]"
            )
            return None

        linhas_lista = ["[b]Editores detectados:[/b]\n"]
        for i, item in enumerate(editores, start=1):
            label = item.get("label") or item.get("id") or item.get("bin") or "editor"
            path = item.get("path") or item.get("bin") or ""
            origin = item.get("origin") or "origem desconhecida"
            linhas_lista.append(f"  [b]{i}[/b]. {label} — {origin}")
            if path:
                linhas_lista.append(f"      [dim]{path}[/dim]")

        ok_ativo, ativo = _external_editor.active_editor_info()
        if ok_ativo and ativo:
            linhas_lista.append("")
            linhas_lista.append(
                "[dim]Atual: {} — {}[/dim]".format(
                    ativo.get("label", "editor"),
                    ativo.get("origin", "origem desconhecida"),
                )
            )

        def _preview(valor: str) -> str:
            valor = valor.strip()
            if not valor:
                return "[dim]Digite o numero do editor.[/dim]"
            try:
                idx = int(valor) - 1
                if idx < 0 or idx >= len(editores):
                    raise ValueError
            except ValueError:
                return "[dim]Numero invalido.[/dim]"

            item = editores[idx]
            label = item.get("label") or item.get("id") or item.get("bin") or "editor"
            origin = item.get("origin") or "origem desconhecida"
            path = item.get("path") or item.get("bin") or ""
            return f"[dim]Selecionado: {label} — {origin} — {path}[/dim]"

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return

            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(editores):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(editores)}")
                return

            item = editores[idx]
            editor_id = item.get("id") or item.get("bin")
            label = item.get("label") or editor_id or "editor"
            origin = item.get("origin") or ""
            prefer_internal = origin == "ambiente ESP Lab"

            if not editor_id:
                self._cw("[red]Editor selecionado nao possui id/bin valido.[/red]")
                return

            ok2, res = _external_editor.set_preferred_editor(
                editor_id,
                prefer_internal=prefer_internal,
            )

            if not ok2:
                self._cw(f"[red]Falha ao ativar editor padrao:[/red] {res}")
                return

            aviso_validacao = ""
            try:
                okv, validacao = _external_editor.validate_active_editor()
                if not okv:
                    aviso_validacao = (
                        "\n\n[yellow]Aviso:[/yellow] a preferência foi salva, "
                        f"mas a validação retornou: {validacao}"
                    )
            except Exception as exc:
                aviso_validacao = (
                    "\n\n[yellow]Aviso:[/yellow] a preferência foi salva, "
                    f"mas a validação silenciosa falhou: {exc}"
                )

            self._cw(
                f"[green]✔ Editor padrao ativado:[/green] {label}\n"
                f"[dim]Origem: {origin or 'origem desconhecida'}[/dim]"
                f"{aviso_validacao}"
            )

        _pedir_input(
            self,
            "Escolher editor padrao",
            f"Digite o numero do editor (1-{len(editores)}):",
            _escolher,
            "1",
            lista=linhas_lista,
            on_change=_preview,
        )

        return None


    def _action_editor_remove(self) -> None:
        """Software > Editores de terminal > Remover editor interno."""
        try:
            ok, detectados = _external_editor.detect_editors()
        except Exception as exc:
            self._cw(f"[red]Erro ao detectar editores:[/red] {exc}")
            return None

        if not ok:
            self._cw(f"[red]Erro ao detectar editores:[/red] {detectados}")
            return None

        internos = []
        vistos = set()
        for item in detectados:
            editor_id = item.get("id") or item.get("bin")
            origin = item.get("origin") or ""
            path = item.get("path") or item.get("bin") or ""

            if editor_id not in {"nano", "micro"}:
                continue
            if origin != "ambiente ESP Lab":
                continue
            if not path:
                continue
            if editor_id in vistos:
                continue

            vistos.add(editor_id)
            internos.append(item)

        if not internos:
            self._cw(
                "[yellow]Nenhum editor interno instalado para remover.[/yellow]\n\n"
                "[dim]Somente editores em data/app-venv/bin podem ser removidos por este menu.[/dim]"
            )
            return None

        linhas_lista = ["[b]Editores internos instalados:[/b]\n"]
        for i, item in enumerate(internos, start=1):
            label = item.get("label") or item.get("id") or item.get("bin") or "editor"
            path = item.get("path") or item.get("bin") or ""
            linhas_lista.append(f"  [b]{i}[/b]. {label}")
            linhas_lista.append(f"      [dim]{path}[/dim]")

        def _preview(valor: str) -> str:
            valor = valor.strip()
            if not valor:
                return "[dim]Digite o numero do editor que deseja remover.[/dim]"
            try:
                idx = int(valor) - 1
                if idx < 0 or idx >= len(internos):
                    raise ValueError
            except ValueError:
                return "[dim]Numero invalido.[/dim]"

            item = internos[idx]
            label = item.get("label") or item.get("id") or item.get("bin") or "editor"
            path = item.get("path") or item.get("bin") or ""
            return f"[dim]Remover: {label} — {path}[/dim]"

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return

            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(internos):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(internos)}")
                return

            item = internos[idx]
            editor_id = item.get("id") or item.get("bin")
            label = item.get("label") or editor_id or "editor"
            path = item.get("path") or item.get("bin") or ""

            def _confirmar_remocao(confirmado: bool) -> None:
                if not confirmado:
                    self._cw("[dim]Remocao cancelada.[/dim]")
                    return

                self._start_operation(f"Remocao do editor {label}")
                self._run_remove_editor_worker(editor_id, label, path)

            _confirmar(
                self,
                titulo=f"Remover {label}",
                mensagem=(
                    f"Remover {label} do ambiente interno do ESP Lab?\n\n"
                    f"[dim]{path}[/dim]\n\n"
                    "Esta operacao remove apenas o binario interno em data/app-venv/bin.\n"
                    "Nao remove pacotes do sistema.\n\n"
                    "Confirma?"
                ),
                on_confirm=_confirmar_remocao,
            )

        _pedir_input(
            self,
            "Remover editor interno",
            f"Digite o numero do editor (1-{len(internos)}):",
            _escolher,
            "1",
            lista=linhas_lista,
            on_change=_preview,
        )

        return None

    @work(thread=True)
    def _run_remove_editor_worker(self, editor_id: str, label: str, path: str) -> None:
        """Remove editor interno com andamento visual."""
        import time as _time
        from pathlib import Path as _Path

        linhas: list[str] = [f"[b]Removendo {label} do ambiente interno...[/b]\n"]

        def _render(linha: str) -> None:
            linhas.append(linha)
            self.call_from_thread(self._cw, "\n".join(linhas))

        try:
            _render("[dim]1/4 Validando caminho interno...[/dim]")
            _time.sleep(0.12)

            try:
                from ..core import paths as _paths

                alvo = _Path(path).expanduser().resolve()
                interno_bin = (_paths.get_paths().app_venv / "bin").resolve()

                try:
                    alvo.relative_to(interno_bin)
                except ValueError:
                    self.call_from_thread(
                        self._cw,
                        "\n".join(linhas)
                        + "\n\n"
                        + "[red]Remocao bloqueada por seguranca.[/red]\n"
                        + f"[dim]Caminho fora do ambiente interno: {alvo}[/dim]",
                    )
                    return

                if not alvo.is_file():
                    self.call_from_thread(
                        self._cw,
                        "\n".join(linhas)
                        + "\n\n"
                        + f"[yellow]Arquivo nao encontrado:[/yellow] {alvo}",
                    )
                    return

                _render(f"[dim]2/4 Removendo binario: {alvo}[/dim]")
                _time.sleep(0.12)
                alvo.unlink()

                _render("[dim]3/4 Verificando preferencia salva...[/dim]")
                _time.sleep(0.12)

                pref_msg = ""
                try:
                    ok_pref, pref = _external_editor.get_preferred_editor()
                    if ok_pref and isinstance(pref, dict) and pref.get("id") == editor_id:
                        ok_clear, clear_res = _external_editor.clear_preferred_editor()
                        if ok_clear:
                            pref_msg = "\n[dim]Preferencia limpa: apontava para esse editor.[/dim]"
                        else:
                            pref_msg = f"\n[yellow]Aviso:[/yellow] nao foi possivel limpar preferencia: {clear_res}"
                except Exception as exc:
                    pref_msg = f"\n[yellow]Aviso:[/yellow] falha ao verificar preferencia: {exc}"

                _render("[dim]4/4 Redetectando editores disponiveis...[/dim]")
                _time.sleep(0.12)

                ok_detect, detectados = _external_editor.detect_editors()
                if ok_detect:
                    restantes = [
                        e.get("label") or e.get("id") or e.get("bin") or "editor"
                        for e in detectados
                    ]
                    if restantes:
                        restante_msg = "\n[dim]Editores restantes: {}[/dim]".format(
                            ", ".join(restantes)
                        )
                    else:
                        restante_msg = "\n[dim]Nenhum editor detectado apos a remocao.[/dim]"
                else:
                    restante_msg = f"\n[yellow]Aviso:[/yellow] falha ao redetectar editores: {detectados}"

                self.call_from_thread(
                    self._cw,
                    "\n".join(linhas)
                    + "\n\n"
                    + f"[green]✔ Editor removido:[/green] {label}\n"
                    + f"[dim]{alvo}[/dim]"
                    + pref_msg
                    + restante_msg,
                )

            except Exception as exc:
                self.call_from_thread(
                    self._cw,
                    "\n".join(linhas)
                    + "\n\n"
                    + f"[red]Erro ao remover editor:[/red] {exc}",
                )
        finally:
            self._finish_operation()


    def _action_editor_validate(self) -> str:
        """Software > Editores de terminal > Validar editor ativo."""
        try:
            ok, info = _external_editor.active_editor_info()
        except Exception as exc:
            return f"[red]Erro ao validar editor:[/red] {exc}"

        if not ok or not info:
            return (
                "[red]Nenhum editor ativo valido.[/red]\n\n"
                "[dim]Use Software > Editores de terminal > Instalar editor interno.[/dim]"
            )

        from pathlib import Path
        path = Path(info.get("path", ""))
        if not path.is_file():
            return (
                "[red]Editor ativo aponta para caminho inexistente.[/red]\n\n"
                f"[dim]{path}[/dim]"
            )

        return (
            "[green]✔ Editor ativo valido.[/green]\n\n"
            f"[b]Editor[/b]   {info.get('label', '?')} {info.get('version', '')}\n"
            f"[b]Origem[/b]   {info.get('origin', '?')}\n"
            f"[b]Caminho[/b]  [dim]{path}[/dim]"
        )


    # ------------------------------------------------------------------
    # Arquivos do projeto (@E8-T8.1 explorador + @E8-T8.2 editor externo)
    # ------------------------------------------------------------------

    def _primeiro_editor_externo(self):
        """
        Devolve o editor de terminal ativo, respeitando a preferencia
        salva em Software > Editores de terminal.
        """
        ok, editor = _external_editor.active_editor()
        if not ok or not editor:
            return None
        return editor
    # ==================================================================
    # ===  [FILES] ARQUIVOS DO PROJETO
    # ===  menu: Programacao > Arquivos
    # ===  usa: _external_editor, _file_explorer
    # ==================================================================



    def _action_files_list(self) -> str:
        """Programacao > Arquivos do projeto > Listar arquivos."""
        if not self._projeto_ativo:
            return self._msg_sem_projeto()
        ok, items = _file_explorer.list_tree(self._projeto_ativo)
        if not ok:
            return f"[red]Erro ao listar arquivos:[/red] {items}"
        from pathlib import Path
        nome_projeto = Path(self._projeto_ativo).name
        arvore = _render_file_tree(items, nome_projeto)
        if not items:
            return f"[b]Arquivos do projeto[/b]\n\n{arvore}"
        return f"[b]Arquivos do projeto[/b]\n\n{arvore}\n\n[dim]{len(items)} item(ns).[/dim]"

    def _action_files_create_file(self) -> None:
        """Programacao > Arquivos do projeto > Criar arquivo."""
        if not self._projeto_ativo:
            self._cw(self._msg_sem_projeto())
            return
        projeto = self._projeto_ativo

        def _criar(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Criacao cancelada.[/dim]")
                return
            ok, res = _file_explorer.create_file(projeto, valor.strip())
            if ok:
                self._cw(f"[green]✔ Arquivo criado:[/green] {res}")
            else:
                self._cw(f"[red]✘ Falha ao criar arquivo:[/red] {res}")

        _pedir_input(
            self,
            "Criar arquivo",
            "Nome do novo arquivo (criado na raiz do projeto):",
            _criar,
            placeholder="novo_arquivo.c",
            lista=[f"[dim]{projeto}/[/dim]"],
        )

    def _action_files_create_dir(self) -> None:
        """Programacao > Arquivos do projeto > Criar pasta."""
        if not self._projeto_ativo:
            self._cw(self._msg_sem_projeto())
            return
        projeto = self._projeto_ativo

        def _criar(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Criacao cancelada.[/dim]")
                return
            ok, res = _file_explorer.create_dir(projeto, valor.strip())
            if ok:
                self._cw(f"[green]✔ Pasta criada:[/green] {res}")
            else:
                self._cw(f"[red]✘ Falha ao criar pasta:[/red] {res}")

        _pedir_input(
            self,
            "Criar pasta",
            "Nome da nova pasta (criada na raiz do projeto):",
            _criar,
            placeholder="nova_pasta",
            lista=[f"[dim]{projeto}/[/dim]"],
        )

    def _action_files_rename(self) -> None:
        """Programacao > Arquivos do projeto > Renomear."""
        if not self._projeto_ativo:
            self.call_from_thread(self._cw, self._msg_sem_projeto())
            return
        projeto = self._projeto_ativo
        ok, items = _file_explorer.list_tree(projeto)
        if not ok:
            self.call_from_thread(self._cw, f"[red]Erro ao listar arquivos:[/red] {items}")
            return
        if not items:
            self.call_from_thread(self._cw, "[dim]Projeto vazio — nada para renomear.[/dim]")
            return

        linhas_lista = [
            f"  [b]{i}[/b]. {'[D]' if it['type'] == 'dir' else '[F]'} {it['relative']}"
            for i, it in enumerate(items, start=1)
        ]

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(items):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(items)}")
                return
            alvo = items[idx]["relative"]

            def _novo_nome(nome: str | None) -> None:
                if nome is None:
                    self._cw("[dim]Renomeacao cancelada.[/dim]")
                    return
                ok2, res = _file_explorer.rename(projeto, alvo, nome.strip())
                if ok2:
                    self._cw(f"[green]✔ Renomeado para:[/green] {res}")
                else:
                    self._cw(f"[red]✘ Falha ao renomear:[/red] {res}")

            _pedir_input(self, "Renomear", f"Novo nome para '{alvo}':", _novo_nome)

        self.call_from_thread(
            _pedir_input, self,
            "Renomear",
            f"Digite o numero do item (1-{len(items)}):",
            _escolher, "1",
            lista=linhas_lista)

    def _action_files_move(self) -> None:
        """Programacao > Arquivos do projeto > Mover."""
        if not self._projeto_ativo:
            self.call_from_thread(self._cw, self._msg_sem_projeto())
            return
        projeto = self._projeto_ativo
        ok, items = _file_explorer.list_tree(projeto)
        if not ok:
            self.call_from_thread(self._cw, f"[red]Erro ao listar arquivos:[/red] {items}")
            return
        if not items:
            self.call_from_thread(self._cw, "[dim]Projeto vazio — nada para mover.[/dim]")
            return

        dirs = [it for it in items if it["type"] == "dir"]
        # Raiz do projeto sempre disponivel como destino, mesmo sem subpastas.
        destinos = [{"relative": ".", "label": "(raiz do projeto)"}] + [
            {"relative": d["relative"], "label": d["relative"]} for d in dirs
        ]

        linhas_origem = [
            f"  [b]{i}[/b]. {'[D]' if it['type'] == 'dir' else '[F]'} {it['relative']}"
            for i, it in enumerate(items, start=1)
        ]

        def _escolher_origem(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(items):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(items)}")
                return
            origem = items[idx]["relative"]

            linhas_destino = [
                f"  [b]{i}[/b]. {d['label']}" for i, d in enumerate(destinos, start=1)
            ]

            def _escolher_destino(valor2: str | None) -> None:
                if valor2 is None:
                    self._cw("[dim]Operacao cancelada.[/dim]")
                    return
                try:
                    idx2 = int(valor2.strip()) - 1
                    if idx2 < 0 or idx2 >= len(destinos):
                        raise ValueError
                except ValueError:
                    self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(destinos)}")
                    return
                destino = destinos[idx2]["relative"]
                ok2, res = _file_explorer.move(projeto, origem, destino)
                if ok2:
                    self._cw(f"[green]✔ Movido para:[/green] {res}")
                else:
                    self._cw(f"[red]✘ Falha ao mover:[/red] {res}")

            _pedir_input(
                self, "Mover — destino",
                f"Mover '{origem}' para qual pasta? (1-{len(destinos)}):",
                _escolher_destino, "1", lista=linhas_destino)

        self.call_from_thread(
            _pedir_input, self,
            "Mover — origem",
            f"Digite o numero do item a mover (1-{len(items)}):",
            _escolher_origem, "1",
            lista=linhas_origem)

    def _action_files_delete(self) -> None:
        """Programacao > Arquivos do projeto > Excluir."""
        if not self._projeto_ativo:
            self.call_from_thread(self._cw, self._msg_sem_projeto())
            return
        projeto = self._projeto_ativo
        ok, items = _file_explorer.list_tree(projeto)
        if not ok:
            self.call_from_thread(self._cw, f"[red]Erro ao listar arquivos:[/red] {items}")
            return
        if not items:
            self.call_from_thread(self._cw, "[dim]Projeto vazio — nada para excluir.[/dim]")
            return

        linhas_lista = [
            f"  [b]{i}[/b]. {'[D]' if it['type'] == 'dir' else '[F]'} {it['relative']}"
            for i, it in enumerate(items, start=1)
        ]

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(items):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(items)}")
                return
            alvo = items[idx]
            relativo = alvo["relative"]
            tipo = "pasta (com todo o conteudo)" if alvo["type"] == "dir" else "arquivo"

            def _confirmar_delete(confirmado: bool) -> None:
                if not confirmado:
                    self._cw("[dim]Exclusao cancelada.[/dim]")
                    return
                ok2, res = _file_explorer.delete(projeto, relativo, confirm=True)
                if ok2:
                    self._cw(f"[green]✔ {res}[/green]")
                else:
                    self._cw(f"[red]✘ Falha ao excluir:[/red] {res}")

            _confirmar(
                self,
                titulo="Excluir",
                mensagem=(
                    f"Remove {tipo}:\n  {relativo}\n\n"
                    "Esta operacao e irreversivel.\n\n"
                    "Confirma?"
                ),
                on_confirm=_confirmar_delete,
            )

        self.call_from_thread(
            _pedir_input, self,
            "Excluir",
            f"Digite o numero do item a excluir (1-{len(items)}):",
            _escolher, "1",
            lista=linhas_lista)

    def _action_files_open_file(self) -> None:
        """Programacao > Arquivos do projeto > Abrir arquivo no editor."""
        if not self._projeto_ativo:
            self.call_from_thread(self._cw, self._msg_sem_projeto())
            return
        editor = self._primeiro_editor_externo()
        if editor is None:
            self.call_from_thread(self._cw, self._msg_sem_editor())
            return
        projeto = self._projeto_ativo
        ok, items = _file_explorer.list_tree(projeto)
        if not ok:
            self.call_from_thread(self._cw, f"[red]Erro ao listar arquivos:[/red] {items}")
            return
        arquivos = [it for it in items if it["type"] == "file"]
        if not arquivos:
            self.call_from_thread(self._cw, "[dim]Nenhum arquivo no projeto.[/dim]")
            return

        from pathlib import Path
        linhas_lista = [
            f"  [b]{i}[/b]. {it['relative']}"
            for i, it in enumerate(arquivos, start=1)
        ]
        linhas_lista.insert(0, f"[dim]Editor: {editor['label']}[/dim]\n")

        def _preview(valor: str) -> str:
            """Mostra o caminho absoluto do item atualmente digitado."""
            valor = valor.strip()
            if not valor:
                return "[dim]Digite o numero de um arquivo.[/dim]"
            try:
                idx = int(valor) - 1
                if idx < 0 or idx >= len(arquivos):
                    raise ValueError
            except ValueError:
                return "[dim]Numero invalido.[/dim]"
            return f"[dim]{Path(projeto) / arquivos[idx]['relative']}[/dim]"

        def _escolher(valor: str | None) -> None:
            if valor is None:
                self._cw("[dim]Operacao cancelada.[/dim]")
                return
            try:
                idx = int(valor.strip()) - 1
                if idx < 0 or idx >= len(arquivos):
                    raise ValueError
            except ValueError:
                self._cw(f"[red]Numero invalido.[/red] Escolha entre 1 e {len(arquivos)}")
                return
            caminho = str(Path(projeto) / arquivos[idx]["relative"])
            nome_rel = arquivos[idx]["relative"]

            # Editor de terminal (vim/nano/...) disputa a mesma TTY do
            # Textual — precisa suspender o TUI, rodar em primeiro
            # plano e bloqueante, e so entao redesenhar.
            try:
                with self.suspend():
                    ok2, res = _external_editor.run_terminal_editor(
                        caminho, editor)
            except SuspendNotSupported:
                self._cw(
                    "[red]Este terminal nao suporta suspender a "
                    "aplicacao.[/red]\n\n"
                    "[dim]Editores de terminal exigem um TTY real "
                    "(via SSH direto, por exemplo).[/dim]"
                )
                return
            if ok2:
                self._cw(
                    f"[green]✔ Editor fechado:[/green] {editor['label']} "
                    f"— {nome_rel}"
                )
            else:
                self._cw(f"[red]✘ Falha ao abrir editor:[/red] {res}")

        self.call_from_thread(
            _pedir_input, self,
            "Abrir arquivo no editor",
            f"Digite o numero do arquivo (1-{len(arquivos)}):",
            _escolher, "1",
            lista=linhas_lista,
            on_change=_preview)
    # ==================================================================
    # ===  [LIBS] BIBLIOTECAS
    # ===  menu: Programacao > Bibliotecas
    # ===  usa: _cmreq, _idfcomp, _libinsp, _libmgr
    # ==================================================================

    # ---- Bibliotecas (@E8-T8.3/T8.4 na TUI) -----------------------------
    # Reusa library_manager.py (camada de dados: manifesto idf_component.yml
    # em main/ + project_config sincronizado). Sem passo de "instalar"
    # separado -- o Component Manager do ESP-IDF baixa automaticamente no
    # proximo build/reconfigure. Guard: so projeto ativo (bibliotecas nao
    # dependem de Placa/target).

    def _libs_guard(self):
        """Projeto ativo? Retorna Path ou None (com mensagem)."""
        if not self._projeto_ativo:
            self._cw("[b]Bibliotecas[/b]\n\n"
                     "[yellow]Nenhum projeto ativo.[/yellow]\n\n"
                     "[dim]Abra um projeto em Workspace > Abrir projeto.[/dim]")
            return None
        from pathlib import Path
        return Path(self._projeto_ativo)

    def _libs_current_label(self, item: dict) -> str:
        """Rótulo curto de uma dependência do manifesto."""
        name = item.get("name", "-")
        version = item.get("version") or "*"
        source = item.get("source") or "manifesto"
        locked = item.get("locked")
        lock_mark = "[TRAVADA] " if locked else ""
        return f"{lock_mark}{name} ({version}) {source}"

    def _libs_current_detail_text(self, item: dict) -> str:
        """Detalhe legível de uma dependência do manifesto."""
        name = item.get("name", "-")
        version = item.get("version") or "*"
        source = item.get("source") or "-"
        locked = item.get("locked")

        def yn(value: object) -> str:
            return "sim" if bool(value) else "não"

        lines = [
            "[b]Dependência do manifesto[/b]",
            "",
            f"[b]Nome:[/b] {name}",
            f"[b]Versão:[/b] {version}",
            f"[b]Origem:[/b] {source}",
            f"[b]Travada:[/b] {yn(locked)}",
        ]

        for key, label in [
            ("git", "Git"),
            ("path", "Path"),
            ("override_path", "Override path"),
            ("registry_url", "Registry URL"),
            ("public", "Public"),
        ]:
            value = item.get(key)
            if value not in (None, "", []):
                lines.append(f"[b]{label}:[/b] {value}")

        lines.extend([
            "",
            "[dim]Remover, travar e destravar editam apenas "
            "main/idf_component.yml após confirmação. Nenhum idf.py, build "
            "ou reconfigure é executado automaticamente.[/dim]",
        ])

        return "\n".join(lines)

    def _libs_current_entries(self):
        """Lê dependências atuais do manifesto."""
        projeto = self._libs_guard()
        if projeto is None:
            return (False, "nenhum projeto ativo")

        ok, libs = _libmgr.list_libs(projeto)
        if not ok:
            return (False, libs)

        return (True, libs)

    def _libs_current_find(self, encoded_name: str):
        """Encontra dependência pelo nome codificado em action:param."""
        name = self._libs_inspect_decode_rel(encoded_name or "")
        ok, libs = self._libs_current_entries()
        if not ok:
            return (False, libs)

        for item in libs:
            if item.get("name") == name:
                return (True, item)

        return (False, f"dependência não encontrada: {name}")

    def _libs_current_node(self, page: int = 0) -> dict:
        """Monta node paginado das dependências atuais."""
        ok, libs = self._libs_current_entries()
        if not ok:
            self._cw(f"[red]Erro ao listar dependências:[/red] {libs}")
            return {"title": "Dependências atuais", "items": []}

        page_size = 6
        total = len(libs)
        total_pages = max(1, (total + page_size - 1) // page_size)

        try:
            page = int(page)
        except Exception:
            page = 0

        page = max(0, min(page, total_pages - 1))
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, total)

        items = []

        if page > 0:
            items.append({
                "label": "← Página anterior",
                "node": None,
                "action": f"libs_current_page:{page - 1}",
            })

        for item in libs[start_idx:end_idx]:
            name = item.get("name", "")
            enc = self._libs_inspect_encode_rel(name)
            items.append({
                "label": self._libs_current_label(item),
                "node": None,
                "action": f"libs_current_detail:{enc}",
            })

        if end_idx < total:
            items.append({
                "label": "Próxima página →",
                "node": None,
                "action": f"libs_current_page:{page + 1}",
            })

        return {
            "title": f"Dependências atuais ({page + 1}/{total_pages})",
            "items": items,
        }

    def _action_libs_list(self) -> None:
        """Programação > Bibliotecas > Dependências atuais."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        node = self._libs_current_node(0)
        self._stack.append(node)
        self._render_menu()

        ok, req = _libmgr.get_idf_requirement(projeto)
        req_txt = req if ok and req else "(não definido)"

        self._cw(
            "[b]Dependências atuais[/b]\n\n"
            f"[b]Projeto:[/b] {projeto}\n"
            f"[b]Requisito de ESP-IDF:[/b] {req_txt}\n\n"
            "[dim]Selecione uma dependência para ver detalhes e ações. "
            "Nenhuma alteração é feita sem confirmação.[/dim]"
        )

    def _action_libs_current_page(self, page: str) -> None:
        """Troca página do menu de dependências atuais."""
        node = self._libs_current_node(int(page or 0))
        self._stack[-1] = node
        self._render_menu()
        self._cw(
            "[b]Dependências atuais[/b]\n\n"
            "[dim]Selecione uma dependência para ver detalhes e ações.[/dim]"
        )

    def _action_libs_current_detail(self, encoded_name: str) -> None:
        """Abre detalhe/ações de uma dependência do manifesto."""
        ok, item = self._libs_current_find(encoded_name)
        if not ok:
            self._cw(f"[red]Erro:[/red] {item}")
            return

        name = item.get("name", "")
        enc = self._libs_inspect_encode_rel(name)
        locked = bool(item.get("locked"))

        items = [
            {
                "label": "Remover do manifesto",
                "node": None,
                "action": f"libs_current_remove:{enc}",
            }
        ]

        if locked:
            items.append({
                "label": "Destravar versão",
                "node": None,
                "action": f"libs_current_unlock:{enc}",
            })
        else:
            items.append({
                "label": "Travar versão",
                "node": None,
                "action": f"libs_current_lock:{enc}",
            })

        self._stack.append({
            "title": f"Dependência: {name}",
            "items": items,
        })
        self._render_menu()
        self._cw(self._libs_current_detail_text(item))

    def _action_libs_current_remove(self, encoded_name: str) -> None:
        """Confirma e remove dependência do manifesto."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        ok, item = self._libs_current_find(encoded_name)
        if not ok:
            self._cw(f"[red]Erro:[/red] {item}")
            return

        name = item.get("name", "")

        def _confirmar_remocao(confirmado: bool) -> None:
            if not confirmado:
                self._cw("[dim]Remoção cancelada.[/dim]")
                return

            ok2, res2 = _libmgr.remove_lib(projeto, name)
            if not ok2:
                self._cw(f"[red]Falha ao remover:[/red] {res2}")
                return

            self._cw(
                f"[green]✔ Dependência removida:[/green] {name}\n"
                "[dim]Arquivo alterado: main/idf_component.yml[/dim]\n"
                "[dim]Nenhum idf.py, build ou reconfigure foi executado.[/dim]"
            )

        _confirmar(
            self,
            titulo="Remover dependência",
            mensagem=(
                f"Remover '{name}' de main/idf_component.yml?\n\n"
                "Isso não apaga arquivos do projeto e não executa idf.py."
            ),
            on_confirm=_confirmar_remocao,
        )

    def _action_libs_current_lock(self, encoded_name: str) -> None:
        """Pede versão e confirma antes de travar dependência."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        ok, item = self._libs_current_find(encoded_name)
        if not ok:
            self._cw(f"[red]Erro:[/red] {item}")
            return

        name = item.get("name", "")
        atual = item.get("version") or "*"

        def _pedir_confirmacao(version: str | None) -> None:
            version = (version or "").strip()
            if not version:
                self._cw("[red]Versão vazia.[/red]")
                return

            def _confirmar_lock(confirmado: bool) -> None:
                if not confirmado:
                    self._cw("[dim]Travamento cancelado.[/dim]")
                    return

                ok2, res2 = _libmgr.lock_lib(projeto, name, version)
                if not ok2:
                    self._cw(f"[red]Falha ao travar versão:[/red] {res2}")
                    return

                self._cw(
                    f"[green]✔ Versão travada:[/green] {name} -> {version}\n"
                    "[dim]Arquivo alterado: main/idf_component.yml[/dim]\n"
                    "[dim]Nenhum idf.py, build ou reconfigure foi executado.[/dim]"
                )

            _confirmar(
                self,
                titulo="Travar versão",
                mensagem=(
                    f"Travar versão de '{name}'?\n\n"
                    f"Versão atual: {atual}\n"
                    f"Nova versão: {version}\n\n"
                    "Será editado apenas main/idf_component.yml. "
                    "Nenhum idf.py/build será executado."
                ),
                on_confirm=_confirmar_lock,
            )

        _pedir_input(
            self,
            "Travar versão",
            f"Versão para '{name}' (atual: {atual}):",
            _pedir_confirmacao,
            atual if atual != "*" else "",
        )

    def _action_libs_current_unlock(self, encoded_name: str) -> None:
        """Confirma e destrava dependência, voltando versão para '*'."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        ok, item = self._libs_current_find(encoded_name)
        if not ok:
            self._cw(f"[red]Erro:[/red] {item}")
            return

        name = item.get("name", "")

        def _confirmar_unlock(confirmado: bool) -> None:
            if not confirmado:
                self._cw("[dim]Destravamento cancelado.[/dim]")
                return

            ok2, res2 = _libmgr.unlock_lib(projeto, name)
            if not ok2:
                self._cw(f"[red]Falha ao destravar:[/red] {res2}")
                return

            self._cw(
                f"[green]✔ Versão destravada:[/green] {name} -> *\n"
                "[dim]Arquivo alterado: main/idf_component.yml[/dim]\n"
                "[dim]Nenhum idf.py, build ou reconfigure foi executado.[/dim]"
            )

        _confirmar(
            self,
            titulo="Destravar versão",
            mensagem=(
                f"Destravar '{name}' e voltar a versão para '*'?\n\n"
                "Será editado apenas main/idf_component.yml."
            ),
            on_confirm=_confirmar_unlock,
        )

    def _format_idf_component_detail(self, detail: dict) -> str:
        """Formata detalhe de componente interno ESP-IDF."""
        status = detail.get("project_status") or {}
        actions = detail.get("available_actions") or []

        def yn(value: object) -> str:
            return "sim" if bool(value) else "não"

        requires = status.get("requires") or []
        priv_requires = status.get("priv_requires") or []

        lines = [
            "[b]Componente ESP-IDF interno[/b]",
            "",
            f"[b]Nome:[/b] {detail.get('name', '-')}",
            f"[b]Origem:[/b] {detail.get('source', '-')}",
            f"[b]Versão efetiva:[/b] {detail.get('effective_version', '-')}",
            f"[b]Caminho:[/b] {detail.get('path', '-')}",
            "",
            "[b]Estrutura:[/b]",
            f"  CMakeLists.txt: {yn(detail.get('has_cmake'))}",
            f"  idf_component_register(): {yn(detail.get('has_component_register'))}",
            "",
            "[b]Status no projeto:[/b]",
            f"  em REQUIRES: {yn(status.get('in_requires'))}",
            f"  em PRIV_REQUIRES: {yn(status.get('in_priv_requires'))}",
            f"  REQUIRES atual: {', '.join(requires) if requires else '(vazio)'}",
            f"  PRIV_REQUIRES atual: {', '.join(priv_requires) if priv_requires else '(vazio)'}",
            "",
            "[b]Ações disponíveis:[/b] "
            + (", ".join(actions) if actions else "(nenhuma)"),
            "",
            "[dim]Ações de adicionar/remover alteram apenas main/CMakeLists.txt "
            "após confirmação. Nenhum idf.py/build/reconfigure é executado "
            "automaticamente.[/dim]",
        ]
        return "\n".join(lines)

    def _libs_idf_components_page_node(self, page: int) -> dict:
        """Monta node dinâmico paginado de componentes internos ESP-IDF."""
        projeto = self._libs_guard()
        if projeto is None:
            return {"title": "Componentes ESP-IDF internos", "items": []}

        ok, data = _idfcomp.list_idf_components(projeto)
        if not ok:
            self._cw(f"[red]Erro ao listar componentes ESP-IDF:[/red] {data}")
            return {"title": "Componentes ESP-IDF internos", "items": []}

        componentes = data.get("components", [])
        page_size = 6
        total = len(componentes)
        total_pages = max(1, (total + page_size - 1) // page_size)

        try:
            page = int(page)
        except Exception:
            page = 0

        page = max(0, min(page, total_pages - 1))
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, total)

        items = []

        if page > 0:
            items.append({
                "label": "← Página anterior",
                "node": None,
                "action": f"libs_idf_components_page:{page - 1}",
            })

        for idx in range(start_idx, end_idx):
            comp = componentes[idx]
            marca = "✓" if comp.get("has_component_register") else "-"
            nome = comp.get("name")
            items.append({
                "label": f"{idx + 1:03d}. {nome} {marca}",
                "node": None,
                "action": f"libs_idf_component_detail:{nome}",
            })

        if end_idx < total:
            items.append({
                "label": "Próxima página →",
                "node": None,
                "action": f"libs_idf_components_page:{page + 1}",
            })

        title = (
            "Componentes ESP-IDF internos "
            f"({page + 1}/{total_pages})"
        )
        return {"title": title, "items": items}

    def _action_libs_idf_components(self) -> None:
        """Abre menu dinamico paginado de componentes ESP-IDF internos."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        node = self._libs_idf_components_page_node(0)
        self._stack.append(node)
        self._render_menu()

        ok, info = _idfcomp.get_project_idf_components_dir(projeto)
        if ok:
            self._cw(
                "[b]Componentes ESP-IDF internos[/b]\n\n"
                f"[b]ESP-IDF:[/b] {info.get('idf_version')}\n"
                f"[b]Diretório:[/b] {info.get('components_dir')}\n\n"
                "[dim]Navegue pelas páginas e selecione um componente. "
                "Nenhuma alteração é feita sem confirmação.[/dim]"
            )

    def _action_libs_idf_components_page(self, page: str) -> None:
        """Troca a pagina atual do menu de componentes internos."""
        node = self._libs_idf_components_page_node(int(page or 0))
        self._stack[-1] = node
        self._render_menu()
        self._cw(
            "[b]Componentes ESP-IDF internos[/b]\n\n"
            "[dim]Selecione um componente para ver detalhes. "
            "Use 8 para avançar quando disponível e 9 para voltar.[/dim]"
        )

    def _action_libs_idf_component_detail(self, name: str) -> None:
        """Abre submenu de detalhe/acoes de um componente interno."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        nome = (name or "").strip()
        if not nome:
            self._cw("[red]Componente vazio.[/red]")
            return

        ok, detail = _idfcomp.get_idf_component_detail(projeto, nome)
        if not ok:
            self._cw(f"[red]Erro ao detalhar componente:[/red] {detail}")
            return

        actions = detail.get("available_actions") or []
        items = []

        if "add_requires" in actions:
            items.append({
                "label": "Adicionar em REQUIRES",
                "node": None,
                "action": f"libs_idf_component_add:{nome}",
            })

        if "remove_requires" in actions:
            items.append({
                "label": "Remover de REQUIRES",
                "node": None,
                "action": f"libs_idf_component_remove:{nome}",
            })

        if not items:
            items.append({
                "label": "Nenhuma ação automática disponível",
                "node": None,
                "action": f"libs_idf_component_noop:{nome}",
            })

        self._stack.append({
            "title": f"Componente: {nome}",
            "items": items,
        })
        self._render_menu()
        self._cw(self._format_idf_component_detail(detail))

    def _action_libs_idf_component_noop(self, name: str) -> None:
        self._cw(
            "[dim]Nenhuma ação automática disponível para este componente.[/dim]"
        )

    def _action_libs_idf_component_add(self, name: str) -> None:
        """Confirma e adiciona componente interno em REQUIRES."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        nome = (name or "").strip()
        if not nome:
            self._cw("[red]Componente vazio.[/red]")
            return

        def _confirmar(resp: str | None) -> None:
            if resp is None:
                self._cw("[dim]Adição cancelada.[/dim]")
                return

            escolha = resp.strip().lower()
            if escolha not in {"s", "sim", "y", "yes"}:
                self._cw("[dim]Nenhuma alteração feita.[/dim]")
                return

            ok, res = _cmreq.add_main_require(projeto, nome)
            if not ok:
                msg = res.get("message") if isinstance(res, dict) else res
                self._cw(f"[red]Falha ao adicionar em REQUIRES:[/red] {msg}")
                return

            self._cw(
                f"[green]✔ Componente adicionado em REQUIRES:[/green] {nome}\n"
                f"[dim]Arquivo alterado: {res.get('path')}[/dim]\n"
                "[dim]Nenhum build/reconfigure foi executado.[/dim]"
            )

        _pedir_input(
            self,
            "Adicionar componente ESP-IDF interno",
            f"Adicionar '{nome}' em main/CMakeLists.txt -> REQUIRES? "
            "Digite sim ou não:",
            _confirmar,
            "não",
        )

    def _action_libs_idf_component_remove(self, name: str) -> None:
        """Confirma e remove componente interno de REQUIRES."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        nome = (name or "").strip()
        if not nome:
            self._cw("[red]Componente vazio.[/red]")
            return

        def _confirmar(resp: str | None) -> None:
            if resp is None:
                self._cw("[dim]Remoção cancelada.[/dim]")
                return

            escolha = resp.strip().lower()
            if escolha not in {"s", "sim", "y", "yes"}:
                self._cw("[dim]Nenhuma alteração feita.[/dim]")
                return

            ok, res = _cmreq.remove_main_require(projeto, nome)
            if not ok:
                msg = res.get("message") if isinstance(res, dict) else res
                self._cw(f"[red]Falha ao remover de REQUIRES:[/red] {msg}")
                return

            self._cw(
                f"[green]✔ Componente removido de REQUIRES:[/green] {nome}\n"
                f"[dim]Arquivo alterado: {res.get('path')}[/dim]\n"
                "[dim]Nenhum build/reconfigure foi executado.[/dim]"
            )

        _pedir_input(
            self,
            "Remover componente ESP-IDF interno",
            f"Remover '{nome}' de main/CMakeLists.txt -> REQUIRES? "
            "Digite sim ou não:",
            _confirmar,
            "não",
        )

    def _format_lib_inspection_result(self, data: dict) -> str:
        """Formata resultado de library_inspector.inspect_library_path()."""
        files = data.get("files") or {}
        score = data.get("score") or {}
        reasons = data.get("reasons") or []
        candidates = data.get("candidate_components") or []

        def yn(value: object) -> str:
            return "sim" if bool(value) else "não"

        lines = [
            "[b]Inspeção de biblioteca/pasta local[/b]",
            "",
            f"[b]Nome:[/b] {data.get('name', '-')}",
            f"[b]Caminho:[/b] {data.get('path', '-')}",
            f"[b]Tipo detectado:[/b] {data.get('type', '-')}",
            f"[b]Pode instalar diretamente:[/b] {yn(data.get('can_install'))}",
            f"[b]Requer conversão:[/b] {yn(data.get('requires_conversion'))}",
            f"[b]Requer seleção:[/b] {yn(data.get('requires_selection'))}",
            "",
            "[b]Arquivos detectados:[/b]",
            f"  CMakeLists.txt: {files.get('cmake') or 'não'}",
            f"  idf_component.yml: {files.get('manifest') or 'não'}",
            f"  library.properties: {files.get('library_properties') or 'não'}",
            f"  keywords.txt: {files.get('keywords') or 'não'}",
            f"  platformio.ini: {files.get('platformio') or 'não'}",
            f"  fontes: {len(files.get('sources') or [])}",
            f"  headers: {len(files.get('headers') or [])}",
            f"  .ino: {len(files.get('ino') or [])}",
            "",
            "[b]Pontuação:[/b]",
            f"  ESP-IDF: {score.get('idf', 0)}",
            f"  Arduino: {score.get('arduino', 0)}",
            f"  Projeto: {score.get('project', 0)}",
            f"  C/C++: {score.get('cpp', 0)}",
        ]

        if candidates:
            lines.extend(["", "[b]Componentes candidatos:[/b]"])
            for item in candidates[:12]:
                lines.append(f"  - {item}")

        if reasons:
            lines.extend(["", "[b]Motivos:[/b]"])
            for reason in reasons[:12]:
                lines.append(f"  - {reason}")

        lines.extend([
            "",
            "[dim]Somente leitura. Nenhum arquivo foi copiado, instalado ou alterado.[/dim]",
        ])
        return "\n".join(lines)

    def _libs_inspect_encode_rel(self, rel: str) -> str:
        """Codifica caminho relativo para uso em action:param."""
        from urllib.parse import quote
        return quote(rel or "", safe="")

    def _libs_inspect_decode_rel(self, raw: str) -> str:
        """Decodifica caminho relativo vindo de action:param."""
        from urllib.parse import unquote
        return unquote(raw or "")

    def _libs_inspect_resolve_dir(self, rel: str):
        """Resolve pasta relativa ao projeto ativo, sem permitir sair dele."""
        from pathlib import Path

        projeto = self._libs_guard()
        if projeto is None:
            return (False, "nenhum projeto ativo")

        root = Path(projeto).expanduser().resolve()
        rel = self._libs_inspect_decode_rel(rel or "").strip()

        target = (root / rel).resolve() if rel else root

        try:
            target.relative_to(root)
        except ValueError:
            return (False, "caminho fora do projeto recusado")

        if not target.is_dir():
            return (False, f"pasta inexistente: {target}")

        return (True, {
            "root": root,
            "target": target,
            "rel": "" if target == root else str(target.relative_to(root)),
        })

    def _libs_inspect_folder_node(self, rel: str = "", page: int = 0) -> dict:
        """Monta node dinâmico paginado para pastas dentro do projeto."""
        from pathlib import Path

        ok, data = self._libs_inspect_resolve_dir(rel)
        if not ok:
            self._cw(f"[red]Erro ao listar pastas:[/red] {data}")
            return {"title": "Inspecionar pasta local", "items": []}

        root = data["root"]
        target = data["target"]
        current_rel = data["rel"]

        skip = {
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            "build",
        }

        try:
            dirs = [
                d for d in sorted(target.iterdir(), key=lambda x: x.name.lower())
                if d.is_dir() and d.name not in skip and not d.name.startswith(".")
            ]
        except Exception as e:
            self._cw(f"[red]Erro ao ler pasta:[/red] {e}")
            dirs = []

        page_size = 4
        total = len(dirs)
        total_pages = max(1, (total + page_size - 1) // page_size)

        try:
            page = int(page)
        except Exception:
            page = 0

        page = max(0, min(page, total_pages - 1))
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, total)

        display = current_rel or root.name
        enc_current = self._libs_inspect_encode_rel(current_rel)

        items = [{
            "label": f"Inspecionar esta pasta: {display}",
            "node": None,
            "action": f"libs_inspect_run:{enc_current}",
        }]

        if current_rel:
            parent = str(Path(current_rel).parent)
            if parent == ".":
                parent = ""
            enc_parent = self._libs_inspect_encode_rel(parent)
            items.append({
                "label": "↑ Pasta superior",
                "node": None,
                "action": f"libs_inspect_page:{enc_parent}|0",
            })

        if page > 0:
            items.append({
                "label": "← Página anterior",
                "node": None,
                "action": f"libs_inspect_page:{enc_current}|{page - 1}",
            })

        for d in dirs[start_idx:end_idx]:
            child_rel = str(d.relative_to(root))
            enc_child = self._libs_inspect_encode_rel(child_rel)
            items.append({
                "label": f"{d.name}/",
                "node": None,
                "action": f"libs_inspect_page:{enc_child}|0",
            })

        if end_idx < total:
            items.append({
                "label": "Próxima página →",
                "node": None,
                "action": f"libs_inspect_page:{enc_current}|{page + 1}",
            })

        title = f"Inspecionar: {display} ({page + 1}/{total_pages})"
        return {"title": title, "items": items}

    def _action_libs_inspect(self) -> None:
        """Programação > Bibliotecas > Inspecionar pasta local.

        Abre menu navegável de pastas dentro do projeto ativo.
        Não usa caminho digitado livre.
        """
        projeto = self._libs_guard()
        if projeto is None:
            return

        node = self._libs_inspect_folder_node("", 0)
        self._stack.append(node)
        self._render_menu()

        self._cw(
            "[b]Inspecionar pasta local[/b]\n\n"
            f"[b]Projeto:[/b] {projeto}\n\n"
            "[dim]Selecione uma pasta do projeto para inspecionar. "
            "Nenhuma alteração é feita.[/dim]"
        )

    def _action_libs_inspect_page(self, arg: str) -> None:
        """Troca pasta/página do navegador de inspeção."""
        raw = arg or "|0"
        if "|" in raw:
            enc_rel, page_raw = raw.rsplit("|", 1)
        else:
            enc_rel, page_raw = raw, "0"

        try:
            page = int(page_raw)
        except Exception:
            page = 0

        node = self._libs_inspect_folder_node(enc_rel, page)
        self._stack[-1] = node
        self._render_menu()

        ok, data = self._libs_inspect_resolve_dir(enc_rel)
        if ok:
            rel = data["rel"] or data["root"].name
            self._cw(
                "[b]Inspecionar pasta local[/b]\n\n"
                f"[b]Pasta atual:[/b] {rel}\n\n"
                "[dim]Use o menu para navegar ou inspecionar a pasta atual.[/dim]"
            )

    def _action_libs_inspect_run(self, arg: str) -> None:
        """Executa inspeção somente leitura na pasta selecionada."""
        ok, data = self._libs_inspect_resolve_dir(arg or "")
        if not ok:
            self._cw(f"[red]Erro ao resolver pasta:[/red] {data}")
            return

        target = data["target"]

        ok2, res = _libinsp.inspect_library_path(target)
        if not ok2:
            self._cw(f"[red]Falha na inspeção:[/red] {res}")
            return

        self._cw(self._format_lib_inspection_result(res))

    def _action_libs_add(self) -> None:
        """Programação > Bibliotecas > Adicionar.

        Menu por origem. Evita pedir nome/caminho local às cegas.
        """
        projeto = self._libs_guard()
        if projeto is None:
            return

        node = {
            "title": "Adicionar biblioteca",
            "items": [
                {
                    "label": "Registry oficial / nome simples",
                    "node": None,
                    "action": "libs_add_registry",
                },
                {
                    "label": "Git",
                    "node": None,
                    "action": "libs_add_git",
                },
                {
                    "label": "Biblioteca local do projeto",
                    "node": None,
                    "action": "libs_add_local",
                },
            ],
        }
        self._stack.append(node)
        self._render_menu()
        self._cw(
            "[b]Adicionar biblioteca[/b]\n\n"
            "[dim]Escolha a origem da biblioteca. Para bibliotecas locais, "
            "a aplicação mostra as pastas do projeto para seleção; não é "
            "necessário digitar caminho às cegas.[/dim]"
        )

    def _action_libs_add_registry(self) -> None:
        """Adiciona dependência do Registry/nome simples ao manifesto."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        def _pedir_versao(nome: str | None) -> None:
            if nome is None:
                self._cw("[dim]Adição cancelada.[/dim]")
                return
            nome = nome.strip()
            if not nome:
                self._cw("[red]Nome vazio.[/red]")
                return

            def _confirmar_versao(versao: str | None) -> None:
                versao = (versao or "*").strip() or "*"
                ok, res = _libmgr.add_lib(projeto, nome, versao)
                if not ok:
                    self._cw(f"[red]Falha ao adicionar:[/red] {res}")
                    return

                criado = (
                    isinstance(res, dict)
                    and res.get("manifest_created")
                )
                extra = (
                    "\n[dim]Manifesto criado em main/idf_component.yml.[/dim]"
                    if criado else ""
                )
                self._cw(
                    f"[green]✔ Biblioteca adicionada:[/green] "
                    f"{nome} ({versao}){extra}\n"
                    "[dim]Arquivo alterado: main/idf_component.yml[/dim]\n"
                    "[dim]Nenhum idf.py, build ou reconfigure foi executado "
                    "agora.[/dim]"
                )

            _pedir_input(
                self,
                "Adicionar biblioteca do Registry",
                f"Versão de '{nome}' (Enter = '*', qualquer versão):",
                _confirmar_versao,
                "*",
            )

        _pedir_input(
            self,
            "Adicionar biblioteca do Registry",
            "Nome do componente no Registry (ex.: espressif/led_strip):",
            _pedir_versao,
            "",
        )

    def _libs_git_suggest_name(self, git_url: str) -> str:
        """Sugere nome de componente a partir da URL Git."""
        from urllib.parse import urlparse
        import re

        url = (git_url or "").strip()
        parsed = urlparse(url)

        if parsed.path:
            name = parsed.path.rstrip("/").split("/")[-1]
        else:
            name = url.rstrip("/").split("/")[-1]

        if name.endswith(".git"):
            name = name[:-4]

        name = name.strip() or "componente_git"
        name = re.sub(r"[^A-Za-z0-9_./-]+", "_", name)
        return name.strip("_") or "componente_git"

    def _libs_add_git_summary_node(
        self,
        git_url: str,
        ref: str | None,
        path_value: str | None,
    ) -> dict:
        """Monta node de confirmação para dependência Git."""
        enc_url = self._libs_inspect_encode_rel(git_url)
        enc_ref = self._libs_inspect_encode_rel(ref or "")
        enc_path = self._libs_inspect_encode_rel(path_value or "")
        suggested = self._libs_git_suggest_name(git_url)
        enc_name = self._libs_inspect_encode_rel(suggested)

        return {
            "title": "Adicionar Git",
            "items": [
                {
                    "label": f"Usar nome sugerido: {suggested}",
                    "node": None,
                    "action": (
                        "libs_add_git_commit:"
                        f"{enc_url}|{enc_ref}|{enc_path}|{enc_name}"
                    ),
                },
                {
                    "label": "Digitar outro nome manualmente",
                    "node": None,
                    "action": (
                        "libs_add_git_custom:"
                        f"{enc_url}|{enc_ref}|{enc_path}"
                    ),
                },
            ],
        }

    def _action_libs_add_git(self) -> None:
        """Adiciona dependência Git ao manifesto.

        Fluxo corrigido:
          1. URL Git primeiro
          2. ref/tag opcional
          3. path interno opcional
          4. nome sugerido automaticamente
        """
        projeto = self._libs_guard()
        if projeto is None:
            return

        def _pedir_ref(url: str | None) -> None:
            if url is None:
                self._cw("[dim]Adição cancelada.[/dim]")
                return

            url = url.strip()
            if not url:
                self._cw("[red]URL Git vazia.[/red]")
                return

            def _pedir_path(ref: str | None) -> None:
                ref = (ref or "").strip() or None

                def _mostrar_confirmacao(path_value: str | None) -> None:
                    path_value = (path_value or "").strip() or None

                    node = self._libs_add_git_summary_node(
                        url,
                        ref,
                        path_value,
                    )
                    self._stack.append(node)
                    self._render_menu()

                    suggested = self._libs_git_suggest_name(url)
                    self._cw(
                        "[b]Adicionar biblioteca Git[/b]\n\n"
                        f"[b]URL:[/b] {url}\n"
                        f"[b]Ref/tag/branch:[/b] {ref or '(padrão)'}\n"
                        f"[b]Path interno:[/b] {path_value or '(raiz)'}\n\n"
                        "[b]Nome sugerido no manifesto:[/b] "
                        f"{suggested}\n\n"
                        "[dim]Escolha uma opção no menu. Nenhuma alteração "
                        "foi feita ainda.[/dim]"
                    )

                _pedir_input(
                    self,
                    "Adicionar biblioteca Git",
                    "Path interno do componente no repositório "
                    "(Enter = raiz):",
                    _mostrar_confirmacao,
                    "",
                )

            _pedir_input(
                self,
                "Adicionar biblioteca Git",
                "Branch/tag/ref/versão (Enter = padrão do repositório):",
                _pedir_path,
                "",
            )

        _pedir_input(
            self,
            "Adicionar biblioteca Git",
            "URL Git do repositório:",
            _pedir_ref,
            "",
        )

    def _action_libs_add_git_custom(self, arg: str) -> None:
        """Permite trocar o nome sugerido para dependência Git."""
        raw = arg or "||"
        parts = raw.split("|")
        while len(parts) < 3:
            parts.append("")

        enc_url, enc_ref, enc_path = parts[:3]
        url = self._libs_inspect_decode_rel(enc_url)
        ref = self._libs_inspect_decode_rel(enc_ref)
        path_value = self._libs_inspect_decode_rel(enc_path)
        suggested = self._libs_git_suggest_name(url)

        def _usar_nome(nome: str | None) -> None:
            nome = (nome or "").strip()
            if not nome:
                self._cw("[red]Nome vazio.[/red]")
                return

            enc_name = self._libs_inspect_encode_rel(nome)
            self._action_libs_add_git_commit(
                f"{enc_url}|{enc_ref}|{enc_path}|{enc_name}"
            )

        _pedir_input(
            self,
            "Nome do componente no manifesto",
            "Nome do componente no manifesto "
            f"(sugerido: {suggested}):",
            _usar_nome,
            suggested,
        )

    def _action_libs_add_git_commit(self, arg: str) -> None:
        """Confirma e grava dependência Git no manifesto."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        raw = arg or "|||"
        parts = raw.split("|")
        while len(parts) < 4:
            parts.append("")

        enc_url, enc_ref, enc_path, enc_name = parts[:4]

        url = self._libs_inspect_decode_rel(enc_url).strip()
        ref = self._libs_inspect_decode_rel(enc_ref).strip() or None
        path_value = self._libs_inspect_decode_rel(enc_path).strip() or None
        nome = self._libs_inspect_decode_rel(enc_name).strip()

        if not url:
            self._cw("[red]URL Git vazia.[/red]")
            return
        if not nome:
            self._cw("[red]Nome vazio.[/red]")
            return

        def _confirmar_adicao(confirmado: bool) -> None:
            if not confirmado:
                self._cw("[dim]Adição cancelada.[/dim]")
                return

            ok, res = _libmgr.add_git_lib(
                projeto,
                nome,
                url,
                version=ref,
                path=path_value,
            )
            if not ok:
                self._cw(f"[red]Falha ao adicionar Git:[/red] {res}")
                return

            self._cw(
                f"[green]✔ Biblioteca Git adicionada:[/green] {nome}\n"
                f"[dim]Git:[/dim] {url}\n"
                f"[dim]Ref/tag/branch:[/dim] {ref or '(padrão)'}\n"
                f"[dim]Path interno:[/dim] {path_value or '(raiz)'}\n"
                "[dim]Arquivo alterado: main/idf_component.yml[/dim]\n"
                "[dim]Nenhum idf.py, build, download ou reconfigure foi "
                "executado agora.[/dim]"
            )

        _confirmar(
            self,
            titulo="Adicionar biblioteca Git",
            mensagem=(
                "Adicionar dependência Git ao manifesto?\n\n"
                f"Nome: {nome}\n"
                f"Git: {url}\n"
                f"Ref/tag/branch: {ref or '(padrão)'}\n"
                f"Path interno: {path_value or '(raiz)'}\n\n"
                "Será editado apenas main/idf_component.yml. "
                "Nenhum download/build será executado agora."
            ),
            on_confirm=_confirmar_adicao,
        )

    def _libs_add_local_folder_node(self, rel: str = "", page: int = 0) -> dict:
        """Monta node paginado para escolher biblioteca local do projeto."""
        from pathlib import Path

        ok, data = self._libs_inspect_resolve_dir(rel)
        if not ok:
            self._cw(f"[red]Erro ao listar pastas:[/red] {data}")
            return {"title": "Adicionar biblioteca local", "items": []}

        root = data["root"]
        target = data["target"]
        current_rel = data["rel"]

        skip = {
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            "build",
        }

        try:
            dirs = [
                d for d in sorted(target.iterdir(), key=lambda x: x.name.lower())
                if d.is_dir() and d.name not in skip and not d.name.startswith(".")
            ]
        except Exception as e:
            self._cw(f"[red]Erro ao ler pasta:[/red] {e}")
            dirs = []

        page_size = 4
        total = len(dirs)
        total_pages = max(1, (total + page_size - 1) // page_size)

        try:
            page = int(page)
        except Exception:
            page = 0

        page = max(0, min(page, total_pages - 1))
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, total)

        display = current_rel or root.name
        enc_current = self._libs_inspect_encode_rel(current_rel)

        items = [{
            "label": f"Selecionar esta pasta: {display}",
            "node": None,
            "action": f"libs_add_local_detail:{enc_current}",
        }]

        if current_rel:
            parent = str(Path(current_rel).parent)
            if parent == ".":
                parent = ""
            enc_parent = self._libs_inspect_encode_rel(parent)
            items.append({
                "label": "↑ Pasta superior",
                "node": None,
                "action": f"libs_add_local_page:{enc_parent}|0",
            })

        if page > 0:
            items.append({
                "label": "← Página anterior",
                "node": None,
                "action": f"libs_add_local_page:{enc_current}|{page - 1}",
            })

        for d in dirs[start_idx:end_idx]:
            child_rel = str(d.relative_to(root))
            enc_child = self._libs_inspect_encode_rel(child_rel)
            items.append({
                "label": f"{d.name}/",
                "node": None,
                "action": f"libs_add_local_page:{enc_child}|0",
            })

        if end_idx < total:
            items.append({
                "label": "Próxima página →",
                "node": None,
                "action": f"libs_add_local_page:{enc_current}|{page + 1}",
            })

        title = f"Adicionar local: {display} ({page + 1}/{total_pages})"
        return {"title": title, "items": items}

    def _action_libs_add_local(self) -> None:
        """Abre navegador de pastas para adicionar biblioteca local."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        node = self._libs_add_local_folder_node("", 0)
        self._stack.append(node)
        self._render_menu()
        self._cw(
            "[b]Adicionar biblioteca local[/b]\n\n"
            f"[b]Projeto:[/b] {projeto}\n\n"
            "[dim]Selecione uma pasta do projeto. A aplicação vai inspecionar "
            "a pasta e sugerir o nome do componente antes de alterar o "
            "manifesto.[/dim]"
        )

    def _action_libs_add_local_page(self, arg: str) -> None:
        """Troca pasta/página do navegador de adição local."""
        raw = arg or "|0"
        if "|" in raw:
            enc_rel, page_raw = raw.rsplit("|", 1)
        else:
            enc_rel, page_raw = raw, "0"

        try:
            page = int(page_raw)
        except Exception:
            page = 0

        node = self._libs_add_local_folder_node(enc_rel, page)
        self._stack[-1] = node
        self._render_menu()

        ok, data = self._libs_inspect_resolve_dir(enc_rel)
        if ok:
            rel = data["rel"] or data["root"].name
            self._cw(
                "[b]Adicionar biblioteca local[/b]\n\n"
                f"[b]Pasta atual:[/b] {rel}\n\n"
                "[dim]Escolha uma subpasta ou selecione a pasta atual "
                "para ver detalhes antes de adicionar.[/dim]"
            )

    def _libs_manifest_path_for_project_rel(self, rel: str) -> str:
        """Converte caminho relativo ao projeto para path no manifesto main."""
        from pathlib import Path

        rel = (rel or "").strip()
        if not rel:
            return ".."
        return str(Path("..") / rel).replace("\\", "/")

    def _action_libs_add_local_detail(self, arg: str) -> None:
        """Mostra inspeção e ações para uma pasta local selecionada."""
        ok, data = self._libs_inspect_resolve_dir(arg or "")
        if not ok:
            self._cw(f"[red]Erro ao resolver pasta:[/red] {data}")
            return

        target = data["target"]
        rel = data["rel"]

        ok2, res = _libinsp.inspect_library_path(target)
        if not ok2:
            self._cw(f"[red]Falha na inspeção:[/red] {res}")
            return

        suggested = target.name.strip().replace(" ", "_")
        enc_rel = self._libs_inspect_encode_rel(rel)
        enc_name = self._libs_inspect_encode_rel(suggested)

        items = []
        if res.get("can_install"):
            items.append({
                "label": f"Adicionar com nome sugerido: {suggested}",
                "node": None,
                "action": f"libs_add_local_commit:{enc_rel}|{enc_name}",
            })
            items.append({
                "label": "Digitar outro nome manualmente",
                "node": None,
                "action": f"libs_add_local_custom:{enc_rel}",
            })
        else:
            items.append({
                "label": "Não instalável diretamente",
                "node": None,
                "action": "libs_add_local_noop",
            })

        self._stack.append({
            "title": f"Biblioteca local: {suggested}",
            "items": items,
        })
        self._render_menu()

        manifest_path = self._libs_manifest_path_for_project_rel(rel)
        extra = (
            "\n\n[b]Sugestão para manifesto:[/b]\n"
            f"  nome: {suggested}\n"
            f"  path: {manifest_path}"
        )
        self._cw(self._format_lib_inspection_result(res) + extra)

    def _action_libs_add_local_noop(self) -> None:
        self._cw(
            "[yellow]Esta pasta não foi classificada como componente "
            "instalável diretamente.[/yellow]\n\n"
            "[dim]Volte e escolha uma subpasta candidata, como uma pasta "
            "com CMakeLists.txt e idf_component_register().[/dim]"
        )

    def _action_libs_add_local_custom(self, arg: str) -> None:
        """Permite alterar o nome sugerido, mas já com pasta selecionada."""
        ok, data = self._libs_inspect_resolve_dir(arg or "")
        if not ok:
            self._cw(f"[red]Erro ao resolver pasta:[/red] {data}")
            return

        suggested = data["target"].name.strip().replace(" ", "_")
        enc_rel = self._libs_inspect_encode_rel(data["rel"])

        def _usar_nome(nome: str | None) -> None:
            nome = (nome or "").strip()
            if not nome:
                self._cw("[red]Nome vazio.[/red]")
                return

            enc_name = self._libs_inspect_encode_rel(nome)
            self._action_libs_add_local_commit(f"{enc_rel}|{enc_name}")

        _pedir_input(
            self,
            "Nome do componente no manifesto",
            "Nome do componente no manifesto "
            f"(sugerido: {suggested}):",
            _usar_nome,
            suggested,
        )

    def _action_libs_add_local_commit(self, arg: str) -> None:
        """Confirma e grava path local no main/idf_component.yml."""
        projeto = self._libs_guard()
        if projeto is None:
            return

        raw = arg or "|"
        if "|" not in raw:
            self._cw("[red]Argumento inválido para adicionar path local.[/red]")
            return

        enc_rel, enc_name = raw.rsplit("|", 1)
        rel = self._libs_inspect_decode_rel(enc_rel)
        nome = self._libs_inspect_decode_rel(enc_name).strip()

        ok, data = self._libs_inspect_resolve_dir(enc_rel)
        if not ok:
            self._cw(f"[red]Erro ao resolver pasta:[/red] {data}")
            return

        if not nome:
            self._cw("[red]Nome vazio.[/red]")
            return

        path_value = self._libs_manifest_path_for_project_rel(rel)

        def _confirmar_adicao(confirmado: bool) -> None:
            if not confirmado:
                self._cw("[dim]Adição cancelada.[/dim]")
                return

            ok2, res2 = _libmgr.add_path_lib(projeto, nome, path_value)
            if not ok2:
                self._cw(f"[red]Falha ao adicionar path local:[/red] {res2}")
                return

            self._cw(
                f"[green]✔ Biblioteca local adicionada:[/green] {nome}\n"
                f"[dim]Path no manifesto:[/dim] {path_value}\n"
                "[dim]Arquivo alterado: main/idf_component.yml[/dim]\n"
                "[dim]Nenhum arquivo foi copiado. Nenhum idf.py, build ou "
                "reconfigure foi executado agora.[/dim]"
            )

        _confirmar(
            self,
            titulo="Adicionar biblioteca local",
            mensagem=(
                f"Adicionar biblioteca local ao manifesto?\n\n"
                f"Nome: {nome}\n"
                f"Path: {path_value}\n\n"
                "Será editado apenas main/idf_component.yml. "
                "Nenhum arquivo será copiado."
            ),
            on_confirm=_confirmar_adicao,
        )


def run() -> None:
    ESPLabApp().run()
