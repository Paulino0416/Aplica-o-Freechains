#!/usr/bin/env python3
"""
servidor_web.py — Interface web do Sistema Comunitário de Alerta e Resposta.

Servidor HTTP local (só biblioteca padrão) que reaproveita a lógica do
alerta.py. Toda ação vira um comando `freechains`; o protocolo não é alterado.

Uso:
    python3 servidor_web.py [--config usuarios.json] [--porta 8080]
e abra http://localhost:8080
"""

import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import alerta as A

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = {}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def usuario(nome):
    u = CONFIG["usuarios"].get(nome)
    if not u:
        raise ValueError(f"usuário '{nome}' não está em usuarios.json")
    return u


def app_para(nome, now=None):
    u = usuario(nome)
    fc = A.Freechains(root=u.get("root"), now=now or None,
                      chain=CONFIG.get("chain", A.DEFAULT_CHAIN),
                      binary=CONFIG.get("freechains", "freechains"))
    return A.App(fc), u


def pub_de(chave_privada):
    try:
        with open(chave_privada + ".pub") as f:
            return " ".join(f.read().split()[:2])
    except OSError:
        return ""


def nome_de_pub(pub):
    for nome, u in CONFIG["usuarios"].items():
        if pub and pub_de(u["chave"]) == pub:
            return nome
    return A.short_key(pub)


def papel(reps):
    if reps >= A.COORDENADOR_MIN:
        return "COORDENADOR"
    if reps >= A.CONFIRMADOR_MIN:
        return "CONFIRMADOR"
    return "membro"


def post_json(app, p):
    return {"id": p.id, "curto": A.short(p.id), "tag": p.tag, "texto": p.body,
            "autor": nome_de_pub(p.author), "reps_autor": app.reps(p.author) if p.author else 0,
            "tempo": p.time, "revogado": p.revoked}


def sincronizar_todos(now=None):
    """Sincroniza automaticamente os nós locais após uma ação na interface web."""
    vistos = set()
    nos = []
    for u in CONFIG.get("usuarios", {}).values():
        r = u.get("root")
        if r and r not in vistos:
            vistos.add(r)
            nos.append((r, u.get("serve")))
    peers = CONFIG.get("peers", [])
    for _ in range(2):
        for root, serve in nos:
            fc = A.Freechains(root=root, now=now or None,
                              chain=CONFIG.get("chain", A.DEFAULT_CHAIN),
                              binary=CONFIG.get("freechains", "freechains"))
            for p in peers:
                if p != serve:
                    try:
                        fc.sync("recv", p)
                    except RuntimeError:
                        pass


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def api_estado(q):
    nome = q.get("usuario", [None])[0] or next(iter(CONFIG["usuarios"]))
    app, u = app_para(nome, q.get("now", [None])[0])
    meu_pub = pub_de(u["chave"])
    alertas = []
    for al in app.alerts():
        st, validos = app.status(al)
        d = post_json(app, al)
        d.update(status=st, confirmacoes=[nome_de_pub(v) for v in validos],
                 reps_post=app.fc.reps_action(al.id),
                 thread=[post_json(app, p) for p in app.related(al.id)])
        alertas.append(d)
    ordem = {"CONFIRMADO": 0, "ATIVO": 1, "PENDENTE": 2, "ENCERRADO": 3, "REVOGADO": 4}
    alertas.sort(key=lambda d: (ordem[d["status"]], -d["tempo"]))

    ranking = []
    for n, uu in CONFIG["usuarios"].items():
        r = app.reps(pub_de(uu["chave"]))
        ranking.append({"nome": n, "reps": r, "papel": papel(r), "pub": pub_de(uu["chave"])})
    ranking.sort(key=lambda d: -d["reps"])

    diario = app.daily_status(meu_pub)
    return {
        "usuario": nome, "meus_reps": app.reps(meu_pub), "meu_papel": papel(app.reps(meu_pub)),
        "coletado_hoje": diario["coletado_hoje"], "sequencia": diario["sequencia"],
        "alertas": alertas,
        "revogados": [post_json(app, p) for p in app.revoked_alerts()],
        "infos": [post_json(app, p) for p in app.posts() if p.tag == "INFO" and not p.revoked][-10:],
        "ranking": ranking,
        "limiares": {"ativo": A.ATIVO_MIN, "confirmador": A.CONFIRMADOR_MIN,
                     "confirmacoes": A.CONFIRMACOES_MIN, "coordenador": A.COORDENADOR_MIN},
        "usuarios": list(CONFIG["usuarios"].keys()),
    }


def api_sugestoes(q):
    app, _ = app_para(q["usuario"][0], q.get("now", [None])[0])
    al = app.find(q["alerta"][0])
    sug = app.suggestions(re.findall(r"\w+", al.body), exclude_after=al.time)
    return {"sugestoes": [{"id": p.id, "curto": A.short(p.id), "texto": p.body,
                           "reps_post": r, "autor": nome_de_pub(p.author)} for _, r, p in sug[:5]]}


def api_participantes(q):
    app, _ = app_para(q["usuario"][0], q.get("now", [None])[0])
    al = app.find(q["alerta"][0])
    out = []
    for pub, acts in app.participants(al).items():
        out.append({"nome": nome_de_pub(pub), "pub": pub, "reps": app.reps(pub), "acoes": acts})
    out.sort(key=lambda d: -d["reps"])
    return {"participantes": out}


