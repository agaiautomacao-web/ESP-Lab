# PROJECT.md — ESP Lab

> Registro de arquitetura e decisões de design.
> Este documento é a fonte de verdade do projeto. README e TASKS derivam dele.

---

## 1. Visão geral

ESP Lab é uma aplicação **TUI (terminal Linux)** em Python para gerenciar o
ciclo completo de desenvolvimento de firmware para placas da família ESP32
(ESP32, S2, S3, C3, C6, etc.): preparação de ambiente, reconhecimento de
hardware, programação, gravação (flash), monitoramento serial e versionamento
local.

A aplicação não tenta ser um editor de código nem um cliente Git completo.
Ela cuida de **tudo ao redor do código**, delegando a escrita ao editor externo
do usuário e o versionamento remoto ao Git/GitHub por fora da aplicação.

### Convenção de idioma

- **Inglês**: estrutura de pastas, nomes de arquivos, variáveis, funções,
  classes, chaves de JSON/YAML e identificadores em geral.
- **Português**: todas as strings de conteúdo — texto visível ao usuário
  (mensagens, labels, avisos, confirmações) e não visível (comentários,
  docstrings, mensagens de log e erro).

### Stack

- Linguagem: Python
- TUI: Textual
- Interação com hardware: esptool
- ESP-IDF: ambiente multi-versão gerenciado
- Dados de compatibilidade: matriz em YAML
- Dados de placas: banco em JSON
- Plataforma alvo: terminal Linux

---

## 2. Filosofia de segurança

Segurança é a marca do produto e o critério que decide os empates de design.
Princípios aplicados de forma transversal:

1. **Validação em toda fronteira** — nenhum dado externo (rede, hardware,
   arquivo, entrada do usuário) entra na lógica sem validação. Dado malformado
   é rejeitado e registrado, nunca absorvido.
2. **Nenhum processo age autonomamente** — a aplicação não toma decisões
   relevantes ou destrutivas sozinha. Ela mostra o estado real e o humano decide.
3. **Decisão destrutiva é sempre consciente e explícita** — operações que
   apagam ou sobrescrevem exigem confirmação clara com aviso do impacto.
4. **A falha nunca derruba a aplicação** — toda operação externa é encapsulada
   com tratamento; falha vira mensagem de status, não crash.
5. **A segurança é feita por nós** — não se confia em nenhuma fonte por
   reputação; confia-se no que a aplicação valida.

---

## 3. Modularidade e escalabilidade

Princípio de arquitetura transversal, válido para todo o código da aplicação.
É declarado aqui, e não apenas implícito nos capítulos das etapas, porque o
implementador pode não ser quem participou do design: sem o princípio
explícito, casos como `key_json_manager` ou o detector de portas pareceriam
soluções isoladas, e não a aplicação de uma regra geral.

### 3.1 A regra

A aplicação só escala se for modular. Crescimento (novas famílias de ESP32,
novas versões de ESP-IDF, novos formatos de placa, novos recursos) deve
acontecer por **encaixe de peças novas**, sem reescrever ou tocar código que já
funciona. Modularidade é o mecanismo; escalabilidade é o resultado. Um não
existe sem o outro.

### 3.2 Módulo com fronteira de dados definida

Cada responsabilidade é um módulo isolado com **entrada e saída definidas**:

- O módulo recebe o que precisa por importação/parâmetro.
- Faz seu trabalho internamente.
- Exporta **dados já convertidos e normalizados** — nunca dados crus.

O dado bruto (saída de texto do esptool, objetos de baixo nível do pyserial,
conteúdo de arquivo não parseado) **nunca vaza** para fora do módulo que o
produz. Quem consome um módulo não sabe nem precisa saber *como* ele obteve o
resultado.

Exemplo (detector de portas): recebe o necessário, varre o barramento, e
devolve uma **lista de portas já tratada e em formato estável** — independente
do sistema operacional ou do chip USB envolvido. Trocar a implementação interna
(de pyserial para outra fonte, por exemplo) não afeta quem usa o módulo, desde
que o formato de saída se mantenha.

### 3.3 Contrato estável entre módulos

A fronteira de cada módulo é um contrato: enquanto a entrada e a saída
definidas forem respeitadas, a implementação interna pode mudar livremente sem
quebrar os consumidores. É isso que permite evoluir um módulo de cada vez.

### 3.4 Exemplos já presentes neste documento

A regra não é nova; vários pontos já decididos são instâncias dela:

- **`key_json_manager`** (6.5): ponto de acesso único ao banco de placas;
  nenhum outro código toca o JSON diretamente.
- **Monitor como visualizador único** (10.5): um componente de exibição, duas
  fontes (stream ao vivo ou arquivo de log) entrando pela mesma fronteira.
- **esptool encapsulado**: a validação recebe dados do chip já parseados, não a
  saída bruta do esptool.
- **Matriz de compatibilidade** (5 / Software): fonte única de verdade
  consultada por uma fronteira, não lida diretamente por cada consumidor.

---

## 4. Caminhos derivados e empacotamento

Princípio de arquitetura transversal, ligado à modularidade e à portabilidade
da aplicação.

### 4.1 Nenhum caminho fixo no código

Nenhum caminho absoluto é escrito como literal no código, em nenhuma hipótese.
Todo caminho **nasce de resolução em tempo de execução**:

- A aplicação descobre a própria raiz em runtime (a partir da localização do
  código em execução e/ou da resolução XDG).
