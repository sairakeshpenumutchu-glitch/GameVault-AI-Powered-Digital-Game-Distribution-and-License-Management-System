"""
GameVault Backend API Service
- Games + DLCs direct entitlement
- Atomic primary checkout
- Peer-to-Peer (P2P) secondary resale marketplace with 3-way split (Buyer, Seller, Publisher)
- Distributed DRM multi-device single-seat conflict detector
- Live database inspection
"""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import os
from datetime import datetime, timedelta
import secrets

try:
    from database import get_connection, DB_PATH, init_db, reset_and_seed
except ImportError:
    from backend.database import get_connection, DB_PATH, init_db, reset_and_seed

app = FastAPI(title="GameVault Core Engine", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users LIMIT 1;")
        conn.close()
    except Exception:
        print("[GameVault] Database tables not found. Seeding initial database...")
        reset_and_seed()
        print("[GameVault] Database seeded successfully.")

# ----------------- Models -----------------
class CheckoutRequest(BaseModel):
    user_id: int = 1
    game_id: int
    include_base_game: bool = True
    selected_dlc_ids: List[int] = []

class RefundRequest(BaseModel):
    user_id: int = 1
    library_id: int

class PlaySessionRequest(BaseModel):
    user_id: int = 1
    game_id: int
    device_name: str = "Desktop-PC-Rig"
    force_takeover: bool = False

class WalletTopupRequest(BaseModel):
    user_id: int = 1
    amount: float

class P2PListRequest(BaseModel):
    seller_id: int
    library_id: int
    asking_price: float

class P2PBuyRequest(BaseModel):
    buyer_id: int
    listing_id: int

class PriceEvaluationRequest(BaseModel):
    game_id: int
    asking_price: float
    library_id: Optional[int] = None

class RawQueryRequest(BaseModel):
    query: str

# ----------------- User Accounts & Profile -----------------

@app.get("/api/users")
def get_all_users():
    """Returns all user accounts for quick testing and account switching."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, email, wallet_balance, avatar_url FROM users ORDER BY user_id ASC;")
    users = [dict(r) for r in cur.fetchall()]
    conn.close()
    return users

@app.get("/api/user")
def get_user_profile(user_id: int = 1):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, email, wallet_balance, avatar_url FROM users WHERE user_id = ?;", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row)

@app.post("/api/user/topup")
def topup_wallet(req: WalletTopupRequest):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id = ?;", (req.amount, req.user_id))
    cur.execute("SELECT wallet_balance FROM users WHERE user_id = ?;", (req.user_id,))
    new_bal = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "new_balance": new_bal}

# ----------------- Catalog & Game Details -----------------

@app.get("/api/games")
def get_games():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT g.game_id, g.title, g.slug, g.tagline, g.genre, g.developer, 
               g.release_date, g.metascore, g.header_image, g.cover_image, g.base_price,
               p.name as publisher_name,
               (SELECT COUNT(*) FROM license_keys lk WHERE lk.game_id = g.game_id AND lk.status = 'AVAILABLE') as available_keys_count,
               (SELECT COUNT(*) FROM game_dlcs d WHERE d.game_id = g.game_id) as dlcs_count
        FROM games g
        JOIN publishers p ON g.publisher_id = p.publisher_id
        ORDER BY g.metascore DESC;
    """)
    games = [dict(row) for row in cur.fetchall()]
    conn.close()
    return games

