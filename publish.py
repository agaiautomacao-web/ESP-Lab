#!/usr/bin/env python3
"""
ESP Lab — Publicação no GitHub (ferramenta de manutenção).

Faz o `git push` do repositório para o remote `origin` **pedindo o token na
hora** (entrada oculta). O token NÃO é gravado em lugar nenhum: não vai para o
.git/config, não vira URL do remote, não fica no histórico do shell. Ele é
passado ao git por um GIT_ASKPASS temporário (via env do processo filho) e
descartado ao fim.

Pré-requisito: o remote `origin` deve apontar para a URL LIMPA (sem token):
    git remote set-url origin https://github.com/<owner>/<repo>.git

Uso:  python3 ~/esplab/publish.py            # push do branch atual
      python3 ~/esplab/publish.py --branch main
"""
from __future__ import annotations

import argparse
import getpass
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _git(args: list[str], env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        env=env, text=True, capture_output=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="ESP Lab — publicar no GitHub")
    parser.add_argument("--branch", help="branch a subir (padrão: o atual)")
    parser.add_argument("--force", action="store_true",
                        help="sobrescreve o remote (use na 1ª consolidação)")
    args = parser.parse_args()

    if not (ROOT / ".git").is_dir():
        print(f"[ERRO] {ROOT} não é um repositório git.")
        return 1

    # Remote deve estar limpo (sem token na URL).
    r = _git(["remote", "get-url", "origin"])
    if r.returncode != 0:
        print("[ERRO] remote 'origin' não configurado. Rode:")
        print("  git remote add origin https://github.com/<owner>/<repo>.git")
        return 1
    url = r.stdout.strip()
    if "@" in url.split("//", 1)[-1]:
        print("[ERRO] há credencial embutida na URL do remote — remova antes:")
        print("  git remote set-url origin https://github.com/<owner>/<repo>.git")
        return 1
    print(f"Remote: {url}")

    branch = args.branch
    if not branch:
        b = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = b.stdout.strip() or "HEAD"
    print(f"Branch: {branch}")

    token = getpass.getpass("Token do GitHub (oculto, não será salvo): ").strip()
    if not token:
        print("[cancelado] token vazio.")
        return 1

    # GIT_ASKPASS temporário: git chama este script pedindo usuário/senha.
    # Retornamos 'x-access-token' para usuário e o token para senha, lendo o
    # token do ambiente (não do argv), e apagamos o script ao fim.
    ask = tempfile.NamedTemporaryFile(
        "w", suffix=".sh", delete=False, encoding="utf-8"
    )
    ask.write(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  *[Uu]sername*) printf "x-access-token" ;;\n'
        '  *) printf "%s" "$GIT_ESPLAB_TOKEN" ;;\n'
        "esac\n"
    )
    ask.close()
    os.chmod(ask.name, stat.S_IRWXU)

    env = dict(os.environ)
    env["GIT_ASKPASS"] = ask.name
    env["GIT_ESPLAB_TOKEN"] = token
    env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        print("\nEnviando..." + ("  (--force)" if args.force else ""))
        push_cmd = ["git", "-C", str(ROOT), "push", "origin", f"HEAD:{branch}"]
        if args.force:
            push_cmd.insert(-1, "--force")
        r = subprocess.run(push_cmd, env=env, text=True)
    finally:
        try:
            os.unlink(ask.name)
        except OSError:
            pass
        # não deixa o token no ambiente do processo
        env.pop("GIT_ESPLAB_TOKEN", None)

    if r.returncode == 0:
        print("\n\033[1mPush concluído.\033[0m")
        print("Para tornar o repositório público (uma vez):")
        print("  gh repo edit <owner>/<repo> --visibility public")
        print("  (ou GitHub → Settings → Danger Zone → Change visibility)")
        return 0
    print("\n[ERRO] push falhou (ver mensagem do git acima).")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
