"""
=============================================================================
Warhammer Online: Return of Reckoning  -  REST API  (v3)
=============================================================================
All 'name' fields renamed to avoid Bubble.io reserved word conflicts:
  items      -> display_name
  npcs       -> display_name
  quests     -> display_name
  zones      -> display_name
  pqs        -> display_name
  abilities  -> display_name

Using a single consistent field name 'display_name' across all endpoints
makes Bubble configuration simpler and avoids all naming conflicts.
=============================================================================
"""

import os
import httpx
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]

app = FastAPI(
    title="Warhammer Online: Return of Reckoning - Database API",
    version="3.0.0",
    description="Items, NPCs, quests, vendors, zones and more for WAR: RoR.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

RARITY = {0:"Common", 1:"Uncommon", 2:"Rare", 3:"Very Rare", 4:"Artifact", 5:"Sovereign"}
REALM  = {0:"Neutral", 1:"Order", 2:"Destruction"}

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def sb(table: str, params: dict = None) -> list[dict]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    p = params or {}
    p.setdefault("limit", "1000")
    try:
        r = httpx.get(url, headers=HEADERS, params=p, timeout=15)
        if r.status_code == 200:
            return r.json()
        raise HTTPException(status_code=r.status_code, detail=r.text[:200])
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=str(e))

def sb_one(table: str, params: dict) -> dict:
    rows = sb(table, params)
    if not rows:
        raise HTTPException(status_code=404, detail=f"Not found in {table}")
    return rows[0]

def rename_name(rows: list[dict]) -> list[dict]:
    """Rename 'name' to 'display_name' to avoid Bubble reserved word conflict."""
    for r in rows:
        if "name" in r:
            r["display_name"] = r.pop("name")
    return rows

def parse_stats(stats_str: str) -> dict:
    STAT_NAMES = {
        1:"Strength", 2:"Toughness", 3:"Initiative", 4:"Quickness",
        5:"Ballistic Skill", 6:"Weapon Skill", 7:"Intelligence",
        8:"Willpower", 9:"Fellowship", 10:"Wounds", 27:"Armor",
        28:"Armor", 24:"Elemental Resist", 25:"Spirit Resist",
        26:"Corporeal Resist",
    }
    if not stats_str:
        return {}
    result = {}
    for pair in stats_str.split(";"):
        parts = pair.split(":")
        if len(parts) == 2:
            try:
                sid, val = int(parts[0]), int(parts[1])
                if sid > 0 and val != 0:
                    result[STAT_NAMES.get(sid, f"Stat_{sid}")] = val
            except ValueError:
                pass
    return result

# =============================================================================
# ITEMS
# =============================================================================

@app.get("/item/{entry}", tags=["Items"])
def get_item(entry: int):
    item = sb_one("item_infos", {"entry": f"eq.{entry}"})
    item["display_name"]  = item.pop("name", "")
    item["rarity_name"]   = RARITY.get(item.get("rarity", 0), "Common")
    item["stats_parsed"]  = parse_stats(item.get("stats", ""))

    drops = sb("creature_loots", {"itemid": f"eq.{entry}", "select": "entry,pct"})
    drop_npcs = []
    for d in drops[:20]:
        npc = sb("creature_protos", {"entry": f"eq.{d['entry']}", "select": "entry,name,minlevel,maxlevel"})
        if npc:
            row = npc[0]
            row["display_name"] = row.pop("name", "")
            drop_npcs.append({**row, "drop_chance": d.get("pct")})

    vendor_rows = sb("creature_vendors", {"itemid": f"eq.{entry}", "select": "entry,price"})
    vendors = []
    for v in vendor_rows[:20]:
        npc = sb("creature_protos", {"entry": f"eq.{v['entry']}", "select": "entry,name"})
        if npc:
            row = npc[0]
            row["display_name"] = row.pop("name", "")
            spawn = sb("creature_spawns", {"entry": f"eq.{v['entry']}", "select": "zoneid", "limit": "1"})
            zone_name = None
            if spawn:
                zone = sb("zone_infos", {"zoneid": f"eq.{spawn[0]['zoneid']}", "select": "name"})
                zone_name = zone[0]["name"] if zone else None
            vendors.append({**row, "price": v.get("price"), "zone": zone_name})

    quest_rewards = []
    quests_data = sb("quests", {"select": "entry,name,level,xp,gold"})
    for q in quests_data:
        given  = q.get("given", "") or ""
        choice = q.get("choice", "") or ""
        if str(entry) in given or str(entry) in choice:
            q["display_name"] = q.pop("name", "")
            quest_rewards.append(q)

    return {
        "item":          item,
        "dropped_by":    drop_npcs,
        "sold_by":       vendors,
        "quest_rewards": quest_rewards[:10],
    }