@app.get("/api/games/{game_id}")
def get_game_details(game_id: int, user_id: int = 1):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT g.*, p.name as publisher_name, p.royalty_percentage,
               (SELECT COUNT(*) FROM license_keys lk WHERE lk.game_id = g.game_id AND lk.status = 'AVAILABLE') as in_stock_keys
        FROM games g
        JOIN publishers p ON g.publisher_id = p.publisher_id
        WHERE g.game_id = ?;
    """, (game_id,))
    game_row = cur.fetchone()
    if not game_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")

    game = dict(game_row)

    cur.execute("""
        SELECT library_id, status FROM user_library 
        WHERE user_id = ? AND game_id = ? AND status = 'ACTIVE';
    """, (user_id, game_id))
    ownership = cur.fetchone()
    game["is_owned"] = bool(ownership)

    cur.execute("""
        SELECT d.dlc_id, d.title, d.dlc_type, d.price, d.description,
               CASE WHEN udl.entitlement_id IS NOT NULL THEN 1 ELSE 0 END as is_owned
        FROM game_dlcs d
        LEFT JOIN user_dlc_library udl ON udl.dlc_id = d.dlc_id AND udl.user_id = ?
        WHERE d.game_id = ?
        ORDER BY d.price DESC;
    """, (user_id, game_id))
    dlcs = [dict(row) for row in cur.fetchall()]
    game["dlcs"] = dlcs

    conn.close()
    return game

# ----------------- Primary Store Checkout -----------------

@app.post("/api/purchase")
def purchase_game_and_dlcs(req: CheckoutRequest):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT g.game_id, g.title, g.base_price, p.publisher_id, p.royalty_percentage
            FROM games g
            JOIN publishers p ON g.publisher_id = p.publisher_id
            WHERE g.game_id = ?;
        """, (req.game_id,))
        game = cur.fetchone()
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")

        cur.execute("""
            SELECT library_id FROM user_library 
            WHERE user_id = ? AND game_id = ? AND status = 'ACTIVE';
        """, (req.user_id, req.game_id))
        is_already_owned = bool(cur.fetchone())

        if not is_already_owned and not req.include_base_game:
            raise HTTPException(status_code=400, detail="You must purchase the Base Game to acquire any DLCs.")

        if is_already_owned and req.include_base_game:
            req.include_base_game = False

        if not req.include_base_game and len(req.selected_dlc_ids) == 0:
            raise HTTPException(status_code=400, detail="No items selected for checkout.")

        total_amount = 0.0
        items_bought = []

        if req.include_base_game:
            total_amount += game["base_price"]
            items_bought.append(f"{game['title']} (Base Game)")

        valid_dlcs = []
        if req.selected_dlc_ids:
            placeholders = ",".join("?" * len(req.selected_dlc_ids))
            cur.execute(f"""
                SELECT dlc_id, title, price FROM game_dlcs
                WHERE game_id = ? AND dlc_id IN ({placeholders});
            """, [req.game_id] + req.selected_dlc_ids)
            valid_dlcs = cur.fetchall()

            for d in valid_dlcs:
                cur.execute("SELECT entitlement_id FROM user_dlc_library WHERE user_id = ? AND dlc_id = ?;", (req.user_id, d["dlc_id"]))
                if cur.fetchone():
                    continue
                total_amount += d["price"]
                items_bought.append(d["title"])

        if total_amount == 0.0:
            raise HTTPException(status_code=400, detail="All selected items are already in your library.")

        total_amount = round(total_amount, 2)

        cur.execute("SELECT wallet_balance FROM users WHERE user_id = ?;", (req.user_id,))
        user_row = cur.fetchone()
        if not user_row or user_row["wallet_balance"] < total_amount:
            raise HTTPException(status_code=400, detail=f"Insufficient funds. Total is ${total_amount:.2f}, but wallet balance is ${user_row['wallet_balance']:.2f}.")

        allocated_key_id = None
        allocated_license_code = None

        if req.include_base_game:
            cur.execute("""
                SELECT key_id, license_code FROM license_keys
                WHERE game_id = ? AND status = 'AVAILABLE'
                LIMIT 1;
            """, (req.game_id,))
            key_row = cur.fetchone()
            if not key_row:
                raise HTTPException(status_code=409, detail=f"Out of Stock: No digital license keys currently available for {game['title']}.")

            allocated_key_id = key_row["key_id"]
            allocated_license_code = key_row["license_code"]

            cur.execute("""
                UPDATE license_keys
                SET status = 'ASSIGNED', assigned_user_id = ?, assigned_at = CURRENT_TIMESTAMP
                WHERE key_id = ?;
            """, (req.user_id, allocated_key_id))

            cur.execute("""
                INSERT INTO user_library (user_id, game_id, key_id, status)
                VALUES (?, ?, ?, 'ACTIVE');
            """, (req.user_id, req.game_id, allocated_key_id))

        for d in valid_dlcs:
            cur.execute("""
                INSERT OR IGNORE INTO user_dlc_library (user_id, game_id, dlc_id)
                VALUES (?, ?, ?);
            """, (req.user_id, req.game_id, d["dlc_id"]))

        cur.execute("UPDATE users SET wallet_balance = wallet_balance - ? WHERE user_id = ?;", (total_amount, req.user_id))

        publisher_cut = round(total_amount * (game["royalty_percentage"] / 100.0), 2)
        cur.execute("UPDATE publishers SET total_royalties = total_royalties + ? WHERE publisher_id = ?;", (publisher_cut, game["publisher_id"]))

        summary_str = ", ".join(items_bought)
        cur.execute("""
            INSERT INTO transaction_ledger (user_id, game_id, key_id, items_summary, amount_paid, publisher_royalty, tx_status)
            VALUES (?, ?, ?, ?, ?, ?, 'PRIMARY_STORE_PURCHASE');
        """, (req.user_id, req.game_id, allocated_key_id, summary_str, total_amount, publisher_cut))

        conn.commit()
        return {
            "status": "SUCCESS",
            "message": f"Successfully purchased {summary_str}",
            "assigned_key": allocated_license_code,
            "total_paid": total_amount,
            "items_unlocked": items_bought
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Transaction Failed: {str(e)}")
    finally:
        conn.close()

# ----------------- P2P Secondary Resale Marketplace & AI Valuation -----------------

def calculate_ai_pricing_model(game_id: int, library_id: Optional[int] = None, user_id: Optional[int] = None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT g.game_id, g.title, g.base_price, g.metascore, g.genre,
               (SELECT COUNT(*) FROM license_keys WHERE game_id = g.game_id AND status = 'AVAILABLE') as store_stock_count
        FROM games g
        WHERE g.game_id = ?;
    """, (game_id,))
    game = cur.fetchone()
    if not game:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")

    base_price = float(game["base_price"])
    stock_count = int(game["store_stock_count"])
    metascore = int(game["metascore"])

    # Attached DLC value if listing from user library
    dlc_total = 0.0
    dlc_titles = []
    if library_id:
        cur.execute("""
            SELECT gd.title, gd.price 
            FROM user_dlc_library udl
            JOIN game_dlcs gd ON udl.dlc_id = gd.dlc_id
            WHERE udl.game_id = ?;
        """, (game_id,))
        for d in cur.fetchall():
            dlc_total += float(d["price"])
            dlc_titles.append(d["title"])

    conn.close()

    # Dynamic Scarcity Model:
    # 0 keys: Out of stock -> Maximum scarcity (95% - 100% of retail)
    # 1 key: High scarcity -> Strong resale value (84% - 88% of retail)
    # 2 keys: Moderate inventory -> Balanced discount (66% - 70% of retail)
    # 3+ keys: Abundant inventory -> Deep discount (50% - 55% of retail)
    if stock_count == 0:
        stock_multiplier = 0.96
        scarcity_tier = "CRITICAL_SCARCITY"
        scarcity_label = "0 Official Keys (Sold Out in Store)"
        reasoning = (
            f"Primary store is sold out of '{game['title']}'. Secondary market scarcity "
            "allows sellers to command high resale prices near full retail value."
        )
    elif stock_count == 1:
        stock_multiplier = 0.85
        scarcity_tier = "HIGH_SCARCITY"
        scarcity_label = "1 Official Key Left in Store"
        reasoning = (
            f"Official store inventory is critically low (only 1 key available in store). "
            f"High scarcity supports a premium secondary valuation of ~85% of retail (${round(base_price * 0.85, 2):.2f})."
        )
    elif stock_count == 2:
        stock_multiplier = 0.68
        scarcity_tier = "MODERATE_STOCK"
        scarcity_label = "2 Official Keys in Store"
        reasoning = (
            f"Official store inventory is moderate (2 keys available). "
            "A balanced ~32% markdown provides an optimal compromise between profit and fast turnover."
        )
    else:
        stock_multiplier = 0.52
        scarcity_tier = "ABUNDANT_STOCK"
        scarcity_label = f"{stock_count} Official Keys in Store"
        reasoning = (
            f"Primary store has abundant stock ({stock_count} keys available). "
            "A competitive markdown of ~48% is recommended to attract buyers over the official store."
        )

    meta_mod = 0.04 if metascore >= 90 else (0.0 if metascore >= 80 else -0.04)
    dlc_bonus = round(dlc_total * 0.40, 2)
    raw_suggested = (base_price * stock_multiplier * (1.0 + meta_mod)) + dlc_bonus
    suggested_price = round(max(5.00, raw_suggested), 2)
    range_min = round(max(4.00, suggested_price * 0.90), 2)
    range_max = round(suggested_price * 1.10, 2)

    # Preset Liquidity Tiers
    fast_sale_price = round(max(4.00, suggested_price * 0.84), 2)
    max_profit_price = round(suggested_price * (1.14 if stock_count <= 1 else 1.08), 2)

    return {
        "game_id": game_id,
        "game_title": game["title"],
        "base_price": base_price,
        "metascore": metascore,
        "store_stock_count": stock_count,
        "scarcity_tier": scarcity_tier,
        "scarcity_label": scarcity_label,
        "suggested_price": suggested_price,
        "fast_sale_price": fast_sale_price,
        "fast_sale_label": "⚡ Fast Sale — 95% chance to sell in 1h",
        "max_profit_price": max_profit_price,
        "max_profit_label": "💰 Max Profit — Patient seller (~40% immediate turnover)",
        "range_min": range_min,
        "range_max": range_max,
        "discount_pct": max(0, int(round((1 - (suggested_price / (base_price + dlc_total if dlc_total else base_price))) * 100))),
        "dlc_bonus": dlc_bonus,
        "dlc_count": len(dlc_titles),
        "dlc_titles": dlc_titles,
        "reasoning": reasoning,
        "confidence_pct": 94 if stock_count <= 1 else 91
    }

def evaluate_custom_asking_price(game_id: int, asking_price: float, library_id: Optional[int] = None):
    pricing = calculate_ai_pricing_model(game_id, library_id)
    suggested = pricing["suggested_price"]
    stock_count = pricing["store_stock_count"]
    retail = pricing["base_price"]

    if asking_price <= 0:
        return {
            "status_type": "invalid",
            "badge": "Invalid Price",
            "deal_score": 0.0,
            "deal_label": "Invalid Asking Price",
            "liquidity_forecast": "N/A",
            "message": "Please enter an asking price above $0.00.",
            "suggested_price": suggested,
            "stock_count": stock_count,
            "scarcity_label": pricing["scarcity_label"]
        }

    ratio = asking_price / (suggested if suggested > 0 else 1.0)
    ratio_retail = asking_price / (retail if retail > 0 else 1.0)
    undervalued_pct = max(5, int(round((1.0 - ratio_retail) * 100)))

    if ratio <= 0.72:
        deal_score = 9.8
        deal_label = f"🔥 AI Deal Rating: 9.8/10 (Undervalued by {undervalued_pct}%)"
        liquidity_forecast = "⚡ Ultra Fast (~30 mins • 98% probability)"
        status_type = "bargain"
        badge = "🔥 Aggressive Bargain"
        message = f"Deeply discounted below AI fair value. High liquidity forecast: estimated sale within ~30 minutes."
    elif ratio <= 0.88:
        deal_score = 9.4
        deal_label = f"🔥 AI Deal Rating: 9.4/10 (Undervalued by {undervalued_pct}%)"
        liquidity_forecast = "⚡ Fast Sale (~1-2 hours • 92% probability)"
        status_type = "bargain"
        badge = "🔥 High-Value Bargain"
        message = f"Attractively priced below market. High liquidity forecast: estimated sale within ~1-2 hours."
    elif ratio <= 1.06:
        deal_score = 8.6 if stock_count <= 1 else 7.4
        scarcity_tag = "Scarcity Pick" if stock_count <= 1 else "Fair Market Price"
        deal_label = f"⚖️ AI Deal Rating: {deal_score}/10 ({scarcity_tag})"
        liquidity_forecast = "✨ Steady Sale (~3-6 hours • 80% probability)"
        status_type = "optimal"
        badge = "✨ Optimal Fair Value"
        message = f"Balanced with store inventory ({pricing['scarcity_label']}). Optimal equilibrium between seller profit and fast turnover."
    elif ratio <= 1.25:
        if stock_count <= 1:
            deal_score = 8.2
            deal_label = "💎 AI Deal Rating: 8.2/10 (Scarcity Premium)"
            liquidity_forecast = "💎 High Margin (~6-12 hours)"
            status_type = "scarcity_premium"
            badge = "💎 Scarcity Premium"
            message = f"Premium pricing supported by scarce store inventory ({pricing['scarcity_label']}). Strong profit margin."
        else:
            deal_score = 5.8
            deal_label = "⚖️ AI Deal Rating: 5.8/10 (Above Market)"
            liquidity_forecast = "⏳ Moderate to Slow (>12 hours)"
            status_type = "above_market"
            badge = "⚠️ Above Suggested Price"
            message = f"With {stock_count} keys in store, buyers may prefer buying brand-new unless discounted further."
    else:
        if stock_count == 0:
            deal_score = 7.1
            deal_label = "📈 AI Deal Rating: 7.1/10 (Out-of-Stock Surcharge)"
            liquidity_forecast = "⏳ Patient Seller (>24 hours)"
            status_type = "collector_premium"
            badge = "📈 Out-of-Stock Markup"
            message = "Official store is sold out, so higher pricing is possible, but sale turnover will be slower."
        else:
            deal_score = 4.2
            deal_label = "⚠️ AI Deal Rating: 4.2/10 (Uncompetitive vs Store)"
            liquidity_forecast = "⏳ Very Slow (>24 hours)"
            status_type = "uncompetitive"
            badge = "⚠️ Uncompetitive vs Store"
            message = f"Asking price approaches or exceeds store price while {stock_count} store keys exist."

    return {
        "status_type": status_type,
        "badge": badge,
        "deal_score": deal_score,
        "deal_label": deal_label,
        "liquidity_forecast": liquidity_forecast,
        "message": message,
        "suggested_price": suggested,
        "stock_count": stock_count,
        "scarcity_label": pricing["scarcity_label"]
    }

@app.get("/api/ai/pricing-suggestion")
def get_ai_pricing_suggestion(game_id: int, library_id: Optional[int] = None):
    """Provides non-binding AI price recommendations and liquidity estimates based on real-time store stock scarcity."""
    return calculate_ai_pricing_model(game_id, library_id)

@app.post("/api/ai/evaluate-price")
def evaluate_seller_price(req: PriceEvaluationRequest):
    """Evaluates seller custom asking price in real-time as they type."""
    return evaluate_custom_asking_price(req.game_id, req.asking_price, req.library_id)

@app.get("/api/ai/bundle-optimizer")
def get_ai_bundle_recommendation(game_id: int, user_id: int = 1):
    """
    AI Dynamic Bundle Builder & Smart Cart Optimizer.
    Evaluates DLC types (Story Expansion vs Item Pack vs Soundtrack),
    ownership status, and optimizes the bundle for narrative value or budget.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT g.game_id, g.title, g.base_price, g.genre, g.metascore,
               p.publisher_id, p.name as publisher_name
        FROM games g
        JOIN publishers p ON g.publisher_id = p.publisher_id
        WHERE g.game_id = ?;
    """, (game_id,))
    game = cur.fetchone()
    if not game:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found")

    cur.execute("""
        SELECT library_id FROM user_library 
        WHERE user_id = ? AND game_id = ? AND status = 'ACTIVE';
    """, (user_id, game_id))
    is_base_owned = bool(cur.fetchone())

    cur.execute("""
        SELECT d.dlc_id, d.title, d.dlc_type, d.price, d.description,
               CASE WHEN udl.entitlement_id IS NOT NULL THEN 1 ELSE 0 END as is_owned
        FROM game_dlcs d
        LEFT JOIN user_dlc_library udl ON udl.dlc_id = d.dlc_id AND udl.user_id = ?
        WHERE d.game_id = ?
        ORDER BY d.price DESC;
    """, (user_id, game_id))
    dlcs = [dict(row) for row in cur.fetchall()]
    conn.close()

    base_price = float(game["base_price"])
    unowned_dlcs = [d for d in dlcs if not d["is_owned"]]
    unowned_story = [d for d in unowned_dlcs if d["dlc_type"] == 'Story Expansion']
    unowned_cosmetic = [d for d in unowned_dlcs if d["dlc_type"] == 'Item Pack']
    unowned_music = [d for d in unowned_dlcs if d["dlc_type"] == 'Soundtrack']

    story_dlc_ids = [d["dlc_id"] for d in unowned_story]
    story_dlc_sum = sum(d["price"] for d in unowned_story)
    all_dlc_sum = sum(d["price"] for d in unowned_dlcs)

    base_cost = base_price if not is_base_owned else 0.0
    story_bundle_total = round(base_cost + story_dlc_sum, 2)
    all_content_total = round(base_cost + all_dlc_sum, 2)
    savings_vs_all = round(all_content_total - story_bundle_total, 2)

    story_titles = [d["title"] for d in unowned_story]

    if unowned_story:
        story_headline = f"Base Game + {len(unowned_story)} Story Expansion{'s' if len(unowned_story) > 1 else ''}"
        if savings_vs_all > 0:
            story_reasoning = (
                f"Recommended: {game['title']} + {', '.join(story_titles)} (${story_bundle_total:.2f}). "
                f"Skipping cosmetic items & soundtracks saves you ${savings_vs_all:.2f} while keeping 100% of major narrative gameplay."
            )
        else:
            story_reasoning = f"Recommended: {game['title']} + {', '.join(story_titles)} (${story_bundle_total:.2f}). Delivers complete narrative campaign."
    else:
        story_headline = f"{game['title']} Digital License"
        story_reasoning = "All story expansions are already owned, or this title focuses on core base gameplay."

    all_dlc_ids = [d["dlc_id"] for d in unowned_dlcs]
    all_reasoning = f"Complete experience: Includes all {len(unowned_dlcs)} available add-ons (Story Expansions, Item Packs, Soundtracks)."

    budget_dlc_ids = [unowned_story[0]["dlc_id"]] if unowned_story else []
    budget_dlc_sum = unowned_story[0]["price"] if unowned_story else 0.0
    budget_total = round(base_cost + budget_dlc_sum, 2)
    budget_reasoning = "Core essentials only — optimal value-per-dollar ratio with zero filler."

    return {
        "game_id": game_id,
        "game_title": game["title"],
        "base_price": base_price,
        "is_base_owned": is_base_owned,
        "strategies": {
            "story": {
                "id": "story",
                "label": "🎯 Story & Expansion Focus",
                "badge": "AI Recommended",
                "include_base": not is_base_owned,
                "selected_dlc_ids": story_dlc_ids,
                "bundle_total": story_bundle_total,
                "savings": savings_vs_all,
                "headline": story_headline,
                "reasoning": story_reasoning
            },
            "complete": {
                "id": "complete",
                "label": "👑 Complete Collector Edition",
                "badge": "All Add-ons",
                "include_base": not is_base_owned,
                "selected_dlc_ids": all_dlc_ids,
                "bundle_total": all_content_total,
                "savings": 0.0,
                "headline": "All Expansions & Add-on Packs",
                "reasoning": all_reasoning
            },
            "budget": {
                "id": "budget",
                "label": "💰 Budget Gamer Pick",
                "badge": "Maximum Thrift",
                "include_base": not is_base_owned,
                "selected_dlc_ids": budget_dlc_ids,
                "bundle_total": budget_total,
                "savings": round(all_content_total - budget_total, 2),
                "headline": "Core Campaign Essentials",
                "reasoning": budget_reasoning
            }
        }
    }

@app.get("/api/marketplace")
def get_marketplace_listings():
    """Lists all active secondary used games for sale with live AI Market Deal evaluations."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.listing_id, m.game_id, m.seller_id, m.library_id, m.key_id, m.asking_price, 
               m.publisher_cut_percentage, m.status, m.created_at,
               g.title as game_title, g.cover_image, g.genre, g.base_price as retail_price,
               u.username as seller_name, u.avatar_url as seller_avatar,
               lk.license_code
        FROM p2p_marketplace_listings m
        JOIN games g ON m.game_id = g.game_id
        JOIN users u ON m.seller_id = u.user_id
        JOIN license_keys lk ON m.key_id = lk.key_id
        WHERE m.status = 'ACTIVE'
        ORDER BY m.created_at DESC;
    """)
    raw_listings = [dict(r) for r in cur.fetchall()]
    conn.close()

    listings = []
    for item in raw_listings:
        pricing = calculate_ai_pricing_model(item["game_id"])
        eval_res = evaluate_custom_asking_price(item["game_id"], item["asking_price"])
        item["ai_evaluation"] = {
            "badge_type": eval_res["status_type"],
            "badge_label": eval_res["badge"],
            "deal_score": eval_res["deal_score"],
            "deal_label": eval_res["deal_label"],
            "liquidity_forecast": eval_res["liquidity_forecast"],
            "feedback": eval_res["message"],
            "suggested_price": pricing["suggested_price"],
            "store_stock_count": pricing["store_stock_count"],
            "scarcity_label": pricing["scarcity_label"]
        }
        listings.append(item)

    return listings

@app.post("/api/marketplace/list")
def list_game_for_resale(req: P2PListRequest):
    """
    Lists a user's owned game on the secondary marketplace.
    Validates that the game is not currently in an active play session!
    """
    if req.asking_price <= 0:
        raise HTTPException(status_code=400, detail="Asking price must be greater than $0.00")

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT ul.library_id, ul.game_id, ul.key_id, ul.status, g.title
            FROM user_library ul
            JOIN games g ON ul.game_id = g.game_id
            WHERE ul.library_id = ? AND ul.user_id = ?;
        """, (req.library_id, req.seller_id))
        record = cur.fetchone()

        if not record or record["status"] != 'ACTIVE':
            raise HTTPException(status_code=400, detail="Game is not available for listing (must be active in library).")

        # Check if currently playing!
        cur.execute("""
            SELECT lease_id FROM active_drm_leases 
            WHERE user_id = ? AND game_id = ? AND lease_status = 'ACTIVE';
        """, (req.seller_id, record["game_id"]))
        if cur.fetchone():
            raise HTTPException(
                status_code=400, 
                detail=f"Security Lock: Cannot resell '{record['title']}' while a live DRM play session is active. Please exit the game first."
            )

        # Mark library item as listed
        cur.execute("UPDATE user_library SET status = 'LISTED_FOR_SALE' WHERE library_id = ?;", (req.library_id,))

        # Insert into marketplace
        cur.execute("""
            INSERT INTO p2p_marketplace_listings (game_id, seller_id, library_id, key_id, asking_price, status)
            VALUES (?, ?, ?, ?, ?, 'ACTIVE');
        """, (record["game_id"], req.seller_id, req.library_id, record["key_id"], round(req.asking_price, 2)))

        conn.commit()
        return {
            "status": "SUCCESS",
            "message": f"Successfully listed '{record['title']}' on P2P Marketplace for ${req.asking_price:.2f}"
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Marketplace listing failed: {str(e)}")
    finally:
        conn.close()

@app.post("/api/marketplace/buy")
def buy_p2p_listing(req: P2PBuyRequest):
    """
    Executes an Atomic 3-Way Financial & Entitlement Swap:
    1. Deducts asking_price from Buyer.
    2. Pays 80% to Seller.
    3. Pays 20% royalty to Publisher.
    4. Revokes Seller's library record.
    5. Transfers license key & DLCs to Buyer.
    """
    conn = get_connection()
    cur = conn.cursor()

    try:
        # 1. Fetch listing details
        cur.execute("""
            SELECT m.listing_id, m.game_id, m.seller_id, m.library_id, m.key_id, m.asking_price, 
                   m.publisher_cut_percentage, m.status,
                   g.title as game_title, g.publisher_id,
                   lk.license_code,
                   seller.username as seller_name
            FROM p2p_marketplace_listings m
            JOIN games g ON m.game_id = g.game_id
            JOIN license_keys lk ON m.key_id = lk.key_id
            JOIN users seller ON m.seller_id = seller.user_id
            WHERE m.listing_id = ?;
        """, (req.listing_id,))
        listing = cur.fetchone()

        if not listing or listing["status"] != 'ACTIVE':
            raise HTTPException(status_code=400, detail="This listing is no longer available.")

        if req.buyer_id == listing["seller_id"]:
            raise HTTPException(status_code=400, detail="You cannot buy your own marketplace listing.")

        # Check if buyer already owns this game
        cur.execute("""
            SELECT library_id FROM user_library 
            WHERE user_id = ? AND game_id = ? AND status = 'ACTIVE';
        """, (req.buyer_id, listing["game_id"]))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="You already own this game in your library.")

        # Check buyer wallet
        cur.execute("SELECT wallet_balance, username FROM users WHERE user_id = ?;", (req.buyer_id,))
        buyer = cur.fetchone()
        asking_price = listing["asking_price"]

        if not buyer or buyer["wallet_balance"] < asking_price:
            raise HTTPException(status_code=400, detail=f"Insufficient funds: You need ${asking_price:.2f}, but your wallet balance is ${buyer['wallet_balance']:.2f}.")

        # 2. Financial 3-Way Split Calculations
        publisher_cut = round(asking_price * (listing["publisher_cut_percentage"] / 100.0), 2)
        seller_payout = round(asking_price - publisher_cut, 2)

        # 3. Execute Balance Updates
        cur.execute("UPDATE users SET wallet_balance = wallet_balance - ? WHERE user_id = ?;", (asking_price, req.buyer_id))
        cur.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id = ?;", (seller_payout, listing["seller_id"]))
        cur.execute("UPDATE publishers SET total_royalties = total_royalties + ? WHERE publisher_id = ?;", (publisher_cut, listing["publisher_id"]))

        # 4. Revoke Seller Library Access & Transfer License Key
        cur.execute("UPDATE user_library SET status = 'SOLD' WHERE library_id = ?;", (listing["library_id"],))
        cur.execute("""
            UPDATE license_keys 
            SET assigned_user_id = ?, assigned_at = CURRENT_TIMESTAMP 
            WHERE key_id = ?;
        """, (req.buyer_id, listing["key_id"]))

        # 5. Grant Ownership to Buyer
        cur.execute("""
            INSERT INTO user_library (user_id, game_id, key_id, status)
            VALUES (?, ?, ?, 'ACTIVE');
        """, (req.buyer_id, listing["game_id"], listing["key_id"]))

        # 6. Transfer any DLCs linked to seller for this game to buyer
        cur.execute("""
            SELECT dlc_id FROM user_dlc_library 
            WHERE user_id = ? AND game_id = ?;
        """, (listing["seller_id"], listing["game_id"]))
        seller_dlcs = cur.fetchall()

        for d in seller_dlcs:
            cur.execute("DELETE FROM user_dlc_library WHERE user_id = ? AND dlc_id = ?;", (listing["seller_id"], d["dlc_id"]))
            cur.execute("INSERT OR IGNORE INTO user_dlc_library (user_id, game_id, dlc_id) VALUES (?, ?, ?);", (req.buyer_id, listing["game_id"], d["dlc_id"]))

        # 7. Update Listing Status
        cur.execute("""
            UPDATE p2p_marketplace_listings 
            SET status = 'SOLD', buyer_id = ?, sold_at = CURRENT_TIMESTAMP 
            WHERE listing_id = ?;
        """, (req.buyer_id, req.listing_id))

        # 8. Audit in Transaction Ledger
        cur.execute("""
            INSERT INTO transaction_ledger (user_id, game_id, key_id, items_summary, amount_paid, publisher_royalty, tx_status)
            VALUES (?, ?, ?, ?, ?, ?, 'P2P_SECONDARY_RESALE');
        """, (req.buyer_id, listing["game_id"], listing["key_id"], f"P2P Resale from {listing['seller_name']}", asking_price, publisher_cut))

        conn.commit()

        return {
            "status": "SUCCESS",
            "message": f"Successfully purchased used license for {listing['game_title']} from {listing['seller_name']}!",
            "amount_paid": asking_price,
            "seller_payout": seller_payout,
            "publisher_royalty": publisher_cut,
            "assigned_key": listing["license_code"]
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"P2P transaction failed: {str(e)}")
    finally:
        conn.close()

# ----------------- User Library & Distributed DRM Sessions -----------------

@app.get("/api/user/library")
def get_user_library(user_id: int = 1):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT ul.library_id, ul.acquired_at, ul.playtime_minutes, ul.status as library_status,
               g.game_id, g.title, g.cover_image, g.header_image, g.genre, g.developer, g.base_price,
               lk.license_code,
               adl.lease_status as active_session_status,
               adl.device_name as active_device_name
        FROM user_library ul
        JOIN games g ON ul.game_id = g.game_id
        JOIN license_keys lk ON ul.key_id = lk.key_id
        LEFT JOIN active_drm_leases adl ON adl.user_id = ul.user_id AND adl.game_id = ul.game_id AND adl.lease_status = 'ACTIVE'
        WHERE ul.user_id = ? AND ul.status = 'ACTIVE'
        ORDER BY ul.acquired_at DESC;
    """, (user_id,))
    library_items = []
    for row in cur.fetchall():
        item = dict(row)
        cur.execute("""
            SELECT gd.title, gd.dlc_type
            FROM user_dlc_library udl
            JOIN game_dlcs gd ON udl.dlc_id = gd.dlc_id
            WHERE udl.user_id = ? AND gd.game_id = ?;
        """, (user_id, item["game_id"]))
        item["unlocked_dlcs"] = [dict(d) for d in cur.fetchall()]
        library_items.append(item)

    conn.close()
    return library_items

@app.post("/api/library/play")
def play_game(req: PlaySessionRequest):
    """
    Launches a game session with Distributed Single-Seat DRM conflict detection.
    If another device already holds an active lease, a 409 CONCURRENCY CONFLICT is raised.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT library_id, playtime_minutes FROM user_library WHERE user_id = ? AND game_id = ? AND status = 'ACTIVE';", (req.user_id, req.game_id))
    entry = cur.fetchone()
    if not entry:
        conn.close()
        raise HTTPException(status_code=404, detail="Game not found in active library")

    # Distributed Conflict Check
    cur.execute("""
        SELECT lease_id, device_name, started_at 
        FROM active_drm_leases 
        WHERE user_id = ? AND game_id = ? AND lease_status = 'ACTIVE';
    """, (req.user_id, req.game_id))
    existing_lease = cur.fetchone()

    if existing_lease and existing_lease["device_name"] != req.device_name and not req.force_takeover:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONCURRENCY_CONFLICT",
                "active_device": existing_lease["device_name"],
                "started_at": existing_lease["started_at"],
                "message": f"CONCURRENCY CONFLICT: Game is already running on '{existing_lease['device_name']}'. GameVault DRM single-seat policy prohibits concurrent play on multiple devices."
            }
        )

    # Terminate prior sessions if taking over
    cur.execute("UPDATE active_drm_leases SET lease_status = 'TERMINATED' WHERE user_id = ? AND game_id = ?;", (req.user_id, req.game_id))

    # Increment playtime by 30 mins
    cur.execute("""
        UPDATE user_library
        SET playtime_minutes = playtime_minutes + 30, last_played_at = CURRENT_TIMESTAMP
        WHERE library_id = ?;
    """, (entry["library_id"],))

    session_token = secrets.token_hex(16)
    expires_at = (datetime.utcnow() + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO active_drm_leases (game_id, user_id, device_id, device_name, session_token, lease_status, expires_at)
        VALUES (?, ?, 'DEV-NODE-01', ?, ?, 'ACTIVE', ?);
    """, (req.game_id, req.user_id, req.device_name, session_token, expires_at))

    cur.execute("SELECT playtime_minutes FROM user_library WHERE library_id = ?;", (entry["library_id"],))
    new_playtime = cur.fetchone()[0]
    conn.commit()
    conn.close()

    return {
        "status": "LAUNCHED",
        "device_name": req.device_name,
        "message": f"Game session active on [{req.device_name}]. Single-seat DRM lease verified.",
        "new_playtime_minutes": new_playtime
    }

@app.post("/api/library/stop")
def stop_game(req: PlaySessionRequest):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE active_drm_leases SET lease_status = 'TERMINATED' WHERE user_id = ? AND game_id = ? AND lease_status = 'ACTIVE';", (req.user_id, req.game_id))
    conn.commit()
    conn.close()
    return {"status": "STOPPED", "message": "Game session ended. DRM lease released."}

# ----------------- Refund Engine -----------------

@app.post("/api/library/refund")
def refund_game(req: RefundRequest):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT ul.library_id, ul.playtime_minutes, ul.game_id, ul.key_id,
                   g.publisher_id, g.title,
                   tl.amount_paid, tl.publisher_royalty
            FROM user_library ul
            JOIN games g ON ul.game_id = g.game_id
            JOIN transaction_ledger tl ON tl.user_id = ul.user_id AND tl.game_id = ul.game_id AND tl.tx_status = 'PRIMARY_STORE_PURCHASE'
            WHERE ul.library_id = ? AND ul.user_id = ? AND ul.status = 'ACTIVE';
        """, (req.library_id, req.user_id))
        record = cur.fetchone()

        if not record:
            raise HTTPException(status_code=404, detail="Active primary purchase record not found for refund")

        if record["playtime_minutes"] > 120:
            cur.execute("""
                INSERT INTO refund_requests (user_id, library_id, game_id, playtime_at_request, decision, decision_reason, amount_refunded)
                VALUES (?, ?, ?, ?, 'REJECTED', 'Playtime exceeds strict 120m threshold', 0.0);
            """, (req.user_id, req.library_id, record["game_id"], record["playtime_minutes"]))
            conn.commit()
            raise HTTPException(status_code=400, detail=f"Refund Denied: Recorded playtime ({record['playtime_minutes']} mins) exceeds 120-minute policy limit.")

        cur.execute("UPDATE user_library SET status = 'REFUNDED' WHERE library_id = ?;", (req.library_id,))
        cur.execute("DELETE FROM user_dlc_library WHERE user_id = ? AND game_id = ?;", (req.user_id, record["game_id"]))
        cur.execute("UPDATE license_keys SET status = 'AVAILABLE', assigned_user_id = NULL, assigned_at = NULL WHERE key_id = ?;", (record["key_id"],))
        cur.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id = ?;", (record["amount_paid"], req.user_id))
        cur.execute("UPDATE publishers SET total_royalties = total_royalties - ? WHERE publisher_id = ?;", (record["publisher_royalty"], record["publisher_id"]))

        cur.execute("""
            INSERT INTO transaction_ledger (user_id, game_id, key_id, items_summary, amount_paid, publisher_royalty, tx_status)
            VALUES (?, ?, ?, 'REFUND REVERSAL', ?, ?, 'REFUNDED');
        """, (req.user_id, record["game_id"], record["key_id"], -record["amount_paid"], -record["publisher_royalty"]))

        cur.execute("""
            INSERT INTO refund_requests (user_id, library_id, game_id, playtime_at_request, decision, decision_reason, amount_refunded)
            VALUES (?, ?, ?, ?, 'APPROVED', 'Playtime verified under 120m threshold', ?);
        """, (req.user_id, req.library_id, record["game_id"], record["playtime_minutes"], record["amount_paid"]))

        conn.commit()
        return {"status": "REFUNDED", "message": f"Successfully refunded {record['title']}. ${record['amount_paid']:.2f} returned to wallet."}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Refund Failed: {str(e)}")
    finally:
        conn.close()

