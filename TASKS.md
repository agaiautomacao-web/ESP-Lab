# TASKS.md — ESP Lab

> Desdobramento em tarefas executáveis, organizadas por fase.
> Referência de tarefa: **@E#-T#.#** (Fase # — Tarefa #.#). Referência de fase:
> **@E#**.
> A ordem das fases segue a **dependência de implementação** (fundação
> primeiro), não a ordem de uso da aplicação.
> Convenção: identificadores em inglês, strings em português (ver PROJECT.md §1).

---

## Legenda de status

- `[ ]` pendente
- `[~]` em andamento
- `[x]` concluída
- `[!]` bloqueada (depende de outra tarefa)

---

## Método de construção

A estrutura é construída **manualmente**, peça por peça, e testada durante o
desenvolvimento. O **empacotamento** (`.zip` + instalador que cria a pasta raiz
e copia os arquivos) é produzido **apenas ao final** (@E12), sobre uma estrutura
já testada — o instalador empacota algo que já funciona, não constrói às cegas.

**Regra transversal — sem caminhos fixos:** nenhum caminho absoluto é literal no
código. Todo caminho nasce de resolução em runtime, derivado da raiz que a
aplicação descobre sozinha (PROJECT.md §4). A pasta raiz pode nascer em qualquer
lugar do disco.

## @E1 — Fundação e arquitetura

- [x] **@E1-T1.8** Venv próprio da aplicação (`app_env.py`): cria o app-venv
  isolado e instala as dependências da ferramenta (textual, pyserial, PyYAML,
  rich) de `requirements-app.txt`. Distinto dos venvs de ESP-IDF. Validado.

Estabelece o esqueleto modular, a convenção de idioma e os utilitários
transversais que todas as outras fases consomem.

- [x] **@E1-T1.0** Módulo `paths` — resolução de caminhos em runtime: descobre a
  raiz, deriva todos os subcaminhos por composição, cria diretórios ausentes.
  Fronteira única de localização no disco; nenhum outro módulo monta caminho
  próprio. **Primeira peça de código.**
  - Dois domínios: `app_root` (raiz da aplicação) e XDG do usuário (config,
    dados, logs), respeitando `XDG_CONFIG_HOME` / `XDG_DATA_HOME`.
  - Venvs e ESP-IDF (um por versão) sob os dados XDG, separados do código.
  - Workspace com pasta default (`~/esplab/workspace`).
  - Detecção da raiz por **arquivo-sentinela** (`.esplab_root`); erro explícito
    para nenhuma ou múltiplas raízes.
  - Validado por bateria de testes (base explícita, XDG, por versão, sentinela,
    override por env, ausência/ambiguidade de raiz).
  - **Depende de @E12-T12.0**: o sentinela `.esplab_root` deve estar na raiz do
    pacote final para a auto-detecção funcionar fora do modo de desenvolvimento.
- [ ] **@E1-T1.1** Estrutura de diretórios do projeto (código em inglês),
  separando módulos por responsabilidade.
- [ ] **@E1-T1.2** Definir o padrão de módulo: entrada por
  parâmetro/importação, saída de dados normalizados, dado cru não vaza
  (PROJECT.md §3).
- [x] **@E1-T1.3** Fonte única de versão da aplicação (SemVer, início `0.1.0`).
  - `version.py`: lê o `VERSION` da raiz (via `paths`), valida SemVer, expõe
    `get_version()` (nunca lança; devolve UNKNOWN em falha). Validado.
- [x] **@E1-T1.4** Camada de persistência atômica genérica (arquivo temporário
  + replace) reutilizável por todos os bancos.
  - `storage.py`: escrita atômica (tmp no mesmo dir + fsync + `os.replace`).
  - Helpers JSON, YAML e texto; `update_json` para edição preservando o resto.
  - Retorno `(ok, result_or_error)`, nunca lança; mensagens em português.
  - Validado: round-trip, criação de dir, sem lixo de tmp, **prova de
    atomicidade** (falha no meio não corrompe o arquivo antigo), parse inválido,
    integração com `paths` (grava em caminho derivado).
- [x] **@E1-T1.5** Política de erros: encapsular toda operação externa; falha
  vira status, nunca crash. Padrão de retorno `(ok, result_or_error)`.
  - `errors.py`: helpers `ok()`/`err()`, `guard()` (encapsula operação externa,
    converte exceção em `(False, motivo)` em português com contexto),
    `is_ok()`/`unwrap()`/`reason()` para consumo.
  - Validado no ambiente do usuário (sucesso, falha capturada, unwrap com
    default).
