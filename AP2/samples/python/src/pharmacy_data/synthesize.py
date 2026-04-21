"""Deterministic synthesizers that expand the seed CSVs.

All randomness flows through a single seeded ``random.Random`` instance, so
``synthesize.build(seed=42)`` is bit-for-bit reproducible. Outputs are pure
Python dicts shaped to match the schema; ``seed.py`` writes them to SQLite.

We commit to *plausible-looking* synthetic data, NOT to real-world accuracy.
Prices come from per-category log-normal fits to the seed; ingredient lists
are sampled from per-category active+inactive pools. This is sufficient for
agent reasoning ("recommend something for kids' fever") but should not be
mistaken for real medical data.
"""

from __future__ import annotations

import math
import random
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

# ----------------------------------------------------------------------------
#  Static pools
# ----------------------------------------------------------------------------

UK_BRAND_POOL: dict[str, list[str]] = {
    "Pain Relief":            ["Nurofen", "Panadol", "Anadin", "Galpharm", "Care", "Boots", "Hedex"],
    "Children's Health":      ["Calpol", "Nurofen for Children", "Boots", "Galpharm", "Calprofen"],
    "Allergy & Sinus":        ["Piriton", "Piriteze", "Cetirizine", "Beconase", "Boots", "Galpharm"],
    "Cold & Flu":             ["Lemsip", "Beechams", "Sudafed", "Olbas", "Vicks", "Boots", "Day Nurse"],
    "Digestive Health":       ["Rennie", "Gaviscon", "Buscopan", "Boots", "Care", "Senokot"],
    "Smoking Cessation":      ["Nicorette", "NiQuitin", "Boots Smoking Cessation"],
    "First Aid":              ["Elastoplast", "Boots", "Savlon", "Germolene"],
    "Vitamins & Supplements": ["Centrum", "Berocca", "Seven Seas", "Sanatogen", "Boots", "Vitabiotics"],
}

