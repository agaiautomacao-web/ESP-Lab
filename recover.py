#!/usr/bin/env python3
"""
ESP Lab — Recuperação do corpo da aplicação (território 1, PROJECT.md Adendo 5).

Roda **quando a aplicação não sobe** (app-venv quebrado, dependências
corrompidas). Standalone: usa o python3 do SISTEMA — não depende do app-venv,
que é justamente o que ele reconstrói. Orquestrador fino: importa o install.py
que mora na mesma raiz e reusa as funções dele, sem reimplementar
download/venv/validação.

Fluxo:
  1. verificar_prerequisitos() — detecta Python 3.10+, Linux, git e internet;
     para com mensagem clara se a plataforma for incompatível.
  2. atualizar(raiz) — baixa a última release do GitHub, recria o app-venv,
     reinstala as dependências, atualiza src/VERSION/requirements e valida,
     preservando config/, workspace/ e o restante de data/.

Uso:  python3 ~/esplab/recover.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# recover.py mora na raiz da instalação; importa o install.py vizinho.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    import install
except ImportError as exc:
    print(f"[ERRO] Não encontrei install.py ao lado de recover.py em {ROOT}.")
    print(f"       Detalhe: {exc}")
    print("       Baixe o pacote do ESP Lab novamente e rode o install.py.")
    sys.exit(1)


def main() -> None:
    install._print("\n\033[1mESP Lab — Recuperação do corpo da aplicação\033[0m")
    install._print(f"Raiz: {ROOT}")

    if not (ROOT / install.SENTINEL_FILE).exists():
        install.warn(
            f"Sentinela {install.SENTINEL_FILE} ausente em {ROOT} — "
            "esta pode não ser uma instalação válida do ESP Lab."
        )

    # 1. Plataforma/Python (opção 1: detectar e orientar; aborta se incompatível)
    install.verificar_prerequisitos()

    # 2. Baixa do GitHub, recria app-venv, reinstala deps, valida.
    #    Preserva config/, workspace/ e o restante de data/.
    install.atualizar(ROOT, None, None)

    install._print(
        "\n\033[1mRecuperação concluída.\033[0m Reabra o ESP Lab:\n"
        f"  bash {ROOT / install.ENTRY_SCRIPT}\n"
    )


if __name__ == "__main__":
    main()