ITEM_TYPES = {
    0:"Heavy Armor", 1:"Medium Armor", 2:"One-Hand Weapon", 3:"Two-Hand Weapon",
    4:"Shield", 5:"Offhand", 6:"Light Armor", 7:"Ranged Weapon",
    8:"Accessory", 9:"Ranged Weapon", 10:"Accessory", 11:"Staff",
    12:"Throwing", 13:"Melee Weapon", 14:"Melee Weapon", 15:"Bag",
    16:"Trophy", 17:"Quest Item", 18:"Light Armor", 19:"Currency",
    20:"Heavy Armor", 21:"Dye", 22:"Medium Armor", 23:"Gathering",
    24:"Enhancement", 25:"Container", 26:"Heavy Armor", 27:"Heavy Armor",
    28:"Accessory", 29:"Accessory", 30:"Accessory", 31:"Trophy",
    32:"Crafting Material", 33:"Crafting Material", 34:"Crafting Material",
    35:"Talisman", 36:"Vessel",
}
ITEM_SLOTS = {
    0:"None", 1:"Main Hand", 2:"Off Hand", 3:"Ranged",
    4:"Helm", 5:"Shoulder", 6:"Body", 7:"Hands",
    8:"Waist", 9:"Feet", 10:"Main Hand", 11:"Off Hand",
    12:"Ranged", 13:"Melee", 14:"Melee", 15:"Head",
    16:"Shoulder", 17:"Hands", 18:"Waist", 19:"Feet",
    20:"Body", 21:"Gloves", 22:"Legs", 23:"Wrist",
    24:"Neck", 25:"Ring", 26:"Ring", 27:"Earring",
    28:"Earring", 29:"Pocket", 30:"Pocket", 31:"Trophy",
    32:"Pocket", 33:"Pocket", 42:"Bag",
}


@app.get("/item_detail", tags=["Items"], summary="Single item detail by entry - returns one object not a list")
def get_item_detail(entry: int):
    rows = sb("item_infos", {
        "entry":  f"eq.{entry}",
        "select": "entry,name,description,type,slotid,rarity,minrank,minrenown,career,dps,speed,armor,stats",
    })
    rows = [r for r in rows if r.get("name")]
    if not rows:
        raise HTTPException(status_code=404, detail="Item not found")
    r = rows[0]
    r["display_name"]  = r.pop("name", "")
    r["rarity_name"]   = RARITY.get(r.get("rarity", 0), "Common")
    r["type_name"]     = ITEM_TYPES.get(r.get("type", 0), f"Type {r.get('type',0)}")
    r["slot_name"]     = ITEM_SLOTS.get(r.get("slotid", 0), f"Slot {r.get('slotid',0)}")
    r["stats_parsed"]  = parse_stats(r.get("stats", ""))

    # NPCs that drop this item
    drops = sb("creature_loots", {"itemid": f"eq.{entry}", "select": "entry,pct"})
    drop_npcs = []
    for d in drops[:20]:
        npc = sb("creature_protos", {"entry": f"eq.{d['entry']}", "select": "entry,name,minlevel,maxlevel"})
        if npc:
            row = npc[0]
            row["display_name"] = row.pop("name", "")
            drop_npcs.append({**row, "drop_chance": d.get("pct")})

    # Vendors that sell this item
    vendor_rows = sb("creature_vendors", {"itemid": f"eq.{entry}", "select": "entry,price"})
    vendors = []
    for v in vendor_rows[:20]:
        npc = sb("creature_protos", {"entry": f"eq.{v['entry']}", "select": "entry,name"})
        if npc:
            row = npc[0]
            row["display_name"] = row.pop("name", "")
            vendors.append({**row, "price": v.get("price")})

    r["dropped_by"]    = drop_npcs
    r["sold_by"]       = vendors
    return r