- Todos os subcaminhos (banco de placas, matriz, venvs, logs, projetos) são
  construídos **por composição** a partir dessa raiz descoberta.
- Os diretórios são criados se não existirem.

Consequência: a pasta raiz pode nascer em **qualquer lugar do disco**, e a
aplicação se localiza sozinha e deriva tudo a partir dali. É isso que torna o
pacote distribuível "instalável em qualquer lugar".

### 4.2 Módulo de resolução de caminhos

Existe um módulo único responsável por resolver e entregar caminhos
(`paths`). Ele expõe funções que devolvem cada caminho derivado — nunca uma
constante de caminho. Todo outro módulo **pede os caminhos a ele**, jamais monta
os seus próprios. É a fronteira única para localização no disco, no mesmo
espírito do capítulo 3.

### 4.3 Construção manual, empacotamento ao final

- Durante o desenvolvimento, a estrutura é construída **manualmente**, peça por
  peça, e testada.
- O **instalador e o empacotamento** (`.zip` + instalador que cria a pasta raiz
  e copia os arquivos) são produzidos **somente ao final**, sobre uma estrutura
  já testada — o instalador empacota algo que já funciona, não constrói às
  cegas.
- O instalador permanece reversível e com manifesto (ver Software); apenas sua
  ordem de produção é deslocada para o fim do ciclo.

---

## 5. SOFTWARE (ambiente e base)

### 5.1 Interface

- Aplicação inteiramente em terminal Linux, construída com **Textual**.
- Escolha do Textual sobre curses: entrega painéis, captura/bloqueio de teclas
  por contexto e tratamento de eventos sem reimplementação manual — exatamente
  os pontos críticos desta aplicação. Custo (uma dependência) é irrelevante
  porque as dependências Python já são isoladas em venv.

### 5.2 Versionamento da aplicação

- **SemVer** (`MAJOR.MINOR.PATCH`), começando em `0.1.0`.
- Fonte única de verdade no código; o cabeçalho lê dela, nunca hardcoded em
  dois lugares.

### 5.3 Tela inicial

- **Cabeçalho fixo** (todas as telas): título + versão.
- **Corpo**, linha a linha:
  - System · Version · Kernel (distro, versão, kernel)
  - Environment type (venv ativo / qual)
  - esptool · version
  - ESP-IDF · version
  - Dependencies · versions (pyserial, textual, requests, etc.)
- Verificações lentas (esptool, ESP-IDF, via subprocess) usam **placeholder de
  carregamento** ("verificando…") para não travar o boot; info instantânea
  aparece de imediato.

### 5.4 Privilégios (sudo)

- A senha de sudo **nunca é persistida**. É solicitada via prompt seguro
  (`sudo -S`, sem eco), descartada da memória após o uso.
- O instalador oferece, de forma **opcional e com consentimento explícito**,
  criar uma regra `sudoers.d` restrita aos comandos exatos necessários.
- Essa regra é a única exceção legítima à política de não tocar pastas do
  sistema (vive em `/etc/sudoers.d/`).

### 5.5 Instalador e desinstalador

- Ambos reversíveis. O instalador registra um **manifesto** de tudo que toca.
- O desinstalador remove venvs, configs, regra sudoers (se criada) e symlinks,
  sem deixar resíduo.

### 5.6 Isolamento e ambientes (multi-versão ESP-IDF)

- **Um ambiente virtual (venv) por versão de ESP-IDF.** É obrigatório, não
  opcional.
- Razão: cada versão de ESP-IDF exige um conjunto de dependências Python
  diferente e frequentemente conflitante. Um único venv não pode satisfazer
  múltiplos conjuntos conflitantes — quebraria a garantia "atualizar não quebra".
- Cada versão vive autocontida na pasta da aplicação, com seu próprio venv e
  suas próprias dependências.
- ESP-IDF é tratado como **gerenciador de versões** (instalar / listar /
  ativar / remover), não como item de "atualização" único.

### 5.7 Janela de versões suportadas

- **Três versões fixas** (a partir da linha 4.x) cobrindo a maioria dos
  projetos antigos, **mais uma quarta** que é a versão corrente, liberada para
  atualização.
- Janela deslizante: quando uma nova entra como quarta, a mais antiga sai da
  janela e seu venv é removido por completo (desinstalação limpa).

### 5.8 Diretórios

- Padrão **XDG**: configs em `~/.config/esplab/`, dados em
  `~/.local/share/esplab/`, workspace onde o usuário escolher.
- Não tocar pastas do sistema, exceto a regra sudoers opcional (5.4).

### 5.9 Matriz de compatibilidade

- Mapa entre cada versão de ESP-IDF e o conjunto de versões de dependências
  validadas pela Espressif. Fonte de verdade para qualquer atualização.
- **Formato YAML.**
- **Append-only**: a compatibilidade de uma versão passada é um fato imutável;
  versões novas adicionam linhas, nunca reescrevem as antigas.
- **Offline-first**: a aplicação embarca uma matriz conhecida-boa que sempre
  funciona sem rede. Só consulta a rede quando encontra uma versão de ESP-IDF
  ausente na matriz.
- Rede é conveniência, nunca dependência crítica. Rede caiu → opera com a
  matriz local; falhou ao obter → mantém a versão anterior.
- **Fonte de dados**: arquivos estruturados e versionados por tag do ESP-IDF
  (e Component Registry), priorizados sobre scraping de HTML — HTML quebra em
  silêncio, e silêncio é inimigo da segurança.