- [x] **@E1-T1.6** Logger interno (mensagens em português) com saída para
  arquivo.
  - `logger.py`: log da app (distinto do log do monitor), arquivo rotativo em
    `data_home/logs` (5 MB x 3 backups, ajustável), degrada para console sem
    quebrar. Validado.
- [x] **@E1-T1.7** Resolução de diretórios XDG (`~/.config/esplab/`,
  - `paths.py` migrado: config_home -> ~/esplab/config/,
    data_home -> ~/esplab/data/. XDG so se explicitamente definido.
    app-venv recriado em ~/esplab/data/app-venv/. TUI validada OK.
  `~/.local/share/esplab/`).

## @E2 — Privilégios e ambiente do sistema

- [x] **@E2-T2.1** Wrapper de sudo: prompt seguro (`sudo -S`, sem eco), senha
  - `sudo_wrapper.py`: check_sudo() + run_sudo(). Senha via stdin,
    nunca logada/persistida, descartada apos uso. Validado.
  nunca persistida, descartada após uso.
- [x] **@E2-T2.2** Geração opcional de regra `sudoers.d` restrita, com
  - `sudoers_manager.py`: install_rule/remove_rule/show_rule/rule_exists.
    Regra restrita a apt-get install/update. Valida com visudo antes de
    gravar. Permissao 0440. Reversivel. show_rule via sudo (0440 root).
    Validado com hardware real.
  consentimento explícito.
- [ ] **@E2-T2.3** Detecção do ambiente do sistema (distro, versão, kernel,
  Python, usuário) — módulo de saída normalizada.
- [x] **@E2-T2.4** Detecção de portas seriais via pyserial, filtro por VID/PID,
  saída em formato estável (consumido por @E5).

## @E3 — Multi-ambiente ESP-IDF e compatibilidade

Núcleo do isolamento. Depende de @E1 e @E2.

- [x] **@E3-T3.1** Modelo da matriz de compatibilidade em YAML (esquema:
  ESP-IDF → faixas de dependências).
- [x] **@E3-T3.2** Matriz embarcada conhecida-boa (offline-first).
- [x] **@E3-T3.3** Validação na fronteira: esquema + formato de versão; rejeita
  e registra malformado.
- [x] **@E3-T3.4** Lógica append-only: anexa versão ausente, nunca reescreve
  registro existente.
- [x] **@E3-T3.5** Consulta de rede sob demanda (só para versão ausente);
  - `idf_releases.py`: fetch_stable_versions() (GitHub API) +
    update_matrix_from_network(). Append-only na matriz local.
    Fallback offline: falha de rede nao propaga erro. Validado.
  fallback para versão anterior em falha de rede.
- [x] **@E3-T3.6** Gerenciador de versões de ESP-IDF: instalar / listar /
  - `idf_manager.py`: list_available/list_installed/install/activate/remove.
    Metodo legado (git clone + install.sh), compativel 4.x+. Isolado em
    ~/esplab/data/esp-idf/<versao>/. Background com progress_cb.
    Janela deslizante (MAX=4) avisa sem bloquear. Logica pura validada;
    instalacao real VALIDADA: v5.4.4 instalada/ativada com sucesso,
    idf.py disponivel, python_env isolado (idf5.4_py3.12_env).
  ativar / remover, autocontido na pasta da aplicação.
- [x] **@E3-T3.7** Um venv por versão de ESP-IDF; criação e isolamento.
  - `python_detect.py` (pré-requisito, validado): descobre Pythons do sistema
    (pergunta versão real ao interpretador), compara faixas sem dependência
    externa, retorna compatíveis + sugestão do mais novo. A app verifica e usa
    Python existente; nunca instala nem troca.
- [x] **@E3-T3.8** Janela deslizante: 3 fixas (4.x+) + 1 corrente; remoção
  - `oldest_installed()` + `enforce_window()` em idf_manager.py.
    Remove a mais antiga quando instaladas > MAX_VERSIONS(4). Validado.
  - logica de aviso implementada em idf_manager.install() (MAX_VERSIONS=4).
    Remocao automatica da mais antiga pendente.
  completa do ambiente ao sair da janela.
- [x] **@E3-T3.9** Requirements por versão **derivados** da matriz (sem
  - Revisao de design: dependencies na matriz ficam vazios (fonte real
    e o requirements/requirements.core.txt dentro do ESP-IDF clonado).
    Instalacao de requirements coberta pelo install.sh em @E3-T3.6.
  `requirements.txt` único na raiz).

