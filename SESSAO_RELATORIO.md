# ESP Lab — Relatório de Sessão
Data: 2026-06-27

## O que foi concluído nesta sessão

### @E4-T4.5 — Workers não-bloqueantes (RESOLVIDO)
Ações síncronas na thread principal do Textual bloqueavam o teclado.
Solução: `@work(thread=True)` + `call_from_thread` para atualizar UI.
Flag `_worker_ativo` bloqueia navegação (teclas 0, 1-8, 9) durante execução.
Callbacks de modais (`ConfirmDialog`, `InputDialog`) corrigidos para não usar
`call_from_thread` quando já estão na thread principal.
Validado: teclado responsivo durante carregamento de todas as ações lentas.

### @E4-T4.7 — InputDialog (NOVO)
Modal de entrada de texto de uma linha adicionado a `tui/dialogs.py`.
Usado em: Workspace > Abrir projeto (número), Novo projeto (nome + versão IDF),
Programação > Definir target.
`pedir_input()` como atalho análogo ao `confirmar()`.

### @E7 — Sessão persistente (NOVO — core/session.py)
`session.py` criado em `core/`: grava/lê `data/session.json`.
Campos: `projeto_ativo` (caminho absoluto) + `recentes` (últimos 5).
`set_projeto_ativo()`, `clear_projeto_ativo()`, `get_projeto_ativo()`, `get_recentes()`.
Validação automática: pastas inexistentes são filtradas silenciosamente.
TUI: `_projeto_ativo` carregado no `on_mount`; subtítulo do header mostra nome do projeto.

### @E7 — Workspace na TUI (COMPLETO)
Menu Workspace expandido para 4 ações:
- **Estado atual**: mostra projeto ativo, recentes e projetos do workspace.
- **Abrir projeto**: lista projetos, usuário digita número, abre e atualiza sessão.
- **Novo projeto**: InputDialog sequencial (nome → versão IDF) → `workspace.new()`.
- **Fechar projeto**: limpa sessão, remove nome do subtítulo.
`_set_projeto_ativo()` centraliza atualização de estado + sessão + subtítulo.

### @E8 — Programação na TUI (COMPLETO)
Menu Programação expandido para 3 ações:
- **Estado do build**: lê `project_config` + `check_build_valid()`.
- **Definir target**: InputDialog → `builder.set_target()` em worker → persiste em `project_config`.
- **Compilar projeto**: `builder.build(background=False)` em worker com progresso linha a linha.
Validado: `teste_flash` compilado para `esp32s3` com ESP-IDF v5.4.4.

### @E9 — Flash na TUI (COMPLETO)
`_action_flash` implementado com fluxo completo:
1. Verifica projeto ativo e porta ESP.
2. Detecta chip family e flash size do scanner.
3. `check_build_valid()` — bloqueia se inválido.
4. Modal de erase (destrutivo, S/N).
5. Modal de confirmação de gravação.
6. `_run_flash_worker` → `flasher.flash(background=False)` com progresso linha a linha.
Validado em hardware real: ESP32-S3 gravado e verificado com sucesso.

### @E10 — Monitor serial em tempo real na TUI (COMPLETO)
`_action_monitor` reescrito: inicia `SerialMonitor`, exibe últimas 30 linhas em tempo real.
`on_line` callback → `call_from_thread` → atualiza `#content` a cada linha.
`_go_back()` para o stream antes de voltar ao menu.
Validado em hardware real: output do `teste_flash` exibido em tempo real,
incluindo boot log completo e "ESP Lab: projeto iniciado".

### @E8-T8.4 — Lock de versão por biblioteca (COMPLETO)
`library_manager.py` atualizado com:
- `lock_lib(project_dir, name, version)` — versão exata (X, X.Y, X.Y.Z).
- `unlock_lib(project_dir, name)` — volta para `*`.
- `_validate_exact_version()` — rejeita `*`, ranges, strings vazias.
- `list_libs()` agora devolve campo `locked: bool`.
- Transacional em ambas as operações.

### @E12 — Instalador/Empacotamento (COMPLETO)
- `make_release.py` na raiz do projeto gera `dist/esplab-vX.Y.Z.zip` + SHA-256.
- `install.py` standalone: baixa da GitHub Releases API, extrai, cria venv,
  instala deps, gera `esplab.sh`, valida 8 itens.