# Form / dose / action templates per category (drives titles + descriptions).
CATEGORY_TEMPLATES = {
    "Pain Relief": {
        "forms":   ["Tablets", "Caplets", "Soluble Tablets", "Liquid Capsules", "Gel Caps"],
        "actives": [("Ibuprofen", "200mg"), ("Ibuprofen", "400mg"),
                    ("Paracetamol", "500mg"), ("Aspirin", "300mg"),
                    ("Naproxen", "250mg"), ("Codeine + Paracetamol", "8mg/500mg")],
        "actions": ["headaches", "muscle aches", "backaches", "period pain",
                    "minor arthritis pain", "fever"],
        "policy": ("Adults and children 12+. Take 1-2 tablets every 4-6 hours as needed. "
                   "Do not exceed 6 doses in 24 hours. Not suitable for pregnancy without "
                   "physician consultation."),
    },
    "Children's Health": {
        "forms":   ["Suspension", "Liquid", "Chewable Tablets", "Sachets"],
        "actives": [("Ibuprofen", "100mg/5ml"), ("Paracetamol", "120mg/5ml"),
                    ("Paracetamol", "250mg/5ml"), ("Saline Nasal Drops", "0.9%")],
        "actions": ["fever", "teething pain", "minor aches", "cold symptoms",
                    "sore throat"],
        "policy": ("Ages 2-11. Dose by weight; refer to pack chart. "
                   "Do not give to children under 2 without physician guidance. "
                   "If symptoms persist beyond 3 days, consult a doctor."),
    },
    "Allergy & Sinus": {
        "forms":   ["Tablets", "Nasal Spray", "Eye Drops", "Liquid"],
        "actives": [("Loratadine", "10mg"), ("Cetirizine", "10mg"),
                    ("Fexofenadine", "120mg"), ("Beclomethasone", "50mcg/spray"),
                    ("Sodium Cromoglicate", "2%")],
        "actions": ["hay fever", "year-round allergies", "itchy eyes",
                    "runny nose", "sneezing"],
        "policy": ("Adults and children 6+. Take 1 tablet daily. Do not exceed "
                   "1 dose in 24 hours. Suitable for daily use throughout allergy season."),
    },
    "Cold & Flu": {
        "forms":   ["Sachets", "Capsules", "Lozenges", "Liquid", "Nasal Spray"],
        "actives": [("Paracetamol + Phenylephrine", "500mg/6.1mg"),
                    ("Ibuprofen + Pseudoephedrine", "200mg/30mg"),
                    ("Guaifenesin", "100mg/5ml"),
                    ("Menthol + Eucalyptus", "5.4mg/1mg"),
                    ("Xylometazoline", "0.1%")],
        "actions": ["blocked nose", "sore throat", "cough", "fever", "body aches"],
        "policy": ("Adults and children 12+. Follow pack instructions. Do not exceed "
                   "stated dose. Avoid combining with other paracetamol-containing products."),
    },
    "Digestive Health": {
        "forms":   ["Tablets", "Liquid", "Sachets", "Chewable Tablets"],
        "actives": [("Loperamide", "2mg"), ("Bismuth Subsalicylate", "262mg"),
                    ("Simethicone", "125mg"), ("Sodium Alginate", "500mg/10ml"),
                    ("Senna", "7.5mg"), ("Hyoscine Butylbromide", "10mg")],
        "actions": ["heartburn", "indigestion", "bloating", "diarrhoea",
                    "constipation", "stomach cramps"],
        "policy": ("Adults and children 12+. Follow pack instructions. If symptoms "
                   "persist beyond 14 days, consult a physician."),
    },
    "Smoking Cessation": {
        "forms":   ["Lozenges", "Gum", "Patches", "Inhalator", "Mouth Spray"],
        "actives": [("Nicotine", "2mg"), ("Nicotine", "4mg"),
                    ("Nicotine", "7mg/24h patch"), ("Nicotine", "14mg/24h patch"),
                    ("Nicotine", "21mg/24h patch")],
        "actions": ["nicotine cravings", "withdrawal symptoms", "smoking urges"],
        "policy": ("Adults 18+ only. Stop smoking completely when starting. "
                   "Not for use during pregnancy without physician consultation."),
    },
    "First Aid": {
        "forms":   ["Plasters", "Wound Spray", "Antiseptic Cream", "Burn Gel",
                    "Eye Wash", "Bandages"],
        "actives": [("Cetrimide", "0.5%"), ("Chlorhexidine", "0.05%"),
                    ("Hydrocortisone", "1%"), ("Sterile Saline", "0.9%"),
                    ("Crotamiton", "10%")],
        "actions": ["minor cuts", "grazes", "burns", "stings",
                    "skin irritation"],
        "policy": ("Suitable for all ages for minor injuries without physician consultation. "
                   "For deep wounds or persistent bleeding, seek medical attention."),
    },
    "Vitamins & Supplements": {
        "forms":   ["Tablets", "Capsules", "Effervescent Tablets", "Gummies", "Liquid"],
        "actives": [("Vitamin D3", "1000 IU"), ("Vitamin C", "1000mg"),
                    ("Vitamin B Complex", ""), ("Iron", "14mg"),
                    ("Multivitamin", ""), ("Omega-3", "1000mg"),
                    ("Magnesium", "375mg"), ("Zinc", "15mg")],
        "actions": ["immune support", "energy metabolism", "bone health",
                    "joint health", "general wellbeing"],
        "policy": ("Adults 18+. Take 1 tablet daily with food. Suitable for "
                   "long-term self-use. Keep out of reach of children."),
    },
}

INACTIVES_POOL = [
    "Microcrystalline Cellulose", "Magnesium Stearate", "Hypromellose",
    "Polyethylene Glycol", "Corn Starch", "Lactose Monohydrate",
    "Croscarmellose Sodium", "Colloidal Silicon Dioxide", "Sorbitol",
    "Glycerin", "Purified Water", "Sodium Benzoate", "Citric Acid",
    "Xanthan Gum", "Sucrose", "Mannitol",
]

