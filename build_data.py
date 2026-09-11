"""
Pulls item/stage/zone metadata and drop-rate data from the Penguin Stats
public API, and produces two JSON files for the site's frontend:

  data/materials.json  -> per-material list of stages that drop it, with:
                            - pure drop rate for that material
                            - the stage's overall "value per sanity" score,
                              derived from real drop-rate data only: each
                              item's value is 1/(its best drop rate anywhere),
                              so rarer side drops make a stage score higher.
                              No numbers are guessed or hand-assigned.
  data/meta.json        -> item/stage/zone names, for display and search

Run this to refresh the data
"""

import json
import os
import requests

BASE = "https://penguin-stats.io/PenguinStats/api/v2"
SERVER = "US"  # change to "CN", "JP", or "KR" if you play a different server
OUT_DIR = "data"

# Stages/items with very few samples produce noisy rates. Skip stage-item pairs where the stage has been played fewer than this many times.
MIN_TIMES = 200


def fetch(path):
    r = requests.get(f"{BASE}/{path}", params={"server": SERVER}, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    print(f"Fetching metadata and drop matrix for server={SERVER} ...")
    items = fetch("items")
    stages = fetch("stages")
    zones = fetch("zones")
    matrix = fetch("result/matrix")["matrix"]

    # Build lookup tables
    item_names = {}
    for i in items:
        name_i18n = i.get("name_i18n", {})
        item_names[i["itemId"]] = name_i18n.get("en") or i["itemId"]

    zone_names = {}
    for z in zones:
        name_i18n = z.get("zoneName_i18n", {})
        zone_names[z["zoneId"]] = name_i18n.get("en") or z["zoneId"]

    stage_info = {}
    for s in stages:
        code_i18n = s.get("code_i18n", {})
        stage_info[s["stageId"]] = {
            "code": code_i18n.get("en") or s["stageId"],
            "apCost": s.get("apCost"),
            "zoneId": s.get("zoneId"),
            "zoneName": zone_names.get(s.get("zoneId"), ""),
        }

    # Group matrix rows by stage, filter noisy samples
    by_stage = {}
    for row in matrix:
        if row.get("times", 0) < MIN_TIMES:
            continue
        by_stage.setdefault(row["stageId"], []).append(row)

    # Compute each item's scarcity-based value
    # An item's value is 1 / (its best drop rate anywhere). Items that only ever drop rarely are worth more; items that drop commonly
    # everywhere are worth less.
    best_rate = {}
    for stage_id, rows in by_stage.items():
        for row in rows:
            rate = row["quantity"] / row["times"]
            item_id = row["itemId"]
            if rate > best_rate.get(item_id, 0):
                best_rate[item_id] = rate

    item_value = {
        item_id: (1 / rate) if rate > 0 else 0
        for item_id, rate in best_rate.items()
    }

    # Compute each stage's overall "value per sanity"
    # Sum of (drop rate x item value) for everything the stage drops, divided by AP cost.
    stage_value = {}
    for stage_id, rows in by_stage.items():
        ap = stage_info.get(stage_id, {}).get("apCost")
        if not ap:
            continue
        total = 0.0
        for row in rows:
            rate = row["quantity"] / row["times"]
            total += rate * item_value.get(row["itemId"], 0)
        stage_value[stage_id] = total / ap

    # Build per-material stage lists
    materials = {}
    for stage_id, rows in by_stage.items():
        info = stage_info.get(stage_id, {})
        for row in rows:
            item_id = row["itemId"]
            rate = row["quantity"] / row["times"]
            entry = {
                "stageId": stage_id,
                "stageCode": info.get("code"),
                "zoneName": info.get("zoneName"),
                "apCost": info.get("apCost"),
                "dropRate": round(rate, 5),
                "stageValue": round(stage_value.get(stage_id, 0), 4),
            }
            materials.setdefault(item_id, []).append(entry)

    os.makedirs(OUT_DIR, exist_ok=True)

    materials_out = {
        item_id: {
            "name": item_names.get(item_id, item_id),
            "stages": stage_list,
        }
        for item_id, stage_list in materials.items()
    }

    with open(os.path.join(OUT_DIR, "materials.json"), "w", encoding="utf-8") as f:
        json.dump(materials_out, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"items": item_names, "stages": stage_info, "zones": zone_names},
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Done. Wrote {len(materials_out)} materials to {OUT_DIR}/materials.json")


if __name__ == "__main__":
    main()