## @E4 — TUI base (Textual)

- [x] **@E4-T4.9** Menu principal navegável: árvore de menus como dado
  - _hardware_text() atualizado: usa scanner.scan() em vez de chip_info
    direto. Tela inicial mostra varredura completa com modelo e divergencias.
  - Submenus reais conectados (desktop): Portas, Placas, ESP-IDF,
    Atalhos, Sobre. Mecanismo action= adicionado ao MENU_TREE.
    Filtro visual de portas (ocultar ttyS*) pendente para consolidacao.
  (MENU_TREE), navegação por números (1-8 itens, 0=Sair no principal,
  9=Voltar em submenus), breadcrumb completo no topo, submenus placeholder
  "em construção". Validado no Termius. Pendências de layout (split
  horizontal, proporções) adiadas para o desktop.

Depende de @E1–@E3 para alimentar a tela inicial.

- [x] **@E4-T4.1** Esqueleto da aplicação Textual; loop principal e navegação
  de menus.
- [x] **@E4-T4.2** Cabeçalho fixo (título + versão) em todas as telas.
- [x] **@E4-T4.3** Corpo da tela inicial: System·Version·Kernel, environment
  type, esptool, ESP-IDF, dependencies.
- [ ] **@E4-T4.4** Placeholder de carregamento para verificações lentas
  (esptool/ESP-IDF) sem travar o boot.
- [~] **@E4-T4.5** Mecanismo de bloqueio de teclado por contexto (estado
  - Tentativas: flag _busy + debounce 300ms. Nao resolveu o caso de
    teclas rapidas entre actions (ex: 3+9 simultaneos). Pendente solucao
    via run_worker do Textual para actions em background.
  crítico); abort explícito e confirmado.
- [x] **@E4-T4.6** Padrão de diálogo de confirmação destrutiva reutilizável.
  - `tui/dialogs.py`: ConfirmDialog (ModalScreen) + confirmar(). Bloqueia
    teclado, S/N, callback. Aplicado em 'Buscar placas'. Validado.
  - Padrao: actions que abrem modal retornam None; _enter_item nao
    sobrescreve #content nesse caso.
- [x] **@E4-T4.7** Menu de atualizações: dependências Python e esptool
  - `updates.py`: list_outdated() (pip --outdated --format json),
    update_package() com pin, get_update_summary() separa python/esptool/
    esp-idf. CRITICAL_PACKAGES destacados. Validado com consulta PyPI real.
  - Nota: app-venv com textual 0.89.1; projeto espera 8.2.7 (recriado na
    migracao de paths). Atualizar quando conveniente, nao urgente.
  (instalado vs. disponível, seletivo/lote, pin), respeitando a matriz.

## @E5 — Hardware: reconhecimento de placa

Depende de @E2 (portas) e @E1 (persistência).

- [x] **@E5-T5.1** Varredura completa no boot (portas + chips), cruzando com o
  - `scanner.py`: scan() orquestra ports->chip_info->boards_db->divergence.
    Falha por porta nao cancela varredura. scan_summary() para TUI.
    Validado: ESP32-S3 16MB/8MB detectado, modelo cruzado com banco.
  banco.
- [x] **@E5-T5.2** Re-varredura manual por botão, com aviso de encerramento de
  - 'Buscar placas' na TUI: ConfirmDialog antes de rescan(confirm=True).
    Aviso de interrupcao de processos. Validado.
  processos e confirmação.
- [x] **@E5-T5.3** Interrogação do chip via esptool encapsulada; saída parseada
  (família, revisão, flash, MAC) — dado cru não vaza.
- [x] **@E5-T5.4** Banco de placas JSON por nome de modelo, com chave padrão
  preservada.
- [x] **@E5-T5.5** `key_json_manager(operation, model_name, data=None)`: add
  (não sobrescreve), edit (mescla), remove (recusa padrão); atômico; retorno
  tratado; mensagens em português.
- [x] **@E5-T5.6** Validação do modelo informado contra o chip real; rejeição
  com erro e **trava de acesso** até modelo válido.
- [x] **@E5-T5.7** Proveniência: marcar dado de chip (travado) vs. dado do
  usuário (editável).
- [ ] **@E5-T5.8** Detecção de divergência (dado travado do chip ≠ registrado →
  alerta).
- [x] **@E5-T5.9** Garantir leitura não-destrutiva (interrogar nunca escreve no
  chip).

