#!/usr/bin/env python3
"""Query the Understand-Anything knowledge graph from the command line.

Usage (run from the kubernetes repo root):
  python3 .ua/ua-query.py find ScheduleOne            # search nodes by name/path
  python3 .ua/ua-query.py show Scheduler.ScheduleOne  # summary + callers/callees/implements
  python3 .ua/ua-query.py chain Kubelet.syncLoop 3    # call tree, N levels deep
  python3 .ua/ua-query.py impl Policy                 # who implements an interface
  python3 .ua/ua-query.py pkg pkg/kubelet/pleg        # package summary + its files
  python3 .ua/ua-query.py tour                        # the guided learning tour
"""
import json, os, sys, collections

G = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge-graph.json")))
N = {n["id"]: n for n in G["nodes"]}
OUT, IN = collections.defaultdict(list), collections.defaultdict(list)
for e in G["edges"]:
    OUT[e["source"]].append(e); IN[e["target"]].append(e)

def short(i):
    n = N.get(i, {})
    loc = f'{n.get("filePath", "")}:{n["lineRange"][0]}' if n.get("lineRange") else n.get("filePath", "")
    return f'{n.get("name", i)}  ({loc})'

def resolve(q):
    if q in N:
        return [q]
    exact = [i for i, n in N.items() if n["name"] == q or i.endswith(":" + q)]
    return exact or [i for i, n in N.items() if q.lower() in i.lower()]

def pick(q):
    c = resolve(q)
    if not c:
        sys.exit(f"no node matches {q!r}")
    if len(c) > 1:
        print(f"{len(c)} matches, using the first; be more specific to choose:")
        for i in c[:10]:
            print("  ", i)
    return c[0]

def show(i):
    n = N[i]
    print(f'[{n["type"]}] {short(i)}\n  {n["summary"]}')
    if n.get("tags"):
        print("  tags:", ", ".join(n["tags"]))
    for title, lst, end in (("calls →", OUT[i], "target"), ("called by ←", IN[i], "source")):
        es = [e for e in lst if e["type"] == "calls"]
        if es:
            print(title)
            for e in es[:30]:
                print("   ", short(e[end]), ("— " + e["description"]) if e.get("description") else "")
    for e in OUT[i]:
        if e["type"] == "implements":
            print("implements:", short(e["target"]))
    for e in IN[i]:
        if e["type"] == "implements":
            print("implemented by:", short(e["source"]))

def chain(i, depth, seen=None, ind=0):
    seen = seen or set()
    print("  " * ind + short(i))
    if depth == 0 or i in seen:
        return
    seen.add(i)
    for e in OUT[i]:
        if e["type"] == "calls":
            chain(e["target"], depth - 1, seen, ind + 1)

cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("help", [])
if cmd == "find":
    for i in resolve(args[0])[:40]:
        print(f'{N[i]["type"]:9} {short(i)}')
elif cmd == "show":
    show(pick(args[0]))
elif cmd == "chain":
    chain(pick(args[0]), int(args[1]) if len(args) > 1 else 2)
elif cmd == "impl":
    for i in resolve(args[0]):
        if N[i]["type"] == "class":
            imps = [e["source"] for e in IN[i] if e["type"] == "implements"]
            if imps:
                print(short(i)); [print("   ←", short(s)) for s in imps]
elif cmd == "pkg":
    m = "module:" + args[0].rstrip("/")
    print(N[m]["summary"] if m in N else "(no module node)")
    for e in OUT[m]:
        if e["type"] == "contains":
            print("  ", N[e["target"]]["name"], "—", N[e["target"]]["summary"])
elif cmd == "tour":
    for st in G["tour"]:
        print(f'{st["order"]}. {st["title"]}\n   {st["description"]}')
        for i in st["nodeIds"]:
            print("     ", N[i]["filePath"])
else:
    print(__doc__)
