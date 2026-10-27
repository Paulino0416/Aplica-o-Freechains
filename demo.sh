#!/usr/bin/env bash
# demo.sh — demonstração do protótipo com 2 nós e tempo simulado (--now).
# Requer: freechains v0.20 no PATH, python3, ssh-keygen.
set -uo pipefail
cd "$(dirname "$0")"
APPDIR=$(pwd)

# dados ficam dentro do projeto (no WSL o /tmp é apagado ao reiniciar)
BASE=$APPDIR/dados
K=$BASE/keys; N1=$BASE/N1; N2=$BASE/N2; P1=8501; P2=8502
C='#alertas-rio-madeira'
DAY=86400
# começa 40 dias no passado: a simulação termina antes de "agora",
# então a interface web pode continuar usando o relógio real
T0=$(( $(date +%s) - 40*DAY ))

pkill -f "git-daemon" 2>/dev/null || true; sleep 1
rm -rf "$BASE"; mkdir -p "$K" "$N1" "$N2"
for u in defesa fernando eva gisele joao; do ssh-keygen -t ed25519 -C '' -N '' -q -f "$K/$u"; done

# configuração da interface web (usuário -> chave + nó)
cat > usuarios.json <<EOF
{
  "chain": "$C",
  "peers": ["localhost:$P1", "localhost:$P2"],
  "usuarios": {
    "Defesa Civil": {"chave": "$K/defesa",   "root": "$N1", "serve": "localhost:$P1"},
    "Fernando":     {"chave": "$K/fernando", "root": "$N1", "serve": "localhost:$P1"},
    "Gisele":       {"chave": "$K/gisele",   "root": "$N1", "serve": "localhost:$P1"},
    "Eva":          {"chave": "$K/eva",      "root": "$N2", "serve": "localhost:$P2"},
    "João (troll)": {"chave": "$K/joao",     "root": "$N2", "serve": "localhost:$P2"}
  }
}
EOF

APP () { local root=$1 t=$2; shift 2; echo; echo ">>> alerta.py $*"; python3 alerta.py --root="$root" --now="$t" "$@"; }
FC  () { echo "\$ freechains $*"; freechains "$@"; }
# publica um alerta e guarda o id em $ID
ALERTAR () { local out; echo; echo ">>> alerta.py alertar $3"
    out=$(python3 alerta.py --root="$1" --now="$2" alertar "$3" --sign="$4"); echo "$out"
    ID=$(sed -n 's/^Alerta publicado: //p' <<<"$out"); }

echo "== Nó 1 cria a chain (Defesa Civil pioneira) e serve; Nó 2 clona =="
FC --root="$N1" --now=$T0 chains add "$C" init --pioneer="$K/defesa.pub"
FC --root="$N1" daemon start --port=$P1 -- --listen=127.0.0.1 --reuseaddr &
sleep 2
FC --root="$N2" chains add "$C" clone localhost:$P1

echo "== Semeadura de confiança (pioneira distribui parte dos seus reps) =="
APP "$N1" $((T0+100)) avaliar "$K/fernando.pub" like 23000 --sign="$K/defesa" --motivo "voluntario"
APP "$N1" $((T0+200)) avaliar "$K/gisele.pub"   like 12000 --sign="$K/defesa" --motivo "abrigo"
APP "$N1" $((T0+300)) avaliar "$K/eva.pub"      like  8000 --sign="$K/defesa" --motivo "lider de rua"
APP "$N1" $((T0+400)) avaliar "$K/joao.pub"     like  3000 --sign="$K/defesa"

echo "== Memória: rota e abrigo publicados semanas antes =="
APP "$N1" $((T0+1*DAY))    info "ROTA enchente Rua Amazonas: Av. Madeira -> Morro do Cruzeiro" --sign="$K/fernando"
APP "$N1" $((T0+1*DAY+60)) info "ABRIGO enchente Rua Amazonas: Escola Municipal, 50 vagas" --sign="$K/gisele"

echo "== Coleta diária ANTES da crise: ninguém contribuiu com alerta ainda => bloqueada =="
APP "$N1" $((T0+2*DAY)) coletar --sign="$K/gisele"
APP "$N2" $((T0+8*DAY+60)) sync localhost:$P1