## @E6 — Hardware: portas e deploy

- [x] **@E6-T6.1** Nome amigável de porta editável, salvo em metadados.
  - `port_config.py`: set_friendly_name(). String livre so para nome.
    Persistido em config_home/port_configs.json atomicamente.
- [x] **@E6-T6.2** Baudrate e demais campos selecionáveis (lista, sem digitação
  - set_baudrate(): aceita so valores de BAUDRATES=[9600..921600].
    Digitacao livre recusada na fronteira.
  livre).
- [x] **@E6-T6.3** Porta em uso inibida na seleção; sem encerramento automático.
  - set_in_use() + list_available_ports() marca campo 'inhibited'.
    TUI decide exibicao; modulo nunca encerra processo.
- [x] **@E6-T6.4** Opções de deploy selecionáveis (PSRAM, partição, debug,
  - set_deploy_option(): psram/debug_level/monitor_output.
    Lista fechada DEPLOY_OPTIONS; valor fora da lista recusado.
  saída do monitor), lista única.
- [x] **@E6-T6.5**
  - `sanity_check()`: compara flash real do chip com ramo escolhido;
    bloqueia se chip < ramo, avisa se subutilizado, ok se igual. Validado.

  - `partition_tables.py` + `partition_tables.yml`: catalogo proprio
    (4/8/16/32MB, 4 variacoes cada, tipos APP/OTA/FATFS/LittleFS);
    gerador de CSV com offsets em branco (seguro); validacoes: teto
    de 8 variacoes e soma que cabe no flash. 16/16 variacoes OK.
 Verificação de sanidade: Flash real (esptool) × tabela de
  partição selecionada, aviso antes do flash.

## @E7 — Workspace

Depende de @E1, @E3, @E5.

- [x] **@E7-T7.1** Operações New / Open / Close / Clone (sem Save manual).
- [ ] **@E7-T7.2** Seleção do diretório de workspace pelo usuário; um diretório
  por projeto na estrutura ESP-IDF.
- [x] **@E7-T7.3** `project_config.json` via camada atômica: nome, versão
  ESP-IDF, entry point, libraries, referência de board, flag do header.
- [x] **@E7-T7.4** Ativação do venv correspondente à versão do projeto ao abrir.
- [x] **@E7-T7.5** Seleção da versão de ESP-IDF pelo usuário (sem inferência;
  sem bloqueio — consequência só em runtime, via monitor).
- [x] **@E7-T7.6** Fechar projeto: encerra monitor, libera porta; **bloqueia se
  houver flash em andamento**.

## @E8 — Programação

Depende de @E5 (pinagem), @E3 (venv/matriz), @E7 (projeto).

- [ ] **@E8-T8.1** Explorador de arquivos (criar/renomear/mover/deletar), sem
  edição.
- [ ] **@E8-T8.2** Integração com editor externo (abrir o projeto/arquivo).
- [ ] **@E8-T8.3** Gestão de bibliotecas: adicionar (Component Registry / Git),
  remover (limpa disco e manifesto), gravação atômica no manifesto.
- [ ] **@E8-T8.4** Trava de versão por biblioteca; compatibilidade contra o venv
  da versão do projeto.
- [x] **@E8-T8.5** Geração de `hardware_pins.h` a partir do JSON de pinagem;
  somente-leitura, reescrito a cada build, com aviso no topo.
  - `board_ascii.py` (validado): diagrama ASCII da placa com contorno,
    duas colunas por `side`, GPIO interno e label externo; coloracao por
    categoria fica para a TUI (Rich).
- [ ] **@E8-T8.6** Validador código-vs-chip antes do build (recurso de família
  incompatível barra a compilação).
- [x] **@E8-T8.7** Build em background (`idf.py build`); captura e colorização
  - `builder.py`: build() ativa ambiente da versao, roda idf.py build,
    classifica linhas (error/warning/info), background com progress_cb.
    check_build_valid() compara mtime fonte vs binario (@E9-T9.1).
    VALIDADO: blink compilado com v5.4.4, proj_blink.bin gerado.
  - Correcoes no idf_manager.activate(): IDF_TOOLS_PATH no env_vars +
    expansao de $PATH literal (cmake/ninja do sistema).
  de erros (sem barra de % precisa).
- [ ] **@E8-T8.8** Templates de projeto no New Project.

## @E9 — Flash

Depende de @E5, @E6, @E7, @E8.

- [x] **@E9-T9.1** Pré-checagem de build válido; binário desatualizado bloqueia
  e avisa (sem compilar sozinho).