- **Validação na fronteira**: todo dado novo passa por validação de esquema e
  de formato de versão antes de ser aceito. Malformado é rejeitado e registrado.

### 5.10 Requirements por versão

- Não há `requirements.txt` único na raiz — seria incapaz de descrever
  conjuntos diferentes por versão.
- A **matriz YAML é a fonte**; o requirements concreto de cada versão é
  **derivado** dela quando a versão é instalada, e consumido pelo pip dentro do
  venv correspondente.

### 5.11 Menu do modo Software — Atualizações

- Categorias com mecanismos distintos:
  - **Dependências Python** (pyserial, textual, requests…): via pip no venv,
    com visão "instalado vs. disponível", atualização seletiva ou em lote, e
    **pin** de versões críticas.
  - **esptool**: mesmo fluxo do pip, destacado por ser crítico.
  - **ESP-IDF**: submenu de gerenciamento de versões (5.6), não "atualizar".
- Toda atualização mostra "antes → depois" e respeita a matriz de
  compatibilidade.

### 5.12 Robustez

- Toda operação externa (esptool, git, subprocess) encapsulada com tratamento e
  log. Falha nunca derruba a TUI; vira mensagem no painel de status.

### 5.13 Bloqueio de teclado em estado crítico

- Durante operações críticas (gravação/flash, captura crítica no monitor), o
  input é restrito; apenas um abort explícito e confirmado é aceito.

---

## 6. HARDWARE

### 6.1 Varredura

- **Varredura completa e automática apenas no boot** (terreno seguro: nada
  gravando). Detecta portas, interroga chips conectados, cruza com o banco e
  confirma.
- **Sem polling contínuo** — varredura constante brigando por porta serial é
  fonte de erro e custo desnecessário.
- **Re-varredura manual** por botão explícito, com aviso de que qualquer
  processo em andamento será encerrado e **confirmação** do usuário. A
  aplicação nunca interrompe um processo por conta própria.

### 6.2 Portas

- **Auto-discovery** no boot via pyserial.
- Filtro por **VID/PID** como critério primário (candidatos prováveis; a
  certeza só vem ao interrogar o chip).
- **Nome amigável editável** (apelido), salvo nos metadados.
- **Baudrate e demais campos: selecionáveis** de lista (sem digitação livre,
  que permitiria valor inválido). Apenas o nome é editável.
- **Porta em uso fica inibida** na seleção; sem encerramento automático.

### 6.3 Reconhecimento de placa

- **Banco de placas em JSON**, manipulado pela interface (não à mão).
- Identificação por **nome do modelo**, não por MAC — o MAC não serve como
  chave de modelo, pois placas iguais têm MACs diferentes.
- Existe uma **chave padrão** preservada, com todos os campos em valores
  default, de onde nascem novos perfis.
- Fluxo:
  1. Placa detectada na porta.
  2. A aplicação pede as características (o usuário informa o modelo, por nome).
  3. Busca pelo nome no banco.
  4. **esptool valida** as funções/características mais relevantes do modelo
     escolhido contra o que o chip realmente reporta.
  5. **Passou** → carrega o perfil e libera acesso à placa.
  6. **Não passou** → rejeita o modelo, retorna erro e **trava qualquer acesso
     à placa** até que um modelo válido seja selecionado.

### 6.4 Proveniência dos dados

- O que vem do chip (família, flash, MAC, revisão) é **confiável e travado**.
- O que o usuário preenche (pinagem, apelido, nome do modelo) é **editável**.
- A distinção permite saber o que pode ser revalidado contra o hardware e o que
  é entrada humana.

### 6.5 Gerenciador único do banco de placas

Porta de entrada única para o JSON; nada toca o arquivo diretamente.

```
key_json_manager(operation, model_name, data=None)
```

- `operation`: "add" | "edit" | "remove"
- `model_name`: chave que identifica o modelo (string)
- `data`: descrições do modelo (obrigatório em add/edit, ignorado em remove)
- Retorna `(ok, result_or_error)` — nunca lança exceção para cima; falha não
  derruba a TUI. Mensagens de retorno em português.
- **add**: não sobrescreve modelo existente em silêncio.
- **edit**: **mescla** campos (preserva o que não veio) — evita perda acidental
  de pinagem.
- **remove**: **recusa** apagar a chave padrão.
- **Escrita atômica** (arquivo temporário + replace) contra corrupção por queda
  de energia.
- **Validação contra hardware fica fora da função** — a função é CRUD puro;
  validação por esptool é camada acima.

### 6.6 Detecção de divergência

- Recurso de segurança: se um dado travado do chip diverge do registrado para
  aquele modelo, a aplicação alerta (hardware trocado, clonado ou problema).

### 6.7 Leitura não-destrutiva

- Interrogar o chip **apenas lê**; nunca escreve nele. Gravar é exclusivo da
  etapa de Flash, sempre por ação explícita.

### 6.8 Deploy

- Opções (PSRAM, tabela de partições, nível de debug, direcionamento do
  monitor) são **selecionáveis** de lista.
- A lista é **a mesma para todos** (não filtrada por chip); o usuário seleciona
  a correta.
- **Verificação de sanidade no momento do flash**: a aplicação compara o
  tamanho real da Flash (lido pelo esptool) contra a tabela de partição
  selecionada e avisa antes de gravar se a escolha for fisicamente impossível.
- O que o esptool consegue conferir (tamanho de Flash, família) é usado como
  rede de segurança no flash; o que não é confiável de checar (ex. PSRAM em
  todas as famílias) fica sob responsabilidade do usuário.

