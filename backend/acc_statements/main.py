import argparse
import json

try:
    import config
    from analyze import build_case_timeline, extract_entities, summarize
    from chat import ask
    from contradictions import detect_contradictions
    from index import build_index, close_client
    from ingest import load_docs, run_ingest
except (ImportError, ModuleNotFoundError):
    from acc_statements import config
    from acc_statements.analyze import build_case_timeline, extract_entities, summarize
    from acc_statements.chat import ask
    from acc_statements.contradictions import detect_contradictions
    from acc_statements.index import build_index, close_client
    from acc_statements.ingest import load_docs, run_ingest


def save(name: str, data):
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    p = config.OUTPUT_DIR / name
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved -> {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["ingest", "index", "summarize", "entities", "timeline",
                                        "contradictions", "ask", "all"])
    ap.add_argument("question", nargs="?", help="question text, for the 'ask' command")
    ap.add_argument("--case", action="append", help="restrict to case number(s), repeatable")
    a = ap.parse_args()
    cmd = a.command

    if cmd in ("ingest", "all"):
        print("[ingest]"); run_ingest()
    if cmd in ("index", "all"):
        print("[index]"); build_index()
    docs = load_docs() if cmd not in ("ingest", "index", "ask") else []

    if cmd in ("summarize", "all"):
        print("[summaries]")
        res = [summarize(d) for d in docs]
        save("summaries.json", res)
        for r in res:
            print(f"\n== {r['person']} ==\n{r['summary']}")
    if cmd in ("entities", "all"):
        print("[entities]")
        res = [extract_entities(d) for d in docs]
        save("entities.json", res)
        for r in res:
            llm_e = [e for e in r["entities"] if e["source"] == "llm"]
            ok = sum(e["verified"] for e in llm_e)
            print(f"  {r['person']}: {len(llm_e)} LLM entities, {ok} verified against text")
    if cmd in ("timeline", "all"):
        print("[timeline]")
        tl = build_case_timeline(docs)
        save("timeline.json", tl)
        for e in tl:
            print(f"  {e['date'] or '(no date)'} {e['time'] or '':5} | {e['event']}  "
                  f"[{e['source']['sentence_id']}]{'' if e['verified'] else ' UNVERIFIED'}")
    if cmd in ("contradictions", "all"):
        print("[contradictions]")
        res = detect_contradictions(docs)
        save("contradictions.json", res)
        print(f"  contradictions flagged: {len(res['contradictions'])}, "
              f"different-detail notes: {len(res['different_detail'])}")
        for c in res["contradictions"]:
            print(f"\n  CONTRADICTION: {c['detail_a']}  vs  {c['detail_b']}\n  {c['explanation']}\n"
                  f"  A: {c['a']['person']} [{c['a']['sentence_id']}]  B: {c['b']['person']} [{c['b']['sentence_id']}]")
    if cmd == "ask":
        if not a.question:
            ap.error("ask needs a question")
        r = ask(a.question, case_nos=a.case)
        print("\n" + r["answer"])
        for s in r["sources"]:
            print(f"  [{s['sentence_id']}] {s['text']}")
        for w in r["warnings"]:
            print("  WARNING:", w)


if __name__ == "__main__":
    try:
        main()
    finally:
        close_client()