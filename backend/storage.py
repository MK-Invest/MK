import duckdb
import os

DB_PATH = "data.duckdb"
con = duckdb.connect(DB_PATH)

# =========================================================
# INIT DB
# =========================================================

def init_db():
    con.execute("""
    CREATE TABLE IF NOT EXISTS fundamentals (
        ticker VARCHAR,
        price DOUBLE,
        revenue DOUBLE,
        net_debt DOUBLE,
        shares DOUBLE,
        ebitda DOUBLE,
        updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

# =========================================================
# SAVE SNAPSHOT
# =========================================================

def save_snapshot(data: dict):
    con.execute("""
        INSERT INTO fundamentals (
            ticker,
            price,
            revenue,
            net_debt,
            shares,
            ebitda
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, [
        data.get("ticker"),
        data.get("price"),
        data.get("revenue"),
        data.get("net_debt"),
        data.get("shares"),
        data.get("ebitda"),
    ])

# =========================================================
# LOAD LATEST
# =========================================================

def load_latest(ticker: str):
    return con.execute("""
        SELECT *
        FROM fundamentals
        WHERE ticker = ?
        ORDER BY updated DESC
        LIMIT 1
    """, [ticker]).fetchdf()

# =========================================================
# BOOTSTRAP
# =========================================================

init_db()