@app.get("/items", tags=["Items"])
def list_items(
    page: int = 1,
    limit: int = Query(50, le=200),
    rarity: Optional[int] = None,
    type: Optional[int] = None,
    minrank: Optional[int] = None,
    search: Optional[str] = None,
    entry: Optional[int] = None,
):
    params = {
        "select": "entry,name,description,type,slotid,rarity,minrank,minrenown,career,dps,speed,armor",
        "limit":  str(limit),
        "offset": str((page - 1) * limit),
        "order":  "name.asc",
        "name":   "neq.",
    }
    if rarity  is not None: params["rarity"]  = f"eq.{rarity}"
    if type    is not None: params["type"]    = f"eq.{type}"
    if minrank is not None: params["minrank"] = f"eq.{minrank}"
    if search:              params["name"]    = f"ilike.*{search}*"
    if entry   is not None: params["entry"]   = f"eq.{entry}"
    rows = sb("item_infos", params)
    # Also filter out any remaining empty names in Python
    rows = [r for r in rows if r.get("name")]
    for r in rows:
        r["display_name"] = r.pop("name", "")
        r["rarity_name"]  = RARITY.get(r.get("rarity", 0), "Common")
        r["type_name"]    = ITEM_TYPES.get(r.get("type", 0), f"Type {r.get('type',0)}")
        r["slot_name"]    = ITEM_SLOTS.get(r.get("slotid", 0), f"Slot {r.get('slotid',0)}")
    return rows


# =============================================================================
# NPCs
# =============================================================================

@app.get("/npc/{entry}", tags=["NPCs"])
def get_npc(entry: int):
    npc = sb_one("creature_protos", {"entry": f"eq.{entry}"})
    npc["display_name"] = npc.pop("name", "")

    spawns = sb("creature_spawns", {
        "entry":  f"eq.{entry}",
        "select": "zoneid,worldx,worldy,worldz",
        "limit":  "50",
    })
    zone_cache = {}
    for s in spawns:
        zid = s.get("zoneid")
        if zid and zid not in zone_cache:
            z = sb("zone_infos", {"zoneid": f"eq.{zid}", "select": "name,tier"})
            zone_cache[zid] = z[0] if z else {"name": "Unknown"}
        s["zone"] = zone_cache.get(zid, {})

    loot = sb("creature_loots", {"entry": f"eq.{entry}", "select": "itemid,pct"})
    loot_items = []
    for l in loot[:30]:
        item = sb("item_infos", {"entry": f"eq.{l['itemid']}", "select": "entry,name,rarity,type"})
        if item:
            row = item[0]
            row["display_name"] = row.pop("name", "")
            row["rarity_name"]  = RARITY.get(row.get("rarity", 0), "Common")
            loot_items.append({**row, "drop_chance": l.get("pct")})

    vendor_items = sb("creature_vendors", {"entry": f"eq.{entry}", "select": "itemid,price"})
    sells = []
    for v in vendor_items[:50]:
        item = sb("item_infos", {"entry": f"eq.{v['itemid']}", "select": "entry,name,rarity,type,slotid"})
        if item:
            row = item[0]
            row["display_name"] = row.pop("name", "")
            row["rarity_name"]  = RARITY.get(row.get("rarity", 0), "Common")
            sells.append({**row, "price": v.get("price")})

    started = sb("quests_creature_starter", {"creatureid": f"eq.{entry}", "select": "entry"})
    quests_started = []
    for qid in [q["entry"] for q in started][:10]:
        q = sb("quests", {"entry": f"eq.{qid}", "select": "entry,name,level,xp"})
        if q:
            row = q[0]
            row["display_name"] = row.pop("name", "")
            quests_started.append(row)

    return {
        "npc":            npc,
        "spawns":         spawns,
        "loot":           loot_items,
        "vendor_items":   sells,
        "quests_started": quests_started,
    }


