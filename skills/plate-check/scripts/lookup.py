#!/usr/bin/env python3
"""Plate check: look up real nutrition data from free public databases.

Sources
  usda      USDA FoodData Central, searched OFFLINE in the bundled table
            data/usda-foods.tsv (about 13,000 generic foods, dishes and some
            chain items from SR Legacy and FNDDS, with household portion
            weights). Public domain. No key, no network, no rate limit.
  usda-api  The live USDA FoodData Central search API. Uses FDC_API_KEY if set,
            otherwise the shared DEMO_KEY (only a few requests per hour).
            Free personal key: https://fdc.nal.usda.gov/api-key-signup
  off       Open Food Facts product search (branded / packaged foods). No key.
  barcode   Open Food Facts product by barcode. No key.

Every value is per 100 g (or 100 ml for some drinks) from the source, and is
scaled to --grams when given. Only standard-library Python is used.

Examples
  python3 lookup.py usda "chicken breast grilled" --grams 150
  python3 lookup.py off "nutella" --grams 15
  python3 lookup.py barcode 3017620422003 --grams 15
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "plate-check-skill/1.0 (open-source agent skill)"
TIMEOUT = 20
FDC_SEARCH = "https://api.nal.usda.gov/fdc/v1/foods/search"
OFF_SEARCH = "https://search.openfoodfacts.org/search"
OFF_PRODUCT = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
KJ_PER_KCAL = 4.184

# FoodData Central nutrient ids.
FDC_KCAL = (1008, 2048, 2047)  # Energy; Atwater specific; Atwater general
FDC_PROTEIN, FDC_FAT, FDC_CARBS = 1003, 1004, 1005
FDC_FIBRE, FDC_SUGARS, FDC_SODIUM = 1079, 2000, 1093


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return json.load(res)


def scaled(per100: dict, grams: float | None) -> dict | None:
    if grams is None:
        return None
    f = grams / 100.0
    return {k: (round(v * f, 1) if isinstance(v, (int, float)) else None) for k, v in per100.items()}


def complete(per100: dict) -> bool:
    return all(isinstance(per100.get(k), (int, float)) and per100[k] >= 0
               for k in ("kcal", "protein_g", "carbs_g", "fat_g"))


# ---------------------------------------------------------------- USDA FDC
def fdc_value(food: dict, ids) -> float | None:
    ids = ids if isinstance(ids, tuple) else (ids,)
    by_id = {n.get("nutrientId"): n for n in food.get("foodNutrients", [])}
    for i in ids:
        n = by_id.get(i)
        if n and isinstance(n.get("value"), (int, float)):
            # Energy can also be reported in kJ; only accept kcal for 1008.
            if i == 1008 and str(n.get("unitName", "")).upper() != "KCAL":
                continue
            return float(n["value"])
    return None


# --------------------------------------------------- USDA, bundled offline table
TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "usda-foods.tsv")
NUMERIC = ("kcal", "protein_g", "carbs_g", "fat_g", "fibre_g", "sugars_g", "sodium_mg")
EXTRA_WEIGHT = 0.0  # extra words only break ties; higher values tested worse on a 19-food check
STOP = {"a", "an", "and", "the", "of", "with", "in", "on", "or", "s"}


def tokens(text: str) -> list[str]:
    text = text.lower().replace("'", "").replace("’", "")
    out = []
    for t in re.split(r"[^a-z0-9%]+", text):
        if not t or t in STOP:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]  # croissants -> croissant, mcdonalds -> mcdonald
        out.append(t)
    return out


def usda_local(query: str, grams: float | None, limit: int) -> list[dict]:
    q = tokens(query)
    if not q:
        return []
    qset = set(q)
    def same(qt: str, dt: str) -> bool:
        # "toast" matches "toasted"; short words must match exactly.
        return qt == dt or (min(len(qt), len(dt)) >= 4 and (dt.startswith(qt) or qt.startswith(dt)))

    scored = []
    with open(TABLE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            dset = set(tokens(row["description"]))
            matched = {d for d in dset if any(same(q_, d) for q_ in qset)}
            hits = sum(1 for q_ in qset if any(same(q_, d) for d in dset))
            if not hits:
                continue
            head = set(tokens(row["description"].split(",")[0]))
            head_hit = sum(1 for h in head if h in matched) / max(len(head), 1)
            extra = len(dset - matched)
            # Rank by query words matched, then by how much of the food's main
            # name (before the first comma) matched, then by fewest extra words.
            scored.append((-(hits - EXTRA_WEIGHT * extra), -head_hit, extra, row))
    scored.sort(key=lambda s: s[:3])
    out = []
    for _, _, _, row in scored[:limit]:
        per100 = {k: (float(row[k]) if row[k] != "" else None) for k in NUMERIC}
        portions = []
        for part in filter(None, (p.strip() for p in row["portions"].split(" | "))):
            label, _, g = part.rpartition("=")
            try:
                portions.append({"label": label, "grams": float(g)})
            except ValueError:
                pass
        fid = row["fdc_id"]
        out.append({
            "source": "USDA FoodData Central (offline table)",
            "source_type": row["dataset"],
            "name": row["description"],
            "id": int(fid),
            "url": f"https://fdc.nal.usda.gov/food-details/{fid}/nutrients",
            "basis": "per 100 g",
            "per_100": per100,
            "usda_portions": portions,
            "for_grams": grams,
            "scaled": scaled(per100, grams),
        })
    return out


def usda(query: str, grams: float | None, limit: int) -> list[dict]:
    key = os.environ.get("FDC_API_KEY") or "DEMO_KEY"
    params = urllib.parse.urlencode({
        "api_key": key,
        "query": query,
        "dataType": "Foundation,SR Legacy,Survey (FNDDS)",
        "pageSize": limit,
    })
    data = get_json(f"{FDC_SEARCH}?{params}")
    out = []
    for food in data.get("foods", [])[:limit]:
        per100 = {
            "kcal": fdc_value(food, FDC_KCAL),
            "protein_g": fdc_value(food, FDC_PROTEIN),
            "carbs_g": fdc_value(food, FDC_CARBS),
            "fat_g": fdc_value(food, FDC_FAT),
            "fibre_g": fdc_value(food, FDC_FIBRE),
            "sugars_g": fdc_value(food, FDC_SUGARS),
            "sodium_mg": fdc_value(food, FDC_SODIUM),
        }
        if not complete(per100):
            continue
        fid = food.get("fdcId")
        out.append({
            "source": "USDA FoodData Central",
            "source_type": food.get("dataType"),
            "name": food.get("description"),
            "id": fid,
            "url": f"https://fdc.nal.usda.gov/food-details/{fid}/nutrients",
            "basis": "per 100 g",
            "per_100": per100,
            "for_grams": grams,
            "scaled": scaled(per100, grams),
        })
    return out


# ---------------------------------------------------------- Open Food Facts
def off_per100(n: dict) -> dict:
    def num(key):
        v = n.get(key)
        try:
            return float(v) if v is not None and v != "" else None
        except (TypeError, ValueError):
            return None

    kcal = num("energy-kcal_100g")
    if kcal is None:
        kj = num("energy-kj_100g") or num("energy_100g")  # energy_100g is kJ
        kcal = round(kj / KJ_PER_KCAL, 1) if kj is not None else None
    sodium = num("sodium_100g")
    return {
        "kcal": kcal,
        "protein_g": num("proteins_100g"),
        "carbs_g": num("carbohydrates_100g"),
        "fat_g": num("fat_100g"),
        "fibre_g": num("fiber_100g"),
        "sugars_g": num("sugars_100g"),
        "sodium_mg": round(sodium * 1000, 1) if sodium is not None else None,
    }


def off_entry(p: dict, grams: float | None) -> dict | None:
    per100 = off_per100(p.get("nutriments") or {})
    if not complete(per100):
        return None
    brands = p.get("brands")
    if isinstance(brands, list):
        brands = ", ".join(brands)
    code = p.get("code")
    return {
        "source": "Open Food Facts",
        "source_type": "product label (crowd-sourced)",
        "name": p.get("product_name"),
        "brand": brands,
        "id": code,
        "url": f"https://world.openfoodfacts.org/product/{code}",
        "basis": "per 100 g/ml",
        "label_serving": p.get("serving_size"),
        "per_100": per100,
        "for_grams": grams,
        "scaled": scaled(per100, grams),
    }


def off(query: str, grams: float | None, limit: int) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": query,
        "page_size": max(limit * 3, 10),  # many hits lack complete nutrition
        "fields": "code,product_name,brands,nutriments,serving_size",
    })
    data = get_json(f"{OFF_SEARCH}?{params}")
    out = [e for e in (off_entry(p, grams) for p in data.get("hits", [])) if e]
    return out[:limit]


def barcode(code: str, grams: float | None) -> list[dict]:
    fields = "code,product_name,brands,nutriments,serving_size"
    data = get_json(OFF_PRODUCT.format(code=urllib.parse.quote(code)) + f"?fields={fields}")
    p = data.get("product")
    if not p:
        return []
    p.setdefault("code", code)
    e = off_entry(p, grams)
    return [e] if e else [{"source": "Open Food Facts", "id": code, "name": p.get("product_name"),
                           "error": "Product found but its label nutrition is incomplete. Do not treat missing values as zero."}]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", choices=["usda", "usda-api", "off", "barcode"])
    ap.add_argument("query", help="food name, or a barcode for 'barcode'")
    ap.add_argument("--grams", "--ml", dest="grams", type=float,
                    help="portion to scale to: edible grams, or ml for drinks (1 ml is treated as 1 g)")
    ap.add_argument("-n", "--limit", type=int, default=8, help="max matches (default 8)")
    ap.add_argument("--json", action="store_true", help="full JSON output (with URLs and fibre/sugars/sodium)")
    a = ap.parse_args()
    if a.grams is not None and a.grams <= 0:
        ap.error("--grams must be positive")
    try:
        if a.source == "usda":
            results = usda_local(a.query, a.grams, a.limit)
        elif a.source == "usda-api":
            results = usda(a.query, a.grams, a.limit)
        elif a.source == "off":
            results = off(a.query, a.grams, a.limit)
        else:
            results = barcode(a.query, a.grams)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            body = ""
        # api.data.gov can signal an exhausted key with 429 or another status
        # whose body says OVER_RATE_LIMIT; report both the same way.
        limited = e.code == 429 or "RATE_LIMIT" in body.upper()
        err = {"error": f"HTTP {e.code} from {a.source}", "kind": "rate_limited" if limited else "http_error"}
        if limited and a.source == "usda-api":
            err["hint"] = ("The shared DEMO_KEY allows only a few requests per hour. "
                           "Set FDC_API_KEY to a free personal key: https://fdc.nal.usda.gov/api-key-signup")
        elif body:
            err["detail"] = body
        print(json.dumps(err))
        return 1
    except OSError as e:
        if a.source == "usda" and not os.path.exists(TABLE):
            print(json.dumps({"error": "bundled table data/usda-foods.tsv is missing; reinstall the skill or use usda-api",
                              "kind": "missing_data"}))
            return 1
        if not isinstance(e, urllib.error.URLError):
            raise
        print(json.dumps({"error": f"lookup failed: {e}", "kind": "network"}))
        return 1
    except (TimeoutError, json.JSONDecodeError) as e:
        print(json.dumps({"error": f"lookup failed: {e}"}))
        return 1
    if a.json:
        print(json.dumps({"query": a.query, "matches": results}, indent=2, ensure_ascii=False))
    else:
        print(brief(a.query, results))
    return 0


def brief(query: str, results: list[dict]) -> str:
    """One compact block per match, small enough to read a whole list at once."""
    def nums(d):
        r = {k: round(d[k], 2) for k in ("kcal", "protein_g", "carbs_g", "fat_g")}
        return f"{r['kcal']:g} kcal, P {r['protein_g']:g} g, C {r['carbs_g']:g} g, F {r['fat_g']:g} g"

    lines = [f'query: "{query}"  ({len(results)} match{"es" if len(results) != 1 else ""})']
    for i, m in enumerate(results, 1):
        if "error" in m:
            lines.append(f"{i}. {m.get('name') or m.get('id')}: {m['error']}")
            continue
        tag = "USDA" if m["source"].startswith("USDA") else "Label"
        name = m["name"] + (f" [{m['brand']}]" if m.get("brand") else "")
        lines.append(f"{i}. {tag} #{m['id']} ({m.get('source_type')}) {name}")
        lines.append(f"   {m['basis']}: {nums(m['per_100'])}")
        if m.get("scaled"):
            lines.append(f"   at {m['for_grams']:g} g: {nums(m['scaled'])}")
        if m.get("usda_portions"):
            lines.append("   USDA portions: " + "; ".join(f"{p['label']} = {p['grams']:g} g" for p in m["usda_portions"]))
        if m.get("label_serving"):
            lines.append(f"   label serving: {m['label_serving']}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
