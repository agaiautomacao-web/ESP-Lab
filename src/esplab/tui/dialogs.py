#!/usr/bin/env python3
"""
Dialogos reutilizaveis da TUI do ESP Lab (@E4-T4.6).
ConfirmDialog : confirmacao destrutiva modal. Aguarda S/N.
InputDialog   : entrada de texto modal. Aguarda texto + Enter (ou Escape).
Nunca age sozinho — so retorna a decisao ao chamador.
Convencao: identificadores em ingles, strings em portugues.
"""
from __future__ import annotations
from typing import Callable, Optional
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Input, Button
from textual.containers import Vertical, Horizontal
from textual import events
# ==========================================================
# ConfirmDialog
# ==========================================================
class ConfirmDialog(ModalScreen):
    """
    Dialogo de confirmacao destrutiva.
    Exibe titulo, mensagem de aviso e aguarda S (confirma) ou N (cancela).
    Chama on_confirm(True) ou on_confirm(False) e fecha o modal.
    """
    CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #dialog_box {
        width: 60;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    #dialog_title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #dialog_msg {
        margin-bottom: 1;
    }
    #dialog_hint {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 1;
    }
    #confirm_buttons {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    #btn_sim {
        margin-right: 2;
    }
    """
    def __init__(
        self,
        titulo: str,
        mensagem: str,
        on_confirm: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__()
        self._titulo     = titulo
        self._mensagem   = mensagem
        self._on_confirm = on_confirm
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog_box"):
            yield Static(self._titulo,   id="dialog_title")
            yield Static(self._mensagem, id="dialog_msg")
            yield Static(
                "[dim]← / → alternar  Enter executa o botão em foco  "
                "Esc cancela  S/N também funcionam[/dim]",
                id="dialog_hint")
            with Horizontal(id="confirm_buttons"):
                yield Button(
                    "Confirmar",
                    variant="primary",
                    id="btn_sim",
                )
                yield Button(
                    "Cancelar",
                    variant="default",
                    id="btn_nao",
                )
    def on_mount(self) -> None:
        """Inicia em Cancelar; Enter nunca confirma por posição."""
        self.query_one("#btn_nao", Button).focus()

    def _confirmar(self) -> None:
        self.dismiss()
        if self._on_confirm:
            self._on_confirm(True)

    def _cancelar(self) -> None:
        self.dismiss()
        if self._on_confirm:
            self._on_confirm(False)

    def _alternar_botao(self) -> None:
        """Alterna o foco entre Confirmar e Cancelar."""
        confirmar = self.query_one("#btn_sim", Button)
        cancelar = self.query_one("#btn_nao", Button)

        if confirmar.has_focus:
            cancelar.focus()
        else:
            confirmar.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_sim":
            self._confirmar()
        elif event.button.id == "btn_nao":
            self._cancelar()

    def on_key(self, event: events.Key) -> None:
        key = event.key.lower()

        if key in {"left", "right"}:
            self._alternar_botao()
            event.stop()
            return

        if key == "s":
            self._confirmar()
            event.stop()
            return

        if key in {"n", "escape"}:
            self._cancelar()
            event.stop()


# ==========================================================
# InputDialog
# ==========================================================
class InputDialog(ModalScreen):
    """
    Dialogo de entrada de texto com lista opcional e botoes clicaveis.
    on_result(texto) -> confirmado; on_result(None) -> cancelado.
    lista: lista de strings exibida acima do campo de entrada.
    """
    CSS = """
    InputDialog {
        align: center middle;
    }
    #input_box {
        width: 64;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    #input_title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #input_lista {
        margin-bottom: 1;
    }
    #input_instrucao {
        margin-bottom: 1;
    }
    #input_hint {
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
    }
    #input_preview {
        margin-top: 1;
        color: $text-muted;
    }
    #input_buttons {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    #btn_confirmar {
        margin-right: 2;
    }
    """
    def __init__(
        self,
        titulo: str,
        instrucao: str,
        placeholder: str = "",
        on_result: Optional[Callable[[Optional[str]], None]] = None,
        valor_inicial: str = "",
        lista: Optional[list] = None,
        on_change: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        super().__init__()
        self._titulo        = titulo
        self._instrucao     = instrucao
        self._placeholder   = placeholder
        self._on_result     = on_result
        self._valor_inicial = valor_inicial
        self._lista         = lista or []
        # on_change: chamado a cada tecla digitada no campo, recebe o
        # valor atual e devolve o texto a exibir no preview (ou None
        # para nao alterar). Usado para mostrar informacao dinamica
        # (ex.: caminho absoluto do item selecionado) sem poluir a
        # lista fixa acima do campo.
        self._on_change     = on_change
    def compose(self) -> ComposeResult:
        with Vertical(id="input_box"):
            yield Static(self._titulo, id="input_title")
            if self._lista:
                yield Static("\n".join(self._lista), id="input_lista")
            yield Static(self._instrucao, id="input_instrucao")
            yield Input(
                value=self._valor_inicial,
                placeholder=self._placeholder,
                id="input_field",
            )
            if self._on_change is not None:
                yield Static("", id="input_preview")
            yield Static(
                "[dim]Tab acessa botões  ← / → alterna  "
                "Enter executa o foco  Esc volta/cancela[/dim]",
                id="input_hint",
            )
            with Horizontal(id="input_buttons"):
                yield Button(
                    "Confirmar",
                    variant="primary",
                    id="btn_confirmar",
                )
                yield Button(
                    "Cancelar",
                    variant="default",
                    id="btn_cancelar",
                )
    def on_mount(self) -> None:
        campo = self.query_one("#input_field", Input)
        campo.focus()
        if self._on_change is not None:
            texto = self._on_change(campo.value)
            if texto is not None:
                self.query_one("#input_preview", Static).update(texto)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "input_field" or self._on_change is None:
            return
        texto = self._on_change(event.value)
        if texto is not None:
            self.query_one("#input_preview", Static).update(texto)
    def _confirmar(self) -> None:
        valor = self.query_one("#input_field", Input).value.strip()
        self.dismiss()
        if self._on_result:
            self._on_result(valor if valor else None)
    def _cancelar(self) -> None:
        self.dismiss()
        if self._on_result:
            self._on_result(None)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_confirmar":
            self._confirmar()
        elif event.button.id == "btn_cancelar":
            self._cancelar()
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._confirmar()
    def on_paste(self, event) -> None:
        """Suporte a Ctrl+Shift+V / paste do terminal."""
        campo = self.query_one("#input_field", Input)
        campo.value = campo.value + event.text
        campo.cursor_position = len(campo.value)
    def on_key(self, event: events.Key) -> None:
        key = event.key.lower()

        if key == "escape":
            self._cancelar()
            event.stop()
            return

        if key not in {"left", "right"}:
            return

        confirmar = self.query_one("#btn_confirmar", Button)
        cancelar = self.query_one("#btn_cancelar", Button)

        # Se o campo de texto estiver focado, as setas continuam
        # movimentando o cursor normalmente. A alternância só ocorre
        # depois que Tab levou o foco para um dos botões.
        if confirmar.has_focus:
            cancelar.focus()
            event.stop()
        elif cancelar.has_focus:
            confirmar.focus()
            event.stop()
# ==========================================================
# Atalhos
# ==========================================================
def confirmar(app, titulo: str, mensagem: str,
              on_confirm: Callable[[bool], None]) -> None:
    """
    Atalho: exibe o ConfirmDialog sobre o app Textual atual.
    on_confirm(True)  -> usuario confirmou.
    on_confirm(False) -> usuario cancelou.
    """
    app.push_screen(ConfirmDialog(titulo, mensagem, on_confirm))
def pedir_input(app, titulo: str, instrucao: str,
                on_result: Callable[[Optional[str]], None],
                placeholder: str = "",
                valor_inicial: str = "",
                lista: Optional[list] = None,
                on_change: Optional[Callable[[str], Optional[str]]] = None) -> None:
    """
    Atalho: exibe o InputDialog sobre o app Textual atual.
    on_result(texto) -> usuario digitou algo.
    on_result(None)  -> usuario cancelou.
    lista: itens exibidos no modal antes do campo de entrada.
    on_change: preview reativo — chamado a cada tecla, devolve o texto
    a exibir abaixo do campo (ou None para nao alterar).
    """
    app.push_screen(InputDialog(
        titulo=titulo,
        instrucao=instrucao,
        placeholder=placeholder,
        on_result=on_result,
        valor_inicial=valor_inicial,
        lista=lista,
        on_change=on_change,
    ))
__all__ = [
    "ConfirmDialog", "InputDialog",
    "confirmar", "pedir_input",
]