T=$((T0+30*DAY))
APP "$N2" $T sync localhost:$P1

echo "== Fase 1: Eva alerta (reps < 15000 => PENDENTE) =="
ALERTAR "$N2" $T "Rio subiu 2 m em 3 h. Rua Amazonas alagada, enchente." "$K/eva"; ALERTA=$ID

echo "== Troll publica alarme falso =="
ALERTAR "$N2" $((T+30)) "BARRAGEM ROMPEU fujam todos" "$K/joao"; FALSO=$ID

# Nó 2 também serve; Nó 1 recebe dele
FC --root="$N2" daemon start --port=$P2 -- --listen=127.0.0.1 --reuseaddr &
sleep 2
APP "$N1" $((T+60)) sync localhost:$P2

echo "== Fase 2: confirmações (2 membros com >= 10000 reps => CONFIRMADO) =="
APP "$N1" $((T+120)) confirmar "$ALERTA" "Confirmo, estou na Rua Amazonas" --like 1000 --sign="$K/fernando"
APP "$N1" $((T+180)) confirmar "$ALERTA" "Agua chegou na escola"           --like  500 --sign="$K/gisele"

echo "== Moderação: comunidade derruba o alarme falso =="
APP "$N1" $((T+200)) votar   "$FALSO" dislike 1000 --sign="$K/fernando" --motivo "falso"
APP "$N1" $((T+210)) revogar "$FALSO" 2000 --sign="$K/defesa"

echo "== Fase 3: protocolo com memória da comunidade =="
APP "$N1" $((T+300)) protocolo "$ALERTA" --usar-memoria --sign="$K/fernando" \
    --texto "PROTOCOLO: Bombeiros 193 / Defesa Civil 199"

echo "== Fase 4: coordenação =="
APP "$N1" $((T+400)) coord "$ALERTA" "Levando barco, preciso de 2 voluntarios" --sign="$K/fernando"
APP "$N1" $((T+500)) coord "$ALERTA" "Escola aberta, 12 pessoas" --sign="$K/gisele"
APP "$N1" $((T+600)) painel
APP "$N1" $((T+600)) ver "$ALERTA"

echo "== Coleta diária DEPOIS de ajudar: só quem contribuiu com um alerta válido nas últimas 24h =="
APP "$N2" $((T+690)) sync localhost:$P1
APP "$N2" $((T+700)) coletar --sign="$K/eva"        # emitiu alerta CONFIRMADO => libera
APP "$N2" $((T+710)) coletar --sign="$K/eva"        # 2ª vez no mesmo dia => bloqueada
APP "$N2" $((T+720)) coletar --sign="$K/joao"       # alerta falso foi revogado => bloqueada
APP "$N1" $((T+730)) sync localhost:$P2
APP "$N1" $((T+740)) coletar --sign="$K/fernando"   # confirmou, protocolo e coordenou => libera
APP "$N1" $((T+750)) coletar --sign="$K/gisele"     # confirmou e coordenou => libera
APP "$N2" $((T+760)) sync localhost:$P1

echo "== Encerramento e Fase 5: avaliação =="
APP "$N1" $((T+DAY))     encerrar "$ALERTA" "Todos resgatados" --sign="$K/fernando"
APP "$N1" $((T+DAY+60))  participantes "$ALERTA"
APP "$N2" $((T+DAY+90))  sync localhost:$P1
APP "$N2" $((T+DAY+120)) avaliar "$K/fernando.pub" like 2000 --sign="$K/eva" --motivo "coordenou bem"
APP "$N1" $((T+DAY+150)) sync localhost:$P2
APP "$N2" $((T+DAY+160)) sync localhost:$P1
APP "$N1" $((T+DAY+180)) reps
APP "$N1" $((T+DAY+180)) painel --todos

echo
echo "== Nós continuam rodando para a interface web =="
echo "   python3 servidor_web.py   ->  http://localhost:8080"
echo "   (parar os nós: pkill -f base-path=$BASE)"
