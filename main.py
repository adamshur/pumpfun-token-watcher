import asyncio
import aiosqlite
import websockets
import json
import time
from dataclasses import dataclass
import math
import os

# =====================
# Configuration
# =====================
@dataclass
class Config:
    # WebSocket
    WS_URI: str = "wss://pumpportal.fun/api/data"
    INITIAL_RECONNECT_DELAY: float = 1.0
    MAX_RECONNECT_DELAY: float = 60.0
    
    # Database
    DB_PATH: str = "token_data.db"
    WRITE_BATCH_SIZE: int = 50
    
    # For stats printing
    STATS_PRINT_INTERVAL: int = 10   # seconds

# =====================
# Color & Formatting Helpers
# =====================
def color_text(text, color_code):
    """
    color_code examples: '31' = red, '32' = green, '33' = yellow,
    '34' = blue, '35' = magenta, '36' = cyan, '37' = white, etc.
    """
    return f"\033[{color_code}m{text}\033[0m"

# =====================
# Database Setup
# =====================
async def initialize_database():
    async with aiosqlite.connect(Config.DB_PATH) as db:
        # Enable WAL and normal sync settings for better concurrency & performance
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA synchronous = NORMAL")
        # Enable foreign key enforcement
        await db.execute("PRAGMA foreign_keys = ON")

        # ------------------------
        # Tokens Table
        # ------------------------
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                mint TEXT PRIMARY KEY,
                timestamp INTEGER,
                initial_sol_liquidity REAL,
                name TEXT,
                symbol TEXT
            )
        ''')

        # ------------------------
        # Raw Transactions (with foreign key)
        # ------------------------
        await db.execute('''
            CREATE TABLE IF NOT EXISTS raw_txs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mint TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                traderPublicKey TEXT,
                tx_type TEXT,
                token_amount REAL,
                sol_amount REAL,
                new_token_balance REAL,
                bondingCurveKey TEXT,
                vTokensInBondingCurve REAL,
                vSolInBondingCurve REAL,
                marketCapSol REAL,
                FOREIGN KEY(mint) REFERENCES tokens(mint)
            )
        ''')

        # ------------------------
        # Indexes
        # ------------------------
        await db.execute('''CREATE INDEX IF NOT EXISTS idx_raw_txs_mint
                          ON raw_txs(mint)''')
        
        await db.commit()

# =====================
# WebSocket Manager
# =====================
class WebSocketManager:
    def __init__(self):
        self.conn = None
        self.active_tokens = set()
        self.reconnect_attempts = 0
        self.pending_subscriptions = asyncio.Queue()

    async def connect(self):
        """Attempt to connect with exponential backoff."""
        delay = Config.INITIAL_RECONNECT_DELAY
        while True:
            try:
                self.conn = await websockets.connect(Config.WS_URI)
                print("WebSocket connected.")
                self.reconnect_attempts = 0
                # Once connected, send initial subscriptions
                await self.initial_subscriptions()
                # Start queue-based subscription handler
                asyncio.create_task(self.subscription_handler())
                return
            except Exception as e:
                print(f"Connection failed: {e}, retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
                self.reconnect_attempts += 1
                delay = min(
                    Config.MAX_RECONNECT_DELAY, 
                    Config.INITIAL_RECONNECT_DELAY * math.exp(self.reconnect_attempts)
                )

    async def subscription_handler(self):
        """Process pending subscriptions in a queue to avoid flooding the WS."""
        while True:
            try:
                while not self.pending_subscriptions.empty():
                    mint = await self.pending_subscriptions.get()
                    if mint not in self.active_tokens:
                        await self.conn.send(json.dumps({
                            "method": "subscribeTokenTrade",
                            "keys": [mint]
                        }))
                        self.active_tokens.add(mint)
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Subscription handler error: {e}")
                await asyncio.sleep(1)

    async def initial_subscriptions(self):
        """
        1) Always subscribe to the 'new token' stream.
        2) Re-subscribe to all tokens found in the `tokens` table.
        """
        # Always subscribe to new token creation events
        await self.conn.send(json.dumps({"method": "subscribeNewToken"}))
        
        # Restore subscriptions for all tokens in the DB
        async with aiosqlite.connect(Config.DB_PATH) as db:
            cursor = await db.execute('SELECT mint FROM tokens')
            all_mints = [row[0] async for row in cursor]
        
        for mint in all_mints:
            await self.subscribe_token(mint)

    async def subscribe_token(self, mint):
        """Queue a token for subscription."""
        await self.pending_subscriptions.put(mint)

# =====================
# Periodic Stats Printer (Optional)
# =====================
async def stats_printer(ws_manager, stats):
    """Periodically print basic statistics about the process."""
    while True:
        await asyncio.sleep(Config.STATS_PRINT_INTERVAL)
        try:
            # Get DB file size
            db_size_bytes = os.path.getsize(Config.DB_PATH)
            db_size_mb = db_size_bytes / (1024 * 1024)

            # Prepare stats
            token_count = len(ws_manager.active_tokens)
            processed_txs = stats['processed_txs']
            token_creations = stats['token_creations']

            print("\n" + "=" * 60)
            print(color_text("[ STATS ]", "36"), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
            print(color_text("Subscribed Tokens:", "34"), f"{token_count:>5}")
            print(color_text("Processed Txs:", "32"), f"{processed_txs:>5}")
            print(color_text("Token Creations:", "35"), f"{token_creations:>5}")
            print(color_text("DB File Size:", "36") + f" {db_size_mb:.2f} MB")
            print("=" * 60 + "\n")
        except Exception as e:
            print(f"Stats printer error: {e}")

# =====================
# Main Application
# =====================
async def main():
    """Main asynchronous entrypoint."""
    await initialize_database()
    
    ws_manager = WebSocketManager()
    await ws_manager.connect()
    
    # Keep track of stats in a simple dictionary
    stats = {
        "processed_txs": 0,    # Number of buy/sell transactions processed
        "token_creations": 0,  # Number of newly created tokens seen
    }
    
    # Start background task for stats printing (optional)
    asyncio.create_task(stats_printer(ws_manager, stats))
    
    try:
        while True:
            try:
                message = await ws_manager.conn.recv()
                receive_time = int(time.time())
                data = json.loads(message)
                data['timestamp'] = receive_time

                # Basic validation: we only need 'mint' and 'txType'
                if not all(k in data for k in ['mint', 'txType']):
                    continue

                # Extract fields that might be missing or set defaults
                signature = data.get('signature', None)
                trader_pubkey = data.get('traderPublicKey', None)
                tx_type = data['txType']
                token_amount = float(data.get('tokenAmount', 0) or 0)
                sol_amount = float(data.get('solAmount', 0) or 0)
                new_token_balance = float(data.get('newTokenBalance', 0) or 0)
                bonding_curve_key = data.get('bondingCurveKey', None)
                v_tokens_bc = float(data.get('vTokensInBondingCurve', 0) or 0)
                v_sol_bc = float(data.get('vSolInBondingCurve', 0) or 0)
                market_cap_sol = float(data.get('marketCapSol', 0) or 0)
                pool = data.get('pool', None)

                async with aiosqlite.connect(Config.DB_PATH) as db:
                    
                    # Token creation event
                    if tx_type == 'create':
                        # store name, symbol, and uri in the tokens table
                        name = data.get('name', '')
                        symbol = data.get('symbol', '')
                        uri = data.get('uri', '')

                        await db.execute('''
                            INSERT OR IGNORE INTO tokens
                            (mint, timestamp, initial_sol_liquidity, name, symbol)
                            VALUES
                            (:mint, :timestamp, :initialBuy, :name, :symbol)
                        ''', {
                            'mint': data['mint'],
                            'timestamp': data['timestamp'],
                            'initialBuy': data.get('initialBuy', 0),
                            'name': name,
                            'symbol': symbol
                        })
                        await db.commit()

                        # Subscribe to this newly created token
                        await ws_manager.subscribe_token(data['mint'])
                        stats["token_creations"] += 1
                    
                    # Buys or sells (and possibly other txTypes if you like)
                    if tx_type in ('create', 'buy', 'sell'):
                        # Even for 'create' we might store a record in raw_txs
                        # to preserve the signature or other data
                        await db.execute('''
                            INSERT INTO raw_txs
                            (mint, timestamp, traderPublicKey, tx_type,
                             token_amount, sol_amount, new_token_balance, bondingCurveKey,
                             vTokensInBondingCurve, vSolInBondingCurve, marketCapSol)
                            VALUES
                            (:mint, :timestamp, :traderPublicKey, :tx_type,
                             :token_amount, :sol_amount, :new_token_balance, :bondingCurveKey,
                             :vTokensInBondingCurve, :vSolInBondingCurve, :marketCapSol)
                        ''', {
                            'mint': data['mint'],
                            'timestamp': data['timestamp'],
                            'traderPublicKey': trader_pubkey,
                            'tx_type': tx_type,
                            'token_amount': token_amount,
                            'sol_amount': sol_amount,
                            'new_token_balance': new_token_balance,
                            'bondingCurveKey': bonding_curve_key,
                            'vTokensInBondingCurve': v_tokens_bc,
                            'vSolInBondingCurve': v_sol_bc,
                            'marketCapSol': market_cap_sol,
                        })
                        await db.commit()
                        
                        if tx_type in ('buy', 'sell'):
                            stats["processed_txs"] += 1

            except websockets.ConnectionClosed:
                print("Connection lost, reconnecting...")
                await ws_manager.connect()
            except json.JSONDecodeError:
                print("Invalid JSON message received.")
            except Exception as e:
                print(f"Processing error: {e}")

    except KeyboardInterrupt:
        print("\n" + color_text("Shutting down gracefully...", "31"))
        if ws_manager.conn:
            await ws_manager.conn.close()

if __name__ == "__main__":
    asyncio.run(main())