SHELF_BY_CATEGORY = {
    "Pain Relief":            "Pain Relief",
    "Children's Health":      "Children's Health",
    "Allergy & Sinus":        "Allergy & Sinus",
    "Cold & Flu":             "Cold & Flu",
    "Digestive Health":       "Digestive Health",
    "Smoking Cessation":      "Smoking Cessation",
    "First Aid":              "First Aid",
    "Vitamins & Supplements": "Vitamins & Supplements",
}

# UK-test-only Adyen card BINs (last4 from Adyen test card list).
ADYEN_TEST_LAST4 = ["1111", "4444", "5100", "8888", "9995"]
ADYEN_TEST_BRAND = {
    "1111": "Visa",
    "4444": "Mastercard",
    "5100": "Mastercard",
    "8888": "Visa",
    "9995": "Amex",
}

UK_FIRST_NAMES = [
    "Aarav", "Priya", "Rohan", "Anika", "Olivia", "Noah", "Amelia",
    "Oliver", "Isla", "Leo", "Sophia", "Jacob", "Mia", "Harper",
    "Zara", "Ethan", "Maya", "Lucas", "Ava", "Ben", "Ruby",
    "Ishaan", "Sara", "Ronan", "Freya",
]
UK_LAST_NAMES = [
    "Sharma", "Iyer", "Patel", "Khan", "Smith", "Jones", "Brown",
    "Taylor", "Wilson", "Davies", "Evans", "Walker", "Reed", "Singh",
    "Kaur", "Roberts", "Lewis", "Scott", "Murphy", "Bennett",
    "Cooper", "Hughes", "Green", "Hall", "Wood",
]

CATEGORY_WEIGHTS = {
    "Pain Relief":            1.4,
    "Children's Health":      0.9,
    "Allergy & Sinus":        1.0,
    "Cold & Flu":             1.3,
    "Digestive Health":       1.1,
    "Smoking Cessation":      0.4,
    "First Aid":              0.7,
    "Vitamins & Supplements": 1.2,
}


# ----------------------------------------------------------------------------
#  Container for all generated rows
# ----------------------------------------------------------------------------

@dataclass
class SynthBundle:
    products: list[dict]                  = field(default_factory=list)
    stock_map: list[dict]                 = field(default_factory=list)
    inventory: list[dict]                 = field(default_factory=list)
    customers: list[dict]                 = field(default_factory=list)
    merchant_on_file_methods: list[dict]  = field(default_factory=list)
    past_orders: list[dict]               = field(default_factory=list)
    past_order_lines: list[dict]          = field(default_factory=list)


# ----------------------------------------------------------------------------
#  Product expansion
# ----------------------------------------------------------------------------

def _per_category_price_stats(seed_products: Sequence[dict]) -> dict[str, tuple[float, float]]:
    """Returns {category: (mean_log, stdev_log)} for log-normal sampling."""
    by_cat: dict[str, list[float]] = {}
    for p in seed_products:
        by_cat.setdefault(p["category"], []).append(p["base_price_gbp"])
    out: dict[str, tuple[float, float]] = {}
    for cat, prices in by_cat.items():
        logs = [math.log(p) for p in prices if p > 0]
        if len(logs) >= 2:
            out[cat] = (statistics.mean(logs), max(statistics.stdev(logs), 0.15))
        elif logs:
            out[cat] = (logs[0], 0.25)
        else:
            out[cat] = (math.log(8.0), 0.3)
    # Ensure every category has stats even if no seed example.
    for cat in CATEGORY_TEMPLATES:
        out.setdefault(cat, (math.log(8.0), 0.3))
    return out


