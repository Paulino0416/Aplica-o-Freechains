# Sistema Comunitário de Alerta e Resposta a Emergências — protótipo sobre Freechains

Aplicação P2P de linha de comando que usa a **reputação do Freechains v0.20** para decidir **como exibir alertas**, **quem é chamado para coordenar** e **quem deve ser avaliado** depois de uma emergência.

O protocolo **não é alterado**: a aplicação só executa comandos `freechains` e interpreta os resultados.

```
┌──────────────────────────────┐
│ alerta.py (UI / aplicação)   │  estados, sugestões, participantes
└──────────────┬───────────────┘
               │ subprocess: freechains post|like|dislike|revoke|reps|list|get|sync
┌──────────────▼───────────────┐
│ Freechains v0.20 (protocolo) │  DAG, reps, consenso, revogação, gossip
└──────────────────────────────┘
```

---

## a. Manual de utilização

### Instalação
```bash
sudo apt install git openssh-client lua5.4 luarocks python3
sudo luarocks --lua-version=5.4 install freechains
git clone <este-repositorio> && cd <este-repositorio>
```
No Windows, use o WSL (`wsl --install -d Ubuntu`) e rode os comandos acima dentro do Ubuntu.

### Primeiros passos
```bash
# 1. identidade
ssh-keygen -t ed25519 -C '' -f ~/.ssh/eva

# 2a. criar a chain (pioneiro, ex.: Defesa Civil) ...
freechains chains add '#alertas-rio-madeira' init --pioneer=~/.ssh/defesa.pub
# 2b. ... ou entrar clonando de um vizinho
freechains chains add '#alertas-rio-madeira' clone <ip-do-vizinho>

# 3. servir a chain para outros peers
freechains daemon start
```

### Opções globais
| Opção | Efeito |
|---|---|
| `--root=<dir>` | repassado ao `freechains` (vários nós na mesma máquina) |
| `--now=<secs>` | tempo simulado, repassado ao `freechains` |
| `--chain=<nome>` | padrão: `#alertas-rio-madeira` |
| `-v` | mostra cada comando `freechains` executado |

### Interface web (recomendado)
```bash
bash demo.sh                 # cria 2 nós, usuários, histórico e gera usuarios.json
python3 servidor_web.py      # abre em http://localhost:8080
```
Na página:
| Elemento | Função |
|---|---|
| **Usuário (nó)** | troca entre Defesa Civil, Fernando, Eva, Gisele e João; mostra seus reps e papel |
| **🎁 Coletar Reps Diários (+1.000)** | botão de coleta diária (1x/dia, liberado **apenas para quem emitiu um alerta válido ou participou ajudando em um alerta nas últimas 24h**; gera +1.000 reps após 24h pela consolidação do protocolo) |
| **Emitir alerta / Publicar informação** | posta `[ALERTA]` ou `[INFO]`; "sem reps (--beg)" para novatos |
| **Cartões de alerta** | cor por estado (cinza PENDENTE, vermelho ATIVO, vermelho pulsando CONFIRMADO, verde ENCERRADO) e a thread de respostas |
| ✅ Confirmar | post `[CONFIRMA]` + like opcional no alerta |
| 🚀 Protocolo | exclusivo para **COORDENADOR** (≥ 19.000 reps): abre as **sugestões da memória** (rotas e abrigos consolidados) para incluir no protocolo |
| 🧭 Coordenar / 🏁 Encerrar | posts `[COORD]` / `[ENCERRA]` (encerramento restrito a **COORDENADOR**, ou ao próprio autor enquanto PENDENTE) |
| ⭐ Participantes / avaliar | lista apenas quem participou diretamente do alerta (emissão, confirmação, protocolo, coordenação ou encerramento), com 👍/👎 direto na pessoa |
| 👍 👎 🚫 | like, dislike e revoke em posts; os revogados aparecem numa caixa com "desfazer revogação" (unrevoke) |
| 🏅 Reputação | ranking com barras e selo membro / CONFIRMADOR / COORDENADOR |
| ⇄ Sincronizar | `sync recv` entre os nós (também ocorre automaticamente após qualquer ação na web) |
| ⏱ `--now` | tempo simulado, opcional |

Para usar com chaves e nós próprios, edite o `usuarios.json`:
```json
{ "chain": "#alertas-rio-madeira",
  "peers": ["192.168.0.10", "192.168.0.11"],
  "usuarios": { "Eva": {"chave": "/home/eva/.ssh/eva", "root": "/home/eva/.freechains"} } }
```

