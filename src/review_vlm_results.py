"""Human review of VLM observations: terminal view + a static HTML labelling page (local files only, read-only).

Run:
  uv run python src/review_vlm_results.py --image-id 2302498470581445        # terminal
  uv run python src/review_vlm_results.py --all                              # terminal, all review images
  uv run python src/review_vlm_results.py --html                             # NVIDIA V2: 21 valid + 6 recovered images
  uv run python src/review_vlm_results.py --html --provider second           # reviewer 2 subset (no reviewer-1 labels)
Then label in the browser, click "Download labels CSV", and merge it with src/merge_manual_labels.py.
One human label per image/category (in the NVIDIA review file) is also used for the Groq comparison (Stage 7), so
there is no separate Groq labelling page.

The page shows MODEL OUTPUT and HUMAN REVIEW as separate blocks. Keyword flags are deliberately NOT shown here, so the
reviewer judges each statement against the image only. Labels: correct | incorrect | uncertain (empty = unreviewed).
"""
import argparse
import csv
import html
import json
import os
from collections import defaultdict
from pathlib import Path

from run_vlm import CATEGORIES

PRIORITY = ["cycling_infrastructure", "street_furniture", "barriers", "curb", "lighting", "public_transport",
            "signage", "pedestrians", "cyclists", "motor_vehicles"]
ORDER = PRIORITY + [c for c in CATEGORIES if c not in PRIORITY]
SOURCES = {  # review csv, image metadata, html output, label column, note column
    "nvidia": (Path("data/processed/vlm_quality_review_observations.csv"),
               Path("data/processed/vlm_evaluation_sample.json"), Path("data/visualizations/vlm_quality_review.html"),
               "manual_label", "manual_note"),
    "second": (Path("data/processed/manual_review_second_reviewer_sample.csv"),
               Path("data/processed/vlm_evaluation_sample.json"),
               Path("data/visualizations/vlm_second_reviewer_review.html"), "reviewer2_label", "reviewer2_note"),
}
RULES = """<table class='rules'><tr><th>model status</th><th>correct</th><th>incorrect</th><th>uncertain</th></tr>
<tr><td>visible</td><td>the described object/category is visibly supported</td><td>it is clearly not supported</td>
<td>ambiguous visual evidence</td></tr>
<tr><td>not_visible <small>(= insufficient visual evidence, NOT absence)</small></td><td>the image does not provide
enough visible evidence</td><td>the object/category is clearly visible</td><td>cannot tell whether it is visible</td></tr>
<tr><td>uncertain</td><td>the model appropriately expressed uncertainty</td><td>the evidence clearly supports visible or
not_visible</td><td>genuinely ambiguous</td></tr></table>"""
COLORS = {"visible": "#2e7d32", "not_visible": "#616161", "uncertain": "#ef6c00"}


def load(provider):
    csv_path, sample_path, _, lab, note = SOURCES[provider]
    meta = {s["image_id"]: s for s in json.loads(sample_path.read_text())["images"]}
    obs = defaultdict(dict)
    for r in csv.DictReader(csv_path.open()):
        obs[r["image_id"]][r["category"]] = {"status": r["status"], "observation": r["observation"],
                                             "confidence": r["confidence"], "model": r["model"],
                                             "manual_label": r.get(lab, ""), "manual_note": r.get(note, ""),
                                             "vlm_source": r.get("vlm_source", "")}
    first = lambda i: next(iter(obs[i].values()))["vlm_source"] != "recovered_v2"  # recovered = first batch
    images = sorted((meta[i] for i in meta if i in obs), key=lambda s: first(s["image_id"]))
    return images, obs


def show(s, o):
    print(f"\n{'#' * 78}\n{s['image_id']}  {s['street_name'] or '(no street name)'} way/{s['street_osm_id']}  "
          f"captured {s['captured_at'][:10]}  seq {s['sequence_id']}\n{s['local_image_path']}")
    for c in ORDER:
        x = o.get(c)
        if x:
            print(f"  {c:24} {x['status']:12} {x['confidence']:<5} {x['observation']}\n"
                  f"  {'':24} HUMAN: {x['manual_label'] or '(unreviewed)'} {x['manual_note']}")


