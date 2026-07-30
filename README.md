# ESP Lab

**Gerenciador completo do ciclo de desenvolvimento de firmware ESP32, em terminal Linux.**

> Versão 1.0.0 — primeira release pública.

ESP Lab é uma aplicação de terminal (TUI) escrita em Python para conduzir todo
o ciclo de trabalho com placas da família ESP32 — ESP32, S2, S3, C3, C6 e
demais — do preparo do ambiente à gravação e ao monitoramento, com
**segurança** como princípio que orienta cada decisão de design.

---

## O que é

A aplicação cobre, em etapas, o ciclo completo:

1. **Ambiente (Software)** — prepara e valida o terreno: ferramentas, ESP-IDF
   multi-versão, dependências isoladas, atualizações controladas.
2. **Hardware** — reconhece a placa conectada, lê suas características reais do
   chip e gerencia um banco de perfis de placa.
3. **Programação** — organiza o projeto, gerencia bibliotecas e liga o código
   ao hardware (pinagem gerada automaticamente).
4. **Flash** — grava o firmware com validações e confirmações em cada passo
   destrutivo.
5. **Monitor** — exibe a saída serial em tempo real e registra log em disco.
6. **Versionamento** — prepara a estrutura Git local do projeto.

## O que ela não é

- **Não é um editor de código.** A escrita é delegada ao editor externo que
  você já usa (VS Code, vim, etc.). A aplicação cuida de tudo ao redor do
  código.
- **Não é um cliente Git completo.** Prepara o repositório local; o envio para
  a nuvem, se houver, é feito por você, por fora da aplicação.

---

## Filosofia: segurança primeiro

Segurança é a marca do produto e o critério de desempate em todo design:

- **Validação em toda fronteira** — nenhum dado externo entra na lógica sem ser
  validado.
- **Nada age sozinho** — a aplicação mostra o estado real; as decisões
  relevantes e destrutivas são sempre suas, conscientes e explícitas.
- **A falha nunca derruba a aplicação** — erros viram mensagem de status, não
  travamento.
- **Persistência segura** — toda gravação em disco é atômica, resistente a
  queda de energia.

Esses princípios não são abstratos: aparecem na varredura de hardware só no
boot (sem polling que brigue por porta), na confirmação destrutiva antes de
apagar a Flash, no monitor que nunca limpa sozinho, e na recusa de gravar um
binário desatualizado.

---

## Arquitetura

A aplicação é **modular por princípio** — só escala porque é modular. Cada
responsabilidade vive em um módulo isolado com fronteira de dados definida:
recebe o que precisa, faz seu trabalho e exporta dados já normalizados, sem
deixar dados crus vazarem. Adicionar suporte a algo novo (uma família de chip,
uma versão de ESP-IDF) é encaixar uma peça, não reescrever o que já funciona.

### Convenção de idioma

- **Inglês**: estrutura de pastas, arquivos, variáveis, funções, classes,
  chaves de configuração e identificadores em geral.
- **Português**: todas as strings de conteúdo — mensagens ao usuário, avisos,
  confirmações, comentários, logs.

### Stack

| Camada | Tecnologia |
|--------|-----------|
| Linguagem | Python |
| Interface (TUI) | Textual |
| Interação com hardware | esptool |
| Build do firmware | ESP-IDF (multi-versão) |
| Compatibilidade de versões | matriz YAML |
| Banco de placas | JSON |
| Plataforma | Terminal Linux |

---

## Isolamento e múltiplas versões de ESP-IDF

Cada versão de ESP-IDF exige um conjunto de dependências Python próprio e muitas
vezes incompatível com as outras. Por isso, a aplicação mantém **um ambiente
virtual por versão de ESP-IDF** — não é opção, é o que garante que atualizar
uma versão nunca quebre as demais.