- Suporte a repos privados: `--token` ou `ESPLAB_GITHUB_TOKEN`.
- Release `v0.1.0` publicada em `github.com/agaiautomacao-web/ESP-Lab` (privado).
- Instalação limpa validada em `/tmp/esplab_teste4`: 8/8 ✔.

---

## Estado atual dos épicos

| Épico | Status | Observação |
|-------|--------|-----------|
| @E1 Fundação | ✔ COMPLETO | paths, storage, errors, version, logger, session |
| @E2 Sudo/Ambiente | ✔ COMPLETO | sudo_wrapper, sudoers_manager, system_info, ports |
| @E3 ESP-IDF multi-versão | ✔ COMPLETO | idf_manager, idf_releases, venv, sliding window |
| @E4 TUI | ✔ COMPLETO | workers, ConfirmDialog, InputDialog, navegação |
| @E5 Hardware | ✔ COMPLETO | scanner, chip_info, boards_db, divergence |
| @E6 Partições/Portas | ✔ COMPLETO | port_config, partition_tables, sanity |
| @E7 Workspace | ✔ COMPLETO | new, open, activate, close, sessão persistente |
| @E8 Programação | ✔ COMPLETO | builder, lock libs, file_explorer, editor, templates |
| @E9 Flash | ✔ COMPLETO | flasher validado + TUI integrada com progresso |
| @E10 Monitor | ✔ COMPLETO | tempo real na TUI, stop ao sair, log em disco |
| @E11 Versionamento | ✔ COMPLETO | git_local: prepare, commit, status |
| @E12 Instalador | ✔ COMPLETO | make_release, install.py, release v0.1.0 publicada |

---

## Pendências para v0.2.0

### Tornar repositório público
Elimina necessidade de token no `install.py`.
GitHub: Settings → Danger Zone → Change visibility → Public.

### Programação > Explorador de arquivos / Editor externo
`file_explorer.py` e `external_editor.py` existem mas não estão integrados na TUI.
@E8-T8.1 e @E8-T8.2 ainda pendentes como submenu de Programação.

### Monitor com scroll interativo
Atualmente exibe as últimas 30 linhas. Para scroll real precisa de widget
Textual dedicado (ex: `RichLog` ou `TextArea` somente leitura).

### @E8-T8.4 integrado na TUI
`lock_lib` / `unlock_lib` implementados em `library_manager.py` mas
sem submenu na TUI ainda.

### Templates de projeto
`template_manager.py` e `workspace/data/templates.yml` existem.
@E8-T8.8 (Templates no New Project) pendente.

---

## Arquivos modificados/criados nesta sessão

### Novos
- `src/esplab/core/session.py` — sessão persistente
- `install.py` (raiz do repo) — instalador standalone
- `make_release.py` (raiz do repo) — gerador de release

### Modificados
- `src/esplab/tui/app.py` — workers, workspace, flash, programação, monitor
- `src/esplab/tui/dialogs.py` — InputDialog + pedir_input()
- `src/esplab/programming/library_manager.py` — lock_lib, unlock_lib

### Repositório
- `github.com/agaiautomacao-web/ESP-Lab` (privado)
- Release `v0.1.0` publicada com `esplab-v0.1.0.zip` (98.8 KB)
- SHA-256: `e59c5255fc164a1e51edeb8e245a539a187768f86e41565e49ccd0fdd06ce399`

---

## Convenções do projeto (para o próximo assistente)

- Identificadores em inglês, strings/mensagens em português
- Retorno sempre `(ok, result_or_error)`, nunca lança exceção
- Escrita atômica via `core/storage.py`
- Paths derivados de `core/paths.py` (sentinel `.esplab_root`), nunca hardcoded
- UI: sem jargão, nomes comunicam o que o usuário conquista
- Ações lentas (I/O) rodam via `@work(thread=True)` + `call_from_thread`
- Callbacks de modais rodam na thread principal — não usar `call_from_thread`
- Confirmação obrigatória para operações destrutivas (`ConfirmDialog`)
- Sessão do projeto: `core/session.py` + `self._projeto_ativo` na TUI
- Comando para rodar: `cd ~/esplab && PYTHONPATH=src ~/esplab/data/app-venv/bin/python -m esplab`


---

# ESP Lab — Relatório de Sessão
Data: 2026-07-28

