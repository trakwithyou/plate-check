# Plate check

A free agent skill that tells you what's in a meal: calories, protein, carbs
and fat, item by item, with every number labelled by where it came from.

Describe a meal or attach a photo. Your agent (Claude Code, Codex, Cursor or
any agent that supports skills) splits it into items, settles each portion in
grams, looks each item up in a real food database, and shows its working:

- **USDA FoodData Central** for generic foods and dishes
- **Open Food Facts** for branded products and barcodes
- a clearly marked **Estimate** when no database entry fits

It gives a range instead of pretending to be exact, says which assumption
would change the number most, and never presents a guess as data.

No account, no sign-up, no API key required. MIT licensed.

## Install

```bash
npx skills add trakwithyou/plate-check
```

This uses the open [`skills`](https://github.com/vercel-labs/skills) installer,
which asks which agents to install for. To install by hand, copy
`skills/plate-check/` into your agent's skills folder, for example
`~/.claude/skills/plate-check/` for Claude Code.

Requirements: Python 3 (standard library only). Generic foods, cooked dishes
and some chain items are looked up **offline** in a bundled USDA table, so
there is no key and no rate limit. Branded products and barcodes need an
internet connection for Open Food Facts.

Optional: the script can also search USDA online (`usda-api`). That needs a
free key (https://fdc.nal.usda.gov/api-key-signup) set as `FDC_API_KEY`;
without one it falls back to USDA's shared `DEMO_KEY`, which allows only a
few requests an hour. You won't normally need it.

## Use

Just ask, for example:

- "Lunch was a McDonald's Big Mac, medium fries and a medium Coke. How many calories?"
- "How much protein is in this?" plus a photo of your plate
- "Check this barcode: 3017620422003, I had about 15 g"

## Example

Input:

> Lunch was a McDonald's Big Mac, medium fries and a medium Coke. How many calories?

Output (a real run, fully offline):

> **McDonald's lunch: Big Mac, medium fries, medium Coke**: about 1130 kcal (range 1025-1270)
> Protein 28 g | Carbs 147 g | Fat 48 g
>
> | Item | Portion | kcal | P | C | F | Source |
> |---|---|---|---|---|---|---|
> | Big Mac | 1 burger, ~205 g (195-220) | 535 | 24 | 44 | 29 | USDA #2706916 |
> | French fries, medium | ~117 g (105-135) | 380 | 4 | 50 | 18 | USDA #170721 |
> | Coca-Cola, regular, medium | ~512 ml (420-620) | 215 | 0 | 53 | 1 | USDA #2710541 |
>
> **Assumed:**
> - US sizes and recipes, using USDA's household weights: 1 Big Mac = 205 g, 1 medium McDonald's fries = 117 g, 1 medium fountain drink = 512 g.
> - Regular Coke, not Diet or Zero (Diet would bring the drink to about 10 kcal).
> - USDA reference values; McDonald's own published nutrition for your country is the best source.
>
> **Would change it most:** which country you ordered in. Medium fries and drinks are smaller in some countries, which could lower the total by about 100-150 kcal.
>
> **Confidence:** Medium. All three items have good USDA matches, but the portions are standard serving weights rather than weighed.

## How it works

`skills/plate-check/SKILL.md` holds the instructions your agent follows: how
to split a meal, how to judge portions from a photo (cooked edible weight,
scale references, no invented fillings or brands), when to trust a match, and
how to format the answer.

`skills/plate-check/scripts/lookup.py` is a small, dependency-free script that
searches the two public databases and scales their per-100 g values to your
portion:

```bash
python3 scripts/lookup.py usda "chicken breast grilled" --grams 150   # offline
python3 scripts/lookup.py off "nutella" --grams 15                    # online
python3 scripts/lookup.py barcode 3017620422003 --grams 15            # online
```

`skills/plate-check/data/usda-foods.tsv` (1.8 MB, plain text) holds 13,224
foods from USDA's SR Legacy and FNDDS survey datasets: per-100 g calories,
protein, carbs, fat, fibre, sugars and sodium, plus USDA's household portion
weights (for example "1 croissant, medium = 57 g"). To rebuild it from USDA's
downloads, see `tools/build_usda_table.py`.

## Limits

- Portions judged from a description or a photo are the biggest source of
  error. Weigh food when it matters.
- Restaurant recipes vary by country and change over time.
- Open Food Facts is crowd-sourced; entries can be wrong or out of date.
- This is a nutrition estimate, not medical or dietary advice.

## Track it every day

This skill checks one meal at a time. To log meals automatically from a photo
or a barcode and see your day, week and progress, use
[Trak](https://trakwithyou.vercel.app).

## Data and license

- USDA FoodData Central, SR Legacy (April 2018) and FNDDS survey foods
  (October 2024): public domain (CC0). U.S. Department of Agriculture,
  Agricultural Research Service, FoodData Central, fdc.nal.usda.gov.
- Open Food Facts: Open Database License. Data © Open Food Facts contributors.
- Code and instructions: MIT, see [LICENSE](LICENSE).