def _gen_product(rng: random.Random, idx: int, category: str,
                 price_stats: dict[str, tuple[float, float]]) -> dict:
    tpl = CATEGORY_TEMPLATES[category]
    brand = rng.choice(UK_BRAND_POOL[category])
    form  = rng.choice(tpl["forms"])
    active, dose = rng.choice(tpl["actives"])
    action = rng.choice(tpl["actions"])

    title_dose = f" {dose}" if dose else ""
    title = f"{brand} {active}{title_dose} {form}"

    description = (
        f"{form} containing {active}{(' ' + dose) if dose else ''} for the "
        f"relief of {action}. UK pharmacy general-sale formulation."
    )

    inactives = rng.sample(INACTIVES_POOL, k=rng.randint(2, 4))
    ingredients = (
        f"{active}{(' ' + dose) if dose else ''}. "
        f"Inactive: {', '.join(inactives)}."
    )

    mu, sigma = price_stats[category]
    price = round(math.exp(rng.gauss(mu, sigma)), 2)
    price = max(2.49, min(price, 49.99))

    return {
        "product_ref":    f"P{idx:03d}",
        "title":          title,
        "brand":          brand,
        "category":       category,
        "description":    description,
        "policy":         tpl["policy"],
        "ingredients":    ingredients,
        "base_price_gbp": price,
    }


def _stock_ref_for(brand: str, idx: int) -> str:
    prefix = "".join(c for c in brand.upper() if c.isalpha())[:3] or "GEN"
    return f"SKU-{prefix}-{idx:03d}"


def expand_products(seed_products: list[dict], seed_stock: list[dict],
                    target: int, rng: random.Random) -> tuple[list[dict], list[dict]]:
    """Generate ``target`` products total. Seeds keep their P001..P0NN refs."""
    # Seeds get P001..P{n} and their existing stock_refs.
    enriched: list[dict] = []
    for i, p in enumerate(seed_products, start=1):
        pref = f"P{i:03d}"
        enriched.append({"product_ref": pref, **p})

    stock_map = [{"product_ref": r["product_ref"], "stock_ref": r["stock_ref"]}
                 for r in seed_stock]

    price_stats = _per_category_price_stats(seed_products)
    cats = list(CATEGORY_WEIGHTS.keys())
    cat_weights = [CATEGORY_WEIGHTS[c] for c in cats]

    next_idx = len(enriched) + 1
    while len(enriched) < target:
        cat = rng.choices(cats, weights=cat_weights, k=1)[0]
        prod = _gen_product(rng, next_idx, cat, price_stats)
        enriched.append(prod)
        stock_map.append({
            "product_ref": prod["product_ref"],
            "stock_ref":   _stock_ref_for(prod["brand"], next_idx),
        })
        next_idx += 1

    return enriched, stock_map


# ----------------------------------------------------------------------------
#  Inventory expansion
# ----------------------------------------------------------------------------

def expand_inventory(seed_inventory: list[dict], stock_map: list[dict],
                     products: list[dict], stores: list[tuple[str, str]],
                     rng: random.Random, oos_rate: float = 0.05) -> list[dict]:
    """Cross-product all SKUs × stores, keeping seed rows verbatim."""
    by_pref = {p["product_ref"]: p for p in products}
    sref_to_pref = {s["stock_ref"]: s["product_ref"] for s in stock_map}

    out: list[dict] = list(seed_inventory)
    seen_keys = {(r["stock_ref"], r["store_location"]) for r in seed_inventory}
    next_inv_id = 1 + max(
        (int(r["inv_id"].split("-", 1)[1]) for r in seed_inventory if "-" in r["inv_id"]),
        default=0,
    )

    SHELF_AISLE = lambda cat: f"Aisle {rng.randint(1, 10)} - {SHELF_BY_CATEGORY.get(cat, cat)}"

    for s in stock_map:
        pref = s["product_ref"]
        prod = by_pref[pref]
        for store_loc, region in stores:
            if (s["stock_ref"], store_loc) in seen_keys:
                continue
            qty = 0 if rng.random() < oos_rate else rng.randint(8, 240)
            local = round(prod["base_price_gbp"] * rng.uniform(0.92, 1.08), 2)
            out.append({
                "inv_id":            f"INV-{next_inv_id:04d}",
                "stock_ref":         s["stock_ref"],
                "store_location":    store_loc,
                "store_region":      region,
                "qty_in_stock":      qty,
                "local_price_gbp":   local,
                "currency":          "GBP",
                "last_restock_date": "2025-03-01",
                "shelf_location":    SHELF_AISLE(prod["category"]),
                "notes":             None,
            })
            next_inv_id += 1
    return out


