#!/usr/bin/env python3
"""
Script de PREPARACAO do ambiente do ESP Lab — NAO faz parte do runtime
da aplicacao.

Baixa o pacote oficial 'nano' do Ubuntu via apt (apt-get download, sem
sudo, sem instalar no sistema) e extrai o binario para dentro do
proprio ambiente do ESP Lab (data/app-venv/bin/nano). Depois de rodado
uma vez, a aplicacao encontra esse editor automaticamente, sem
qualquer acesso a rede durante o uso normal.

Decisao (2026-07-02): o empacotamento NUNCA acontece durante o runtime
da TUI — so aqui, sob demanda explicita do usuario (ou, no futuro,
como parte do fluxo do instalador). Reaproveita a mesma logica ja
testada em external_editor.bundle_nano() — so muda QUANDO ela roda.

Uso:
    cd ~/esplab && python3 bundle_nano.py

Requer conexao com a internet. Nao precisa de sudo/root.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Permite importar o pacote esplab sem depender de PYTHONPATH externo —
# mesma convencao de install.py / make_release.py (scripts standalone
# na raiz do projeto).
_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from esplab.programming import external_editor as _editor  # noqa: E402


def main() -> int:
    print("ESP Lab — preparacao do ambiente: empacotando nano")
    print("(baixa o pacote oficial do Ubuntu via apt; nao instala no "
          "sistema, nao precisa de sudo)\n")

    def _progresso(tipo: str, linha: str) -> None:
        print("  {}".format(linha))

    ok, res = _editor.bundle_nano(progress_cb=_progresso)

    print()
    if ok:
        print("✔ nano instalado em: {}".format(res["path"]))
        print("A aplicacao vai encontra-lo automaticamente na proxima vez "
              "que abrir — nenhuma acao adicional necessaria.")
        return 0

    print("✘ Falha ao instalar o nano: {}".format(res))
    print("\nNenhuma alteracao foi feita no sistema. Verifique a conexao "
          "com a internet e tente novamente.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
