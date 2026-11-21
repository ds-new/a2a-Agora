"""Run the agent-network simulation.

    python -m agora.sim.run                              # 24 consumers, 13 producers, 12 rounds, real HTTP
    python -m agora.sim.run --transport memory           # same protocol bytes, no sockets (faster)
    python -m agora.sim.run --seeds 5 --transport memory # repeat with 5 seeds, report mean and sd
    AGORA_LLM_BASE_URL=... python -m agora.sim.run --llm # LLM brains (rules as fallback)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from .world import SimConfig, World

GROUP_NAMES = {"x": "with X skills", "no_x": "base skills only"}


def _fmt_round(s: dict) -> str:
    g = s["groups"]
    x, n = g.get("x", {}), g.get("no_x", {})
    acc = s["honest_acceptance"]
    return (f"round {s['round']:>2} | shown relevance X {x.get('mean_relevance', 0):.3f} / base {n.get('mean_relevance', 0):.3f}"
            f" | liked X {x.get('positive_rate', 0):.2f} / base {n.get('positive_rate', 0):.2f}"
            f" | need buys {x.get('need_purchases', 0) + n.get('need_purchases', 0)}"
            f" | producer acceptance {acc if acc is None else f'{acc:.2f}'} ({s['honest_proposals']} sent)"
            f" | spam sent {s['spam_proposals']} | msgs {s['a2a_messages']}")


def markdown(rep: dict) -> str:
    t = rep["totals"]
    L = ["# Agora agent-network simulation report", "",
         f"{rep['agents']} agents, {rep['config']['rounds']} rounds, transport `{rep['config']['transport']}`, "
         f"seed {rep['config']['seed']}.", "", "## Totals", "", "| metric | value |", "|---|---|",
         *[f"| {k} | {v} |" for k, v in t.items()],
         f"| reputation_vs_quality_spearman | {rep['reputation_vs_quality_spearman']} |", "",
         "## Consumer agents: with vs without X's ranking stack as skills", "",
         "| group | consumers | relevance of shown | liked | scam share | shown/tick | need fulfilment | "
         "hours to fulfil | purchases/consumer | surplus/consumer |", "|---|---|---|---|---|---|---|---|---|---|"]
    for g, d in rep["groups"].items():
        L.append(f"| {GROUP_NAMES[g]} | {d['consumers']} | {d['mean_relevance']} | {d['positive_rate']} | {d['scam_share']} | "
                 f"{d['shown_per_consumer_tick']} | {d['need_fulfilment']} | {d['hours_to_fulfil']} | "
                 f"{d['purchases_per_consumer']} | {d['surplus_per_consumer']} |")
    L += ["", "Rejection reasons the agents sent back: " +
          "; ".join(f"{GROUP_NAMES[g]}: {d['reject_reasons']}" for g, d in rep["groups"].items()), "",
          "## Preference learning", "",
          f"Spearman correlation between the principal's true tastes over 12 categories and the agent's profile: "
          f"{rep['preference_learning']['spearman_learned']} after learning vs "
          f"{rep['preference_learning']['spearman_stated_only']} from stated preferences alone.", "",
          "## Disclosure", "", "| disclosure | consumers | need fulfilment | proposals received/consumer |",
          "|---|---|---|---|"]
    for disc, d in rep["by_disclosure"].items():
        L.append(f"| {disc} | {d['consumers']} | {d['need_fulfilment']} | {d['proposals_received_per_consumer']} |")
    L += ["", "## By round", "", "| round | relevance X / base | liked X / base | honest producer acceptance | "
          "honest proposals | spam proposals | A2A messages |", "|---|---|---|---|---|---|---|"]
    for s in rep["rounds"]:
        x, n = s["groups"].get("x", {}), s["groups"].get("no_x", {})
        L.append(f"| {s['round']} | {x.get('mean_relevance', 0):.3f} / {n.get('mean_relevance', 0):.3f} | "
                 f"{x.get('positive_rate', 0):.2f} / {n.get('positive_rate', 0):.2f} | {s['honest_acceptance']} | "
                 f"{s['honest_proposals']} | {s['spam_proposals']} | {s['a2a_messages']} |")
    L += ["", "## Producers", "", "| producer | kind | honest | quality | proposals | acceptance | blocked by | "
          "sales | refunds | revenue | made to order | reputation | labels |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in sorted(rep["merchants"], key=lambda m: -(m["acceptance"] or 0)):
        L.append(f"| {m['name']} | {m['kind']} | {m['honest']} | {m['true_quality']} | {m['proposals']} | "
                 f"{m['acceptance']} | {m['blocked_by']} | {m['sales']} | {m['refunds']} | {m['revenue']} | "
                 f"{m['made_to_order']} | {m['reputation']} | {', '.join(m['labels']) or '-'} |")
    L += ["", "## Sample decisions (with the reasons agents recorded)", ""]
    for e in rep["decision_examples"]:
        L.append(f"- `{e['action']}` {e.get('title') or e.get('target', '')}: {e['reason']}")
    return "\n".join(L) + "\n"


async def run_world(cfg: SimConfig, out_dir: Path, verbose: bool = True) -> dict:
    world = World(cfg)
    t0 = time.time()
    await world.setup()
    if verbose:
        print(f"started {len(world.agents)} agents ({cfg.transport}) in {time.time() - t0:.1f}s")
    try:
        for r in range(cfg.rounds):
            stats = await world.run_round(r)
            if verbose:
                print(_fmt_round(stats), flush=True)
        report = world.report()
    finally:
        await world.close()
    report["wall_seconds"] = round(time.time() - t0, 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    (out_dir / "report.md").write_text(markdown(report))
    return report


def summarize(reports: list[dict]) -> dict:
    def ms(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return {"mean": round(statistics.fmean(vals), 4), "sd": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0}

    out: dict = {"seeds": [r["config"]["seed"] for r in reports]}
    for g in ("x", "no_x"):
        for k in ("mean_relevance", "positive_rate", "scam_share", "need_fulfilment", "hours_to_fulfil",
                  "purchases_per_consumer", "surplus_per_consumer"):
            out[f"{g}.{k}"] = ms([r["groups"].get(g, {}).get(k) for r in reports])
    for k in ("gmv", "deals_completed", "deals_refunded", "paid_out_to_bad_actors", "a2a_messages",
              "honest_proposals", "honest_acceptance"):
        out[k] = ms([r["totals"][k] for r in reports])
    out["money_conserved_all"] = all(r["totals"]["money_conserved"] for r in reports)
    out["spearman_learned"] = ms([r["preference_learning"]["spearman_learned"] for r in reports])
    out["spearman_stated_only"] = ms([r["preference_learning"]["spearman_stated_only"] for r in reports])
    out["spearman_unstated_categories"] = ms([r["preference_learning"]["spearman_unstated_categories"] for r in reports])
    out["first_round_acceptance"] = ms([r["rounds"][0]["honest_acceptance"] for r in reports])
    out["last_round_acceptance"] = ms([r["rounds"][-1]["honest_acceptance"] for r in reports])
    spam = [m for r in reports for m in r["merchants"] if m["name"] == "brandz-outlet"]
    out["spammer_acceptance"] = ms([m["acceptance"] for m in spam])
    out["spammer_blocked_by"] = ms([m["blocked_by"] for m in spam])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--consumers", type=int, default=24)
    ap.add_argument("--transport", choices=["http", "memory"], default="http")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--seeds", type=int, default=1, help="repeat with seeds seed, seed+1, ...")
    ap.add_argument("--no-scammers", action="store_true")
    ap.add_argument("--llm", action="store_true", help="use LLM brains (needs AGORA_LLM_BASE_URL)")
    ap.add_argument("--no-producer-learning", action="store_true", help="ablation: producers ignore feedback")
    ap.add_argument("--out", default="runs/latest")
    args = ap.parse_args()
    reports = []
    for i in range(args.seeds):
        cfg = SimConfig(rounds=args.rounds, consumers=args.consumers, transport=args.transport, seed=args.seed + i,
                        scammers=not args.no_scammers, llm=args.llm,
                        producer_learning=not args.no_producer_learning)
        out = Path(args.out) / (f"seed{cfg.seed}" if args.seeds > 1 else "")
        reports.append(asyncio.run(run_world(cfg, out, verbose=args.seeds == 1)))
        if args.seeds > 1:
            g = reports[-1]["groups"]
            print(f"seed {cfg.seed}: liked X {g['x']['positive_rate']} / base {g['no_x']['positive_rate']}, "
                  f"needs X {g['x']['need_fulfilment']} / base {g['no_x']['need_fulfilment']}, "
                  f"GMV {reports[-1]['totals']['gmv']}, bad-actor payouts {reports[-1]['totals']['paid_out_to_bad_actors']}",
                  flush=True)
    if args.seeds > 1:
        summary = summarize(reports)
        Path(args.out, "summary.json").write_text(json.dumps(summary, indent=2))
        print("\n== mean (sd) over seeds ==")
        for k, v in summary.items():
            if isinstance(v, dict):
                print(f"{k:>34}: {v['mean']} ({v['sd']})")
            elif k != "seeds":
                print(f"{k:>34}: {v}")
        return
    rep = reports[0]
    print("\n== totals ==")
    for k, v in rep["totals"].items():
        print(f"{k:>24}: {v}")
    for g, d in rep["groups"].items():
        print(f"{GROUP_NAMES[g]:>24}: relevance {d['mean_relevance']}, liked {d['positive_rate']}, needs met "
              f"{d['need_fulfilment']}, purchases/consumer {d['purchases_per_consumer']}, surplus/consumer {d['surplus_per_consumer']}")
    print(f"{'preference learning':>24}: {rep['preference_learning']}")
    print(f"report written to {args.out}/report.md ({rep['wall_seconds']}s)")


if __name__ == "__main__":
    main()