- [x] **@E9-T9.2** Encadear a sanidade Flash × partição (@E6-T6.5) antes de
  gravar.
- [x] **@E9-T9.3** Erase opcional, explícito, com confirmação destrutiva
  (irreversível).
- [x] **@E9-T9.4** `write_flash` com progresso real do esptool e teclado travado.
- [x] **@E9-T9.5** Abort com aviso destrutivo e confirmação.

  - `flash/flasher.py`: sanity_check/erase_flash/write_flash/verify_flash + flash() orquestradora. Offsets do flasher_args.json (nao hardcoded). builder.set_target() configura target do chip. VALIDADO com hardware real: ESP32-S3 gravado e verificado (Hash of data verified, verified:True).
- [ ] **@E9-T9.6** Verificação pós-gravação obrigatória.
- [ ] **@E9-T9.7** Oferecer abrir o monitor após sucesso (sem abrir sozinho).

## @E10 — Monitor

Depende de @E2 (portas) e @E1 (log).

- [x] **@E10-T10.1** Componente de exibição único (somente leitura; sem entrada
  - `serial_reader.py`: SerialMonitor + create_monitor. Thread nao-bloqueante,
    callback on_line/on_error, buffer deque limitado, disconnect_stream/reconnect.
    Validado com hardware real ESP32-S3.
  de dados).
- [x] **@E10-T10.2** Buffer de exibição limitado (padrão configurável); descarte
  - deque(maxlen=buffer_lines) em SerialMonitor. clear_screen_buffer() limpa
    so a exibicao. Log em disco preservado independentemente.
  do topo sem perder o log em disco.
- [x] **@E10-T10.3** Controles de exibição: timestamp e quebra de linha.
  - set_timestamp()/set_wordwrap()/get_display_options() em SerialMonitor.
    Thread-safe. Validado.
- [x] **@E10-T10.4** Controles de porta manuais: flush, close, restart.
  - flush_port() (reset_input_buffer no loop), close_port() (alias stop),
    restart_port() (stop+reconnect). Buffer preservado em todos. Validado.
- [x] **@E10-T10.5** Nunca fechar nem limpar automaticamente
  - Por design em SerialMonitor: stop() preserva buffer, clear_screen_buffer()
    so limpa exibicao, log em disco independente.; limpeza de tela
  manual; tela e canal independentes.
- [x] **@E10-T10.6** Três saídas: terminal externo (detecção de emulador +
  - `log_writer.py`: MonitorLogWriter, rotativo 5MB x 3 backups, timestamp,
    read_tail() para visualizador. make_log_path() deriva path da porta.
    Validado com hardware real.
  fallback), console interno ANSI, arquivo de log rotativo por tamanho.
- [x] **@E10-T10.7** Abertura do log pelo menu
  - _action_monitor() na TUI: le ultimas 30 linhas via read_tail(),
    detecta porta ESP automaticamente. Validado com 2 ESPs conectados., reutilizando o monitor como
  visualizador.
- [x] **@E10-T10.8** Prioridade do chip
  - disconnect_stream() libera porta para flash sem fechar/limpar painel.
    reconnect() reestabelece apos flash. Por design em SerialMonitor.: portas diferentes coexistem; mesma
  porta desconecta o stream (sem fechar/limpar) e oferece reconectar.

## @E11 — Versionamento (Git local)

- [x] **@E11-T11.1** Ação "preparar versionamento" (sob demanda, não automática).
- [x] **@E11-T11.2** `git init` + `.gitignore` (build/, sdkconfig.old, caches,
  lixo) + primeiro commit automático.
- [x] **@E11-T11.3** Commits seguintes manuais por menu.
- [x] **@E11-T11.4** Garantir ausência de rede/token/push/pull (fora de escopo).

## @E12 — Instalador, desinstalador e empacotamento