---

## 7. PROGRAMAÇÃO

### 7.1 Editor

- **A aplicação não edita código.** A escrita é delegada ao **editor externo**
  do usuário (VS Code, vim, etc.).
- Razão: um editor de terminal com syntax highlighting, LSP e linter seria um
  projeto do tamanho do resto da aplicação e ainda inferior ao que o usuário já
  tem. Foco no diferencial, não em competir com editores.

### 7.2 Explorador de arquivos

- Árvore de diretórios do projeto: criar, renomear, mover, deletar arquivos.
- **Sem capacidade de edição** — abrir para editar é função do editor externo.

### 7.3 Gestão de bibliotecas

- Adicionar componentes do Espressif Component Registry ou repositórios Git;
  gravar no manifesto (`idf_component.yml` / `CMakeLists.txt`).
- Remover: deleta arquivos físicos e limpa referências de build.
- **Trava de versão** por biblioteca.
- A compatibilidade respeita a **versão de ESP-IDF do projeto** (o venv
  específico, multi-ambiente) — não instala componente que quebra a versão em
  uso. Escrita no manifesto segue a filosofia do `key_json_manager` (ponto
  único, atômica).

### 7.4 Vínculo código ↔ hardware (diferencial central)

- **Header de pinos auto-gerado** (`hardware_pins.h`): a aplicação lê o JSON de
  pinagem (etapa Hardware) e gera defines como `#define LED_STATUS 2`. O
  desenvolvedor usa o nome amigável no código sem decorar GPIOs.
  - O header é **gerado e somente-leitura**, sobrescrito a cada build, com aviso
    no topo de que não deve ser editado à mão.
- **Validador código-vs-chip** antes do build: se o código/biblioteca exige
  recurso de uma família (ex. câmera no S3) e o projeto está em outra (ex. C3),
  a compilação é barrada com alerta.

### 7.5 Build

- Chamado em background (`idf.py build`) via subprocess.
- **Captura e colorização de erros** ao final. Não promete barra de
  porcentagem precisa para o build (o progresso de compilação não é confiável de
  parsear).

### 7.6 Templates e snippets

- **Templates de projeto**: mantidos (encaixam no "Novo Projeto", poupam
  trabalho real).
- **Snippets arrastáveis**: cortados — dependiam de um editor próprio, que não
  existe.

---

## 8. FLASH

Sequência completa:

```
build válido → sanidade (Flash × partição) → [erase opcional] →
write_flash → verificação pós-gravação → oferece monitor
```

### 8.1 Build obrigatório

- O flash é sempre precedido de um build válido. Binário desatualizado (fonte
  mais novo que o binário) ou inexistente **bloqueia o flash** e avisa para
  fazer o build manualmente.
- A aplicação **não compila sozinha** — build é ação explícita do usuário.

### 8.2 Sanidade

- Verificação de Flash real × tabela de partição (6.8) antes de gravar.

### 8.3 Erase

- **Nunca automático.** Opção separada e explícita, com **confirmação
  destrutiva**: apaga toda a Flash, incluindo NVS e dados salvos, irreversível.
- Flash normal (sem erase) é o caminho padrão.

### 8.4 Gravação

- `write_flash` com **progresso real do esptool** (a porcentagem de escrita é
  confiável) e **teclado travado** em estado crítico.

### 8.5 Abort

- Permitido, mas com **aviso destrutivo**: interromper a gravação pode deixar a
  placa inoperante até nova gravação completa. Só prossegue com confirmação.

### 8.6 Verificação pós-gravação

- **Obrigatória.** Confirma que o conteúdo escrito confere com o binário. Custa
  segundos, evita falha silenciosa.

### 8.7 Pós-flash

- A aplicação **oferece** abrir o monitor (não abre sozinha), respeitando a
  não-autonomia e a inibição de porta em uso.

---

## 9. WORKSPACE

### 9.1 Ciclo de vida

- Operações: **New, Open, Close, Clone**.
- **Sem "Save" manual** — não há editor; a aplicação persiste metadados
  automaticamente quando algo muda (pinagem, libs, config).

### 9.2 Estrutura em disco

- O usuário **escolhe o diretório de workspace**; um diretório por projeto
  dentro dele, seguindo a estrutura ESP-IDF (`main/`, `CMakeLists.txt`) mais os
  arquivos da aplicação.

### 9.3 Metadados do projeto

- Arquivo `project_config.json`, manipulado pela mesma filosofia do
  `key_json_manager` (ponto único, escrita atômica, nunca corrompe).
- Registra: nome, versão de ESP-IDF do projeto (aponta para o venv), entry
  point, bibliotecas, referência à pinagem/board, flag do header auto-gerado.

### 9.4 Vínculo projeto ↔ versão de ESP-IDF

- A aplicação **não infere** em que versão o projeto foi escrito — não há forma
  confiável de fazê-lo.
- O **usuário é responsável** por selecionar a versão correta.
- Se errar, **não há prejuízo ao sistema**: carregar, gerar e gravar o `.bin`
  podem funcionar; a consequência aparece em **runtime**, via mensagens do
  próprio chip **no monitor** (panic, reboot loop, comportamento estranho).
- Esses erros são inofensivos e reversíveis (regravar com a versão certa
  resolve); custam apenas tempo do usuário. A aplicação não bloqueia nem tenta
  corrigir.
