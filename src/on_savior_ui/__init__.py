"""on-savior-ui: Ostranauts save reader, progress metrics, and social-move analysis."""

from __future__ import annotations

import argparse
import json


def _add_serve(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("serve", help="run the save-library web UI")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address; use 0.0.0.0 to reach it from another device")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--saves-dir", help="override save folder auto-detection")
    p.add_argument("--store", help="path to the tags/notes/policies file")
    p.add_argument("--allow-delete", action="store_true",
                   help="permit deleting saves and applying auto-rotate")
    p.add_argument("--trash-dir", help="move deleted saves here instead of erasing them")
    p.add_argument("--archive-dir", help="destination for 'archive copy'")
    p.add_argument("--auto-rotate", action="store_true",
                   help="run enabled retention policies in the background")
    p.add_argument("--rotate-interval", type=float, default=300.0,
                   help="seconds between auto-rotate sweeps (default 300)")
    p.add_argument("--no-link-reseeded", action="store_true",
                   help="keep re-seeded runs as separate continuities")


def _add_library(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("library", help="print the save library grouped by continuity")
    p.add_argument("--saves-dir")
    p.add_argument("--json", action="store_true", help="dump the raw index")
    p.add_argument("--no-link-reseeded", action="store_true")


def _add_rotate(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("rotate", help="preview or apply retention for a continuity")
    p.add_argument("continuity", nargs="?",
                   help="continuity id or a substring of its label; omit for all")
    p.add_argument("--saves-dir")
    p.add_argument("--store")
    p.add_argument("--apply", action="store_true", help="actually delete the saves")
    p.add_argument("--trash-dir")


def _add_bangbang(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("bangbang", help="run the bang-bang burn planner (Streamlit)")
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--host", default="localhost",
                   help="bind address; use 0.0.0.0 to reach it from another device")


def main() -> None:
    parser = argparse.ArgumentParser(prog="on-savior-ui")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("saves", help="list saves with headline metrics")

    p_save = sub.add_parser("save", help="detailed metrics for one save")
    p_save.add_argument("name")

    p_graph = sub.add_parser("social-graph", help="export social-move graph as CSV")
    p_graph.add_argument("--out", default="analysis/social_graph")

    _add_serve(sub)
    _add_library(sub)
    _add_rotate(sub)
    _add_bangbang(sub)

    args = parser.parse_args()

    if args.cmd == "saves":
        from .saves import list_saves

        for save in list_saves():
            info = save.info
            print(
                f"{save.name:35s} {info.get('playerName',''):20s} "
                f"${info.get('money', 0):>12,.0f}  "
                f"{(info.get('playTimeElapsed') or 0) / 3600:6.1f}h  "
                f"{info.get('realWorldTime', '')}"
            )
    elif args.cmd == "save":
        from .saves import find_saves_dir, Save

        save = Save(find_saves_dir() / args.name)
        print(json.dumps(save.metrics(), indent=2, default=str))
        player = save.player
        if player:
            print(f"\nplayer found on ship {player.ship}")
            print("skills:", json.dumps(player.skills, indent=2))
            traits = {
                n: c.magnitude
                for n, c in player.conditions.items()
                if n.startswith("Is") and c.duration == 1.0
            }
            print(f"conditions (Is*): {len(traits)}")
    elif args.cmd == "social-graph":
        from .gamedata import GameData
        from .social import export_graph

        stats = export_graph(GameData(), args.out)
        print(f"wrote {args.out}/nodes.csv and edges.csv: {stats}")
    elif args.cmd == "serve":
        from .web import serve

        serve(
            host=args.host,
            port=args.port,
            saves_dir=args.saves_dir,
            store_path=args.store,
            allow_delete=args.allow_delete,
            trash_dir=args.trash_dir,
            archive_dir=args.archive_dir,
            auto_rotate=args.auto_rotate,
            rotate_interval=args.rotate_interval,
            link_reseeded=not args.no_link_reseeded,
        )
    elif args.cmd == "library":
        _cmd_library(args)
    elif args.cmd == "rotate":
        _cmd_rotate(args)
    elif args.cmd == "bangbang":
        _cmd_bangbang(args)


def _cmd_library(args: argparse.Namespace) -> None:
    from .catalog import Library

    lib = Library.load(args.saves_dir, link_reseeded=not args.no_link_reseeded)
    if args.json:
        print(json.dumps(lib.as_dict(), indent=2))
        return
    print(f"{lib.root}  —  {len(lib.refs)} saves, "
          f"{sum(r.size_bytes for r in lib.refs) / 1e9:.1f} GB\n")
    for group in lib.groups:
        info = group.as_dict()
        print(f"■ {info['label']}  [{group.id[:8]}]  "
              f"{info['save_count']} saves · {info['size_bytes'] / 1e9:.1f} GB · "
              f"{info['play_time_max']:.0f}h played · {info['version']}")
        ordered = sorted(group.saves, key=lambda r: (r.play_time, r.created_epoch))
        children = group.children()
        for pos, ref in enumerate(ordered):
            parent = lib.by_key(group.parents.get(ref.key) or "")
            mark = "◆" if len(children.get(ref.key, [])) > 1 else (
                "·" if ref.is_autosave else "●")
            # Only worth pointing out when the save did not continue the line above it.
            resumed = parent is not None and (pos == 0 or ordered[pos - 1].key != parent.key)
            branch = f"  ← branched from {parent.name}" if resumed else ""
            print(f"   {mark} {ref.play_time:7.2f}h  ${ref.money:>10,.0f}  "
                  f"{ref.size_bytes / 1e6:6.0f} MB  {ref.name}{branch}")
        print()


def _cmd_bangbang(args: argparse.Namespace) -> None:
    import subprocess
    import sys
    from pathlib import Path

    app_path = Path(__file__).parent / "bangbang" / "app.py"
    subprocess.run(
        [
            sys.executable, "-m", "streamlit", "run", str(app_path),
            "--server.port", str(args.port),
            "--server.address", args.host,
        ],
        check=False,
    )


def _cmd_rotate(args: argparse.Namespace) -> None:
    from pathlib import Path

    from .catalog import Library
    from .manage import delete
    from .rotate import plan
    from .store import JsonStore

    lib = Library.load(args.saves_dir)
    store = JsonStore(args.store)
    meta = store.all_save_meta()
    targets = [
        g for g in lib.groups
        if not args.continuity
        or args.continuity == g.id
        or args.continuity.lower() in g.label.lower()
    ]
    if not targets:
        raise SystemExit(f"no continuity matches {args.continuity!r}")

    for group in targets:
        policy = store.policy(group.id)
        if policy.max_bytes is None and policy.max_count is None:
            print(f"■ {group.label}: no budget set — configure it in the web UI\n")
            continue
        result = plan(group, policy, meta)
        print(f"■ {group.label}  "
              f"{result.size_before / 1e9:.1f} GB → "
              f"{(result.size_before - result.freed_bytes) / 1e9:.1f} GB "
              f"({len(result.remove)} of {result.count_before} saves)"
              f"{'  [budget unreachable]' if result.over_budget else ''}")
        for decision in result.decisions:
            verb = "keep" if decision.keep else "DROP"
            print(f"   {verb}  {decision.play_time:7.2f}h  "
                  f"{decision.size_bytes / 1e6:6.0f} MB  "
                  f"{decision.name:44s} {decision.reason}")
        if args.apply and result.remove:
            trash = Path(args.trash_dir) if args.trash_dir else None
            for decision in result.remove:
                ref = lib.by_key(decision.key)
                if ref is None:
                    continue
                delete(lib.root, ref, trash)
                store.drop_save_meta(decision.key)
            print(f"   removed {len(result.remove)} saves, "
                  f"freed {result.freed_bytes / 1e9:.2f} GB")
        print()