# ----------------- Database Inspector -----------------

@app.get("/api/db/stats")
def get_db_stats():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM games;")
    total_games = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM license_keys WHERE status = 'AVAILABLE';")
    available_keys = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM license_keys WHERE status = 'ASSIGNED';")
    assigned_keys = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM user_library WHERE status = 'ACTIVE';")
    owned_games = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM transaction_ledger;")
    total_tx = cur.fetchone()[0]
    conn.close()
    return {
        "total_games": total_games,
        "available_keys": available_keys,
        "assigned_keys": assigned_keys,
        "owned_games": owned_games,
        "total_transactions": total_tx
    }

@app.get("/api/db/table/{table_name}")
def get_table_data(table_name: str, limit: int = 100):
    allowed_tables = [
        "license_keys", "games", "user_library", "user_dlc_library", 
        "game_dlcs", "p2p_marketplace_listings", "users", "transaction_ledger",
        "refund_requests", "publishers", "active_drm_leases"
    ]
    if table_name not in allowed_tables:
        raise HTTPException(status_code=400, detail="Invalid table name")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table_name} ORDER BY 1 DESC LIMIT ?;", (limit,))
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"table": table_name, "count": len(rows), "rows": rows}

@app.post("/api/db/query")
def execute_custom_query(req: RawQueryRequest):
    clean_q = req.query.strip()
    if not clean_q.upper().startswith("SELECT") and not clean_q.upper().startswith("PRAGMA"):
        raise HTTPException(status_code=400, detail="Only SELECT or PRAGMA statements are permitted.")
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(clean_q)
        rows = [dict(row) for row in cur.fetchall()]
        return {"status": "SUCCESS", "rows": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/api/db/reset")
def reset_database():
    try:
        reset_and_seed()
        return {"status": "SUCCESS", "message": "Database reset to factory default state."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount frontend
frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
