import argparse
import json
from pathlib import Path

from .engine import TidalMemory
from .models import RecallPolicy


def parser():
    root = argparse.ArgumentParser(prog="tidal-memory")
    root.add_argument("--db", default="tidal-memory.db")
    sub = root.add_subparsers(dest="command", required=True)

    remember = sub.add_parser("remember", help="save a durable fact or event")
    remember.add_argument("summary")
    remember.add_argument("--layer", default="semantic")
    remember.add_argument("--importance", type=int, default=5)

    impression = sub.add_parser("impression", help="save a low-resolution window impression")
    impression.add_argument("conversation_id")
    impression.add_argument("text")
    impression.add_argument("--title", default="Untitled")

    context = sub.add_parser("context", help="print the bounded opening context")
    context.add_argument("--conversation-id", default="")

    recall = sub.add_parser("recall", help="explicitly retrieve old detail")
    recall.add_argument("query")
    recall.add_argument("--trigger", choices=["explicit", "balanced", "active"], default="balanced")
    recall.add_argument("--force", action="store_true")

    forget = sub.add_parser("forget", help="archive one memory")
    forget.add_argument("memory_id", type=int)

    link = sub.add_parser("link", help="connect two memories for one-hop association")
    link.add_argument("from_id", type=int)
    link.add_argument("to_id", type=int)
    link.add_argument("--relation", default="related")

    sub.add_parser("rollup", help="merge old window impressions into week/month impressions")
    sub.add_parser("demo", help="load synthetic memories and show both memory paths")
    return root


def run_demo(memory: TidalMemory):
    memory.remember("Rin prefers jasmine tea to coffee.", layer="semantic", importance=6,
                    tags="preference,drink", occurred_at="2026-01-04T10:00:00+00:00")
    memory.store.upsert_window_impression(
        "demo-1",
        "They talked about rainy walks and small interface fixes; the mood was easy and affectionate.",
        title="Rainy afternoon", occurred_at="2026-01-05T18:00:00+00:00",
    )
    print("OPENING CONTEXT")
    print(memory.opening_context("demo-new") or "(empty)")
    print("\nEXPLICIT DETAIL RECALL")
    print(memory.recall("Do you remember what Rin likes to drink?", force=True) or "(empty)")


def main(argv=None):
    args = parser().parse_args(argv)
    policy = RecallPolicy(trigger=getattr(args, "trigger", "balanced"))
    with TidalMemory(args.db, policy=policy) as memory:
        if args.command == "remember":
            print(memory.remember(args.summary, layer=args.layer, importance=args.importance))
        elif args.command == "impression":
            print(memory.store.upsert_window_impression(
                args.conversation_id, args.text, title=args.title,
            ))
        elif args.command == "context":
            print(memory.opening_context(args.conversation_id))
        elif args.command == "recall":
            print(memory.recall(args.query, force=args.force))
        elif args.command == "forget":
            memory.forget(args.memory_id)
            print("forgotten")
        elif args.command == "link":
            memory.store.link(args.from_id, args.to_id, args.relation)
            print("linked")
        elif args.command == "rollup":
            print(json.dumps(memory.rollup(), ensure_ascii=False))
        elif args.command == "demo":
            run_demo(memory)


if __name__ == "__main__":
    main()
