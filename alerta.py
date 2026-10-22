#!/usr/bin/env python3
"""
alerta.py — Sistema Comunitário de Alerta e Resposta a Emergências
Protótipo de aplicação P2P sobre o Freechains v0.20.

A aplicação NÃO altera o protocolo: ela apenas executa comandos `freechains`
(post, like, dislike, revoke, reps, list, get, sync) e INTERPRETA os
resultados para exibir estados (PENDENTE / ATIVO / CONFIRMADO / ENCERRADO /
REVOGADO), sugerir ações e listar participantes para avaliação.

Convenção de payload (camada de aplicação, texto puro dentro do post):
    [ALERTA] <texto>
    [CONFIRMA <id-alerta>] <texto>
    [PROTOCOLO <id-alerta>] <texto>      rotas, abrigos, telefones
    [COORD <id-alerta>] <texto>          coordenação durante a crise
    [ENCERRA <id-alerta>] <texto>
    [INFO] <texto>                       informação de rotina (rotas, abrigos)
"""

import argparse
import re
import subprocess
import sys
import time

# --------------------------------------------------------------------------
# Limiares da APLICAÇÃO (não são regras do protocolo; são decisões da UI)
# --------------------------------------------------------------------------
ATIVO_MIN = 15000        # reps do autor para o alerta já nascer ATIVO
CONFIRMADOR_MIN = 10000  # reps mínimos para uma confirmação contar
CONFIRMACOES_MIN = 2     # confirmações válidas para virar CONFIRMADO
COORDENADOR_MIN = 19000  # reps para ser COORDENADOR (publicar protocolo e encerrar)
CONSOLIDADO_SEG = 24 * 3600  # post com 24h+ e não revogado = memória confiável

DEFAULT_CHAIN = "#alertas-rio-madeira"

TAG_RE = re.compile(r"^\[(ALERTA|CONFIRMA|PROTOCOLO|COORD|ENCERRA|INFO|COLETA)(?:\s+([0-9a-fA-F]+))?\]\s*(.*)", re.S)


# --------------------------------------------------------------------------
# Acesso ao Freechains (único ponto de contato com o protocolo)
# --------------------------------------------------------------------------
class Freechains:
    def __init__(self, root=None, now=None, chain=DEFAULT_CHAIN, binary="freechains", verbose=False):
        self.root, self.now, self.chain, self.bin, self.verbose = root, now, chain, binary, verbose

    def _base(self):
        cmd = [self.bin]
        if self.root:
            cmd.append(f"--root={self.root}")
        if self.now:
            cmd.append(f"--now={self.now}")
        return cmd

    def run(self, *args, check=True):
        cmd = self._base() + list(args)
        if self.verbose:
            print("$ " + " ".join(cmd), file=sys.stderr)
        p = subprocess.run(cmd, capture_output=True, text=True)
        if check and p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout).strip() or f"falha: {' '.join(cmd)}")
        return p

    def chain_cmd(self, *args, check=True):
        return self.run("chain", self.chain, *args, check=check)

    # --- ações ---
    def post(self, text, sign, beg=False):
        args = ["post", "inline", text if text.endswith("\n") else text + "\n"]
        if beg:
            args.append("--beg")
        out = self.chain_cmd(*args, f"--sign={sign}").stdout.strip()
        return out.splitlines()[-1] if out else ""

    def vote(self, kind, n, target_type, target, sign, why=None):
        args = [kind, str(n), target_type, target, f"--sign={sign}"]
        if why:
            args.append(f"--why={why}")
        return self.chain_cmd(*args).stdout.strip()

    def revoke(self, kind, n, cid, sign):
        return self.chain_cmd(kind, str(n), cid, f"--sign={sign}").stdout.strip()

    # --- consultas ---
    def order(self):
        out = self.chain_cmd("list", "order").stdout
        return [ln.split()[0].rstrip(".").strip("~") for ln in out.splitlines() if ln.strip()]

    def metadata(self, cid):
        p = self.chain_cmd("get", "metadata", cid, check=False)
        if p.returncode != 0:
            return {"id": cid, "erro": (p.stderr or p.stdout).strip()}
        out = p.stdout
        meta = {}
        for i, ln in enumerate(out.splitlines()):
            ln = ln.split("#")[0].rstrip()
            if not ln:
                continue
            if i == 0 and " " not in ln.strip():
                meta["id"] = ln.strip()
                continue
            k, _, v = ln.strip().partition(" ")
            meta[k] = v.strip()
        meta.setdefault("id", cid)
        return meta

    def payload(self, cid):
        """Retorna o texto, ou None se o payload foi revogado."""
        p = self.chain_cmd("get", "payload", cid, check=False)
        return p.stdout if p.returncode == 0 else None

    def reps_author(self, pub):
        p = self.chain_cmd("reps", "author", pub, check=False)
        return _to_int(p.stdout)

    def reps_action(self, cid):
        p = self.chain_cmd("reps", "action", cid, check=False)
        return _to_int(p.stdout)

    def sync(self, direction, remote):
        return self.chain_cmd("sync", direction, remote).stdout