- Este é um dos motivos do **monitor integral** (capítulo 10): é onde o chip
  conta o que deu errado.

### 9.5 Fechar projeto

- Encerra monitor ativo, libera porta, volta à tela inicial.
- **Fechamento protegido**: bloqueia se houver um flash em andamento.

---

## 10. MONITOR

### 10.1 Natureza

- **Somente exibição** — não é entrada de dados (sem envio serial para o chip).
- **Nunca fecha nem limpa automaticamente**, mesmo em processo crítico. A
  informação exibida pode ser necessária.
- Limpeza de tela é **manual**.

### 10.2 Exibição

- **Buffer de exibição limitado** (padrão configurável): a tela mantém as
  últimas N linhas/caracteres e descarta o excedente do topo, evitando
  travamento de rolagem com conteúdo grande.
- Isso **não conflita** com "nunca limpar": o **arquivo de log** preserva o
  conteúdo integral. Tela leve (performance), log completo (memória).
- Controles: **timestamp** (carimbo de hora por linha) e **quebra de linha**
  (word wrap on/off).

### 10.3 Controles de porta (todos manuais)

- **Flush**: esvazia o buffer enfileirado da serial sem fechar a conexão
  (destrava o fluxo quando dados velhos congestionam o canal).
- **Close**: encerra a conexão com a porta.
- **Restart**: fecha, limpa e reabre a porta (resolve travamentos persistentes).
- Limpeza de **tela** e limpeza de **canal** são independentes; conteúdo já
  exibido nunca some por essas operações.

### 10.4 Saídas

- **Terminal externo**: tempo real, padrão, com detecção do emulador disponível
  (gnome-terminal, konsole, xterm, alacritty) e fallback.
- **Console interno ANSI**: tempo real, fallback dentro da TUI quando não há
  terminal externo.
- **Arquivo de log**: registro em disco, **rotativo por tamanho**, aberto pelo
  menu para análise posterior (não é painel em tempo real).

### 10.5 Monitor como visualizador único

- A leitura posterior de um log **reutiliza o próprio monitor** para exibir. Um
  componente de exibição, duas fontes: stream ao vivo ou arquivo de log.

### 10.6 Prioridade do chip

- Flash e monitor em **portas diferentes**: monitor permanece ativo e visível
  durante o flash, sem conflito.
- **Mesma porta**: o chip tem prioridade absoluta. Ao iniciar o flash, o
  monitor naquela porta **desconecta o stream** (libera a porta) mas **não
  fecha nem limpa** o painel — o conteúdo permanece. Após o flash, a aplicação
  **oferece reconectar**.
- Em caso de falha no lado do monitor durante um flash, a aplicação **não trata
  o monitor** — apenas o desconecta e deixa a gravação seguir intocada.

---

## 11. VERSIONAMENTO (Git local)

### 11.1 Escopo

- **Apenas estrutura Git local.** Sem nuvem, sem API do GitHub, sem token, sem
  push/pull, sem rede.
- A aplicação deixa o projeto pronto para ser versionado e subido manualmente
  pelo usuário, por fora da aplicação, se e quando ele quiser.

### 11.2 Preparação (sob demanda)

- Criada por ação explícita do usuário ("preparar versionamento"), **não
  automática** no Novo Projeto.
- Ao preparar:
  - `git init` (cria o repositório local).
  - Gera o **`.gitignore`** correto (ignora `build/`, `sdkconfig.old`, caches e
    lixo).
  - Faz o **primeiro commit automaticamente**.
- Commits seguintes são **manuais**, por menu.

### 11.3 Fora de escopo

- Sem criação de repositório remoto, push/pull, autenticação ou token. Operações
  destrutivas de histórico remoto (force push) não existem na aplicação.

---

## 12. Resumo das decisões transversais

| Tema | Decisão |
|------|---------|
| Idioma de código | Inglês (identificadores) / Português (strings) |
| TUI | Textual |
| Versionamento da app | SemVer, início em 0.1.0, fonte única |
| Privilégios | sudo nunca persistido; sudoers restrito opcional |
| Isolamento | Um venv por versão de ESP-IDF |
| Versões suportadas | 3 fixas (4.x+) + 1 corrente atualizável, janela deslizante |
| Compatibilidade | Matriz YAML, append-only, offline-first, validada |
| Banco de placas | JSON, por nome de modelo, chave padrão preservada |
| Acesso a JSON | `key_json_manager`, atômico, edit mescla, retorno tratado |
| Edição de código | Externa (delegada) |
| Diferencial | `hardware_pins.h` auto-gerado + validador código-vs-chip |
| Flash | Build obrigatório, sanidade, erase explícito, verificação pós |
| Monitor | Só exibe, nunca limpa sozinho, buffer limitado, prioridade do chip |
| Git | Local apenas, sob demanda, sem nuvem |
| Persistência | Escrita atômica em todo arquivo de estado |


---

## 13. Adendos

> Correções e evolução registradas de forma **append-only**: as seções acima
> permanecem como registro histórico; cada adendo abaixo é numerado e diz qual
> seção **corrige, substitui ou complementa**. **Em conflito, vale o adendo.**
> Esta seção consolida duas rodadas de correção documental (Software e Hardware)
> e a reconciliação de partes que o código já havia superado.

---

### Adendo 1 — Placas chaveadas por MAC (corrige §6.3, §6.5 e §12)