@app.get("/npcs", tags=["NPCs"])
def list_npcs(
    page: int = 1,
    limit: int = Query(50, le=200),
    search: Optional[str] = None,
    faction: Optional[int] = None,
    zone: Optional[int] = None,
):
    if zone:
        spawns = sb("creature_spawns", {"zoneid": f"eq.{zone}", "select": "entry", "limit": "1000"})
        entries = list({s["entry"] for s in spawns})
        if not entries:
            return []
        params = {
            "select": "entry,name,minlevel,maxlevel,faction,creaturetype",
            "entry":  f"in.({','.join(str(e) for e in entries[:500])})",
            "limit":  str(limit),
        }
    else:
        params = {
            "select": "entry,name,minlevel,maxlevel,faction,creaturetype",
            "limit":  str(limit),
            "offset": str((page - 1) * limit),
            "order":  "name.asc",
        }
    if search:              params["name"]    = f"ilike.*{search}*"
    if faction is not None: params["faction"] = f"eq.{faction}"
    rows = sb("creature_protos", params)
    for r in rows:
        r["display_name"] = r.pop("name", "")
    return rows


# =============================================================================
# QUESTS
# =============================================================================

@app.get("/quest/{entry}", tags=["Quests"])
def get_quest(entry: int):
    quest = sb_one("quests", {"entry": f"eq.{entry}"})
    quest["display_name"] = quest.pop("name", "")

    objectives = sb("quests_objectives", {"entry": f"eq.{entry}", "select": "objtype,objcount,description,objid"})

    starters = sb("quests_creature_starter", {"entry": f"eq.{entry}", "select": "creatureid"})
    start_npcs = []
    for s in starters:
        npc = sb("creature_protos", {"entry": f"eq.{s['creatureid']}", "select": "entry,name"})
        if npc:
            row = npc[0]
            row["display_name"] = row.pop("name", "")
            spawn = sb("creature_spawns", {"entry": f"eq.{s['creatureid']}", "select": "zoneid", "limit": "1"})
            zone_name = None
            if spawn:
                z = sb("zone_infos", {"zoneid": f"eq.{spawn[0]['zoneid']}", "select": "name"})
                zone_name = z[0]["name"] if z else None
            start_npcs.append({**row, "zone": zone_name})

    finishers = sb("quests_creature_finisher", {"entry": f"eq.{entry}", "select": "creatureid"})
    finish_npcs = []
    for f in finishers:
        npc = sb("creature_protos", {"entry": f"eq.{f['creatureid']}", "select": "entry,name"})
        if npc:
            row = npc[0]
            row["display_name"] = row.pop("name", "")
            finish_npcs.append(row)

    reward_items = []
    for field in [quest.get("given", ""), quest.get("choice", "")]:
        if not field: continue
        for token in str(field).split(","):
            token = token.strip()
            if token.isdigit():
                item = sb("item_infos", {"entry": f"eq.{token}", "select": "entry,name,rarity,type"})
                if item:
                    row = item[0]
                    row["display_name"] = row.pop("name", "")
                    row["rarity_name"]  = RARITY.get(row.get("rarity", 0), "Common")
                    reward_items.append(row)

    return {
        "quest":       quest,
        "objectives":  objectives,
        "start_npcs":  start_npcs,
        "finish_npcs": finish_npcs,
        "rewards":     reward_items,
    }


@app.get("/quests", tags=["Quests"])
def list_quests(
    page: int = 1,
    limit: int = Query(50, le=200),
    search: Optional[str] = None,
    level: Optional[int] = None,
    type: Optional[int] = None,
):
    params = {
        "select": "entry,name,type,level,xp,gold",
        "limit":  str(limit),
        "offset": str((page - 1) * limit),
        "order":  "level.asc,name.asc",
    }
    if search: params["name"]  = f"ilike.*{search}*"
    if level:  params["level"] = f"eq.{level}"
    if type:   params["type"]  = f"eq.{type}"
    rows = sb("quests", params)
    for r in rows:
        r["display_name"] = r.pop("name", "")
    return rows


# =============================================================================
# VENDORS
# =============================================================================