### Comandos (CLI)
| Comando | Fase | O que faz |
|---|---|---|
| `coletar --sign=K` | – | Coleta diária de reps (1x/dia, condicionada a ter emitido um alerta válido ou ajudado em um alerta nas últimas 24h; gera +1.000 reps após 24h pela consolidação) |
| `alertar "<texto>" --sign=K [--beg]` | 1 | Publica `[ALERTA]` e mostra o estado e os coordenadores a notificar. Use `--beg` se você não tem reps. |
| `confirmar <id> "<texto>" --sign=K [--like N]` | 2 | Publica `[CONFIRMA id]` e, se pedido, dá um like no alerta |
| `protocolo <id> [--texto "..."] [--usar-memoria] --sign=K` | 3 | Busca rotas e abrigos **consolidados** no histórico e publica `[PROTOCOLO id]` (restrito a COORDENADOR) |
| `coord <id> "<texto>" --sign=K` | 4 | Mensagem de coordenação `[COORD id]` |
| `encerrar <id> "<texto>" --sign=K` | 5 | Publica `[ENCERRA id]` e libera a avaliação (restrito a COORDENADOR) |
| `participantes <id>` | 5 | Lista quem participou diretamente do alerta (`ALERTA`, `CONFIRMA`, `PROTOCOLO`, `COORD`, `ENCERRA`) |
| `avaliar <chave.pub> like\|dislike N --sign=K` | 5 | Avalia uma **pessoa** (`like … author`) |
| `votar <id> like\|dislike N --sign=K` | – | Avalia um **post** (`like … action`) |
| `revogar <id> N --sign=K [--desfazer]` | – | `revoke` ou `unrevoke` |
| `info "<texto>" --sign=K` | – | Rotina: rotas, abrigos (vira memória após 24h) |
| `painel [--todos]` | – | Alertas ordenados por estado, mais os posts revogados |
| `ver <id>` | – | Alerta com a thread de confirmações, protocolo e coordenação |
| `reps [chave]` | – | Reputação e papel exibido (membro / confirmador / coordenador) |
| `sync <peer>... [--enviar]` | – | `sync recv` (e `send`) com cada peer |

### Exemplo rápido
```bash
python3 alerta.py alertar "Rio subiu 2 m em 3 h. Rua Amazonas alagada." --sign=~/.ssh/eva
python3 alerta.py painel
python3 alerta.py confirmar a1b2c3d "Confirmo no local" --like 1000 --sign=~/.ssh/fernando
python3 alerta.py confirmar a1b2c3d "Agua chegou na escola" --like 500 --sign=~/.ssh/gisele
python3 alerta.py coletar --sign=~/.ssh/eva       # liberado pois emitiu alerta válido (CONFIRMADO)
python3 alerta.py coletar --sign=~/.ssh/fernando  # liberado pois ajudou confirmando o alerta
python3 alerta.py protocolo a1b2c3d --usar-memoria --texto "Bombeiros 193" --sign=~/.ssh/fernando
python3 alerta.py encerrar a1b2c3d "Todos resgatados" --sign=~/.ssh/fernando
python3 alerta.py participantes a1b2c3d
```

### Demonstração completa
```bash
bash demo.sh
```
Cria 2 nós, uma pioneira, voluntários e um troll. Percorre as 5 fases com `--now`, incluindo a revogação do alarme falso e a validação da coleta diária condicionada à participação em alertas válidos.

---

## b. O que foi implementado

1. **Estados de alerta calculados pela UI** (lendo `reps author`, posts e payloads):
   | Estado | Regra da aplicação |
   |---|---|
   | ⚪ PENDENTE | autor com menos de 15.000 reps |
   | 🔴 ATIVO | autor com 15.000 reps ou mais |
   | 🚨 CONFIRMADO | 2 ou mais `[CONFIRMA]` de autores **diferentes** (exceto o próprio autor do alerta), cada um com pelo menos 10.000 reps |
   | ✅ ENCERRADO | existe um `[ENCERRA id]` publicado por um **COORDENADOR** (≥ 19.000 reps) ou pelo próprio autor enquanto PENDENTE |
   | 🚫 REVOGADO | `get payload` falha (payload revogado pelo protocolo) |
2. **Convenção de mensagens** no payload (`[ALERTA]`, `[CONFIRMA id]`, `[PROTOCOLO id]`, `[COORD id]`, `[ENCERRA id]`, `[INFO]`, `[COLETA]`), usada para montar threads sem alterar o formato dos posts do protocolo.
3. **Coleta diária de reps condicionada à contribuição (1x/dia)**: botão `🎁 Coletar Reps Diários (+1.000)` e comando `coletar` (gerando +1.000 reps após 24h pela Regra 1.b de consolidação do protocolo) liberados **exclusivamente para quem contribuiu nas últimas 24h**:
   - **Emitindo um alerta válido** (que atingiu estado `ATIVO` ou `CONFIRMADO`, e não foi revogado); **ou**
   - **Participando/ajudando no alerta de outra pessoa** (com `[CONFIRMA]`, `[PROTOCOLO]`, `[COORD]` ou `[ENCERRA]` não revogados).
   - Usuários sem contribuição recente ou que emitiram apenas alarmes falsos/revogados ficam com a coleta bloqueada (`🔒`). Limite de 1 coleta por dia com contagem de sequência (`🔥`).