Produzido **ao final**, sobre a estrutura manual já testada (ver "Método de
construção"). Empacota o que já funciona.

- [ ] **@E12-T12.0** Gerar o pacote `.zip` com toda a estrutura testada,
  **incluindo o arquivo-sentinela `.esplab_root` na raiz** (exigido pelo módulo
  `paths` para auto-detecção da raiz fora do modo de desenvolvimento).
- [ ] **@E12-T12.1** Instalador: cria a pasta raiz onde o usuário escolher, copia
  os arquivos, registra manifesto de tudo que toca (caminhos derivados em
  runtime, nada fixo).
- [ ] **@E12-T12.2** Desinstalador reversível (venvs, configs, sudoers, symlinks)
  sem resíduo, a partir do manifesto.
- [ ] **@E12-T12.3** Verificação de pré-requisitos (Python, git, acesso a portas).

---

## Ordem de execução recomendada

```
@E1 → @E2 → @E3 → @E4 → @E5 → @E6 → @E7 → @E8 → @E9 → @E10 → @E11 → @E12
```

@E1–@E4 são fundação (sem elas nada se sustenta). @E5–@E6 entregam o
reconhecimento de hardware. @E7 amarra o projeto. @E8–@E9 entregam o fluxo
principal (programar e gravar). @E10 pode ser desenvolvido em paralelo a partir
de @E2. @E11–@E12 fecham o ciclo.

## Comunicação entre implementadores

Referencie tarefas por **@E#-T#.#** e fases por **@E#**. Mudanças de decisão de
design vão primeiro ao PROJECT.md (fonte de verdade); este arquivo desdobra o
que lá estiver fechado.


---

## Rodada — Reconciliação de doc, tela inicial, painéis e interação (2026-07-28)

Desdobra os adendos incorporados ao **PROJECT.md §13** (fonte de verdade). Onde o
texto original de @E5 diz "por nome de modelo / `model_name`" (T5.4, T5.5), vale
o **Adendo 1** (placas por MAC); os itens abaixo refletem o estado atual.

### Correção de base (o código já superava a doc)
- [x] Placas chaveadas por **MAC**, não por nome de modelo — PROJECT.md Adendo 1
      (corrige @E5-T5.4/T5.5 e §6.3/§6.5/§12).

### Tela inicial — quatro painéis (Adendo 6)
- [x] Painel HARDWARE reescrito: Dispositivo ativo · Recursos da placa · Build
      (sdkconfig) · Detectados.
- [x] Painel PROJETOS (novo): reconciliação projeto↔dispositivo + dependências do
      manifesto + requisito de ESP-IDF.
- [x] Painel LOCAIS: Backup e Bancada (`paths.backups`/`.workbench`, §4).

### Boot e hardware (Adendos 7–10)
- [x] Boot identifica hardware (varredura do menu, sem modal, em worker,
      cancelável).
- [x] Auto-conexão pela placa do projeto (MAC do perfil), sem 2º reset.
- [x] Estado de conexão por MAC (Conectada / Não conectada / Não verificada),
      setter dedicado idempotente.
- [x] Menu "Exibir layout da placa" readicionado; desenho ajustado (título=chip,
      legenda de A, corpo só GPIO, duas colunas, topo alinhado).

### Interação (Adendo 11)
- [x] "Aguarde..." em todo clique de menu.
- [x] Barra de status (laranja) nomeia a tarefa lenta (pontinhos 0→3).
- [x] Rolagem do painel de resultados só acima de 50 linhas (rastro removido).
- [x] Ctrl+C confirma antes de cancelar (boot e flash inclusos).

### Pendências para o passo seguinte (subir ao GitHub)
- [ ] Testar o versionamento local (`git_local`: status → prepare → commit).
- [x] Auditoria pré-público: `.gitignore` (`data/`, `workspace/`, `backups/`,
      `.old`, `__pycache__`, `_workbench/`, `config/`, `.claude/`), segredos,
      histórico recomeçado (sem MACs), caminhos absolutos.
- [ ] Remover exigência de token do `install.py` (repo passa a público).
- [x] `config/` e `workspace/` sobem vazias (`.gitkeep`); sentinela
      `.esplab_root` presente na raiz (empacotamento final: @E12).
- [ ] Subir ao GitHub público e validar instalação limpa pelo instalador.

### Fechamento v1.0.0 (Adendo 12 do PROJECT, 2026-07-29)
- [x] `bump.py` (raiz): incremento SemVer manual-assistido, reusa
      `version.py`; `--set` e `--keep-suffix`. Sem bump automático.
- [x] Versão elevada para `1.0.0` (primeira release pública); barra e "Sobre"
      leem em runtime; README alinhado.
- [x] Tela "Sobre" enriquecida: ciclo, filosofia, famílias ESP32 completas,
      autor, contato, isolamento/responsabilidade, repo marcado público.
- [x] Command palette em português (comandos, placeholder, tooltip, binding);
      "Screenshot" removido; `Ctrl+P` com `show=False` (sem duplicar no rodapé).
- [x] ESC prioriza o painel de ajuda (1º fecha o painel, 2º age no menu).
