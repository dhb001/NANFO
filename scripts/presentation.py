#!/usr/bin/env python3
"""Build an offline presentation from pinned ADR014 evidence; never starts a lab."""

import argparse
import csv
import hashlib
import html
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI = ROOT / "ai-engine"
HOLDOUT = AI / "artifacts/adr014-holdout-001"
TRAIN = AI / "artifacts/adr014-001"
CHECKPOINT = TRAIN / "train-06/checkpoint.ptz"
CHECKPOINT_SHA = "5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5"
PINS = {
    "outcome.json": "69b0f193923384698cababa495548ec406ca37fc0a5a48549dcd994a2510bb3a",
    "test-report.json": "f323186fee013a3c55acac9e061500c2245c36976db01495a86f48a83c57392b",
    "plan.json": "0763dd582933da18e20b7bf879a37c96bb6414faf8ab66cade8bc2b02a855b28",
    "selection.json": "654a411f16b7607c9ddd40d6a4d0c8dcdb9ec8b2c6b1f20eac5a5070808ca180",
}
POLICIES = ("ppo", "ospf", "heuristic", "constant0", "constant1")
# Exact per-session files copied into a pack; never a directory sweep (ADR-028).
SESSION_FILES = ("summary.json", "evidence.jsonl", "last-history.json", "progress.json")
LABELS = {"ppo": "PPO", "ospf": "Actual OSPF", "heuristic": "Heuristic",
          "constant0": "Constant route 0", "constant1": "Constant route 1"}


def copyAllowlisted(source, target, names):
    """Copy only the named regular files; links, other names and subdirectories never travel."""
    target.mkdir()
    for name in names:
        path = source / name
        require(path.is_file() and not path.is_symlink(), f"Allowlisted evidence missing: {name}")
        shutil.copy2(path, target / name)


def digest(path):
    with path.open("rb") as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
        return result.hexdigest()


def readJson(path):
    return json.loads(path.read_text())


def writeJson(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def table(headers, rows):
    return "<table><thead><tr>" + "".join(
        f"<th>{html.escape(str(cell))}</th>" for cell in headers
    ) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    ) + "</tbody></table>"


