"""
GameVault Database Engine & Schema (Direct Games + DLCs Model)
- 3NF Normalized schema
- Foreign key constraints
- Atomic key allocation per game title
- DLC entitlements linked to base games
- Full financial auditing and refund logs
"""

import sqlite3
import os
import random
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gamevault.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # 1. Users & Wallet
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        wallet_balance REAL NOT NULL DEFAULT 250.00,
        avatar_url TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Publishers
    cur.execute("""
    CREATE TABLE IF NOT EXISTS publishers (
        publisher_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        royalty_percentage REAL NOT NULL DEFAULT 15.0,
        total_royalties REAL DEFAULT 0.0
    );
    """)

    # 3. Games Catalog
    cur.execute("""
    CREATE TABLE IF NOT EXISTS games (
        game_id INTEGER PRIMARY KEY AUTOINCREMENT,
        publisher_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        tagline TEXT,
        description TEXT,
        genre TEXT,
        developer TEXT,
        release_date TEXT,
        metascore INTEGER,
        header_image TEXT,
        cover_image TEXT,
        base_price REAL NOT NULL,
        FOREIGN KEY (publisher_id) REFERENCES publishers (publisher_id) ON DELETE CASCADE
    );
    """)

    # 4. DLCs and Add-ons (Linked directly to Parent Games)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS game_dlcs (
        dlc_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        dlc_type TEXT NOT NULL,     -- 'Story Expansion', 'Soundtrack', 'Item Pack'
        price REAL NOT NULL,
        description TEXT,
        FOREIGN KEY (game_id) REFERENCES games (game_id) ON DELETE CASCADE
    );
    """)

    # 5. Digital License Keys Inventory (Assigned to Base Game)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS license_keys (
        key_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        license_code TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'AVAILABLE', -- 'AVAILABLE', 'ASSIGNED', 'REVOKED'
        assigned_user_id INTEGER,
        assigned_at DATETIME,
        FOREIGN KEY (game_id) REFERENCES games (game_id),
        FOREIGN KEY (assigned_user_id) REFERENCES users (user_id)
    );
    """)

    # 6. User Library (Game Entitlements)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_library (
        library_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        key_id INTEGER NOT NULL,
        playtime_minutes INTEGER DEFAULT 0,
        acquired_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_played_at DATETIME,
        status TEXT DEFAULT 'ACTIVE',            -- 'ACTIVE', 'REFUNDED'
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (game_id) REFERENCES games (game_id),
        FOREIGN KEY (key_id) REFERENCES license_keys (key_id),
        UNIQUE(user_id, game_id)
    );
    """)

    # 7. User DLC Library (Child Entitlements)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_dlc_library (
        entitlement_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        dlc_id INTEGER NOT NULL,
        unlocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (game_id) REFERENCES games (game_id),
        FOREIGN KEY (dlc_id) REFERENCES game_dlcs (dlc_id),
        UNIQUE(user_id, dlc_id)
    );
    """)

    # 8. Financial & Audit Transaction Ledger
    cur.execute("""
    CREATE TABLE IF NOT EXISTS transaction_ledger (
        tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        key_id INTEGER,
        items_summary TEXT NOT NULL,
        amount_paid REAL NOT NULL,
        publisher_royalty REAL NOT NULL,
        payment_method TEXT DEFAULT 'STORE_WALLET',
        tx_status TEXT DEFAULT 'COMPLETED',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (game_id) REFERENCES games (game_id),
        FOREIGN KEY (key_id) REFERENCES license_keys (key_id)
    );
    """)

    # 9. Refund Requests & Policy Audit Log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS refund_requests (
        request_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        library_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        playtime_at_request INTEGER NOT NULL,
        reason TEXT DEFAULT 'Customer remorse / performance issues',
        decision TEXT NOT NULL, -- 'APPROVED', 'REJECTED'
        decision_reason TEXT,
        amount_refunded REAL DEFAULT 0.0,
        requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (game_id) REFERENCES games (game_id)
    );
    """)

    # 10. Active DRM Leases (Single-Seat Session Locks)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS active_drm_leases (
        lease_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        device_id TEXT NOT NULL,
        device_name TEXT NOT NULL,
        session_token TEXT UNIQUE NOT NULL,
        lease_status TEXT DEFAULT 'ACTIVE', -- 'ACTIVE', 'TERMINATED', 'EXPIRED'
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (game_id) REFERENCES games (game_id)
    );
    """)

    # 11. P2P Marketplace Resale Listings
    cur.execute("""
    CREATE TABLE IF NOT EXISTS p2p_marketplace_listings (
        listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        seller_id INTEGER NOT NULL,
        library_id INTEGER NOT NULL,
        key_id INTEGER NOT NULL,
        asking_price REAL NOT NULL,
        publisher_cut_percentage REAL NOT NULL DEFAULT 20.0,
        status TEXT NOT NULL DEFAULT 'ACTIVE', -- 'ACTIVE', 'SOLD', 'CANCELLED'
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        sold_at DATETIME,
        buyer_id INTEGER,
        FOREIGN KEY (game_id) REFERENCES games (game_id),
        FOREIGN KEY (seller_id) REFERENCES users (user_id),
        FOREIGN KEY (library_id) REFERENCES user_library (library_id),
        FOREIGN KEY (key_id) REFERENCES license_keys (key_id),
        FOREIGN KEY (buyer_id) REFERENCES users (user_id)
    );
    """)

    conn.commit()
    conn.close()