@app.get("/vendor/{entry}", tags=["Vendors"])
def get_vendor(entry: int):
    npc = sb_one("creature_protos", {"entry": f"eq.{entry}"})
    npc["display_name"] = npc.pop("name", "")

    spawns = sb("creature_spawns", {"entry": f"eq.{entry}", "select": "zoneid,worldx,worldy", "limit": "5"})
    zone_cache = {}
    for s in spawns:
        zid = s.get("zoneid")
        if zid and zid not in zone_cache:
            z = sb("zone_infos", {"zoneid": f"eq.{zid}", "select": "name"})
            zone_cache[zid] = z[0]["name"] if z else "Unknown"
        s["zone_name"] = zone_cache.get(zid)

    items = sb("creature_vendors", {"entry": f"eq.{entry}", "select": "itemid,price", "limit": "500"})
    item_list = []
    for v in items:
        item = sb("item_infos", {"entry": f"eq.{v['itemid']}", "select": "entry,name,rarity,type,slotid,minrank"})
        if item:
            row = item[0]
            row["display_name"] = row.pop("name", "")
            row["rarity_name"]  = RARITY.get(row.get("rarity", 0), "Common")
            item_list.append({**row, "price": v.get("price")})

    return {"vendor": npc, "locations": spawns, "items": item_list}


@app.get("/vendors", tags=["Vendors"])
def list_vendors(
    page: int = 1,
    limit: int = Query(50, le=200),
    search: Optional[str] = None,
    zone: Optional[int] = None,
):
    vendor_entries = sb("creature_vendors", {"select": "entry", "limit": "10000"})
    unique_entries = list({v["entry"] for v in vendor_entries})

    if zone:
        spawns = sb("creature_spawns", {"zoneid": f"eq.{zone}", "select": "entry", "limit": "1000"})
        zone_entries = {s["entry"] for s in spawns}
        unique_entries = [e for e in unique_entries if e in zone_entries]

    if not unique_entries:
        return []

    offset = (page - 1) * limit
    batch  = unique_entries[offset: offset + limit]
    params = {
        "select": "entry,name,minlevel,maxlevel,faction",
        "entry":  f"in.({','.join(str(e) for e in batch)})",
    }
    if search: params["name"] = f"ilike.*{search}*"
    rows = sb("creature_protos", params)
    for r in rows:
        r["display_name"] = r.pop("name", "")
    return rows


# =============================================================================
# ZONES
# =============================================================================

@app.get("/zone/{zoneid}", tags=["Zones"])
def get_zone(zoneid: int):
    zone = sb_one("zone_infos", {"zoneid": f"eq.{zoneid}"})
    zone["display_name"] = zone.pop("name", "")

    spawns = sb("creature_spawns", {"zoneid": f"eq.{zoneid}", "select": "entry,worldx,worldy", "limit": "500"})
    unique_entries = list({s["entry"] for s in spawns})
    npcs = []
    if unique_entries:
        npc_rows = sb("creature_protos", {
            "entry":  f"in.({','.join(str(e) for e in unique_entries[:100])})",
            "select": "entry,name,minlevel,maxlevel,faction,creaturetype",
        })
        for r in npc_rows:
            r["display_name"] = r.pop("name", "")
        npcs = npc_rows

    pqs = sb("pquest_info", {"zoneid": f"eq.{zoneid}", "select": "entry,name,level,pinx,piny"})
    for r in pqs:
        r["display_name"] = r.pop("name", "")

    chapters = sb("chapter_infos", {"zoneid": f"eq.{zoneid}", "select": "entry,name,chapterrank,pinx,piny"})
    for r in chapters:
        r["display_name"] = r.pop("name", "")

    return {
        "zone":            zone,
        "npcs":            npcs,
        "npc_spawn_count": len(spawns),
        "public_quests":   pqs,
        "chapters":        chapters,
    }


@app.get("/zones", tags=["Zones"])
def list_zones(
    tier: Optional[int] = None,
    search: Optional[str] = None,
):
    params = {"select": "zoneid,name,minlevel,maxlevel,type,tier,region", "order": "tier.asc,name.asc"}
    if tier:   params["tier"] = f"eq.{tier}"
    if search: params["name"] = f"ilike.*{search}*"
    rows = sb("zone_infos", params)
    for r in rows:
        r["display_name"] = r.pop("name", "")
    return rows