def page(provider, images, obs):
    out = SOURCES[provider][2]
    cards = []
    for s in images:
        i, o = s["image_id"], obs[s["image_id"]]
        img = os.path.relpath(s["local_image_path"], out.parent)
        rows = []
        for c in ORDER:
            x = o.get(c)
            if not x:
                continue
            key = f"{i}|{c}"
            radios = "".join(
                f"<label><input type='radio' name='{html.escape(key)}' value='{v}'"
                f"{' checked' if x['manual_label'] == v else ''}>{v or 'unreviewed'}</label>"
                for v in ("correct", "incorrect", "uncertain", ""))
            rows.append(
                f"<tr class='{'prio' if c in PRIORITY[:6] else ''}'><td class='cat'>{c}</td>"
                f"<td class='model'><span style='color:{COLORS.get(x['status'], '#000')};font-weight:600'>"
                f"{html.escape(x['status'])}</span> <span class='conf'>conf {html.escape(str(x['confidence']))}*</span>"
                f"<br>{html.escape(x['observation'])}</td>"
                f"<td class='human' data-key='{html.escape(key)}'>{radios}<br>"
                f"<input class='note' placeholder='note (optional)' value='{html.escape(x['manual_note'])}'></td></tr>")
        src = next(iter({x["vlm_source"] for x in o.values()}))
        model = next(iter({x["model"] for x in o.values()}))
        badge = "<span class='badge'>FIRST BATCH</span> " if src == "recovered_v2" else ""
        meta = (f"{badge}<b>{html.escape(s['street_name'] or '(no street name)')}</b> · way/{s['street_osm_id']}<br>"
                f"captured {s['captured_at'][:10]} · sequence {html.escape(str(s['sequence_id']))}<br>"
                f"<a href='https://www.mapillary.com/app/?pKey={i}'>Mapillary {i}</a> · VLM data: {html.escape(src)}<br>"
                f"provider/model: NVIDIA hosted · {html.escape(model)}")
        cards.append(f"<section id='{i}'><div class='img'><a href='{img}'><img src='{img}' alt='Mapillary image {i}'>"
                     f"</a><p>{meta}</p></div><table><tr><th>category</th><th class='model'>MODEL OUTPUT (NVIDIA V2)</th>"
                     f"<th class='human'>HUMAN REVIEW</th></tr>{''.join(rows)}</table></section>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>VLM Human Review</title>
<style>body{{font:14px system-ui,sans-serif;margin:16px;background:#fafafa;color:#222}}
section{{display:flex;gap:16px;background:#fff;border:1px solid #ddd;padding:12px;margin:0 0 16px;flex-wrap:wrap}}
.img{{flex:1 1 420px;max-width:560px}} img{{width:100%;height:auto}} table{{flex:1 1 560px;border-collapse:collapse;font-size:13px}}
td,th{{border-bottom:1px solid #eee;padding:4px 6px;text-align:left;vertical-align:top}}
td.model,th.model{{background:#eceff1;width:48%}} td.human,th.human{{background:#fff8e1;border-left:3px dashed #f9a825}}
.cat{{white-space:nowrap}} tr.prio .cat{{font-weight:700}} .conf{{color:#777;font-size:12px}}
label{{margin-right:8px;white-space:nowrap}} .note{{width:95%;margin-top:3px}}
header{{padding:6px 0}} nav{{display:flex;flex-wrap:wrap;gap:4px 8px}}
button{{font:inherit;padding:4px 10px}} .badge{{background:#1565c0;color:#fff;padding:1px 6px;border-radius:3px;font-size:12px}}
table.rules{{flex:none;margin:6px 0;font-size:12px;background:#fff}} table.rules td,table.rules th{{border:1px solid #ddd}}</style></head><body>
<header><h1>Human review of VLM observations{' — SECOND REVIEWER' if provider == 'second' else ''} ({len(images)} images)</h1>
<p><b>Judge each MODEL OUTPUT statement against the image only</b> (not OSM, not the other provider).
<b>not_visible</b> = the image gives insufficient evidence: mark <i>correct</i> if the image really gives no evidence,
<i>uncertain</i> if ambiguous, <i>incorrect</i> if the element is clearly visible. Do not infer hidden infrastructure.
*Model confidence is uncalibrated. Bold categories are the review priority. Images marked FIRST BATCH (the 6 locally
recovered images) come first. Partial labelling is fine: unlabelled rows stay unreviewed. Notes never become labels.</p>
{RULES}
<button id="dl">Download labels CSV</button> <span id="count"></span>
<nav>{''.join(f"<a href='#{s['image_id']}'>{s['image_id']}</a>" for s in images)}</nav></header>
{''.join(cards)}
<script>
const KEY = 'vlm-review-{provider}';
function cells() {{ return [...document.querySelectorAll('td.human')]; }}
function state() {{ return cells().map(td => {{ const [image_id, category] = td.dataset.key.split('|');
  const r = td.querySelector('input[type=radio]:checked'); return {{image_id, category,
  manual_label: r ? r.value : '', manual_note: td.querySelector('.note').value}}; }}); }}
function save() {{ try {{ localStorage.setItem(KEY, JSON.stringify(state())); }} catch (e) {{}} count(); }}
function count() {{ document.getElementById('count').textContent = state().filter(s => s.manual_label).length +
  ' / ' + cells().length + ' labelled'; }}
try {{ const saved = JSON.parse(localStorage.getItem(KEY) || '[]'); const m = new Map(saved.map(s => [s.image_id + '|' + s.category, s]));
  cells().forEach(td => {{ const s = m.get(td.dataset.key); if (!s) return;
    if (td.querySelector('input[type=radio]:checked:not([value=""])')) return;  // merged CSV label wins
    td.querySelectorAll('input[type=radio]').forEach(r => r.checked = r.value === s.manual_label);
    td.querySelector('.note').value = s.manual_note; }}); }} catch (e) {{}}
document.addEventListener('change', save); document.addEventListener('input', save); count();
document.getElementById('dl').onclick = () => {{
  const q = v => '"' + String(v).replace(/"/g, '""') + '"';
  const csv = 'image_id,category,manual_label,manual_note\\n' +
    state().map(s => [s.image_id, s.category, s.manual_label, s.manual_note].map(q).join(',')).join('\\n') + '\\n';
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], {{type: 'text/csv'}}));
  a.download = 'manual_labels_{provider}.csv'; a.click(); }};
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--image-id")
    g.add_argument("--all", action="store_true")
    g.add_argument("--html", action="store_true")
    ap.add_argument("--provider", choices=sorted(SOURCES), default="nvidia")
    a = ap.parse_args()
    images, obs = load(a.provider)
    if a.html:
        out = SOURCES[a.provider][2]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(a.provider, images, obs))
        print(f"Wrote {out} ({len(images)} images, {sum(len(v) for v in obs.values())} observations). Open: xdg-open {out}")
        return
    chosen = [s for s in images if a.all or s["image_id"] == a.image_id]
    if not chosen:
        raise SystemExit(f"{a.image_id} is not in the {a.provider} review set")
    for s in chosen:
        show(s, obs[s["image_id"]])


if __name__ == "__main__":
    main()