def api_acao(body):
    nome = body["usuario"]
    now = body.get("now")
    app, u = app_para(nome, now)
    k = u["chave"]
    meu_pub = pub_de(k)
    fc = app.fc
    a = body["acao"]
    txt = (body.get("texto") or "").strip()

    if a == "alertar":
        cid = fc.post(f"[ALERTA] {txt}", k, beg=body.get("beg", False))
        sincronizar_todos(now)
        return {"ok": f"Alerta publicado ({A.short(cid)})"}
    if a == "info":
        cid = fc.post(f"[INFO] {txt}", k, beg=body.get("beg", False))
        sincronizar_todos(now)
        return {"ok": f"Informação publicada ({A.short(cid)})"}
    if a == "coletar":
        st = app.daily_status(meu_pub)
        if st["coletado_hoje"]:
            raise ValueError("⏳ Você já coletou seus reps diários hoje (limite: 1x por dia). Volte amanhã!")
        cid = fc.post("[COLETA] Coleta diaria de reps", k, beg=body.get("beg", False))
        sincronizar_todos(now)
        seq = st["sequencia"] + 1
        return {"ok": f"🎁 Coleta diária realizada ({A.short(cid)}) — 🔥 {seq} dia(s) seguido(s)! +1.000 reps em 24h"}
    if a in ("confirmar", "protocolo", "coord", "encerrar"):
        al = app.find(body["alerta"])
        st_al, _ = app.status(al)
        if st_al == "ENCERRADO":
            raise ValueError("Este alerta já foi encerrado.")
        if a == "confirmar" and al.author == meu_pub:
            raise ValueError("Você não pode confirmar o próprio alerta.")
        if a == "protocolo" and app.reps(meu_pub) < A.COORDENADOR_MIN:
            raise ValueError(f"Apenas um COORDENADOR (≥ {A.COORDENADOR_MIN} reps) pode publicar o protocolo de resposta.")
        if a == "encerrar":
            eh_autor_pendente = (meu_pub == al.author and st_al == "PENDENTE")
            if app.reps(meu_pub) < A.COORDENADOR_MIN and not eh_autor_pendente:
                raise ValueError(f"Apenas um COORDENADOR (≥ {A.COORDENADOR_MIN} reps) pode encerrar uma emergência ativa/confirmada.")
        tag = {"confirmar": "CONFIRMA", "protocolo": "PROTOCOLO", "coord": "COORD", "encerrar": "ENCERRA"}[a]
        if a == "protocolo" and body.get("memoria"):
            txt += "\n" + "\n".join("• " + s for s in body["memoria"])
        cid = fc.post(f"[{tag} {al.id[:12]}] {txt}", k)
        msg = f"{tag} publicado ({A.short(cid)})"
        if a == "confirmar" and int(body.get("like") or 0) > 0:
            fc.vote("like", int(body["like"]), "action", al.id, k, why="confirmo o alerta")
            msg += f" + like de {body['like']}"
        sincronizar_todos(now)
        return {"ok": msg}
    if a in ("like", "dislike"):
        n = int(body["n"])
        if body.get("pessoa"):
            if body["pessoa"] == meu_pub:
                raise ValueError("Não é permitido dar like/dislike em si mesmo (queimaria 10% dos seus reps).")
            fc.vote(a, n, "author", body["pessoa"], k, why=body.get("motivo") or None)
            sincronizar_todos(now)
            return {"ok": f"{a} de {n} em {nome_de_pub(body['pessoa'])}"}
        p = app.find(body["post"])
        if p.author == meu_pub:
            raise ValueError("Não é permitido dar like/dislike no próprio post (queimaria 10% dos seus reps).")
        fc.vote(a, n, "action", p.id, k, why=body.get("motivo") or None)
        sincronizar_todos(now)
        return {"ok": f"{a} de {n} no post {A.short(p.id)}"}
    if a in ("revoke", "unrevoke"):
        p = app.find(body["post"])
        fc.revoke(a, int(body["n"]), p.id, k)
        sincronizar_todos(now)
        return {"ok": f"{a} de {body['n']} no post {A.short(p.id)}"}
    if a == "sync":
        sincronizar_todos(now)
        return {"ok": "Sync concluído entre todos os nós locais"}
    raise ValueError(f"ação desconhecida: {a}")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, data, ctype="application/json; charset=utf-8"):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _guard(self, fn, *args):
        try:
            self._send(200, fn(*args))
        except SystemExit as e:              # app.find() usa SystemExit
            self._send(400, {"erro": str(e)})
        except (RuntimeError, ValueError, KeyError) as e:
            self._send(400, {"erro": str(e)})

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(AQUI, "web", "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        routes = {"/api/estado": api_estado, "/api/sugestoes": api_sugestoes,
                  "/api/participantes": api_participantes}
        if u.path in routes:
            return self._guard(routes[u.path], q)
        self._send(404, {"erro": "não encontrado"})

    def do_POST(self):
        if self.path != "/api/acao":
            return self._send(404, {"erro": "não encontrado"})
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        self._guard(api_acao, body)

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] " + fmt % args + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(AQUI, "usuarios.json"))
    ap.add_argument("--porta", type=int, default=8080)
    a = ap.parse_args()
    global CONFIG
    with open(a.config) as f:
        CONFIG = json.load(f)
    print(f"Interface em http://localhost:{a.porta}  (config: {a.config})")
    ThreadingHTTPServer(("0.0.0.0", a.porta), Handler).serve_forever()


if __name__ == "__main__":
    main()