def _to_int(s):
    m = re.search(r"-?\d+", s or "")
    return int(m.group()) if m else 0


def short(x, n=7):
    return (x or "")[:n]


def short_key(pub):
    return "…" + pub[-8:] if pub else "?"


# --------------------------------------------------------------------------
# Modelo da aplicação (montado lendo a chain)
# --------------------------------------------------------------------------
class Post:
    def __init__(self, cid, meta, text):
        self.id = cid
        self.author = meta.get("sign", "")
        self.time = _to_int(meta.get("time", "0"))
        self.revoked = text is None
        self.text = text or ""
        m = TAG_RE.match(self.text.strip()) if text else None
        self.tag = m.group(1) if m else None
        self.ref = m.group(2) if m else None
        self.body = (m.group(3) if m else self.text).strip()


class App:
    def __init__(self, fc: Freechains):
        self.fc = fc
        self._posts = None
        self._reps = {}

    # --- leitura ---
    def posts(self):
        if self._posts is None:
            self._posts = []
            for cid in self.fc.order():
                meta = self.fc.metadata(cid)
                if meta.get("action", "post") != "post":
                    continue
                self._posts.append(Post(cid, meta, self.fc.payload(cid)))
        return self._posts

    def reps(self, pub):
        if pub not in self._reps:
            self._reps[pub] = self.fc.reps_author(pub)
        return self._reps[pub]

    def find(self, prefix):
        hits = [p for p in self.posts() if p.id.startswith(prefix)]
        if not hits:
            raise SystemExit(f"post '{prefix}' não encontrado")
        return hits[0]

    def related(self, alert_id, tag=None):
        # um post é "filho" do alerta se a referência na tag é prefixo do id
        return [p for p in self.posts()
                if p.ref and alert_id.startswith(p.ref) and (tag is None or p.tag == tag)]

    def now(self):
        return int(self.fc.now) if self.fc.now else int(time.time())

    # --- regra de estado (decisão da UI) ---
    def status(self, alert: Post):
        if alert.revoked:
            return "REVOGADO", []
        valid = sorted({c.author for c in self.related(alert.id, "CONFIRMA")
                        if not c.revoked and c.author != alert.author
                        and self.reps(c.author) >= CONFIRMADOR_MIN})
        encerramentos = [p for p in self.related(alert.id, "ENCERRA")
                         if not p.revoked and (
                             self.reps(p.author) >= COORDENADOR_MIN
                             or (p.author == alert.author and len(valid) < CONFIRMACOES_MIN)
                         )]
        if encerramentos:
            return "ENCERRADO", valid
        if len(valid) >= CONFIRMACOES_MIN:
            return "CONFIRMADO", valid
        if self.reps(alert.author) >= ATIVO_MIN:
            return "ATIVO", valid
        return "PENDENTE", valid

    def alerts(self):
        return [p for p in self.posts() if p.tag == "ALERTA"]

    def revoked_alerts(self):
        # payload revogado: não dá para ler a tag; mostramos como "post revogado"
        return [p for p in self.posts() if p.revoked]

    # --- memória institucional ---
    def suggestions(self, keywords, exclude_after=None):
        kws = [k.lower() for k in keywords if len(k) > 3]
        out = []
        for p in self.posts():
            if p.revoked or p.tag not in ("PROTOCOLO", "INFO"):
                continue
            if exclude_after and p.time >= exclude_after:
                continue
            if self.now() - p.time < CONSOLIDADO_SEG:
                continue
            score = sum(1 for k in kws if k in p.body.lower())
            if score:
                out.append((score, self.fc.reps_action(p.id), p))
        out.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return out

    def coordinators(self):
        authors = {p.author for p in self.posts() if p.author}
        return sorted(((self.reps(a), a) for a in authors if self.reps(a) >= COORDENADOR_MIN), reverse=True)

    def participants(self, alert: Post):
        people = {}
        if alert.author and not alert.revoked:
            people.setdefault(alert.author, []).append(f"ALERTA:{short(alert.id)}")
        for p in self.related(alert.id):
            if p.author and not p.revoked:
                people.setdefault(p.author, []).append(f"{p.tag}:{short(p.id)}")
        return people

    def daily_status(self, pub):
        """Verifica se o usuário já coletou seus reps diários hoje (1x por dia) e sua sequência."""
        hoje = self.now() // 86400
        dias = {p.time // 86400 for p in self.posts() if p.tag == "COLETA" and p.author == pub and not p.revoked}
        coletado_hoje = hoje in dias
        seq = 1 if coletado_hoje else 0
        d = hoje - 1
        while d in dias:
            seq, d = seq + 1, d - 1
        return {"coletado_hoje": coletado_hoje, "sequencia": seq}


# --------------------------------------------------------------------------
# Comandos da CLI
# --------------------------------------------------------------------------
BADGE = {"PENDENTE": "⚪ PENDENTE", "ATIVO": "🔴 ATIVO", "CONFIRMADO": "🚨 CONFIRMADO",
         "ENCERRADO": "✅ ENCERRADO", "REVOGADO": "🚫 REVOGADO"}


def cmd_alertar(app, a):
    cid = app.fc.post(f"[ALERTA] {a.texto}", a.sign, beg=a.beg)
    print(f"Alerta publicado: {cid}")
    app._posts = None
    alert = app.find(cid) if not a.beg else None
    if alert:
        st, _ = app.status(alert)
        print(f"Estado exibido pela UI: {BADGE[st]}  (seus reps: {app.reps(alert.author)})")
        if st == "PENDENTE":
            print(f"→ Aguardando {CONFIRMACOES_MIN} confirmações de membros com ≥ {CONFIRMADOR_MIN} reps.")
        coords = app.coordinators()
        if coords:
            print("→ Notificar coordenadores:", ", ".join(f"{short_key(k)} ({r})" for r, k in coords))
    else:
        print("Post enviado como --beg (sem reps): aguarda um like para entrar na chain.")


def cmd_confirmar(app, a):
    alert = app.find(a.alerta)
    cid = app.fc.post(f"[CONFIRMA {alert.id[:12]}] {a.texto}", a.sign)
    print(f"Confirmação publicada: {cid}")
    if a.like:
        app.fc.vote("like", a.like, "action", alert.id, a.sign, why="confirmo o alerta")
        print(f"Like de {a.like} no alerta {short(alert.id)}.")
    app._posts, app._reps = None, {}
    st, valid = app.status(app.find(alert.id))
    print(f"Estado do alerta agora: {BADGE[st]} ({len(valid)} confirmação(ões) válida(s))")
    if st == "CONFIRMADO":
        print("→ Sugestão: publique o protocolo de resposta com `alerta.py protocolo`.")


def cmd_protocolo(app, a):
    alert = app.find(a.alerta)
    st, _ = app.status(alert)
    words = re.findall(r"\w+", alert.body)
    sugs = app.suggestions(words, exclude_after=alert.time)
    if sugs:
        print("💡 Memória da comunidade (posts consolidados, não revogados):")
        for score, reps, p in sugs[:5]:
            print(f"   [{short(p.id)}] reps {reps:>6} | {p.body.splitlines()[0]}")
    else:
        print("Nenhuma rota/abrigo consolidado encontrado no histórico.")
    if a.texto is None:
        print("\n(use --texto '...' para publicar o protocolo)")
        return
    if app.reps(app_signer_pub(a.sign)) < COORDENADOR_MIN and not a.forcar:
        raise SystemExit(f"Apenas um COORDENADOR (≥ {COORDENADOR_MIN} reps) pode publicar o protocolo de resposta.")
    if st not in ("CONFIRMADO", "ATIVO") and not a.forcar:
        raise SystemExit(f"Alerta está {st}. Use --forcar para publicar mesmo assim.")
    texto = a.texto
    if a.usar_memoria and sugs:
        texto += "\n" + "\n".join("• " + p.body.splitlines()[0] for _, _, p in sugs[:3])
    cid = app.fc.post(f"[PROTOCOLO {alert.id[:12]}] {texto}", a.sign)
    print(f"Protocolo publicado: {cid}")


def cmd_coord(app, a):
    alert = app.find(a.alerta)
    cid = app.fc.post(f"[COORD {alert.id[:12]}] {a.texto}", a.sign)
    print(f"Coordenação publicada: {cid}")


def cmd_encerrar(app, a):
    alert = app.find(a.alerta)
    st, _ = app.status(alert)
    pub = app_signer_pub(a.sign)
    eh_autor_pendente = (pub == alert.author and st == "PENDENTE")
    if app.reps(pub) < COORDENADOR_MIN and not eh_autor_pendente and not a.forcar:
        raise SystemExit(f"Apenas um COORDENADOR (≥ {COORDENADOR_MIN} reps) pode encerrar uma emergência ativa/confirmada.")
    cid = app.fc.post(f"[ENCERRA {alert.id[:12]}] {a.texto}", a.sign)
    print(f"Encerramento publicado: {cid}")
    print("→ Fase de avaliação: `alerta.py participantes", short(alert.id), "`")


def cmd_info(app, a):
    cid = app.fc.post(f"[INFO] {a.texto}", a.sign, beg=a.beg)
    print(f"Informação publicada: {cid}")


def cmd_coletar(app, a):
    """Coleta diária de reps (máx. 1x por dia por usuário).
    Usa a regra consolidação 24h -> +1.000 reps para crescer a comunidade."""
    pub = app_signer_pub(a.sign)
    st = app.daily_status(pub)
    if st["coletado_hoje"]:
        raise SystemExit("⏳ Você já coletou seus reps diários hoje (limite: 1x por dia). Volte amanhã!")
    antes = app.reps(pub)
    cid = app.fc.post("[COLETA] Coleta diaria de reps", a.sign)
    seq = st["sequencia"] + 1
    print(f"🎁 Coleta diária registrada: {cid}")
    print(f"Reps antes: {antes} (custo temporário de 500 descontado agora, devolvido em até 12h)")
    print(f"🔥 Sequência ativa: {seq} dia(s). Em 24h o protocolo consolida e credita +1.000 reps!")


def cmd_painel(app, a):
    alerts = app.alerts()
    if not alerts:
        print("Nenhum alerta na chain.")
    order = {"CONFIRMADO": 0, "ATIVO": 1, "PENDENTE": 2, "ENCERRADO": 3, "REVOGADO": 4}
    rows = []
    for al in alerts:
        st, valid = app.status(al)
        rows.append((order[st], -al.time, st, valid, al))
    rows.sort()
    for _, _, st, valid, al in rows:
        if st in ("ENCERRADO",) and not a.todos:
            continue
        print(f"{BADGE[st]:<14} [{short(al.id)}] autor {short_key(al.author)} ({app.reps(al.author)} reps) "
              f"confirmações válidas: {len(valid)}")
        print(f"      {al.body.splitlines()[0]}")
    rev = app.revoked_alerts()
    if rev:
        print(f"\n🚫 {len(rev)} post(s) revogado(s) pela comunidade (conteúdo oculto, metadados no DAG):")
        for p in rev:
            print(f"      [{short(p.id)}] autor {short_key(p.author)}")


def cmd_ver(app, a):
    al = app.find(a.alerta)
    st, valid = app.status(al)
    print(f"{BADGE[st]}  [{al.id}]")
    print(f"Autor: {al.author}  ({app.reps(al.author)} reps)")
    print(f"Reps do post: {app.fc.reps_action(al.id)}")
    print(f"\n{al.body}\n")
    for p in app.related(al.id):
        flag = " (REVOGADO)" if p.revoked else ""
        print(f"  └─ {p.tag:<9} [{short(p.id)}] {short_key(p.author)} ({app.reps(p.author)} reps){flag}")
        if not p.revoked:
            for ln in p.body.splitlines():
                print(f"       {ln}")


def cmd_participantes(app, a):
    al = app.find(a.alerta)
    people = app.participants(al)
    print(f"Participantes do alerta [{short(al.id)}] (para avaliação pós-emergência):")
    for pub, acts in sorted(people.items(), key=lambda kv: -app.reps(kv[0])):
        print(f"  {short_key(pub)} ({app.reps(pub):>6} reps)  {', '.join(acts)}")
        print(f"      chave: {pub}")
    print("\nAvalie com: alerta.py avaliar <chave> like|dislike <n> --sign=<sua-chave>")


def cmd_avaliar(app, a):
    out = app.fc.vote(a.tipo, a.n, "author", a.chave, a.sign, why=a.motivo)
    print(f"{a.tipo} de {a.n} registrado em {short_key(a.chave)}. {out}")


def cmd_votar(app, a):
    p = app.find(a.post)
    app.fc.vote(a.tipo, a.n, "action", p.id, a.sign, why=a.motivo)
    print(f"{a.tipo} de {a.n} no post {short(p.id)}.")


def cmd_revogar(app, a):
    p = app.find(a.post)
    kind = "unrevoke" if a.desfazer else "revoke"
    app.fc.revoke(kind, a.n, p.id, a.sign)
    print(f"{kind} de {a.n} no post {short(p.id)}.")


def cmd_reps(app, a):
    if a.chave:
        print(app.reps(a.chave))
        return
    authors = {p.author for p in app.posts() if p.author}
    for r, k in sorted(((app.reps(k), k) for k in authors), reverse=True):
        papel = "COORDENADOR" if r >= COORDENADOR_MIN else ("CONFIRMADOR" if r >= CONFIRMADOR_MIN else "membro")
        print(f"{r:>8}  {papel:<12} {k}")


def cmd_sync(app, a):
    for peer in a.peers:
        try:
            app.fc.sync("recv", peer)
            print(f"recebido de {peer}")
        except RuntimeError as e:
            print(f"falha com {peer}: {e}")
        if a.enviar:
            try:
                app.fc.sync("send", peer)
                print(f"enviado para {peer}")
            except RuntimeError as e:
                print(f"falha ao enviar para {peer}: {e}")


def app_signer_pub(sign_path):
    try:
        with open(sign_path + ".pub") as f:
            return " ".join(f.read().split()[:2])
    except OSError:
        return sign_path + ".pub"


# --------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(prog="alerta.py", description="Alertas comunitários sobre Freechains v0.20")
    ap.add_argument("--root", help="diretório do Freechains (repassado como --root)")
    ap.add_argument("--now", help="tempo simulado em segundos (repassado como --now)")
    ap.add_argument("--chain", default=DEFAULT_CHAIN)
    ap.add_argument("--bin", default="freechains", help="executável do freechains")
    ap.add_argument("-v", "--verbose", action="store_true", help="mostra os comandos freechains executados")
    sp = ap.add_subparsers(dest="cmd", required=True)

    def signed(p):
        p.add_argument("--sign", required=True, help="chave privada (ssh-keygen -t ed25519)")
        return p

    p = signed(sp.add_parser("alertar", help="emite um alerta"))
    p.add_argument("texto"); p.add_argument("--beg", action="store_true", help="sem reps: pede entrada")
    p.set_defaults(fn=cmd_alertar)

    p = signed(sp.add_parser("confirmar", help="confirma um alerta (post filho + like opcional)"))
    p.add_argument("alerta"); p.add_argument("texto"); p.add_argument("--like", type=int, default=0)
    p.set_defaults(fn=cmd_confirmar)

    p = sp.add_parser("protocolo", help="sugere memória e publica protocolo de resposta")
    p.add_argument("alerta"); p.add_argument("--texto"); p.add_argument("--sign")
    p.add_argument("--usar-memoria", action="store_true"); p.add_argument("--forcar", action="store_true")
    p.set_defaults(fn=cmd_protocolo)

    p = signed(sp.add_parser("coord", help="mensagem de coordenação"))
    p.add_argument("alerta"); p.add_argument("texto"); p.set_defaults(fn=cmd_coord)

    p = signed(sp.add_parser("encerrar", help="encerra a emergência"))
    p.add_argument("alerta"); p.add_argument("texto"); p.add_argument("--forcar", action="store_true")
    p.set_defaults(fn=cmd_encerrar)

    p = signed(sp.add_parser("info", help="informação de rotina (rotas, abrigos)"))
    p.add_argument("texto"); p.add_argument("--beg", action="store_true"); p.set_defaults(fn=cmd_info)

    p = signed(sp.add_parser("coletar", help="Coleta diária de reps (1x/dia via consolidação 24h)"))
    p.set_defaults(fn=cmd_coletar)

    p = sp.add_parser("painel", help="lista alertas com estado calculado pela UI")
    p.add_argument("--todos", action="store_true", help="inclui encerrados"); p.set_defaults(fn=cmd_painel)

    p = sp.add_parser("ver", help="mostra um alerta e sua thread"); p.add_argument("alerta"); p.set_defaults(fn=cmd_ver)

    p = sp.add_parser("participantes", help="quem participou (para avaliação)")
    p.add_argument("alerta"); p.set_defaults(fn=cmd_participantes)

    p = signed(sp.add_parser("avaliar", help="like/dislike em uma pessoa"))
    p.add_argument("chave"); p.add_argument("tipo", choices=["like", "dislike"]); p.add_argument("n", type=int)
    p.add_argument("--motivo"); p.set_defaults(fn=cmd_avaliar)

    p = signed(sp.add_parser("votar", help="like/dislike em um post"))
    p.add_argument("post"); p.add_argument("tipo", choices=["like", "dislike"]); p.add_argument("n", type=int)
    p.add_argument("--motivo"); p.set_defaults(fn=cmd_votar)

    p = signed(sp.add_parser("revogar", help="revoga (ou desfaz) um post"))
    p.add_argument("post"); p.add_argument("n", type=int); p.add_argument("--desfazer", action="store_true")
    p.set_defaults(fn=cmd_revogar)

    p = sp.add_parser("reps", help="reputação e papel exibido pela UI"); p.add_argument("chave", nargs="?")
    p.set_defaults(fn=cmd_reps)

    p = sp.add_parser("sync", help="sincroniza com peers"); p.add_argument("peers", nargs="+")
    p.add_argument("--enviar", action="store_true"); p.set_defaults(fn=cmd_sync)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    fc = Freechains(root=a.root, now=a.now, chain=a.chain, binary=a.bin, verbose=a.verbose)
    try:
        a.fn(App(fc), a)
    except RuntimeError as e:
        raise SystemExit(f"Erro do Freechains: {e}")


if __name__ == "__main__":
    main()
