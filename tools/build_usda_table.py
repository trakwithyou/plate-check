#!/usr/bin/env python3
"""Build skills/plate-check/data/usda-foods.tsv from USDA FoodData Central CSVs.

Download and unzip these public-domain datasets from
https://fdc.nal.usda.gov/download-datasets :
  - SR Legacy           (FoodData_Central_sr_legacy_food_csv_2018-04.zip)
  - FNDDS survey foods  (FoodData_Central_survey_food_csv_2024-10-31.zip)

Then run, passing each unzipped folder (the one that contains food.csv):
  python3 tools/build_usda_table.py <sr_legacy_dir> <survey_dir> [out.tsv]

Output: one row per food with per-100 g calories and macros (plus fibre,
sugars, sodium when present) and up to 8 household portions with gram weights.
Foods without complete calories, protein, carbs and fat are left out.
"""
from __future__ import annotations

import csv
import os
import sys

# SR Legacy's food_nutrient.csv uses nutrient ids; the FNDDS file uses the older
# nutrient numbers. The two sets do not overlap, so one map handles both.
NUTRIENTS = {"1008": "kcal", "1003": "protein_g", "1005": "carbs_g", "1004": "fat_g",
             "1079": "fibre_g", "2000": "sugars_g", "1093": "sodium_mg",
             "208": "kcal", "203": "protein_g", "205": "carbs_g", "204": "fat_g",
             "291": "fibre_g", "269": "sugars_g", "307": "sodium_mg"}
COLUMNS = ["fdc_id", "dataset", "description", "kcal", "protein_g", "carbs_g", "fat_g",
           "fibre_g", "sugars_g", "sodium_mg", "portions"]
REQUIRED = ("kcal", "protein_g", "carbs_g", "fat_g")
MAX_PORTIONS = 8
DATASET_LABEL = {"sr_legacy_food": "SR Legacy", "survey_fndds_food": "FNDDS"}


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def load(folder: str) -> dict:
    foods = {r["fdc_id"]: {"fdc_id": r["fdc_id"], "dataset": DATASET_LABEL.get(r["data_type"], r["data_type"]),
                           "description": r["description"].replace("\t", " ").strip(), "portions": []}
             for r in rows(os.path.join(folder, "food.csv"))}
    for r in rows(os.path.join(folder, "food_nutrient.csv")):
        key = NUTRIENTS.get(r["nutrient_id"])
        food = foods.get(r["fdc_id"])
        if key and food is not None and r["amount"] != "":
            food[key] = float(r["amount"])
    units = {r["id"]: r["name"] for r in rows(os.path.join(folder, "measure_unit.csv"))}
    for r in rows(os.path.join(folder, "food_portion.csv")):
        food = foods.get(r["fdc_id"])
        try:
            grams = float(r["gram_weight"] or 0)
        except ValueError:
            continue
        if food is None or grams <= 0 or len(food["portions"]) >= MAX_PORTIONS:
            continue
        label = (r.get("portion_description") or "").strip()
        if not label:  # SR Legacy: amount + unit + modifier
            unit = units.get(r["measure_unit_id"], "")
            unit = "" if unit == "undetermined" else unit
            amount = r["amount"].rstrip("0").rstrip(".") if "." in r["amount"] else r["amount"]
            label = " ".join(p for p in (amount, unit, r["modifier"].strip()) if p)
        if not label or label.lower().startswith("quantity not specified"):
            continue
        label = label.replace("|", "/").replace("=", "-").replace("\t", " ")
        food["portions"].append(f"{label}={fmt(grams)}")
    return foods


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        os.path.dirname(__file__), "..", "skills", "plate-check", "data", "usda-foods.tsv")
    foods = {}
    for folder in sys.argv[1:3]:
        foods.update(load(folder))
    kept = [f for f in foods.values() if all(k in f for k in REQUIRED)]
    kept.sort(key=lambda f: (f["dataset"], f["description"].lower()))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(COLUMNS)
        for food in kept:
            w.writerow([food["fdc_id"], food["dataset"], food["description"],
                        *(fmt(food[k]) if k in food else "" for k in COLUMNS[3:10]),
                        " | ".join(food["portions"])])
    print(f"wrote {len(kept)} foods (skipped {len(foods) - len(kept)} incomplete) to {os.path.abspath(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