O reconhecimento de placa passou a ser **chaveado por MAC**, não por nome de
modelo. O MAC é o identificador único da placa física (o "CPF da placa"); os
perfis nascem e são reencontrados por ele (`find_or_create_by_mac`). A chave
reservada `default` (somente leitura) segue como base de onde nascem novos
perfis.

- Onde **§6.3** diz "identificação por nome do modelo, não por MAC", leia-se
  **identificação por MAC**. O usuário completa os campos editáveis (pinagem,
  apelido, nome do modelo) sobre o perfil daquele MAC; a validação por esptool
  (família) continua sendo o filtro que libera ou trava o acesso à placa.
- Em **§6.5**, a assinatura é `key_json_manager(operation, mac, data)` — a chave
  é o MAC. As garantias permanecem: `add` não sobrescreve, `edit` mescla,
  `remove` recusa a chave `default`, escrita atômica, validação de hardware fora
  da função (CRUD puro).
- Em **§12**, "Banco de placas: JSON, por nome de modelo" → **por MAC**.

---

### Adendo 2 — Territórios (capítulo transversal, inserir antes de §5)

A aplicação separa três territórios. Todo item de menu pertence a exatamente um,
e é essa pertença — não o hábito — que decide o que cada modo faz e onde uma
função nova encaixa.

1. **Corpo da aplicação** — o app-venv, o código da própria aplicação e sua
   configuração. É *da app*. Provisionado exclusivamente pelo instalador; em
   runtime a aplicação **apenas se observa**, nunca se auto-modifica (feriria
   §2.4). Reparo **e** atualização do corpo são feitos rodando o instalador sob
   demanda (Adendo 5), nunca por menu.
2. **Ambiente de trabalho** — as versões de ESP-IDF (uma com seu venv cada) e os
   editores de terminal. A aplicação **provisiona sob comando do usuário**
   (instalar, ativar, atualizar, remover). É o conteúdo do modo **Software**.
3. **Trabalho do usuário** — o projeto, o código-fonte, a pinagem, os binários.
   É *do usuário*. A aplicação **usa** o ambiente contra ele (Programação, Flash,
   Monitor, Versionamento): lê muito, escreve pouco e só com confirmação, e
   **nunca edita o código-fonte**.

**Régua de encaixe de menu:** *provisionar a ferramenta → Software; usar a
ferramenta contra o projeto → o modo de trabalho correspondente.* Instalar um
editor é Software; abrir um arquivo com ele é Programação.

---

### Adendo 3 — Definição de Software (abertura de §5)

**Software = provisionamento do ambiente de trabalho de que o projeto depende**
(versões de ESP-IDF e editores de terminal). Não abrange o corpo da própria
aplicação (território 1, reparado pelo instalador) nem o uso das ferramentas
contra o projeto (territórios de trabalho).

---

### Adendo 4 — Substitui §5.11 (Menu do modo Software — Atualizações)

O §5.11 original prometia um menu de atualização de dependências Python do app
(pip no venv) que **não existe e não deve existir** (o app-venv é corpo da
aplicação). Fica substituído por:

A atualização no modo Software cobre **apenas o ambiente de trabalho**:

- **ESP-IDF** — gerenciamento de versões (§5.6). Apenas o **slot corrente** (a
  quarta versão, da janela deslizante de §5.7) recebe "atualizar" e "reverter";
  os três slots fixos são congelados. Toda operação mostra "antes → depois" e
  respeita a matriz de compatibilidade (§5.9).
- **Editores de terminal** — instalar, atualizar, escolher o padrão e remover.

O **app-venv não é atualizável por menu** — é território 1; a tela "Estado do
ambiente" o exibe só como leitura (sinal de saúde), e reparo/atualização de fato
são pelo instalador (Adendo 5). O **esptool não é dependência do app**: é
artefato de cada versão de ESP-IDF, exibido por slot.

---

### Adendo 5 — Instalador sob demanda (complementa §5.5)

O instalador é também **invocável sob demanda após a instalação**, e é o
**único caminho para reparar ou atualizar o corpo da aplicação**. Dois gatilhos:
**reparo** (instalação nova com dificuldade de rodar) e **atualização** (versão
mais nova de item do corpo). Em ambos, reconstitui todo o corpo (app-venv +
arquivos da app).

**Escopo:** só o corpo da aplicação (território 1). **Fica de fora o ambiente de
trabalho** — editores e ESP-IDF são geridos no menu (§5.11) e são potencialmente
volumosos. Permanece reversível e com manifesto.

Relevância prática: é o instalador que resolve **instalações novas em plataformas
Linux do usuário final com incompatibilidades** — por isso é peça essencial do
projeto, não opcional.

---

### Adendo 6 — Tela inicial: quatro painéis (substitui §5.3; adiciona §5.3.1)

O §5.3 original descrevia uma lista de coluna única. A tela inicial passou a ser
um **retrato do estado ativo em quatro painéis**, montado no boot, sempre
visível, agrupado pela régua dos territórios:

**SOFTWARE** — ESP-IDF ativa e o esptool dela; editor padrão; e o corpo da app
(versão, Python do app-venv e dependências) em leitura. Verificações lentas usam
placeholder; a info instantânea aparece de imediato.

**HARDWARE** — retrato do **dispositivo físico** presente (não mais identidade de
projeto):
- *Dispositivo ativo*: Porta · Conexão · Placa · MAC · CPU (chip · rev ·
  velocidade) · Flash (tamanho · modo/freq · fabricante) · PSRAM (tamanho físico
  · modo do build) · Cristal · USB · prontidão do perfil desta placa. O físico
  vem da varredura; as facetas de build vêm do `sdkconfig` do projeto ativo (ex.
  `PSRAM 8MB presente · Desabilitada` mostra físico e build lado a lado).