4. **Papéis por reputação e controle de permissões na UI/aplicação**:
   - `membro` (< 10.000 reps): emite alertas (que nascem `PENDENTE`), coordena e vota.
   - `CONFIRMADOR` (≥ 10.000 reps): suas confirmações contam para validar alertas pendentes.
   - `COORDENADOR` (≥ 19.000 reps): único papel autorizado a publicar o `[PROTOCOLO]` de resposta e a `[ENCERRA]` emergências ativas/confirmadas; listado automaticamente para notificação quando um alerta é aberto.
5. **Memória institucional**: `protocolo` busca posts `[INFO]`/`[PROTOCOLO]` antigos que têm palavras em comum com o alerta, têm 24h ou mais (consolidados) e não foram revogados. Ordena pelos reps do post (`reps action`) e, com `--usar-memoria`, inclui os melhores no novo protocolo.
6. **Lista de participantes diretos** para a avaliação pós-emergência: filtra exclusivamente quem participou daquele alerta específico (autor do `[ALERTA]` e autores de `CONFIRMA`, `PROTOCOLO`, `COORD` e `ENCERRA` não revogados daquele alerta).
7. **Avaliação, moderação e travas de segurança na UI**: like/dislike em autor e em post, revoke e unrevoke, com bloqueio contra dar like/dislike em si mesmo ou no próprio post (evitando queimar a taxa de 10% por acidente) e bloqueio contra auto-confirmação do próprio alerta.
8. **Entrada sem reps** com `--beg`.
9. **Sincronização P2P** (`sync recv/send`) manual e automática entre os nós locais após ações na interface web.
10. **Simulação de tempo e de vários nós** (`--now`, `--root`) e um `demo.sh` reproduzível.
11. **Interface web** (`servidor_web.py` + `web/index.html`): painel de alertas colorido por estado, botão de coleta diária de reps (1x/dia), threads, botões contextuais conforme o papel do usuário, diálogo de protocolo com sugestões da memória, tela de avaliação dos participantes do alerta, ranking de reputação, troca de usuário/nó, sincronização e atualização automática a cada 15 s.

## c. O que **não** foi implementado

- **App móvel / instalável e autenticação individual por dispositivo**: a interface web é local (`localhost:8080`) e permite alternar entre os perfis/nós da simulação em um seletor para fins de demonstração do protótipo.
- **Notificações push reais**: a UI apenas *lista* quais coordenadores deveriam ser notificados.
- **Confirmação por likes**: o estado CONFIRMADO conta *posts* `[CONFIRMA]`, não likes, porque a contagem de likes por votante não é exposta individualmente pela CLI de consulta. O like opcional no alerta é executado, mas a validação de estado usa o post assinado `[CONFIRMA]`.
- **Fotos/anexos** (`post file`) e **geolocalização/mapa**: a "mesma rua/região" é aproximada por palavras em comum no texto.
- **Chains privadas/criptografadas**: toda a coordenação acontece na chain pública `#alertas-rio-madeira`.
- **Ações automáticas de protocolo**: nada é postado sem um humano clicar ou executar o comando.
- **Integração externa com sistemas oficiais** (193/199): a Defesa Civil e voluntários operam como pares dentro da própria chain.
- **Descoberta automática de peers na rede local (mDNS/DHT)**: os peers conhecidos são lidos do arquivo `usuarios.json`.
- **Cache/índice em banco de dados**: a cada leitura a aplicação consulta o estado da chain via CLI (`list order` + `get`). Funciona bem para o protótipo, mas exigiria indexação local em chains com milhares de posts.
- **Testes unitários automatizados** (a verificação é feita pelo script ponta a ponta `demo.sh`).

## d. Ferramentas utilizadas

| Ferramenta | Uso |
|---|---|
| **Freechains v0.20** (Lua 5.4 + Git) | protocolo P2P: DAG, reputação, revogação, sincronização |
| **Python 3**, só a biblioteca padrão (`argparse`, `subprocess`, `re`, `http.server`, `json`) | lógica da aplicação, CLI e servidor web |
| **HTML + CSS + JavaScript puro** (sem frameworks) | interface web |
| **Bash** | `demo.sh` (cenário reproduzível) |
| **OpenSSH (`ssh-keygen`, ed25519)** | identidades dos usuários |
| **Git / git daemon** | base de armazenamento e transporte usada pelo Freechains |
| **WSL (Ubuntu)** | execução no Windows |
| **GitHub** | hospedagem do código |

---

### Estrutura
```
alerta.py         # lógica da aplicação + CLI
servidor_web.py   # servidor HTTP + API JSON (reaproveita alerta.py)
web/index.html    # interface web
demo.sh           # 5 fases com 2 nós e --now; gera usuarios.json
README.md
```