A janela de suporte são **três versões fixas** (a partir da linha 4.x, cobrindo
a maioria dos projetos antigos) **mais uma versão corrente** liberada para
atualização. Quando uma nova entra, a mais antiga sai e seu ambiente é removido
por completo.

A compatibilidade entre versões vem de uma **matriz YAML**, que funciona
offline por padrão (a aplicação embarca uma matriz conhecida-boa), só consulta a
rede quando encontra uma versão ainda não registrada, e valida todo dado novo
antes de aceitá-lo.

---

## Requisitos

- Linux com terminal
- Python (gerenciado em ambiente isolado pela própria aplicação)
- `git` instalado (para a preparação de versionamento local)
- Acesso às portas seriais (`/dev/ttyUSB*`, `/dev/ttyACM*`)

Operações que exigem privilégio solicitam a senha de sudo **na hora**, sem nunca
armazená-la. Opcionalmente, o instalador pode criar uma regra `sudoers` restrita
apenas aos comandos necessários, com seu consentimento explícito.

---

## Instalação

Você precisa de **um único arquivo** para instalar: o `install.py`. Ele baixa
o ESP Lab, monta um ambiente isolado e prepara tudo para rodar.

**1. Baixe o instalador e execute-o** (com o Python do sistema):

```bash
curl -LO https://github.com/agaiautomacao-web/ESP-Lab/releases/latest/download/install.py
python3 install.py
```

O instalador **mostra o que vai fazer e pede confirmação** antes de agir:
baixa o ESP Lab do GitHub, cria um ambiente virtual isolado em
`~/esplab/data/app-venv` e gera o script de inicialização (`esplab.sh`).
**Nada fora de `~/esplab/` é modificado** — exceto a regra `sudoers` opcional,
criada só com o seu consentimento explícito.

**2. Abra o ESP Lab:**

```bash
bash ~/esplab/esplab.sh
```

Por padrão, tudo vive dentro de `~/esplab/` (código, `config/`, `data/`,
`workspace/`) — isolamento total. Se preferir os diretórios XDG
(`~/.config/esplab/`, `~/.local/share/esplab/`), defina `XDG_CONFIG_HOME` /
`XDG_DATA_HOME` antes de instalar.

### Se a aplicação não abrir

Ambientes virtuais podem quebrar (uma atualização de sistema, uma dependência
corrompida). Para reconstruir o ambiente **sem reinstalar do zero**,
preservando `config/`, `workspace/` e seus dados:

```bash
python3 ~/esplab/recover.py
```

### Atualizar ou remover

```bash
python3 ~/esplab/install.py --update      # atualiza a instalação existente
python3 ~/esplab/install.py --uninstall   # remove a instalação
```

---

## Uso em resumo

1. Ao abrir, a tela inicial mostra o estado do terreno: sistema, ambiente,
   versões de esptool, ESP-IDF e dependências.
2. A aplicação faz uma varredura completa de portas e chips no boot. Placas
   conectadas depois são reconhecidas por uma re-varredura manual (com
   confirmação).
3. Você seleciona ou cataloga o modelo da placa; a identidade é validada contra
   o chip real pelo esptool antes de liberar o acesso.
4. Organiza o projeto, gerencia bibliotecas e deixa a aplicação gerar o cabeçalho
   de pinos a partir do mapeamento da placa.
5. Compila e grava, com verificação de sanidade e confirmação de cada passo
   destrutivo.
6. Acompanha a saída pelo monitor (terminal externo, painel interno ou registro
   em log).

---

## Documentação do projeto

- **PROJECT.md** — arquitetura e todas as decisões de design, com as
  justificativas. É a fonte de verdade.
- **TASKS.md** — desdobramento em tarefas executáveis, organizadas por fase.
- **README.md** — este documento, a apresentação geral.

---

## Estado atual

Primeira release pública (`1.0.0`). O desenho conceitual de todas as etapas
está fechado e documentado no PROJECT.md; a evolução continua registrada no
TASKS.md, versão a versão.