- *Recursos da placa*: contagem de pinos por função (ADC, Touch, UART, SPI,
  Strapping, Octal) do `pinout_mapping`, mais Portas USB com nomes. GPIO e USB de
  dados ficam fora da contagem (GPIO é ~todos; USB é coberto por "Portas USB").
- *Build (sdkconfig)*: Partição e Depuração do projeto ativo.
- *Detectados nesta varredura*: cada dispositivo com família, MAC e estado de
  conexão (Adendo 9).

**PROJETOS** — a reconciliação **projeto ↔ dispositivo** (que saiu do HARDWARE):
Projeto ativo, Perfil/Placa associada, MAC esperado, Target, Prontidão, Última
porta, Estado (confere? pronto para gravar?) e Pendências do perfil. Ampliado com
**Requisito de ESP-IDF** e **Dependências** do manifesto (`idf_component.yml`):
contagem + nomes + travadas.

**LOCAIS** — caminhos derivados (§4): Projetos, Config, Dados, Logs, **Backup** e
**Bancada** (o `_workbench`).

**§5.3.1 — "Estado do ambiente" (menu Software), raio-X sob demanda.** É o
drill-down que o cabeçalho não cabe: todos os slots de ESP-IDF (não só o ativo),
o que está disponível além do instalado, e por qual caminho cada item se
atualiza (menu / instalador / leitura). **Princípio do retorno exibido:** cada
item mostra a que território pertence e como se age sobre ele — o usuário nunca
fica com um dado sem saber o caminho para agir. Os campos de §5.3 e §5.3.1 são
base ilustrativa: extrair e exibir dado disponível **não é divergência de
documento**.

---

### Adendo 7 — Boot identifica hardware (complementa §6.1)

O boot deixou de apenas limpar o contexto de hardware e passou a **identificar as
placas** na montagem da tela: a **mesma varredura** do menu "Identificar e
selecionar portas" (porta → placa: classe, sondagem, chip, MAC, perfil), **sem
modal de seleção**. Roda em **worker** (não bloqueia a montagem) e **trava a
navegação** enquanto corre. A sondagem por chip-id **reseta a placa uma vez** — o
único reset do ciclo; o chip fica em cache (sustenta o Adendo 8). A varredura é
**cancelável** e informa o andamento na barra de status (Adendo 11).

---

### Adendo 8 — Auto-conexão pela placa do projeto (complementa §6.2/§6.3)

No término da varredura, havendo projeto ativo, a aplicação resolve o **MAC
esperado** pelo perfil do projeto (sem sondar) e, se a placa está presente e
selecionável, **conecta a porta automaticamente** — sem modal e sem segundo
reset (reaproveita o chip da varredura). Sem projeto, ou sem MAC correspondente,
as placas ficam apenas identificadas. Efeito: nenhuma operação de perfil/porta
pede mais a seleção manual quando o projeto tem placa presente.

---

### Adendo 9 — Estado de conexão por MAC (complementa §6.5)

Cada placa (por MAC) ganha um estado de **conexão ao vivo**: **Conectada**
(identificada na última varredura), **Não conectada** (esperada por projeto e
ausente) e **Não verificada** (inicial). É **distinto da prontidão do perfil**
(completude, recalculada a cada leitura): registra a **presença física** e **não
é derivado** — gravado explicitamente, sobrevive à normalização.

**Rebaixamento:** placa esperada por projeto ativo e ausente na varredura →
"Conectada" vira "Não conectada". **Escrita:** setter dedicado que não toca
confirmação do perfil nem layout; idempotente; ignora a chave `default`.

---

### Adendo 10 — Menu Hardware: layout sob demanda e desenho (complementa §6.3)

O item **"Exibir layout da placa"** desenha a pinagem ASCII (placa viva, ou do
projeto na falta), **sob demanda** — o painel HARDWARE não carrega o diagrama
completo (só o resumo "Recursos da placa"), para não empurrar os demais painéis
nem exigir rolagem. Desenho: título = identidade do chip (família + variante +
revisão); legenda re-letrada a partir de A (sem GPIO); corpo mostra número + GPIO
apenas; duas colunas; topo alinhado.

**Decisão registrada:** "Associar perfil ao projeto" e "Configurar target do
projeto" **permanecem** no menu Hardware, embora sejam configuração de projeto
sourceada do hardware — decisão adiada, sem prejuízo técnico.

---

### Adendo 11 — Interação e feedback (complementa §5.13 e §5.3)

- **"Aguarde..." em todo clique de menu.** O painel de resultados limpa e mostra
  "Aguarde..." na hora, para não exibir dados do menu anterior.
- **Barra de status (laranja) para tarefas lentas.** Ações em worker acendem a
  barra nomeando o que executa, com três pontinhos animados; some ao terminar.
- **Rolagem do painel de resultados.** Sem barra por padrão; **acima de 50
  linhas** a rolagem interna é ligada e a caixa é limitada.
- **Confirmação ao interromper.** **Ctrl+C** em qualquer operação cancelável
  **pede confirmação** antes de cancelar (boot e flash inclusos). Estende o
  princípio de §5.13 e alinha-se a sair do app e fechar projeto, que já
  confirmam. Ctrl+C ocioso continua não encerrando a aplicação.

---

