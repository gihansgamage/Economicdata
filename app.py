"""Flask backend for the LankaEconomy.lk Sri Lanka & Global Economic Dashboard.

Serves the interactive dashboard UI and provides REST endpoints for:
* ``GET  /api/summary``        – KPI cards, live ticker, sidebar series & stats
* ``GET  /api/cbsl``           – All CBSL statistical tables & time-series
* ``GET  /api/cbsl/<table_id>``– Single CBSL table with all series
* ``GET  /api/imf``            – All IMF DataMapper global indicators & country series
* ``GET  /api/imf/<ind_id>``   – Single IMF indicator with optional ``?entities=LKA,WLD,IND``
* ``GET  /api/search?q=...``   – Cross-source search across CBSL + IMF series
* ``POST /api/refresh``        – Live re-extraction from CBSL & IMF APIs
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from backend.build_data import build_all_data

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"

app = Flask(__name__, static_folder=str(ROOT_DIR), static_url_path="")

_MEM_CACHE: dict[str, dict] = {}


def _load_json(filename: str) -> dict:
    path = DATA_DIR / filename
    if not path.exists():
        build_all_data(ROOT_DIR, refresh_remote=False)
    mtime = path.stat().st_mtime
    cached = _MEM_CACHE.get(filename)
    if not cached or cached["mtime"] != mtime:
        _MEM_CACHE[filename] = {
            "mtime": mtime,
            "data": json.loads(path.read_text(encoding="utf-8")),
        }
    return _MEM_CACHE[filename]["data"]


@app.route("/")
def index():
    return send_from_directory(str(ROOT_DIR), "index.html")


@app.route("/data/<path:filename>")
def serve_data(filename: str):
    return send_from_directory(str(DATA_DIR), filename)


@app.route("/api/summary")
def api_summary():
    return jsonify(_load_json("summary.json"))


@app.route("/api/cbsl")
def api_cbsl():
    data = _load_json("cbsl_data.json")
    cat = request.args.get("category")
    freq = request.args.get("freq")
    if not cat and not freq:
        return jsonify(data)
    tables = data["tables"]
    if cat:
        tables = [t for t in tables if t["category"].lower() == cat.lower()]
    if freq:
        tables = [t for t in tables if freq.upper() in t["frequencies"]]
    return jsonify({**data, "tables": tables})


@app.route("/api/cbsl/<table_id>")
def api_cbsl_table(table_id: str):
    data = _load_json("cbsl_data.json")
    for t in data["tables"]:
        if t["id"] == table_id:
            return jsonify(t)
    abort(404, description=f"Table {table_id!r} not found")


@app.route("/api/imf")
def api_imf():
    data = _load_json("imf_data.json")
    cat = request.args.get("category")
    if not cat:
        return jsonify(data)
    inds = [i for i in data["indicators"] if i["category"].lower() == cat.lower()]
    return jsonify({**data, "indicators": inds})


@app.route("/api/imf/<ind_id>")
def api_imf_indicator(ind_id: str):
    data = _load_json("imf_data.json")
    ents = request.args.get("entities")
    ent_set = {e.strip().upper() for e in ents.split(",") if e.strip()} if ents else None
    for ind in data["indicators"]:
        if ind["id"].upper() == ind_id.upper():
            if ent_set:
                vals = {k: v for k, v in ind["values"].items() if k in ent_set}
                return jsonify({**ind, "values": vals})
            return jsonify(ind)
    abort(404, description=f"Indicator {ind_id!r} not found")


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify({"cbsl": [], "imf": []})
    cbsl = _load_json("cbsl_data.json")
    imf = _load_json("imf_data.json")

    cbsl_hits = []
    for t in cbsl["tables"]:
        t_match = q in t["title"].lower() or q in t["category"].lower()
        for s in t["series"]:
            if t_match or q in s["name"].lower():
                cbsl_hits.append({
                    "table_id": t["id"],
                    "table_title": t["title"],
                    "category": t["category"],
                    "unit": t["unit"],
                    "series_id": s["id"],
                    "series_name": s["name"],
                    "freq": s["freq"],
                    "start": s["start"],
                    "end": s["end"],
                    "last": s["last"],
                })
                if len(cbsl_hits) >= 60:
                    break
        if len(cbsl_hits) >= 60:
            break

    imf_hits = []
    for ind in imf["indicators"]:
        if q in ind["title"].lower() or q in ind["id"].lower() or q in ind["category"].lower() or q in ind.get("description", "").lower():
            imf_hits.append({
                "id": ind["id"],
                "title": ind["title"],
                "category": ind["category"],
                "unit": ind["unit"],
                "dataset": ind["dataset"],
                "start": ind["start"],
                "end": ind["end"],
                "entity_count": ind["entity_count"],
            })

    return jsonify({"cbsl": cbsl_hits, "imf": imf_hits})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    summary = build_all_data(ROOT_DIR, refresh_remote=True)
    _MEM_CACHE.clear()
    return jsonify({"status": "ok", "stats": summary["stats"], "generated_at": summary["generated_at"]})


if __name__ == "__main__":
    if not (DATA_DIR / "summary.json").exists():
        build_all_data(ROOT_DIR, refresh_remote=False)
    port = int(os.environ.get("PORT", 5050))
    print(f"LankaEconomy.lk Dashboard running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