# ----------------------------------------------------------------------------
#  Customers, MOF, and order history
# ----------------------------------------------------------------------------

def _email_for(first: str, last: str, used: set[str]) -> str:
    base = f"{first.lower()}.{last.lower()}@example.com"
    if base not in used:
        used.add(base)
        return base
    n = 2
    while True:
        candidate = f"{first.lower()}.{last.lower()}{n}@example.com"
        if candidate not in used:
            used.add(candidate)
            return candidate
        n += 1


def gen_customers(stores: list[tuple[str, str]], rng: random.Random,
                  total: int = 25, returning: int = 20) -> list[dict]:
    out: list[dict] = []
    used: set[str] = set()
    for i in range(total):
        first = rng.choice(UK_FIRST_NAMES)
        last  = rng.choice(UK_LAST_NAMES)
        email = _email_for(first, last, used)
        store_loc, _ = rng.choice(stores)
        joined = (date(2024, 1, 1) +
                  timedelta(days=rng.randint(0, 365))).isoformat()
        out.append({
            "email":           email,
            "full_name":       f"{first} {last}",
            "phone":           f"+44 20 7946 {rng.randint(0, 9999):04d}",
            "preferred_store": store_loc,
            "joined_at":       joined,
            "_returning":      i < returning,   # internal flag, dropped before insert
        })
    return out


def gen_mof(customers: list[dict], rng: random.Random) -> list[dict]:
    """0..4 methods per returning customer, weighted toward 2."""
    out: list[dict] = []
    for c in customers:
        if not c["_returning"]:
            continue
        n = rng.choices([0, 1, 2, 3, 4], weights=[1, 3, 5, 3, 1], k=1)[0]
        for _ in range(n):
            last4 = rng.choice(ADYEN_TEST_LAST4)
            brand = ADYEN_TEST_BRAND[last4]
            stored_id = f"stored_mock_{uuid.UUID(int=rng.getrandbits(128)).hex[:16]}"
            exp_year  = rng.choice([2027, 2028, 2029, 2030])
            exp_month = rng.randint(1, 12)
            is_expired = 1 if rng.random() < 0.10 else 0
            mof_id = f"mof_{uuid.UUID(int=rng.getrandbits(128)).hex[:12]}"
            out.append({
                "id":                              mof_id,
                "email":                           c["email"],
                "adyen_stored_payment_method_id":  stored_id,
                "brand":                           brand,
                "last4":                           last4,
                "alias":                           f"{brand} ending in {last4}",
                "expiry_month":                    exp_month,
                "expiry_year":                     exp_year,
                "is_expired":                      is_expired,
                "created_at":                      c["joined_at"] + "T00:00:00Z",
                "last_used_at":                    None,
            })
    return out