def writeCsv(path, headers, rows):
    with path.open("w", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(headers)
        writer.writerows(rows)


def runPython(arguments, timeout=120):
    python = AI / ".venv/bin/python"
    require(python.exists(), "Missing ai-engine/.venv; see PRESENTATION_GUIDE.md setup.")
    result = subprocess.run(
        [str(python), *arguments], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
    )
    require(result.returncode == 0, "Read-only AI command failed: " + result.stderr[-3000:])
    return json.loads(result.stdout)


def auditArchive():
    # This verifies archived measurement and tensor consistency, not compatibility
    # with today's lab source or permission to collect another held-out campaign.
    code = """
import json
from pathlib import Path
from nanfo_routing.cli import report
root = Path('ai-engine/artifacts/adr014-holdout-001')
saved = json.loads((root/'test-report.json').read_text())
rebuilt = report([root/('test-'+p)/'summary.json' for p in
    ('ppo','constant1','constant0','heuristic','ospf')],
    checkpoint=Path('ai-engine/artifacts/adr014-001/train-06/checkpoint.ptz'))
different = [k for k,v in rebuilt.items() if saved.get(k) != v]
if different:
    raise ValueError('Archived report mismatch: '+str(different))
print(json.dumps({'archived_raw_report_matches':True, 'sessions':len(rebuilt['sessions']),
    'checkpoint_replay_requested':True, 'fresh_network_measurements':False,
    'current_lab_compatibility_checked':False}))
"""
    return runPython(["-c", code])


def exportPdf(output):
    code = """
import { chromium } from 'playwright';
import { pathToFileURL } from 'node:url';
const browser = await chromium.launch({headless:true});
try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    await page.goto(pathToFileURL(process.argv[1]+'/slides.html').href);
    await page.evaluate(()=>document.body.classList.add('hide-notes'));
    await page.pdf({path:process.argv[1]+'/slides.pdf', preferCSSPageSize:true,
        printBackground:true});
    await page.screenshot({path:process.argv[1]+'/slides-preview.png'});
} finally {
    await browser.close();
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code, str(output)], cwd=ROOT / "frontend",
        capture_output=True, text=True, timeout=60,
    )
    require(result.returncode == 0, "PDF export failed (frontend Playwright required): " +
            result.stderr[-2000:])
    require((output / "slides.pdf").read_bytes().startswith(b"%PDF-"), "Invalid PDF output.")


def inferHistories(output):
    histories = {}
    with (HOLDOUT / "test-ppo/evidence.jsonl").open() as source:
        for line in source:
            row = json.loads(line)
            if row.get("kind") != "ipc" or row["request"]["command"] != "reset":
                continue
            scenario = row["request"]["scenario"]
            if scenario not in histories:
                histories[scenario] = {"version": 3, "frames": [
                    {"request": row["request"], "response": row["response"]}
                ]}
    require(set(histories) == {"path0", "path1"}, "Both measured directions are required.")
    results = {}
    for scenario in ("path0", "path1"):
        history = output / f"history-{scenario}.json"
        writeJson(history, histories[scenario])
        command = ["-m", "nanfo_routing", "infer", "--checkpoint", str(CHECKPOINT),
                   "--history", str(history)]
        first, second = runPython(command), runPython(command)
        keys = ("action", "probabilities", "value", "input_sha256", "policy_sha256")
        require(all(first[k] == second[k] for k in keys), "Fresh-process inference differs.")
        require(first["policy_sha256"] == CHECKPOINT_SHA, "Unexpected inferred policy.")
        require(first["execution"] == "not_applied", "Inference must not apply an action.")
        results[scenario] = {"first": first, "second": second, "exact_outputs_match": True,
                             "source": "archived measured reset; first episode in direction"}
        print(f"{scenario}: action={first['action']}, probabilities={first['probabilities']}; "
              "two fresh processes match; execution=not_applied")
    writeJson(output / "inference-demo.json", results)
    return results


def bars(metrics, key, title, unit, multiplier=1):
    maximum = max(metrics[p][key] * multiplier for p in POLICIES)
    rows = []
    for policy in POLICIES:
        value = metrics[policy][key] * multiplier
        width = 100 * value / maximum if maximum else 0
        rows.append(f'<div class="barrow"><span>{LABELS[policy]}</span>'
                    f'<div class="track"><div class="bar {policy}" style="width:{width:.3f}%">'
                    f'</div></div><b>{value:.3f} {unit}</b></div>')
    return f"<h3>{title}</h3>" + "".join(rows)


def buildDeck(outcome, curves, inference, audited):
    metrics = outcome["metrics"]
    goodputGain = 100 * (metrics["ppo"]["mean_goodput_mbps"] /
                         metrics["ospf"]["mean_goodput_mbps"] - 1)
    rttReduction = 100 * (1 - metrics["ppo"]["mean_icmp_rtt_ms"] /
                          metrics["ospf"]["mean_icmp_rtt_ms"])
    sections = []

    def slide(title, body, note):
        sections.append(f'<section><p class="eyebrow">NANFO · {len(sections)+1:02}</p>'
                        f'<h1>{title}</h1>{body}<aside><strong>Speaker cue:</strong> {note}</aside>'
                        '<footer>Archived measured evidence · ADR014 · Isolated lab benchmark</footer>'
                        '</section>')

    slide("Measured learning for network routing",
          "<p class='lead'>A trained PPO actor-critic, real packet traffic, and a locked "
          "comparison against actual FRR OSPF.</p>"
          f"<div class='cards'><div><b>+{goodputGain:.1f}%</b>mean goodput</div>"
          f"<div><b>−{rttReduction:.1f}%</b>mean ICMP RTT</div><div><b>12</b>paired test seeds</div></div>"
          "<p>Scope: stationary 2/20 Mbps path impairment; OSPF costs frozen at nominal bandwidth.</p>",
          "These are scoped held-out results, not a claim that PPO always outperforms OSPF.")
    slide("What problem are we solving?",
          "<p>A nominally preferred route can remain selected when its available capacity "
          "degrades. Queues grow, delivery falls, and RTT increases.</p>"
          "<pre>h1 → access1 ─┬─ dist1 ─┬─ access2 → h3\n"
          "              └─ dist2 ─┘\n"
          "      route 0: dist1     route 1: dist2\n"
          "      core + dist1↔dist2 redundancy; h2→h4 background traffic</pre>"
          "<p>The learned policy chooses between two complete routes using observed conditions.</p>",
          "The model has a fixed two-route action space. It is not a general graph neural router.")
    slide("Two working experimental layers",
          "<ul><li>Application control: FastAPI → durable worker → isolated Mininet/OVS/Ryu; "
          "reroute, multipath, shaping, policing, readback and rollback.</li>"
          "<li>Model benchmark: matched Linux/FRR router namespaces with identical capacities, "
          "traffic, addressing and background routing for all five methods.</li>"
          "<li>Learning: separate CPU PyTorch process consumes measured observations; "
          "training and inference are separate.</li></ul>",
          "Distinguish the application OpenFlow demo from the matched FRR model experiment. "
          "A qualified research checkpoint is not an enabled autonomous deployment.")
    slide("Inside the trained model",
          "<pre>13 scaled metrics + RTT availability + previous-route one-hot = 16 inputs\n"
          "Actor:  16 → Linear(32) → Tanh → 2 route logits → probabilities\n"
          "Critic: 16 → Linear(32) → Tanh → 1 expected-return estimate</pre>"
          "<p>Inputs include capacity, utilization, queues, goodput, actual/target offered load, "
          "loss, RTT and time since route change. Scaling: log1p(value/reference).</p>"
          "<p>Fixed seed 44 · learning rate 0.003 · gamma 0.9 · clipped PPO · GAE.</p>",
          "Action probabilities describe the policy distribution; they are not safety confidence.")
    slide("Reward and training discipline",
          "<pre>reward = delivered / actually sent\n"
          "       − 0.2 × RTT/50ms − loss_fraction\n"
          "       − 0.1 × max_utilization − 0.1 × max_queue/100\n"
          "       − 0.05 × actual_route_change</pre>"
          "<p>384 fresh transitions · 96 episodes · 24 PPO updates. Invalid measurement "
          "windows cannot enter training. No scenario name, seed or future workload enters the actor.</p>",
          "A reward curve alone is insufficient. We test real decisions and packet outcomes.")
    slide("Learning progression", table(
        ["Transitions", "Updates", "Validation reward", "P(correct), path0", "P(correct), path1"],
        [[r[0], r[1], f"{r[2]:.6f}", f"{r[3]:.3f}", f"{r[4]:.3f}"] for r in curves]),
        "These reused validation seeds supported selection. They are not the final test. "
        "The original 512-transition minimum was explicitly waived in a test-only continuation.")
    slide("Locked held-out protocol",
          "<ul><li>Training: seeds 1600–1695. Validation: 2700–2707. Test: 3900–3911.</li>"
          "<li>12 seeds per method, 4 decisions per seed: 48 decisions per method.</li>"
          "<li>PPO, actual OSPF, pressure heuristic, constant route 0, constant route 1.</li>"
          "<li>Five methods: 240 decisions + 60 resets; 0 invalid windows, 0 retries.</li>"
          "<li>95% paired Student-t intervals use 12 seed means, not individual packets.</li>"
          "<li>Checkpoint locked before test access; no test-driven training or tuning.</li></ul>",
          "One randomized method order and one trained initialization limit generalization.")
    slide("Measured delivery, delay and loss",
          bars(metrics, "mean_goodput_mbps", "Goodput — higher is better", "Mbps") +
          bars(metrics, "mean_icmp_rtt_ms", "ICMP RTT — lower is better", "ms") +
          bars(metrics, "mean_verified_drain_loss_fraction", "Mean window loss — lower is better", "%", 100),
          "These are decision-window means. Loss uses final receiver totals after verified queue drain.")
    comparisons = next(r for r in outcome["paired_seed_comparisons"] if r["baseline"] == "ospf")
    rows = []
    for key, label in (("goodput_mbps", "Goodput, Mbps"), ("icmp_rtt_ms", "ICMP RTT, ms"),
                       ("loss_fraction", "Loss, fraction")):
        item = comparisons["metrics"][key]
        rows.append([label, f"{item['mean_delta']:+.6f}",
                     f"[{item['ci95'][0]:.6f}, {item['ci95'][1]:.6f}]"])
    slide("What does the comparison establish?",
          table(["PPO minus OSPF", "Mean difference", "Paired 95% interval"], rows) +
          "<p>Predeclared criterion passed: goodput lower bound &gt; 0 and RTT upper bound &lt; 0.</p>"
          "<p>The gain occurs when nominal OSPF route 0 is impaired. When route 0 is already "
          "healthy, PPO and OSPF perform effectively equally.</p>",
          "Capacity-aware OSPF was not tested. Do not generalize this result to all networks.")
    slide("Control cost and inference timing",
          table(["Measurement", "PPO", "OSPF"], [
              ["Route changes / 48 decisions", "6", "0"],
              ["Live model inference p95", "1.261 ms", "Not an SPF measurement"],
              ["Control/readback p50", "173.487 ms", "48.095 ms"],
              ["Observation/control/IPC p50", "4.280 s", "4.099 s"],
          ]),
          "The benefit is delivery and RTT under the tested impairment, not faster routing computation.")
    body = "<p>Run saved weights on original, measured observations in a fresh process.</p>"
    if inference:
        body += table(["Recorded condition", "Predicted route", "Route probabilities", "Execution"], [
            [name + " impaired", row["first"]["action"],
             ", ".join(f"{x:.5f}" for x in row["first"]["probabilities"]), "not_applied"]
            for name, row in inference.items()
        ])
        body += "<p>Both conditions replayed twice; action, probabilities and value match exactly.</p>"
    else:
        body += "<p>Inference not run in this pack. Rebuild with --infer to capture fresh outputs.</p>"
    slide("Live model computation; recorded network input", body,
          "Call this an inference replay, not newly measured network performance or live actuation.")
    slide("Engineering verification beyond the model",
          table(["Recorded milestone", "Evidence"], [
              ["Manual network control", "Reroute 18.689 Mbps; multipath 37.798 Mbps"],
              ["5 Mbps shaping / policing", "4.758 / 4.870 Mbps; restore verified"],
              ["Durability", "Concurrent dedup, worker death, lost result, rollback, event replay"],
              ["Latest documented application gates", "2,028 backend / 487 frontend / 41 browser passed"],
              ["Step14 acceptance", "22 passed, 0 failed after retests, 9 blocked; partial"],
          ]),
          "Test counts are dated records of different layers, not extra independent model trials. "
          "The current working tree contains later deployment changes.")
    slide("Earlier experiments and remaining work",
          table(["Campaign", "Honest outcome"], [
              ["V2 / ADR013", "Changed weights; fixed-route policies; no useful qualification"],
              ["ADR014", "Learned directionality and scoped held-out result; selected checkpoint"],
              ["ADR015", "512 new transitions; modest validation gain, missed replacement thresholds"],
              ["ADR016", "Stopped at 384 new transitions / 12 updates; no validation or promotion"],
          ]) + "<p>Remaining: broader repeated evaluation, calibrated safety bounds, compatible "
          "governed autonomous deployment and full release acceptance.</p>",
          "Report unsuccessful experiments. The incumbent is retained on evidence, not recency.")
    slide("Takeaway and evidence",
          "<p class='lead'>NANFO demonstrates measured actor-critic route selection that improves "
          "delivery and RTT in a defined held-out congestion benchmark.</p>"
          f"<p>Checkpoint SHA-256:</p><code>{CHECKPOINT_SHA}</code>"
          f"<p>Pack verification: pinned file hashes checked; raw/tensor replay "
          f"{'passed' if audited else 'not requested in this build'}.</p>"
          "<p>Companion files: metrics.csv, paired-seeds.csv, learning-curve.csv, evidence/, "
          "verification.json, PRESENTATION_GUIDE.md.</p>",
          "Close with the measured result, its scope, and the next experiment needed.")
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NANFO — Measured PPO Presentation</title><style>
*{box-sizing:border-box}body{margin:0;background:#e8edf5;color:#16243a;font:20px/1.5 system-ui,sans-serif}
nav{position:sticky;top:0;background:#10243e;color:white;padding:10px 24px;z-index:2;font-size:15px}
button,a{cursor:pointer}nav button{padding:6px 14px;margin-right:10px}section{background:white;
max-width:1200px;margin:28px auto;padding:44px 60px;min-height:690px;scroll-margin-top:65px;
box-shadow:0 8px 30px #16243a18;border-top:6px solid #087f8c}h1{font-size:38px;line-height:1.15;
margin:12px 0 28px}h3{font-size:20px;margin:16px 0 6px}.lead{font-size:27px}.eyebrow,footer{
font-size:13px;letter-spacing:.06em;color:#536780}aside{font-size:16px;border-left:4px solid #d18d13;
padding:10px 16px;background:#fff8e8;margin-top:24px}footer{margin-top:28px}table{border-collapse:collapse;
width:100%;font-size:18px}th,td{text-align:left;padding:10px;border-bottom:1px solid #d4dce8}
th{background:#ecf4f8}pre{background:#edf4f8;padding:22px;font-size:18px;overflow:auto}
code{overflow-wrap:anywhere;font-size:16px}.cards{display:flex;gap:24px}.cards div{flex:1;background:#e9f6f4;
padding:20px}.cards b{display:block;font-size:40px;color:#087f8c}.barrow{display:grid;
grid-template-columns:170px 1fr 150px;gap:12px;align-items:center;font-size:16px;margin:6px 0}
.track{background:#eef1f6;height:18px}.bar{height:18px;background:#8a9bb0}.ppo{background:#087f8c}
.ospf{background:#c76840}.heuristic{background:#7462ae}body.hide-notes aside{display:none}
@media(max-width:700px){section{padding:24px}h1{font-size:29px}.cards{flex-direction:column}
.barrow{grid-template-columns:110px 1fr 100px;font-size:12px}table{font-size:14px}}
@media print{@page{size:A4 landscape;margin:10mm}body{background:white;font-size:16px}nav{display:none}
section{break-after:page;box-shadow:none;margin:0;padding:12px;min-height:0;height:auto}h1{font-size:30px}
aside{font-size:13px}table{font-size:15px}.barrow{font-size:13px}footer{margin-top:14px}}
</style><nav><button onclick="move(-1)">Previous</button><button onclick="move(1)">Next</button>
<button onclick="document.body.classList.toggle('hide-notes')">Speaker notes</button>
<button onclick="window.print()">Print / Save PDF</button> ← → navigation · F11 fullscreen · offline</nav>
""" + "".join(sections) + """<script>
function move(d){let s=[...document.querySelectorAll('section')];
let i=s.reduce((a,v,j)=>Math.abs(v.getBoundingClientRect().top-65)<Math.abs(s[a].getBoundingClientRect().top-65)?j:a,0);
s[Math.max(0,Math.min(s.length-1,i+d))].scrollIntoView({behavior:'smooth'});}
document.addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){
e.preventDefault();move(e.key==='ArrowRight'?1:-1);}});
</script></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New directory; existing directories are refused")
    parser.add_argument("--audit", action="store_true", help="Reconstruct archived raw metrics and PPO outputs")
    parser.add_argument("--infer", action="store_true", help="Run two fresh model processes per recorded direction")
    parser.add_argument("--pdf", action="store_true", help="Export PDF with installed frontend Playwright Chromium")
    args = parser.parse_args()
    output = (args.output or ROOT / "docs/presentation/generated" /
              datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")).resolve()
    for name, expected in PINS.items():
        require(digest(HOLDOUT / name) == expected, f"Pinned evidence changed: {name}")
    require(digest(CHECKPOINT) == CHECKPOINT_SHA, "Selected checkpoint bytes changed.")
    outcome = readJson(HOLDOUT / "outcome.json")
    plan = readJson(HOLDOUT / "plan.json")
    for suffix in ("02", "04", "06"):
        name = f"qualification-{suffix}.json"
        require(digest(TRAIN / name) == plan["original_evidence_sha256"][name],
                f"Pinned validation evidence changed: {name}")
    for policy in POLICIES:
        require(digest(HOLDOUT / f"test-{policy}/evidence.jsonl") ==
                outcome["metrics"][policy]["evidence_sha256"], f"Raw evidence changed: {policy}")
    output.mkdir(parents=True, exist_ok=False)
    verification = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "checkpoint_sha256": CHECKPOINT_SHA, "pinned_hashes_match": True,
                    "fresh_network_measurements": False, "audit": "not_requested",
                    "inference": "not_requested", "pack_complete": False}
    writeJson(output / "verification.json", verification)
    try:
        if args.audit:
            verification["audit"] = auditArchive()
        inference = inferHistories(output) if args.infer else {}
        if inference:
            verification["inference"] = "both_directions_exact_fresh_process_replay"
        curves = []
        for suffix in ("02", "04", "06"):
            q = readJson(TRAIN / f"qualification-{suffix}.json")
            directional = q["directional_dependence"]
            curves.append([q["transitions"], q["updates"], q["validation_mean_reward"],
                           directional["path0"]["mean_desired_probability"],
                           directional["path1"]["mean_desired_probability"]])
        metrics = outcome["metrics"]
        headers = ["method", "goodput_mbps", "icmp_rtt_ms", "mean_window_loss_percent",
                   "packet_weighted_loss_percent", "route_changes", "reward", "seeds", "decisions"]
        rows = [[p, metrics[p]["mean_goodput_mbps"], metrics[p]["mean_icmp_rtt_ms"],
                 100 * metrics[p]["mean_verified_drain_loss_fraction"],
                 100 * metrics[p]["aggregate_packet_weighted_loss_fraction"],
                 metrics[p]["route_changes"], metrics[p]["mean_reward"],
                 metrics[p]["seed_count"], metrics[p]["decision_windows"]] for p in POLICIES]
        writeCsv(output / "metrics.csv", headers, rows)
        writeCsv(output / "learning-curve.csv", ["transitions", "updates", "validation_reward",
                 "p_correct_path0", "p_correct_path1"], curves)
        pairs = [[c["baseline"], key, p["seed"], p["policy"], p["baseline"], p["delta"]]
                 for c in outcome["paired_seed_comparisons"] for key, values in c["metrics"].items()
                 for p in values["pairs"]]
        writeCsv(output / "paired-seeds.csv", ["comparator", "metric", "seed", "ppo", "baseline", "delta"], pairs)
        archive = output / "evidence"
        archive.mkdir()
        for name in PINS:
            shutil.copy2(HOLDOUT / name, archive / name)
        for policy in POLICIES:
            copyAllowlisted(HOLDOUT / f"test-{policy}", archive / f"test-{policy}", SESSION_FILES)
        for suffix in ("02", "04", "06"):
            shutil.copy2(TRAIN / f"qualification-{suffix}.json", archive)
        shutil.copy2(CHECKPOINT, archive / "checkpoint.ptz")
        for name in ("ADR014-HOLDOUT-RESULTS.md", "ADR014-RESULTS-001.md", "ADR015-RESULTS-001.md"):
            shutil.copy2(AI / name, archive)
        shutil.copy2(ROOT / "docs/presentation/PRESENTATION_GUIDE.md", output)
        (output / "slides.html").write_text(buildDeck(outcome, curves, inference, args.audit))
        if args.pdf:
            exportPdf(output)
        verification["pdf"] = "exported" if args.pdf else "not_requested"
        verification["pack_complete"] = True
        writeJson(output / "verification.json", verification)
        manifest = {str(p.relative_to(output)): {"sha256": digest(p), "bytes": p.stat().st_size}
                    for p in sorted(output.rglob("*")) if p.is_file()}
        writeJson(output / "manifest.json", manifest)
        print(f"\nPresentation ready: {output}\nOpen: {(output / 'slides.html').as_uri()}")
        print("PDF: use Print / Save PDF in the slide deck. Recorded results; no lab started.")
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        verification["error"] = str(exc)
        writeJson(output / "verification.json", verification)
        raise


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(f"Presentation build failed: {error}", file=sys.stderr)
        sys.exit(1)