def reset_and_seed():
    """Drops old tables and creates the clean streamlined schema."""
    conn = get_connection()
    cur = conn.cursor()

    # Drop existing tables cleanly
    tables_to_drop = [
        "p2p_marketplace_listings", "active_drm_leases", "refund_requests", 
        "transaction_ledger", "user_dlc_library", "user_library", 
        "license_keys", "game_dlcs", "game_editions", "system_requirements",
        "games", "publishers", "users"
    ]
    for tbl in tables_to_drop:
        cur.execute(f"DROP TABLE IF EXISTS {tbl};")

    conn.commit()
    conn.close()

    init_db()

    conn = get_connection()
    cur = conn.cursor()

    # Seed Multiple Distinct Users for P2P & Multi-Device Testing
    users_data = [
        ('Commander_Rakesh', 'rakesh@gamevault.io', 250.00, 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=120&auto=format&fit=crop&q=80'),
        ('Alex_Valkyrie', 'alex@gamevault.io', 180.00, 'https://images.unsplash.com/photo-1570295999919-56ceb5ecca61?w=120&auto=format&fit=crop&q=80'),
        ('Elena_Ghost', 'elena@gamevault.io', 90.00, 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=120&auto=format&fit=crop&q=80')
    ]
    cur.executemany("""
    INSERT INTO users (username, email, wallet_balance, avatar_url)
    VALUES (?, ?, ?, ?);
    """, users_data)

    # Seed Publishers
    publishers_data = [
        ('CD PROJEKT RED', 18.0),
        ('FromSoftware / Bandai Namco', 15.0),
        ('Rockstar Games', 20.0),
        ('Bethesda Softworks', 15.0),
        ('PlayStation Studios', 16.0),
        ('Capcom', 14.0),
        ('Game Science', 12.0),
        ('Larian Studios', 15.0),
        ('Xbox Game Studios', 14.0),
        ('Epic Games Publishing', 12.0),
        ('Warner Bros. Games', 15.0)
    ]
    cur.executemany("INSERT INTO publishers (name, royalty_percentage) VALUES (?, ?);", publishers_data)

    # Seed Games (16 total titles)
    games_data = [
        (
            1, 'Cyberpunk 2077', 'cyberpunk-2077',
            'Welcome to the dark future of Night City.',
            'Cyberpunk 2077 is an open-world, action-adventure RPG set in the megalopolis of Night City, where you play as a cyberpunk mercenary wrapped up in a do-or-die fight for survival.',
            'Action RPG, Sci-Fi', 'CD PROJEKT RED', 'Dec 10, 2020', 89,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1091500/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1091500/library_600x900.jpg',
            59.99
        ),
        (
            2, 'Elden Ring', 'elden-ring',
            'Rise, Tarnished, and become the Elden Lord.',
            'THE NEW FANTASY ACTION RPG. Rise, Tarnished, and be guided by grace to brandish the power of the Elden Ring and become an Elden Lord in the Lands Between.',
            'Action RPG, Dark Fantasy', 'FromSoftware', 'Feb 25, 2022', 96,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1245620/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1245620/library_600x900.jpg',
            59.99
        ),
        (
            3, 'Grand Theft Auto V', 'gta-v',
            'Welcome to Los Santos. Play the blockbuster legend.',
            'When a young street hustler, a retired bank robber and a terrifying psychopath find themselves entangled with some of the most frightening elements of the criminal underworld.',
            'Action-Adventure, Open World', 'Rockstar North', 'Apr 14, 2015', 97,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/271590/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/271590/library_600x900.jpg',
            29.99
        ),
        (
            4, 'God of War Ragnarök', 'god-of-war-ragnarok',
            'The Norse saga concludes in mythic battle.',
            'Kratos and Atreus embark on a mythic journey for answers and allies before Ragnarök arrives in this acclaimed sequel from Santa Monica Studio.',
            'Action-Adventure, Story-Rich', 'Santa Monica Studio', 'Sep 19, 2024', 94,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2322010/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2322010/library_600x900.jpg',
            59.99
        ),
        (
            5, 'Resident Evil 4', 'resident-evil-4',
            'Survival is only the beginning.',
            'Survival horror reimagined. Agent Leon S. Kennedy is dispatched on a mission to rescue the president\'s kidnapped daughter in a secluded European village.',
            'Survival Horror, Action', 'Capcom', 'Mar 24, 2023', 93,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2050650/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2050650/library_600x900.jpg',
            39.99
        ),
        (
            6, 'The Witcher 3: Wild Hunt', 'witcher-3-wild-hunt',
            'You are Geralt of Rivia, mercenary monster slayer.',
            'Venture through a war-torn world crawling with beasts. Your contract? Tracking down Ciri — the Child of Prophecy, a living weapon of doom.',
            'RPG, Open World', 'CD PROJEKT RED', 'May 18, 2015', 93,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/292030/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/292030/library_600x900.jpg',
            39.99
        ),
        (
            7, 'Black Myth: Wukong', 'black-myth-wukong',
            'Destiny calls the Monkey King.',
            'Black Myth: Wukong is an action RPG rooted in Chinese mythology. Set out as the Destined One to venture into the marvels and challenges ahead to uncover the obscured truth beneath a glorious legend.',
            'Action RPG, Souls-like', 'Game Science', 'Aug 20, 2024', 98,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2358720/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2358720/library_600x900.jpg',
            59.99
        ),
        (
            8, 'Red Dead Redemption 2', 'red-dead-redemption-2',
            'Outlaws for life in an unforgiving heartland.',
            'America, 1899. Arthur Morgan and the Van der Linde gang are outlaws on the run. With federal agents and bounty hunters massing, the gang must rob, steal and fight across the rugged heartland of America.',
            'Action-Adventure, Open World', 'Rockstar Studios', 'Nov 5, 2019', 97,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1174180/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1174180/library_600x900.jpg',
            59.99
        ),
        (
            9, 'Baldur\'s Gate 3', 'baldurs-gate-3',
            'Gather your party and return to the Forgotten Realms.',
            'Choose from 12 classes and 11 races from the D&D Player\'s Handbook and create your own identity, or play as an Origin hero with a hand-crafted background in a story of fellowship and betrayal.',
            'CRPG, Tactical', 'Larian Studios', 'Aug 3, 2023', 96,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1086940/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1086940/library_600x900.jpg',
            59.99
        ),
        (
            2, 'Sekiro: Shadows Die Twice', 'sekiro-shadows-die-twice',
            'Carve your own clever path to vengeance.',
            'In Sekiro: Shadows Die Twice you are the one-armed wolf, a disgraced and disfigured warrior rescued from the brink of death. Bound to protect a young lord, you become the target of vicious foes.',
            'Action, Souls-like', 'FromSoftware', 'Mar 22, 2019', 90,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/814380/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/814380/library_600x900.jpg',
            59.99
        ),
        (
            10, 'Alan Wake 2', 'alan-wake-2',
            'Monsters wear many faces in the Dark Place.',
            'Saga Anderson arrives to investigate ritualistic murders in a small town. Alan Wake pens a dark story to shape the reality around him. Two heroes, two realities, connected in ways they cannot understand.',
            'Survival Horror, Psychological', 'Remedy Entertainment', 'Oct 27, 2023', 89,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1087100/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1087100/library_600x900.jpg',
            49.99
        ),
        (
            9, 'Forza Horizon 5', 'forza-horizon-5',
            'Your ultimate Horizon adventure awaits in Mexico.',
            'Explore the vibrant and ever-evolving open world landscapes of Mexico with limitless, fun driving action in hundreds of the world’s greatest cars.',
            'Racing, Open World', 'Playground Games', 'Nov 9, 2021', 88,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1551360/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1551360/library_600x900.jpg',
            59.99
        ),
        (
            5, 'Ghost of Tsushima', 'ghost-of-tsushima',
            'Forge a new path and wage an unconventional war.',
            'In the late 13th century, the Mongol empire has laid waste to entire nations. Tsushima island is all that stands between mainland Japan and a massive Mongol invasion fleet.',
            'Action-Adventure, Open World', 'Sucker Punch Productions', 'May 16, 2024', 87,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2215430/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2215430/library_600x900.jpg',
            59.99
        ),
        (
            5, 'Marvel\'s Spider-Man Remastered', 'spiderman-remastered',
            'Be greater together across Marvel\'s New York.',
            'Developed by Insomniac Games, play as an experienced Peter Parker fighting big crime and iconic villains in Marvel’s New York.',
            'Action, Superhero', 'Insomniac Games', 'Aug 12, 2022', 87,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1817070/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1817070/library_600x900.jpg',
            59.99
        ),
        (
            11, 'Hogwarts Legacy', 'hogwarts-legacy',
            'Live the unwritten in the 1800s wizarding world.',
            'Experience Hogwarts in the 1800s. Your character is a student who holds the key to an ancient secret that threatens to tear the wizarding world apart.',
            'Action RPG, Open World', 'Avalanche Software', 'Feb 10, 2023', 85,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/990080/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/990080/library_600x900.jpg',
            59.99
        ),
        (
            5, 'Helldivers 2', 'helldivers-2',
            'Join the Helldivers and fight for Freedom across a hostile galaxy.',
            'The Galaxy’s Last Line of Offence. Enlist in the Helldivers and join the fight for freedom across a hostile galaxy in a fast, frantic, and ferocious third-person shooter.',
            'Co-op Shooter, Sci-Fi', 'Arrowhead Game Studios', 'Feb 8, 2024', 84,
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/553850/library_hero.jpg',
            'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/553850/library_600x900.jpg',
            39.99
        )
    ]

    cur.executemany("""
    INSERT INTO games (publisher_id, title, slug, tagline, description, genre, developer, release_date, metascore, header_image, cover_image, base_price)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, games_data)

    # Seed DLCs for games
    dlcs_data = [
        # Cyberpunk (1)
        (1, 'Phantom Liberty Expansion', 'Story Expansion', 29.99, 'Explore the lawless district of Dogtown with Idris Elba as secret agent Solomon Reed.'),
        (1, 'Night City Official Soundtrack', 'Soundtrack', 9.99, '28 official original score tracks in high-fidelity lossless audio.'),
        (1, 'Cyberpunk 2020 Digital Sourcebook', 'Item Pack', 14.99, 'Original tabletop RPG rulebook, lore compendium, and concept artwork.'),

        # Elden Ring (2)
        (2, 'Shadow of the Erdtree Expansion', 'Story Expansion', 39.99, 'Journey to the Realm of Shadow guided by Empyrean Miquella with brand new bosses.'),
        (2, 'Official Soundtrack & Digital Artbook', 'Soundtrack', 14.99, 'Full orchestral soundtrack and 120-page high-resolution digital artbook.'),

        # GTA V (3)
        (3, 'Criminal Enterprise Starter Pack', 'Item Pack', 19.99, 'High-end properties, vehicles, weaponry, and $1,000,000 bonus GTA Online cash.'),
        (3, 'Megalodon Shark Cash Card', 'Item Pack', 24.99, 'Instant $8,000,000 in-game currency deposit for GTA Online.'),

        # God of War (4)
        (4, 'Valhalla Expansion Pack', 'Story Expansion', 19.99, 'Roguelite-inspired epilogue journey into Kratos\' past and deepest memories.'),
        (4, 'Darkdale Armor & Weapon Cosmetics', 'Item Pack', 9.99, 'Exclusive Darkdale armor, axe grip, blades handles, and runic attachments.'),

        # Resident Evil 4 (5)
        (5, 'Separate Ways (Ada Wong Story)', 'Story Expansion', 9.99, 'Full standalone story campaign from Ada Wong\'s perspective revealing hidden missions.'),
        (5, 'Extra DLC Pack (Costumes & Guns)', 'Item Pack', 14.99, 'Romantic and Casual costume sets, Sentinel Nine & Skull Shaker special weapons.'),

        # Witcher 3 (6)
        (6, 'Hearts of Stone Expansion', 'Story Expansion', 9.99, '10-hour adventure investigating the immortal bandit captain Olgierd von Everec.'),
        (6, 'Blood and Wine Expansion', 'Story Expansion', 19.99, 'Over 30 hours of story in the idyllic, vampire-infested duchy of Toussaint.'),

        # Black Myth: Wukong (7)
        (7, 'Deluxe Upgrade Edition Pack', 'Item Pack', 9.99, 'Bronzecloud Staff, Folk Opera Armor Set, and Selected Digital Soundtrack.'),

        # Red Dead Redemption 2 (8)
        (8, 'Special Edition Story Content', 'Item Pack', 19.99, 'Bank Robbery Mission, Dappled Black Thoroughbred, and Talisman gameplay bonuses.'),

        # Baldur\'s Gate 3 (9)
        (9, 'Digital Deluxe Upgrade', 'Item Pack', 9.99, 'Bard Song Pack, Exclusive Dice Theme, Paintings from Rivellon, and Adventurer\'s Pouch.')
    ]

    cur.executemany("""
    INSERT INTO game_dlcs (game_id, title, dlc_type, price, description)
    VALUES (?, ?, ?, ?, ?);
    """, dlcs_data)

    # Seed Keys for Games: format e.g. cbp-ba-389
    GAME_CODES = {
        1: 'cbp', 2: 'elr', 3: 'gta', 4: 'gow', 5: 're4', 6: 'wt3',
        7: 'bmw', 8: 'rdr', 9: 'bg3', 10: 'sek', 11: 'awk', 12: 'fzh',
        13: 'got', 14: 'spm', 15: 'hwl', 16: 'hd2'
    }
    random.seed(42)

    key_records = []
    used_codes = set()
    for g_id, g_code in GAME_CODES.items():
        # Black Myth: Wukong (game_id=7) has EXACTLY 1 KEY!
        # Every other game has strictly LESS THAN 5 keys (3 keys):
        if g_id == 7:
            num_keys = 1
        else:
            num_keys = 3
        for _ in range(num_keys):
            while True:
                rnd = random.randint(100, 999)
                code = f"{g_code}-ba-{rnd}"
                if code not in used_codes:
                    used_codes.add(code)
                    break
            key_records.append((g_id, code, 'AVAILABLE'))

    cur.executemany("""
    INSERT INTO license_keys (game_id, license_code, status)
    VALUES (?, ?, ?);
    """, key_records)

    # Clean Website State:
    # All users start fresh with pristine wallets and zero pre-assigned games/DLCs.
    # No pre-existing P2P listings or DRM leases.
    conn.commit()
    conn.close()

if __name__ == "__main__":
    reset_and_seed()
    print("GameVault schema streamlined: Games + DLCs initialized and seeded successfully.")
