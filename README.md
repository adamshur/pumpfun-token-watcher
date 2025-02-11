# Pump.fun Token Watcher

A Python-based monitoring system for tracking cryptocurrency token transactions and liquidity events in real-time via WebSocket connection to [PumpPortal](https://pumpportal.fun/), which transmits data from [pump.fun](https://pump.fun/), your favorite Solana memecoin launching platform.

## Features
- Real-time monitoring of token creation, as well as transactions related to those tokens
- Intended simply to gather data of the full lifecycle of newly created tokens to facilitate subsequent data processing-- good luck finding winners!
- SQLite database storage for historical data
- Automatic WebSocket reconnection with exponential backoff
- Periodic statistics reporting
- Efficient batched database writes
- If program is stopped then resumed, it will re-subscribe to any tokens that were previously saved (although any transactions that occured during the gap will be missed)

## Note 
I personally was able to run the program for a week straight with no issues, during which I subscribed to ~100,000 tokens and stored over 4 million transactions, totalling about 3.5gb for the SQLite database. See PumpPortal's [Telegram group](https://t.me/PumpPortalAPI) for any questions. Per the group's admin, there is no limit to the number of subscriptions. Thanks to PumpPortal for the free API. Please use only one WebSocket connection for all subscriptions.

## Requirements
- Python 3.9+

## Installation
```bash
git clone https://github.com/yourusername/pump_fun_watcher.git
cd pump_fun_watcher
pip install -r requirements.txt
```

## Configuration
Edit the `Config` class in `main.py` to customize:
```python
class Config:
    WS_URI = "wss://pumpportal.fun/api/data"  # WebSocket endpoint
    DB_PATH = "token_data.db"                 # Database file path
    WRITE_BATCH_SIZE = 50                     # Batch size for DB writes
    STATS_PRINT_INTERVAL = 10                 # Stats display interval (seconds)
```

## Database Schema
### Tokens Table
| Column               | Type    | Description                     |
|----------------------|---------|---------------------------------|
| mint (PK)            | TEXT    | Token contract address          |
| timestamp            | INTEGER | Creation timestamp              |
| initial_sol_liquidity| REAL    | Initial SOL liquidity            |
| name                 | TEXT    | Token name                       |
| symbol               | TEXT    | Token symbol                     |

### Raw Transactions Table
| Column                   | Type    | Description                     |
|--------------------------|---------|---------------------------------|
| mint                     | TEXT    | Token contract address          |
| timestamp                | INTEGER | Transaction timestamp           |
| tx_type                  | TEXT    | Transaction type (create/buy/sell)|
| token_amount             | REAL    | Token amount transferred        |
| sol_amount               | REAL    | SOL amount transferred          |
| marketCapSol             | REAL    | Calculated market cap in SOL     |

## Usage
```bash
python main.py
```

Sample output:
```
[STATS] 2025-02-07 23:55:00
Subscribed Tokens:   142
Processed Txs:     8923
Token Creations:    42
DB File Size: 12.45 MB
```

## License
MIT
