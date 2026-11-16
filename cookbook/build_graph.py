#!/usr/bin/env python
"""Builds the graphify graph of the kitchen cookbook. Zero LLM, only stdlib + graphify.

Rebuild everything (from the repo root; needs the pantry for the hook names):
    python -X utf8 -I cookbook/build_graph.py

Inputs (read-only): cookbook/COOKBOOK.md, cookbook/ecc-index.md, docs/ecc-adoption-plan.md (only used to
link recipes to roles; its text is never copied into the graph), <pantry>/ecc/hooks/hooks.json (only to
name the 27 hooks). work-cli is cited as a source.
Output: cookbook/graphify-out/ (graph.json, GRAPH_REPORT.md, graph.html).
All paths inside the graph are relative (to agentes/ locally, to the repo root once published) and use "/".

Query: cd cookbook && graphify query "SEO"   (graphify reads graphify-out/graph.json from the current dir)
Search works in English and pt-BR: occasions and roles carry pt-BR synonyms in their label and in the
`synonyms` field.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

AG = Path(__file__).resolve().parent.parent  # .../agentes (local) or the repo root (published)
REC = AG / "cookbook"
OUT = REC / "graphify-out"

# Two layouts, same script:
#  - published repo: docs/ at the root, pantry in cookbook/pantry/{ecc,work-cli}
#  - local workspace: docs in pub/en/docs, pantry in ref/{ecc,work-cli}
if (AG / "docs" / "ecc-adoption-plan.md").exists():
    DOCS, PAN, PAN_DIR = "docs", "pantry", REC / "pantry"
else:
    DOCS, PAN, PAN_DIR = "pub/en/docs", "ref", AG / "ref"
DOC_ECC = f"{DOCS}/ecc-adoption-plan.md"  # source of the brigade roles (read-only)
DOC_WCLI = f"{DOCS}/work-cli-adoption-plan.md"

ECC_COMMIT = "d2ef268"
ECC_VER = "2.2.3"

# pt-BR search synonyms per occasion (key = fragment of the COOKBOOK title, accent-free, lowercase)
SINONIMOS = {
    "web app": "frontend front-end React Vue Next Angular acessibilidade a11y E2E Playwright design site interface aplicativo web",  # noqa: E501
    "back-end": "backend API REST FastAPI Django Node Docker contêiner container deploy servidor Python",
    "databases and sql": "banco de dados SQL Postgres MySQL Redis ClickHouse migração consulta database",
    "another language": "outra linguagem Go Rust Java Kotlin C++ C# F# PHP Ruby Perl Swift Bengali revisor de código",
    "mobile": "celular aplicativo móvel Flutter Android iOS Compose React Native SwiftUI app",
    "applied ai": "IA inteligência artificial ML aprendizado de máquina RAG recomendação pesquisa prompt LLM modelo",
    "networking, homelab": "rede homelab VPN firewall roteador servidor escritório infraestrutura",
    "security, pentest": "segurança pentest bug bounty vulnerabilidade guarda proteção invasão hardening auditoria",
    "crypto, defi": "cripto criptomoeda DeFi trading mercado de previsão blockchain bitcoin",
    "marketing, seo": "marketing SEO conteúdo redes sociais vendas investidores blog campanha copy texto publicidade",
    "video, 3d": "vídeo 3D motion mídia Blender After Effects Premiere Higgsfield estúdio animação",
    "open source": "código aberto publicação pacote npm PyPI licença release repositório",
    "healthcare and compliance": "saúde HIPAA prontuário conformidade LGPD privacidade",
    "business operations": "operações de negócio cobrança logística e-mail Jira contratos compras estoque produção",
    "scientific research": "pesquisa científica artigos bases abertas papers literatura",
    "machine fleet": "frota de máquinas agendador scheduler cron SSH orquestração multiagente fila workers paralelo",
    "other harnesses": "outros harnesses Codex Cursor Gemini Qwen OpenCode Hermes Antigravity outro agente",
    "memory, continuous": "memória aprendizado contínuo governança docs skills instinto",
    "cost, tokens": "custo tokens medição desempenho economia contexto orçamento",
    "quality, testing": "qualidade testes TDD revisão processo engenharia superpowers provador verificação",
    "windows and desktop": "Windows desktop aplicativo PowerShell WinUI instalador",
    "ecc itself": "o próprio ECC instalação scripts manifests guias hooks Node",
    "work-cli": "work-cli ClickUp frota SSH Postgres grafo de código módulos Go agendador",
}

# kitchen brigade: key = accent-free pt-BR name (the English row of docs/ecc-adoption-plan.md is matched by English name)  # noqa: E501
# value = (English name, pt-BR name, English description, pt-BR search synonyms)
PAPEIS = {
    "garcom": (
        "Waiter",
        "Garçom",
        "Talks to the owner, logs requests, dispatches work and gives the final word.",
        "garçom atendente despachante pedido discord",
    ),
    "chef": (
        "Chef",
        "Chef",
        "Planner: breaks big requests into small tasks, picks the model and writes decidable acceptance criteria. Model: opus.",  # noqa: E501
        "chef planejador plano planejar tarefa",
    ),
    "arqueologo": (
        "Archaeologist",
        "Arqueólogo",
        "Reads legacy code and describes the current behavior before anything changes. Read-only.",
        "arqueólogo código legado legacy comportamento",
    ),
    "cozinheiro": (
        "Cook",
        "Cozinheiro",
        "Executes one small task and delivers files plus a Result section with evidence. Model: sonnet or haiku.",
        "cozinheiro executor executar tarefa implementação",
    ),
    "provador": (
        "Taster",
        "Provador",
        "Checks a delivery against the acceptance criteria and tries to refute every serious finding; always a different model than the cook.",  # noqa: E501
        "provador revisor revisão prova verificação avaliador testador",
    ),
    "provador duplo": (
        "Double taster",
        "Provador duplo",
        "Two independent tasters with the same rubric; passes only if both approve, up to 3 rounds. Mandatory for external writes and client deliveries.",  # noqa: E501
        "provador duplo fiscal de risco dois revisores aprovação",
    ),
    "provadores de estacao": (
        "Station tasters",
        "Provadores de estação",
        "Stack-specific checklists (Python, web, 3D) added to the taster's rubric.",
        "provadores de estação checklist stack linguagem",
    ),
    "maitre": (
        "Maitre",
        "Maître",
        "Watchdog: watches tmux, posts to Discord, flags stuck or waiting sessions and escalates. Plain Python, no model.",  # noqa: E501
        "maître vigia monitor tmux travado escalada",
    ),
    "fiscal de seguranca": (
        "Security inspector",
        "Fiscal de segurança",
        "Denies dangerous commands before they run (Python hook).",
        "fiscal de segurança guarda bloqueio comando perigoso proteção",
    ),
    "porteiro": (
        "Doorman",
        "Porteiro",
        "Sanitizes external text (invisible Unicode, bidi, HTML comments) before anyone reads it.",
        "porteiro sanear limpar texto externo entrada",
    ),
    "caixa": (
        "Cashier",
        "Caixa",
        "Counts tokens and context; warns about loops of identical calls.",
        "caixa tokens contexto custo laço medição",
    ),
    "despenseiro": (
        "Pantry keeper",
        "Despenseiro",
        "Decides what becomes memory; promotes and prunes it.",
        "despenseiro memória poda promover",
    ),
    "copeiro": (
        "Dishwasher",
        "Copeiro",
        "Cleanup: removes dead code and simplifies without changing behavior.",
        "copeiro limpeza código morto simplificar refatorar",
    ),
    "almoxarife": (
        "Storekeeper",
        "Almoxarife",
        "Monthly audit of skills, config and rules; proposes new guard rules from the logs. Read-only.",
        "almoxarife auditoria mensal skills config regras",
    ),
}

# occasion -> brigade roles (key = fragment of SINONIMOS above; values = English role names)
OCASIAO_PAPEL = {
    "web app": ["Station tasters", "Cook", "Taster"],
    "back-end": ["Cook", "Station tasters"],
    "databases and sql": ["Cook", "Archaeologist"],
    "another language": ["Station tasters", "Cook"],
    "mobile": ["Cook", "Station tasters"],
    "applied ai": ["Chef", "Cashier"],
    "networking, homelab": ["Security inspector", "Cook"],
    "security, pentest": ["Security inspector", "Doorman", "Double taster"],
    "crypto, defi": ["Security inspector", "Double taster"],
    "marketing, seo": ["Cook", "Doorman"],
    "video, 3d": ["Station tasters", "Cook"],
    "open source": ["Chef", "Taster"],
    "healthcare and compliance": ["Security inspector", "Double taster", "Doorman"],
    "business operations": ["Double taster", "Cook"],
    "scientific research": ["Archaeologist", "Chef"],
    "machine fleet": ["Maitre", "Chef", "Cook"],
    "other harnesses": ["Chef", "Cook"],
    "memory, continuous": ["Pantry keeper", "Storekeeper"],
    "cost, tokens": ["Cashier", "Maitre"],
    "quality, testing": ["Taster", "Station tasters", "Dishwasher"],
    "windows and desktop": ["Cook", "Station tasters"],
    "ecc itself": ["Chef", "Storekeeper"],
    "work-cli": ["Maitre", "Chef", "Cashier"],
}


def norm(s):
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")


def secao(texto, titulo):
    """Lines of the '## title...' section of the index."""
    m = re.search(r"^## " + re.escape(titulo) + r".*?$(.*?)(?=^## |\Z)", texto, re.S | re.M)
    return m.group(1) if m else ""


def linhas_tabela(bloco):
    for l in bloco.split("\n"):  # noqa: E741
        if l.startswith("|") and not l.startswith("|---"):
            cel = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", l.strip())[1:-1]]
            yield cel


def curto(s, n=220):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[A-Za-z]:[" + chr(92) * 2 + "/]+", "drive/", s).replace(chr(92), "/")  # never an absolute Windows path
    return s if len(s) <= n else s[: n - 1] + "…"


def main():
    nodes, edges = {}, []

    def no(id_, label, tipo, src, desc="", ft="document", **extra):
        n = {"id": id_, "label": label, "file_type": ft, "source_file": src, "tipo": tipo, "description": curto(desc)}
        n.update(extra)
        nodes[id_] = n

    def aresta(a, b, rel, src, conf="EXTRACTED"):
        if a in nodes and b in nodes:
            edges.append({"source": a, "target": b, "relation": rel, "confidence": conf, "source_file": src})

    idx = (REC / "ecc-index.md").read_text(encoding="utf-8")
    livro = (REC / "COOKBOOK.md").read_text(encoding="utf-8")
    brig = (AG / DOC_ECC).read_text(encoding="utf-8")

    # ---- sources
    no(
        "source-ecc",
        f"source: ECC v{ECC_VER} (commit {ECC_COMMIT})",
        "source",
        PAN + "/ecc",
        f"Everything Claude Code v{ECC_VER}, commit {ECC_COMMIT}. Read-only pantry in " + PAN + "/ecc.",
        ft="concept",
    )
    no(
        "source-workcli",
        "source: work-cli v0.6.1",
        "source",
        PAN + "/work-cli",
        "work-cli v0.6.1 (Go). Read-only pantry in " + PAN + "/work-cli.",
        ft="concept",
    )

    # ---- ECC recipes
    por_caminho = {}  # caminho relativo a agentes/ -> [ids]
    por_tipo_nome = {}  # (tipo, nome) -> id

    def receita(tipo, nome, desc, caminho, rotulo):
        id_ = f"ecc-{tipo}-{slug(caminho)}"
        no(id_, f"{rotulo}: {nome}", tipo, caminho, desc)
        aresta(id_, "source-ecc", "comes_from", "cookbook/ecc-index.md")
        por_caminho.setdefault(caminho, []).append(id_)
        por_tipo_nome[(tipo, nome)] = id_
        return id_

    contagem = {}
    for sec, tipo, rotulo in (
        ("Agents", "agent", "agent"),
        ("Commands", "command", "command"),
        ("Skills", "skill", "skill"),
    ):
        for c in linhas_tabela(secao(idx, sec)):
            if len(c) >= 3 and c[0] != "name":
                receita(tipo, c[0], c[1], PAN + "/ecc/" + c[2], rotulo)
                contagem[tipo] = contagem.get(tipo, 0) + 1
    for c in linhas_tabela(secao(idx, "Rules")):
        if len(c) >= 3 and c[0] != "folder/file":
            receita("rule", c[0], c[1], PAN + "/ecc/" + c[2], "rule")
            contagem["rule"] = contagem.get("rule", 0) + 1
    for c in linhas_tabela(secao(idx, "Scripts")):
        if len(c) >= 3 and c[0] != "file":
            receita("script", c[0], c[1], PAN + "/ecc/" + c[2], "script")
            contagem["script"] = contagem.get("script", 0) + 1
    hooks = json.loads((PAN_DIR / "ecc/hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
    n = 0
    for ev, lista in hooks.items():
        for e in lista:
            n += 1
            cmd = e["hooks"][0]["command"]
            achados = re.findall(r"hooks/([\w.-]+?)\.js", cmd)
            nome = achados[-1] if achados else f"hook-{n}"
            mt = e.get("matcher") or "-"
            id_ = f"ecc-hook-{n:02d}-{slug(nome)}"
            no(
                id_,
                f"hook: {nome} ({ev} / {mt})",
                "hook",
                PAN + "/ecc/hooks/hooks.json",
                f"ECC hook on event {ev}, matcher {mt}, script {nome}.js (idea only; do not install).",
            )
            aresta(id_, "source-ecc", "comes_from", "cookbook/ecc-index.md")
            por_caminho.setdefault(PAN + "/ecc/hooks/hooks.json", []).append(id_)
    contagem["hook"] = n

    # ---- brigade roles (English; pt-BR name and synonyms kept for search)
    papeis = {}
    for c in linhas_tabela(secao(brig, "1. The kitchen brigade")):
        if len(c) >= 6 and c[0] not in ("Role", "Papel"):
            nome_en = norm(re.split(r" \(", c[0].replace("**", ""))[0])
            cand = [k for k, v in PAPEIS.items() if nome_en.startswith(norm(v[0]))]
            chave_pt = max(cand, key=lambda k: len(PAPEIS[k][0]))
            en, pt, desc, syn = PAPEIS[chave_pt]
            pid = "role-" + slug(en)
            primeiro = en if pt == en else f"{en} ({pt})"
            no(pid, f"role: {primeiro} [{syn}]", "role", DOC_ECC, desc, synonyms=syn)
            papeis[en] = (pid, " ".join(c))  # the pt-BR text is used only to match recipe names
            aresta(pid, "source-ecc", "adapts", DOC_ECC, "INFERRED")
    assert len(papeis) == len(PAPEIS), (len(papeis), len(PAPEIS))

    # recipe -> role: recipe name cited in the brigade row
    for _pnome, (pid, texto) in papeis.items():
        t = norm(texto)
        for (tipo, nome), rid in por_tipo_nome.items():
            if tipo in ("agent", "skill", "command") and (len(nome) >= 8 and "-" in nome):
                if re.search(r"(?<![\w-])" + re.escape(norm(nome)) + r"(?![\w-])", t):
                    aresta(rid, pid, "serves_role", DOC_ECC, "INFERRED")

    # ---- occasions and work-cli (from COOKBOOK.md)
    sec2 = livro.split("## 2. Menu by occasion", 1)[1].split("\n## 3.", 1)[0]
    blocos = re.split(r"^### When we need… ", sec2, flags=re.M)[1:]
    ocasioes = []
    workcli = {}
    sem_receita = []
    extras = []
    for b in blocos:
        titulo = b.split("\n", 1)[0].strip()
        chave = next((k for k in SINONIMOS if k in norm(titulo)), None)
        assert chave, f"no synonyms for: {titulo}"
        corpo = b

        def campo(nome, corpo=corpo):
            m = re.search(r"^- \*\*" + nome + r":\*\* (.*)$", corpo, re.M)
            return m.group(1).strip() if m else ""

        oid = "occasion-" + slug(titulo)[:60]
        no(
            oid,
            f"occasion: {titulo} [{SINONIMOS[chave]}]",
            "occasion",
            "cookbook/COOKBOOK.md",
            f"{campo('Occasion')} What to adapt: {campo('What to adapt')} Effort: {campo('Effort')}",
            ft="concept",
            synonyms=SINONIMOS[chave],
        )
        ocasioes.append(oid)
        aresta(oid, "source-workcli" if chave == "work-cli" else "source-ecc", "uses_source", "cookbook/COOKBOOK.md")
        for pnome in OCASIAO_PAPEL[chave]:
            pid = papeis[pnome][0] if pnome in papeis else None
            assert pid, f"missing role: {pnome}"
            aresta(oid, pid, "needs_role", "cookbook/COOKBOOK.md", "INFERRED")
        nrec = 0
        for c in linhas_tabela(b):
            if len(c) < 3 or c[0] == "recipe":
                continue
            nome, tipo, cam = c[0], c[1], c[2].strip("`")
            if cam.startswith(PAN + "/work-cli"):
                wid = "wcli-" + slug(cam + "-" + nome)[:70]
                if wid not in nodes:
                    no(wid, f"work-cli: {nome}", "work-cli module", cam, f"{tipo}. {nome}")
                    aresta(wid, "source-workcli", "comes_from", "cookbook/COOKBOOK.md")
                workcli[wid] = cam
                aresta(wid, oid, "serves_occasion", "cookbook/COOKBOOK.md")
                nrec += 1
                continue
            alvo = por_caminho.get(cam)
            if not alvo:  # rules folder
                alvo = [i for k, v in por_caminho.items() if k.startswith(cam + "/") for i in v]
            if not alvo:  # ECC folder/file outside the index
                xid = "ecc-extra-" + slug(cam)[:30] + "-" + slug(nome)[:40]
                no(xid, f"ECC {tipo}: {nome}", tipo, cam, nome)
                aresta(xid, "source-ecc", "comes_from", "cookbook/COOKBOOK.md")
                extras.append(xid)
                alvo = [xid]
            for rid in alvo:
                aresta(rid, oid, "serves_occasion", "cookbook/COOKBOOK.md")
                nrec += 1
        if nrec == 0:
            sem_receita.append(titulo)

    # ---- already on the menu
    sec3 = livro.split("## 3. Already on the menu", 1)[1]
    no(
        "menu-of-the-day",
        "already on the menu (what the INFRA-033 plan brings)",
        "menu",
        DOC_ECC,
        "Items of the INFRA-033 plan: already adapted or being adapted; not new recipes. Synonyms: cardápio do dia, já no plano.",  # noqa: E501
        ft="concept",
        synonyms="cardápio do dia já no plano",
    )
    aresta("menu-of-the-day", "source-ecc", "uses_source", DOC_ECC)
    aresta("menu-of-the-day", "source-workcli", "uses_source", DOC_WCLI)
    tipos = {"Agents": "agent", "Commands": "command", "Skills": "skill"}
    ncard = 0
    for m in re.finditer(r"^- \*\*([^:*]+):\*\* (.*)$", sec3, re.M):
        cat, itens = m.group(1).strip(), m.group(2)
        if cat not in tipos and cat not in ("Rules", "work-cli", "Contexts/workflows"):
            continue
        for it in re.split(r",\s*(?![^()]*\))", itens):
            nome = (
                re.sub(r"\(.*?\)", "", it).strip().strip("'").split(" ")[0]
                if cat in tipos or cat == "work-cli"
                else it.strip()
            )
            if not nome:
                continue
            cid = f"menu-{slug(cat)}-{slug(nome)}"
            no(
                cid,
                f"menu {cat}: {nome}",
                "menu item",
                DOC_ECC,
                f"INFRA-033 plan item ({cat}). {it.strip()}",
                ft="concept",
            )
            aresta(cid, "menu-of-the-day", "part_of", "cookbook/COOKBOOK.md")
            ncard += 1
            alvo = []
            if cat in tipos:
                if (tipos[cat], nome) in por_tipo_nome:
                    alvo = [por_tipo_nome[(tipos[cat], nome)]]
            elif cat == "Rules":
                for pasta in re.findall(r"common/\w+|\b(?:python|typescript|react|web)\b", it):
                    pre = PAN + "/ecc/rules/" + pasta
                    alvo += [
                        i for k, v in por_caminho.items() if k.startswith(pre + "/") or k == pre + ".md" for i in v
                    ]
            if cat == "work-cli":
                aresta(cid, "source-workcli", "comes_from", DOC_WCLI)
            elif alvo:
                for rid in alvo:
                    aresta(cid, rid, "is_recipe", "cookbook/COOKBOOK.md")
            else:
                aresta(cid, "source-ecc", "comes_from", DOC_ECC, "INFERRED")

    # ---- hyperedges: one per occasion (recipes that serve it)
    hyper = []
    por_oc = {}
    for e in edges:
        if e["relation"] == "serves_occasion":
            por_oc.setdefault(e["target"], []).append(e["source"])
    for oid, membros in por_oc.items():
        if len(membros) >= 3:
            hyper.append(
                {
                    "id": "hyper-" + oid.split("-", 1)[1],
                    "label": nodes[oid]["label"].split(" [")[0] + " (recipes)",
                    "nodes": [oid] + membros[:60],
                    "relation": "participate_in",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": "cookbook/COOKBOOK.md",
                }
            )

    # ---- edge dedup (same triple)
    vistos, unicas = set(), []
    for e in edges:
        k = (e["source"], e["target"], e["relation"])
        if k not in vistos:
            vistos.add(k)
            unicas.append(e)
    edges = unicas
    # directed graph: the "source" hub only receives (does not spread the search); the rest goes both ways
    for e in list(edges):
        if not e["target"].startswith("source-") and e["relation"] != "needs_role":
            edges.append(dict(e, source=e["target"], target=e["source"], relation=e["relation"] + "_inv"))

    ext = {"nodes": list(nodes.values()), "edges": edges, "hyperedges": hyper, "input_tokens": 0, "output_tokens": 0}

    # ---- graphify: build, cluster, report, json, html
    from graphify.build import build_from_json
    from graphify.cluster import cluster, score_all
    from graphify.analyze import god_nodes, surprising_connections, suggest_questions
    from graphify.report import generate
    from graphify.export import to_json, to_html

    G = build_from_json(ext, directed=True)
    comunidades = cluster(G)
    coesao = score_all(G, comunidades)
    rotulos = {}
    for cid, ids in comunidades.items():
        cont = {}
        for i in ids:
            t = G.nodes[i].get("tipo", "?")
            cont[t] = cont.get(t, 0) + 1
        oc = [
            G.nodes[i]["label"].split(" [")[0].replace("occasion: ", "")
            for i in ids
            if G.nodes[i].get("tipo") == "occasion"
        ]
        base = oc[0][:50] if oc else max(cont, key=cont.get)
        rotulos[cid] = f"{base} ({len(ids)})"
    gods = god_nodes(G)
    surp = surprising_connections(G, comunidades)
    perguntas = suggest_questions(G, comunidades, rotulos)
    OUT.mkdir(exist_ok=True)
    rel = generate(
        G,
        comunidades,
        coesao,
        rotulos,
        gods,
        surp,
        {"warning": "built by script (cookbook/build_graph.py), no LLM; no files scanned"},
        {"input": 0, "output": 0},
        "agentes",
        suggested_questions=perguntas,
    )
    (OUT / "GRAPH_REPORT.md").write_text(rel, encoding="utf-8")
    to_json(G, comunidades, str(OUT / "graph.json"), force=True, community_labels=rotulos)
    try:
        to_html(G, comunidades, str(OUT / "graph.html"), community_labels=rotulos)
    except Exception as ex:  # graph too large for html: the rest is enough
        print("WARNING: graph.html not generated:", ex, file=sys.stderr)
        (OUT / "graph.html").unlink(missing_ok=True)
    (OUT / ".graphify_labels.json").write_text(
        json.dumps({str(k): v for k, v in rotulos.items()}, ensure_ascii=False), encoding="utf-8"
    )

    print(
        "ECC recipes:",
        contagem,
        "| work-cli:",
        len(workcli),
        "| occasions:",
        len(ocasioes),
        "| roles:",
        len(papeis),
        "| extras outside the index:",
        len(extras),
        "| menu:",
        ncard,
    )
    print("nodes:", G.number_of_nodes(), "edges:", G.number_of_edges(), "communities:", len(comunidades))
    if sem_receita:
        print("occasions/rows without recipes:", sem_receita)


if __name__ == "__main__":
    main()