## Foco
Ajustes de boot e da tela inicial (quatro painéis) e **reconciliação da
documentação com o código**, que estava meses atrás.

## Achado importante
Os três documentos (PROJECT/TASKS/SESSAO) descreviam estado anterior ao código:
placa **por nome de modelo** (o código já usa **MAC**) e tela inicial em coluna
única (o código já tem **quatro painéis**). Reconciliado via PROJECT.md §13
Adendos (append-only; corpo original preservado).

## O que foi feito (código, entregue por patches idempotentes)
- **Boot com varredura** (etapa 1): boot identifica hardware, auto-conexão pela
  placa do projeto (MAC), estado de conexão persistido por MAC (setter dedicado).
- **Painel HARDWARE** reescrito: retrato físico (Dispositivo ativo · Recursos da
  placa · Build/sdkconfig · Detectados); saiu a reconciliação de projeto.
- **Painel PROJETOS** (novo, 4º): reconciliação + dependências do manifesto +
  requisito de ESP-IDF.
- **Painel LOCAIS**: Backup e Bancada (`paths.py` ganhou `backups`/`workbench`).
- **Menu Hardware**: "Exibir layout da placa" readicionado; desenho do
  `board_ascii` ajustado.
- **Interação**: "Aguarde..." em todo clique; barra laranja nomeia a tarefa lenta
  (pontinhos 0→3); rolagem do `#content` só acima de 50 linhas (rastro removido);
  Ctrl+C confirma antes de cancelar (boot e flash).

## Documentação
- **PROJECT.md** — criada §13 Adendos (11 adendos) incorporando
  `CORRECOES_SOFTWARE.md` + `CORRECOES_HARDWARE.md` + a reconciliação (MAC,
  painéis). Corpo original intacto.
- **TASKS.md** — rodada 2026-07-28 anexada.
- **CORRECOES_*.md** — incorporadas; serviram de staging, podem ser arquivadas.

## Próximos passos (sequência acordada)
1. (feito) Fechar a documentação.
2. Testar o versionamento (`git_local`).
3. Auditoria pré-público (`.gitignore`, segredos/token, caminhos, sentinela).
4. Subir ao GitHub **público** (elimina o token do `install.py`).
5. Validar instalação limpa pelo instalador (caso de incompatibilidade de
   plataforma Linux do usuário final).

## Nota
O instalador é peça **essencial** (território 1): único caminho para
constituir/reparar o corpo da app em plataformas novas com incompatibilidade.

---

# Sessão 2026-07-29 — Fechamento v1.0.0 (pré-push público)

## Versionamento
- Esclarecido: a versão é **manual** (fonte única `VERSION`, lida em runtime).
  Não havia — nem passou a haver — bump automático por commit. O que é
  automático no projeto é a atualização do **ESP-IDF** (slot corrente), coisa
  distinta.
- Novo `bump.py` (raiz): `patch`/`minor`/`major` e `--set`, validando pelo
  próprio `version.py`. Escrita atômica. Testado nos três níveis.
- Versão elevada `0.1.0` → **`1.0.0`**. README alinhado (topo e "Estado atual").

## Tela "Sobre" (_action_about)
- Traduzida e enriquecida: ciclo por etapa, filosofia com exemplos, famílias
  ESP32 completas (S2, S3, C2, C3, C5, C6, C61, H2, H4, H21, P4), autor
  Antonio Goncalves, contato e parágrafo de isolamento/responsabilidade.
- Repositório marcado como **público**.

## Command palette (Textual 8.2.7)
- Comandos, placeholder, tooltip e binding `Ctrl+P` em português; "Screenshot"
  removido; `Ctrl+P` com `show=False` (Footer não duplica).
- ESC prioriza o `HelpPanel`: 1º ESC fecha o painel, 2º age no menu.

## Publicação
- `.gitignore` cobre runtime (`config/`, `workspace/`, `backups/`, `data/`,
  `_workbench/`, `.claude/`); `config/` e `workspace/` sobem vazias.
- Histórico git recomeçado (sem `boards_db.json`/MACs). Remote público
  configurado. Portão de auditoria aprovado.

## Próximos passos
1. Reindexar (`git add -A`) e reconferir o portão antes do commit.
2. Commit + push pela aplicação (Versionamento / `publish.py`).
3. Validar instalação limpa pelo instalador em plataforma nova (@E12).
