"""
=============================================================================
Warhammer Online: Return of Reckoning  -  REST API  (v2)
=============================================================================
Updated to match the actual WarDB table structure in Supabase.

Run locally:
    pip install fastapi uvicorn httpx python-dotenv
    uvicorn main:app --reload

Then visit http://localhost:8000/docs for the interactive explorer.

Deploy to Railway or Render (both have free tiers).
=============================================================================
"""

import os
import json
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
    version="2.0.0",
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

# ---------------------------------------------------------------------------
# SUPABASE QUERY HELPER
# ---------------------------------------------------------------------------

def sb(table: str, params: dict = None) -> list[dict]:
    """Query Supabase REST API and return rows."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    p = params or {}
    # Always request full representation
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

# ---------------------------------------------------------------------------
# RARITY / TYPE LOOKUPS
# ---------------------------------------------------------------------------

RARITY = {0:"Common", 1:"Uncommon", 2:"Rare", 3:"Very Rare", 4:"Artifact", 5:"Sovereign"}
REALM  = {0:"Neutral", 1:"Order", 2:"Destruction"}

def parse_stats(stats_str: str) -> dict:
    """Parse WAR stats format: '28:50;0:0;...' into {stat_id: value}"""
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
                    name = STAT_NAMES.get(sid, f"Stat_{sid}")
                    result[name] = val
            except ValueError:
                pass
    return result

# =============================================================================
# ITEMS  —  /item/{entry}
# =============================================================================

@app.get("/item/{entry}", tags=["Items"], summary="Item details + who drops it + who sells it + quest rewards")
def get_item(entry: int):
    item = sb_one("item_infos", {"entry": f"eq.{entry}"})
    item["rarity_name"] = RARITY.get(item.get("rarity", 0), "Common")
    item["stats_parsed"] = parse_stats(item.get("stats", ""))

    # NPCs that drop this item
    drops = sb("creature_loots", {"itemid": f"eq.{entry}", "select": "entry,pct"})
    drop_npcs = []
    for d in drops[:20]:  # cap at 20
        npc = sb("creature_protos", {"entry": f"eq.{d['entry']}", "select": "entry,name,minlevel,maxlevel,faction"})
        if npc:
            drop_npcs.append({**npc[0], "drop_chance": d.get("pct")})

    # Vendors that sell this item
    vendor_rows = sb("creature_vendors", {"itemid": f"eq.{entry}", "select": "entry,price"})
    vendors = []
    for v in vendor_rows[:20]:
        npc = sb("creature_protos", {"entry": f"eq.{v['entry']}", "select": "entry,name"})
        if npc:
            # Find where this NPC spawns
            spawn = sb("creature_spawns", {"entry": f"eq.{v['entry']}", "select": "zoneid,worldx,worldy", "limit": "1"})
            zone_name = None
            if spawn:
                zone = sb("zone_infos", {"zoneid": f"eq.{spawn[0]['zoneid']}", "select": "name"})
                zone_name = zone[0]["name"] if zone else None
            vendors.append({**npc[0], "price": v.get("price"), "zone": zone_name})

    # Quest rewards
    quest_rewards = []
    quests_data = sb("quests", {"select": "entry,name,level,xp,gold"})
    for q in quests_data:
        given  = q.get("given", "") or ""
        choice = q.get("choice", "") or ""
        if str(entry) in given or str(entry) in choice:
            quest_rewards.append(q)

    return {
        "item":         item,
        "dropped_by":   drop_npcs,
        "sold_by":      vendors,
        "quest_rewards": quest_rewards[:10],
    }


@app.get("/items", tags=["Items"], summary="Browse all items")
def list_items(
    page: int = 1,
    limit: int = Query(50, le=200),
    rarity: Optional[int] = None,
    type: Optional[int] = None,
    minrank: Optional[int] = None,
    search: Optional[str] = None,
):
    params = {
        "select": "entry,name,description,type,slotid,rarity,minrank,minrenown,career,dps,speed,armor",
        "limit":  str(limit),
        "offset": str((page - 1) * limit),
        "order":  "name.asc",
    }
    if rarity  is not None: params["rarity"]  = f"eq.{rarity}"
    if type    is not None: params["type"]    = f"eq.{type}"
    if minrank is not None: params["minrank"] = f"eq.{minrank}"
    if search:              params["name"]    = f"ilike.*{search}*"
    rows = sb("item_infos", params)
    for r in rows:
        r["rarity_name"] = RARITY.get(r.get("rarity", 0), "Common")
    return rows


# =============================================================================
# NPCs  —  /npc/{entry}
# =============================================================================

@app.get("/npc/{entry}", tags=["NPCs"], summary="NPC details + spawn locations + loot + vendor items")
def get_npc(entry: int):
    npc = sb_one("creature_protos", {"entry": f"eq.{entry}"})

    # Spawn locations
    spawns = sb("creature_spawns", {
        "entry":  f"eq.{entry}",
        "select": "zoneid,worldx,worldy,worldz",
        "limit":  "50",
    })
    # Enrich with zone names
    zone_cache = {}
    for s in spawns:
        zid = s.get("zoneid")
        if zid and zid not in zone_cache:
            z = sb("zone_infos", {"zoneid": f"eq.{zid}", "select": "name,tier"})
            zone_cache[zid] = z[0] if z else {"name": "Unknown"}
        s["zone"] = zone_cache.get(zid, {})

    # Loot table
    loot = sb("creature_loots", {"entry": f"eq.{entry}", "select": "itemid,pct"})
    loot_items = []
    for l in loot[:30]:
        item = sb("item_infos", {"entry": f"eq.{l['itemid']}", "select": "entry,name,rarity,type"})
        if item:
            loot_items.append({**item[0], "drop_chance": l.get("pct"), "rarity_name": RARITY.get(item[0].get("rarity",0),"Common")})

    # Vendor inventory
    vendor_items = sb("creature_vendors", {"entry": f"eq.{entry}", "select": "itemid,price"})
    sells = []
    for v in vendor_items[:50]:
        item = sb("item_infos", {"entry": f"eq.{v['itemid']}", "select": "entry,name,rarity,type,slotid"})
        if item:
            sells.append({**item[0], "price": v.get("price"), "rarity_name": RARITY.get(item[0].get("rarity",0),"Common")})

    # Quests started by this NPC
    started = sb("quests_creature_starter", {"creatureid": f"eq.{entry}", "select": "entry"})
    quest_ids = [q["entry"] for q in started]
    quests_started = []
    for qid in quest_ids[:10]:
        q = sb("quests", {"entry": f"eq.{qid}", "select": "entry,name,level,xp"})
        if q: quests_started.append(q[0])

    return {
        "npc":            npc,
        "spawns":         spawns,
        "loot":           loot_items,
        "vendor_items":   sells,
        "quests_started": quests_started,
    }


@app.get("/npcs", tags=["NPCs"], summary="Browse all NPCs")
def list_npcs(
    page: int = 1,
    limit: int = Query(50, le=200),
    search: Optional[str] = None,
    faction: Optional[int] = None,
    zone: Optional[int] = None,
):
    if zone:
        # Get NPC entries in this zone via spawns
        spawns = sb("creature_spawns", {"zoneid": f"eq.{zone}", "select": "entry", "limit": "1000"})
        entries = list({s["entry"] for s in spawns})
        if not entries:
            return {"page": page, "limit": limit, "count": 0, "data": []}
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
    if search:  params["name"]    = f"ilike.*{search}*"
    if faction is not None: params["faction"] = f"eq.{faction}"
    return sb("creature_protos", params)


# =============================================================================
# QUESTS  —  /quest/{entry}
# =============================================================================

@app.get("/quest/{entry}", tags=["Quests"], summary="Quest details + objectives + rewards + NPCs")
def get_quest(entry: int):
    quest = sb_one("quests", {"entry": f"eq.{entry}"})

    # Objectives
    objectives = sb("quests_objectives", {"entry": f"eq.{entry}", "select": "objtype,objcount,description,objid"})

    # Starter NPC
    starters = sb("quests_creature_starter", {"entry": f"eq.{entry}", "select": "creatureid"})
    start_npcs = []
    for s in starters:
        npc = sb("creature_protos", {"entry": f"eq.{s['creatureid']}", "select": "entry,name"})
        if npc:
            spawn = sb("creature_spawns", {"entry": f"eq.{s['creatureid']}", "select": "zoneid", "limit": "1"})
            zone_name = None
            if spawn:
                z = sb("zone_infos", {"zoneid": f"eq.{spawn[0]['zoneid']}", "select": "name"})
                zone_name = z[0]["name"] if z else None
            start_npcs.append({**npc[0], "zone": zone_name})

    # Finisher NPC
    finishers = sb("quests_creature_finisher", {"entry": f"eq.{entry}", "select": "creatureid"})
    finish_npcs = []
    for f in finishers:
        npc = sb("creature_protos", {"entry": f"eq.{f['creatureid']}", "select": "entry,name"})
        if npc: finish_npcs.append(npc[0])

    # Item rewards (parse from given/choice fields)
    reward_items = []
    for field in [quest.get("given",""), quest.get("choice","")]:
        if not field: continue
        for token in str(field).split(","):
            token = token.strip()
            if token.isdigit():
                item = sb("item_infos", {"entry": f"eq.{token}", "select": "entry,name,rarity,type"})
                if item:
                    reward_items.append({**item[0], "rarity_name": RARITY.get(item[0].get("rarity",0),"Common")})

    return {
        "quest":        quest,
        "objectives":   objectives,
        "start_npcs":   start_npcs,
        "finish_npcs":  finish_npcs,
        "rewards":      reward_items,
    }


@app.get("/quests", tags=["Quests"], summary="Browse all quests")
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
    return sb("quests", params)



# =============================================================================
# VENDORS  —  /vendor/{entry}
# =============================================================================

@app.get("/vendor/{entry}", tags=["Vendors"], summary="Vendor NPC + full item list with prices")
def get_vendor(entry: int):
    npc = sb_one("creature_protos", {"entry": f"eq.{entry}"})

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
            item_list.append({
                **item[0],
                "price": v.get("price"),
                "rarity_name": RARITY.get(item[0].get("rarity", 0), "Common"),
            })

    return {"vendor": npc, "locations": spawns, "items": item_list}


@app.get("/vendors", tags=["Vendors"], summary="Browse all vendor NPCs")
def list_vendors(
    page: int = 1,
    limit: int = Query(50, le=200),
    search: Optional[str] = None,
    zone: Optional[int] = None,
):
    # Get NPC entries that have vendor inventory
    vendor_entries = sb("creature_vendors", {"select": "entry", "limit": "10000"})
    unique_entries = list({v["entry"] for v in vendor_entries})

    if zone:
        spawns = sb("creature_spawns", {"zoneid": f"eq.{zone}", "select": "entry", "limit": "1000"})
        zone_entries = {s["entry"] for s in spawns}
        unique_entries = [e for e in unique_entries if e in zone_entries]

    if not unique_entries:
        return {"page": page, "limit": limit, "count": 0, "data": []}

    offset = (page - 1) * limit
    batch  = unique_entries[offset: offset + limit]
    params = {
        "select": "entry,name,minlevel,maxlevel,faction",
        "entry":  f"in.({','.join(str(e) for e in batch)})",
    }
    if search: params["name"] = f"ilike.*{search}*"
    return sb("creature_protos", params)



# =============================================================================
# ZONES  —  /zone/{zoneid}
# =============================================================================

@app.get("/zone/{zoneid}", tags=["Zones"], summary="Zone details + NPCs + quests + public quests")
def get_zone(zoneid: int):
    zone = sb_one("zone_infos", {"zoneid": f"eq.{zoneid}"})

    # NPCs in zone (via spawns)
    spawns = sb("creature_spawns", {"zoneid": f"eq.{zoneid}", "select": "entry,worldx,worldy", "limit": "500"})
    unique_entries = list({s["entry"] for s in spawns})
    npcs = []
    if unique_entries:
        npc_rows = sb("creature_protos", {
            "entry":  f"in.({','.join(str(e) for e in unique_entries[:100])})",
            "select": "entry,name,minlevel,maxlevel,faction,creaturetype",
        })
        npcs = npc_rows

    # Public quests
    pqs = sb("pquest_info", {"zoneid": f"eq.{zoneid}", "select": "entry,name,level,pinx,piny"})

    # Chapters
    chapters = sb("chapter_infos", {"zoneid": f"eq.{zoneid}", "select": "entry,name,chapterrank,pinx,piny"})

    return {
        "zone":     zone,
        "npcs":     npcs,
        "npc_spawn_count": len(spawns),
        "public_quests": pqs,
        "chapters": chapters,
    }


@app.get("/zones", tags=["Zones"], summary="All zones")
def list_zones(
    tier: Optional[int] = None,
    search: Optional[str] = None,
):
    params = {"select": "zoneid,name,minlevel,maxlevel,type,tier,region", "order": "tier.asc,name.asc"}
    if tier:   params["tier"] = f"eq.{tier}"
    if search: params["name"] = f"ilike.*{search}*"
    return sb("zone_infos", params)



# =============================================================================
# PUBLIC QUESTS  —  /pq/{entry}
# =============================================================================

@app.get("/pq/{entry}", tags=["Public Quests"], summary="Public quest details + stages + spawn locations")
def get_pq(entry: int):
    pq = sb_one("pquest_info", {"entry": f"eq.{entry}"})

    objectives = sb("pquest_objectives", {"entry": f"eq.{entry}", "select": "stage,stagename,description,type,count"})
    spawns     = sb("pquest_spawns",     {"entry": f"eq.{entry}", "select": "zoneid,worldx,worldy,worldz,objective,type"})

    zone = None
    if pq.get("zoneid"):
        z = sb("zone_infos", {"zoneid": f"eq.{pq['zoneid']}", "select": "name,tier"})
        zone = z[0] if z else None

    return {"pq": pq, "zone": zone, "objectives": objectives, "spawns": spawns}


@app.get("/pqs", tags=["Public Quests"], summary="Browse public quests")
def list_pqs(zone: Optional[int] = None, search: Optional[str] = None):
    params = {"select": "entry,name,level,zoneid,pinx,piny", "order": "zoneid.asc,name.asc"}
    if zone:   params["zoneid"] = f"eq.{zone}"
    if search: params["name"]   = f"ilike.*{search}*"
    return sb("zone_infos", params)



# =============================================================================
# SEARCH  —  /search?q=...
# =============================================================================

@app.get("/search", tags=["Search"], summary="Search across items, NPCs, quests, zones and public quests")
def search(
    q: str = Query(..., min_length=2),
    limit: int = Query(10, le=50),
):
    like = f"ilike.*{q}*"
    results = {
        "items":  sb("item_infos",    {"name": like, "select": "entry,name,rarity,type,minrank", "limit": str(limit)}),
        "npcs":   sb("creature_protos",{"name": like, "select": "entry,name,minlevel,maxlevel,faction", "limit": str(limit)}),
        "quests": sb("quests",         {"name": like, "select": "entry,name,level,xp", "limit": str(limit)}),
        "zones":  sb("zone_infos",     {"name": like, "select": "zoneid,name,tier", "limit": str(limit)}),
        "pqs":    sb("pquest_info",    {"name": like, "select": "entry,name,zoneid", "limit": str(limit)}),
    }
    for item in results["items"]:
        item["rarity_name"] = RARITY.get(item.get("rarity", 0), "Common")
    total = sum(len(v) for v in results.values())
    return {"query": q, "total": total, "results": results}


# =============================================================================
# ABILITIES  —  /ability/{entry}
# =============================================================================

@app.get("/ability/{entry}", tags=["Abilities"], summary="Ability details + stats by level")
def get_ability(entry: int):
    ability = sb_one("ability_infos", {"entry": f"eq.{entry}"})
    stats   = sb("ability_stats", {"entry": f"eq.{entry}", "select": "level,description,damages,heals,percents", "order": "level.asc"})
    return {"ability": ability, "stats": stats}


@app.get("/abilities", tags=["Abilities"], summary="Browse abilities by career")
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
    return {"page": page, "limit": limit, "data": sb("ability_infos", params)}


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/", tags=["Health"])
def root():
    return {
        "status": "ok",
        "api": "WAR: Return of Reckoning Database API v2",
        "endpoints": ["/items", "/npcs", "/quests", "/vendors", "/zones", "/pqs", "/abilities", "/search"],
    }