### Adendo 12 — Fechamento da v1.0.0: versionamento, "Sobre" e localização (2026-07-29)

**Versionamento manual-assistido.** A versão continua vivendo num único lugar
(o arquivo `VERSION`, lido em runtime por `core/version.py`). Acrescentou-se
`bump.py` na raiz — ferramenta de desenvolvimento, roda fora da aplicação —
que incrementa a versão por nível SemVer (`patch`/`minor`/`major`) ou define
explicitamente (`--set X.Y.Z`), reusando a validação de `version.py` (sem
segunda fonte de verdade). O incremento é **manual e consciente**: não há bump
automático por commit — coerente com o princípio "nada age sozinho". Um bump
descarta o sufixo pré-release por padrão (a pré-release virou release);
`--keep-suffix` preserva. A versão foi elevada de `0.1.0` para **`1.0.0`**
(primeira release pública); a barra da TUI e a tela "Sobre" leem o novo número
em runtime, e o README foi alinhado.

**Tela "Sobre" como fronteira pública.** Com o repositório passando a público,
o texto de `_action_about` foi enriquecido: ciclo detalhado por etapa,
filosofia de segurança com exemplos concretos, famílias ESP32 atualizadas
(clássico + S2, S3, C2, C3, C5, C6, C61, H2, H4, H21, P4, conforme o catálogo
oficial da Espressif), autoria (Antonio Goncalves — AG AI Automação), contato
e um parágrafo de **isolamento e responsabilidade** (a aplicação não escreve
fora da própria pasta, roda em ambientes virtuais isolados, na dúvida não
instale, e o autor não se responsabiliza por uso incorreto ou por scripts
alterados). O marcador do repositório passou de "(privado)" para "(público)".

**Localização da command palette (Textual).** Os comandos de sistema, o
placeholder da busca, o tooltip do botão e a descrição da binding `Ctrl+P`
foram traduzidos para português; o comando "Screenshot" foi removido por não
servir ao produto. O `Ctrl+P` foi declarado no `BINDINGS` com `show=False`
para o Footer não duplicar a entrada (ele já a desenha à direita). O **ESC**
passou a priorizar o painel de ajuda: com o `HelpPanel` aberto, o 1º ESC fecha
só o painel (consome o evento) e o 2º age sobre o menu.

**Publicação.** `.gitignore` reescrito para cobrir tudo que é estado de
runtime (`config/`, `workspace/`, `backups/`, `data/`, `_workbench/`,
`.claude/`); `config/` e `workspace/` sobem vazias (via `.gitkeep`). O
histórico git local foi recomeçado para não carregar dados sensíveis
(`boards_db.json` com MACs) de commits antigos. Remote público configurado.

---

### Adendo 13 — Bootstrap do primeiro uso e modelo de distribuição (2026-07-30)

**Modelo de distribuição: `install.py` standalone.** A aplicação não é
distribuída por `git clone`, mas por um instalador de arquivo único. O usuário
baixa apenas o `install.py` (avulso, via `curl` do raw do GitHub) e o executa
com o Python do sistema; ele baixa o repositório público, cria o `app-venv`
isolado em `data/app-venv`, instala as dependências e gera o script de entrada
`esplab.sh`. Rodar a aplicação é `bash esplab.sh` (que usa o Python do venv e
põe `src/` no `PYTHONPATH`). O `install.py` e o `make_release.py` passaram a
ser versionados — sem eles no repositório, o `curl` do README não teria de
onde baixar e o primeiro uso ficaria impossível.

**Recuperação (`recover.py`).** Quando o ambiente quebra (venv corrompido,
dependência ausente), `python3 recover.py` reconstrói o `app-venv` reusando o
`install.py`, preservando `config/`, `workspace/` e o restante de `data/`.
Território 1 (o corpo da aplicação), coerente com o Adendo 5.

**Diretórios criados sob demanda, não versionados.** `paths.py` cria os
diretórios de runtime via `ensure_dirs()` (`config/`, `data/`, `logs/`,
`run/`, `envs/`, `esp-idf/`, `workspace/`) no boot. Por isso `data/`,
`backups/` e `_workbench/` não sobem ao repositório: são recriáveis e/ou
pesados (venvs e ESP-IDF são específicos da máquina — caminhos absolutos
embutidos não sobrevivem a outra instalação). O default é tudo dentro de
`app_root` (isolamento total); XDG só se `XDG_CONFIG_HOME`/`XDG_DATA_HOME`
estiverem definidos.

**`install.py`: fallback para `main` e confirmação.** Sem `--branch`/
`--version`, o instalador tentava a última release (GitHub Releases API); como
pode não haver release publicada, isso abortava. Agora, na ausência de
release, cai para o branch `main` (que sempre existe), avisando. Releases,
quando existirem, mantêm prioridade. Além disso, numa instalação nova o
`install.py` passou a **mostrar o que fará e pedir confirmação** antes de
baixar/instalar — coerente com "nada age sozinho" (§5.13).

**Publicar o ESP Lab vs. versionar projetos.** Registro de uma distinção que
gerou confusão: o menu **Versionamento** da TUI versiona os **projetos ESP32
do usuário** no workspace (opera em `self._projeto_ativo`), não o código do
ESP Lab. Publicar o próprio ESP Lab é tarefa do autor, feita **apenas** pelo
`publish.py` (o app não o invoca). São dois repositórios Git com propósitos
distintos; um eventual atalho no app para publicar o ESP Lab seria item
separado do "Commit" de projetos (decisão adiada).