# =============================================================================
# PUBLIC QUESTS
# =============================================================================

@app.get("/pq/{entry}", tags=["Public Quests"])
def get_pq(entry: int):
    pq = sb_one("pquest_info", {"entry": f"eq.{entry}"})
    pq["display_name"] = pq.pop("name", "")

    objectives = sb("pquest_objectives", {"entry": f"eq.{entry}", "select": "stage,stagename,description,type,count"})
    spawns     = sb("pquest_spawns",     {"entry": f"eq.{entry}", "select": "zoneid,worldx,worldy,worldz,objective,type"})

    zone = None
    if pq.get("zoneid"):
        z = sb("zone_infos", {"zoneid": f"eq.{pq['zoneid']}", "select": "name,tier"})
        zone = z[0] if z else None

    return {"pq": pq, "zone": zone, "objectives": objectives, "spawns": spawns}


@app.get("/pqs", tags=["Public Quests"])
def list_pqs(zone: Optional[int] = None, search: Optional[str] = None):
    params = {"select": "entry,name,level,zoneid,pinx,piny", "order": "zoneid.asc,name.asc"}
    if zone:   params["zoneid"] = f"eq.{zone}"
    if search: params["name"]   = f"ilike.*{search}*"
    rows = sb("pquest_info", params)
    for r in rows:
        r["display_name"] = r.pop("name", "")
    return rows


# =============================================================================
# SEARCH
# =============================================================================

@app.get("/search", tags=["Search"])
def search(
    q: str = Query(..., min_length=2),
    limit: int = Query(10, le=50),
):
    like = f"ilike.*{q}*"
    items  = sb("item_infos",     {"name": like, "select": "entry,name,rarity,type,minrank", "limit": str(limit)})
    npcs   = sb("creature_protos",{"name": like, "select": "entry,name,minlevel,maxlevel",   "limit": str(limit)})
    quests = sb("quests",          {"name": like, "select": "entry,name,level,xp",            "limit": str(limit)})
    zones  = sb("zone_infos",      {"name": like, "select": "zoneid,name,tier",               "limit": str(limit)})
    pqs    = sb("pquest_info",     {"name": like, "select": "entry,name,zoneid",              "limit": str(limit)})

    for r in items:
        r["display_name"] = r.pop("name", "")
        r["rarity_name"]  = RARITY.get(r.get("rarity", 0), "Common")
    for r in npcs:   r["display_name"] = r.pop("name", "")
    for r in quests: r["display_name"] = r.pop("name", "")
    for r in zones:  r["display_name"] = r.pop("name", "")
    for r in pqs:    r["display_name"] = r.pop("name", "")

    return {
        "query":   q,
        "total":   len(items) + len(npcs) + len(quests) + len(zones) + len(pqs),
        "results": {"items": items, "npcs": npcs, "quests": quests, "zones": zones, "pqs": pqs},
    }


# =============================================================================
# ABILITIES
# =============================================================================

@app.get("/ability/{entry}", tags=["Abilities"])
def get_ability(entry: int):
    ability = sb_one("ability_infos", {"entry": f"eq.{entry}"})
    ability["display_name"] = ability.pop("name", "")
    stats = sb("ability_stats", {"entry": f"eq.{entry}", "select": "level,description,damages,heals,percents", "order": "level.asc"})
    return {"ability": ability, "stats": stats}


@app.get("/abilities", tags=["Abilities"])
def list_abilities(
    careerline: Optional[int] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = Query(50, le=200),
):
    params = {
        "select": "entry,name,careerline,minimumrank,minimumrenown,casttime,cooldown",
        "limit":  str(limit),
        "offset": str((page - 1) * limit),
        "order":  "careerline.asc,minimumrank.asc",
    }
    if careerline is not None: params["careerline"] = f"eq.{careerline}"
    if search: params["name"] = f"ilike.*{search}*"
    rows = sb("ability_infos", params)
    for r in rows:
        r["display_name"] = r.pop("name", "")
    return rows


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/", tags=["Health"])
def root():
    return {
        "status": "ok",
        "api":    "WAR: Return of Reckoning Database API v3",
        "note":   "All 'name' fields are returned as 'display_name'",
    }