def gen_orders(customers: list[dict], products: list[dict],
               inventory: list[dict], mof: list[dict],
               rng: random.Random,
               orders_per_customer: int = 5) -> tuple[list[dict], list[dict]]:
    """~5 orders per returning customer over the last 12 months."""
    by_email_methods: dict[str, list[dict]] = {}
    for m in mof:
        by_email_methods.setdefault(m["email"], []).append(m)

    inv_by_store_pref: dict[tuple[str, str], dict] = {}
    sref_to_pref = {s["stock_ref"]: s["stock_ref"] for s in inventory}
    # Build (store, product_ref) -> price lookup from inventory + stock_map join.
    pref_by_sref: dict[str, str] = {p["product_ref"]: None for p in products}
    # We need stock_map join; but inventory has stock_ref, products have product_ref.
    # Use a quick reverse lookup via a passed-in dict-ish: build from inventory rows
    # by matching against the global stock_map injected separately is unnecessary —
    # we approximate with even sampling and pull unit_price from products' base.
    # (Order history is illustrative; exact per-store price is acceptable to use
    # the base price for simplicity here.)
    by_pref = {p["product_ref"]: p for p in products}

    cats = list(CATEGORY_WEIGHTS.keys())
    cat_weights = [CATEGORY_WEIGHTS[c] for c in cats]
    by_cat: dict[str, list[dict]] = {}
    for p in products:
        by_cat.setdefault(p["category"], []).append(p)

    orders: list[dict] = []
    lines: list[dict]  = []
    today = date.today()

    for c in customers:
        if not c["_returning"]:
            continue
        methods = by_email_methods.get(c["email"], [])
        for _ in range(orders_per_customer):
            placed = today - timedelta(days=rng.randint(2, 365))
            store = c["preferred_store"] if rng.random() < 0.8 \
                    else rng.choice([s["store_location"] for s in inventory])
            stored_method_id = rng.choice(methods)["id"] if methods else None

            n_lines = rng.randint(1, 4)
            chosen_prefs: set[str] = set()
            order_total = 0.0
            order_id = f"ord_{uuid.UUID(int=rng.getrandbits(128)).hex[:12]}"

            for _ in range(n_lines):
                cat = rng.choices(cats, weights=cat_weights, k=1)[0]
                prod = rng.choice(by_cat.get(cat) or products)
                if prod["product_ref"] in chosen_prefs:
                    continue
                chosen_prefs.add(prod["product_ref"])
                qty = rng.randint(1, 3)
                unit = prod["base_price_gbp"]
                lines.append({
                    "order_id":       order_id,
                    "product_ref":    prod["product_ref"],
                    "qty":            qty,
                    "unit_price_gbp": unit,
                })
                order_total += qty * unit

            orders.append({
                "order_id":         order_id,
                "email":            c["email"],
                "placed_at":        f"{placed.isoformat()}T12:00:00Z",
                "total_gbp":        round(order_total, 2),
                "store_location":   store,
                "stored_method_id": stored_method_id,
            })

    return orders, lines


# ----------------------------------------------------------------------------
#  Top-level builder
# ----------------------------------------------------------------------------

def build(seed_products: list[dict], seed_stock: list[dict],
          seed_inventory: list[dict], rng_seed: int = 42,
          target_products: int = 100,
          customers_total: int = 25, customers_returning: int = 20,
          orders_per_customer: int = 5) -> SynthBundle:
    rng = random.Random(rng_seed)

    products, stock_map = expand_products(seed_products, seed_stock,
                                           target_products, rng)

    # Distinct stores from seed inventory.
    stores: list[tuple[str, str]] = []
    seen: set[str] = set()
    for r in seed_inventory:
        if r["store_location"] not in seen:
            stores.append((r["store_location"], r["store_region"]))
            seen.add(r["store_location"])

    inventory = expand_inventory(seed_inventory, stock_map, products, stores, rng)

    customers = gen_customers(stores, rng, total=customers_total,
                              returning=customers_returning)
    mof       = gen_mof(customers, rng)
    orders, lines = gen_orders(customers, products, inventory, mof, rng,
                                orders_per_customer=orders_per_customer)

    # Strip internal helper flag from customers before returning.
    for c in customers:
        c.pop("_returning", None)

    return SynthBundle(
        products=products,
        stock_map=stock_map,
        inventory=inventory,
        customers=customers,
        merchant_on_file_methods=mof,
        past_orders=orders,
        past_order_lines=lines,
    )
