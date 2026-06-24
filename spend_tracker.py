"""
Personal Spend Tracker - Single File Version
----------------------------------------------
Parses bank SMS messages, categorizes spending, detects recurring
charges/subscriptions, and shows it all on a dashboard.

SETUP:
    pip install streamlit pandas

RUN:
    streamlit run spend_tracker.py

Then open the link shown in your terminal (usually http://localhost:8501)
"""

import re
import sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import streamlit as st
import pandas as pd

DB_PATH = Path(__file__).parent / "transactions.db"

CATEGORY_KEYWORDS = {
    "subscription": [
        "netflix", "spotify", "amazon prime", "prime video", "hotstar",
        "youtube premium", "apple", "google one", "gym", "cult.fit",
        "audible", "icloud", "adobe", "chatgpt", "openai", "claude",
    ],
    "food": [
        "swiggy", "zomato", "dominos", "mcdonald", "kfc", "starbucks",
        "cafe", "restaurant", "blinkit", "zepto",
    ],
    "shopping": [
        "amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa",
    ],
    "travel": [
        "uber", "ola", "irctc", "indigo", "makemytrip", "redbus", "rapido",
    ],
    "bills_utilities": [
        "electricity", "airtel", "jio", "vi ", "vodafone", "broadband",
        "wifi", "recharge", "dth",
    ],
    "transfer": [
        "upi", "neft", "imps", "transfer",
    ],
}


# ---------------------------------------------------------
# PARSER: raw SMS text -> structured transaction dict
# ---------------------------------------------------------
def parse_transaction(sms_text: str):
    text = sms_text.strip()

    amount_match = re.search(r'(?:Rs\.?|INR)\s?([\d,]+\.?\d*)', text, re.IGNORECASE)
    if not amount_match:
        return None

    amount = float(amount_match.group(1).replace(',', ''))

    if re.search(r'debit|spent|paid|purchase', text, re.IGNORECASE):
        txn_type = "debit"
    elif re.search(r'credit|received|refund', text, re.IGNORECASE):
        txn_type = "credit"
    else:
        txn_type = "unknown"

    merchant_match = re.search(r'(?:to|at|for|from)\s+([A-Z][A-Za-z0-9&.\-\* ]{2,30})', text)
    merchant = merchant_match.group(1).strip() if merchant_match else "UNKNOWN"
    merchant = re.split(r'\.|\bavl\b|\bbal\b|\bon\s+\d', merchant, flags=re.IGNORECASE)[0].strip()

    date_match = re.search(r'(\d{1,2}[-/](?:\d{1,2}|[A-Za-z]{3})[-/]\d{2,4})', text)
    date_str = date_match.group(1) if date_match else datetime.today().strftime('%d-%m-%y')

    return {
        "amount": amount, "type": txn_type, "merchant": merchant,
        "date": date_str, "raw_text": text,
    }


# ---------------------------------------------------------
# CATEGORIZER: merchant name -> spending category
# ---------------------------------------------------------
def categorize(merchant: str) -> str:
    merchant_lower = merchant.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in merchant_lower for keyword in keywords):
            return category
    return "other"


def add_category(transaction: dict) -> dict:
    transaction["category"] = categorize(transaction.get("merchant", ""))
    return transaction


# ---------------------------------------------------------
# RECURRING DETECTOR: spot subscriptions & price hikes
# ---------------------------------------------------------
def _parse_date(date_str: str) -> datetime:
    for fmt in ["%d-%m-%y", "%d-%m-%Y", "%d/%m/%y", "%d/%m/%Y", "%d-%b-%y", "%d-%b-%Y"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime.today()


def find_recurring_charges(transactions: list, min_occurrences: int = 2) -> list:
    grouped = defaultdict(list)
    for txn in transactions:
        if txn.get("type") != "debit":
            continue
        grouped[txn["merchant"]].append(txn)

    recurring = []
    for merchant, txns in grouped.items():
        if len(txns) < min_occurrences:
            continue
        txns_sorted = sorted(txns, key=lambda t: _parse_date(t["date"]))
        amounts = [t["amount"] for t in txns_sorted]
        first_amount, latest_amount = amounts[0], amounts[-1]
        price_increased = latest_amount > first_amount

        recurring.append({
            "merchant": merchant, "occurrences": len(txns_sorted), "amounts": amounts,
            "first_amount": first_amount, "latest_amount": latest_amount,
            "price_increased": price_increased,
            "increase_amount": round(latest_amount - first_amount, 2) if price_increased else 0.0,
        })

    recurring.sort(key=lambda r: r["latest_amount"], reverse=True)
    return recurring


# ---------------------------------------------------------
# STORAGE: SQLite database (single file, no server needed)
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL, type TEXT, merchant TEXT,
            category TEXT, date TEXT, raw_text TEXT,
            UNIQUE(amount, merchant, date, raw_text)
        )
    """)
    conn.commit()
    conn.close()


def save_transaction(txn: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR IGNORE INTO transactions (amount, type, merchant, category, date, raw_text)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (txn.get("amount"), txn.get("type"), txn.get("merchant"),
          txn.get("category", "other"), txn.get("date"), txn.get("raw_text", "")))
    conn.commit()
    conn.close()


def get_all_transactions() -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM transactions ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ---------------------------------------------------------
# DASHBOARD: Streamlit UI
# ---------------------------------------------------------
init_db()

st.set_page_config(page_title="Spend Tracker", page_icon="💰", layout="wide")
st.title("💰 Personal Spend Tracker")
st.caption("Paste your bank SMS messages below to track spending and catch sneaky recurring charges.")

st.subheader("Add new transactions")
sms_input = st.text_area(
    "Paste one or more bank SMS messages (one per line):",
    height=150,
    placeholder="Rs.499.00 debited from a/c XX1234 on 05-06-26 to NETFLIX. Avl bal Rs.12,450.00",
)

if st.button("Parse & Save"):
    lines = [line.strip() for line in sms_input.split("\n") if line.strip()]
    saved_count = 0
    for line in lines:
        parsed = parse_transaction(line)
        if parsed is None:
            continue
        parsed = add_category(parsed)
        save_transaction(parsed)
        saved_count += 1

    if saved_count > 0:
        st.success(f"Saved {saved_count} transaction(s)!")
    else:
        st.warning("No valid transactions found in that text.")

st.divider()

all_transactions = get_all_transactions()

if not all_transactions:
    st.info("No transactions saved yet. Add some above to see your dashboard!")
else:
    df = pd.DataFrame(all_transactions)

    st.subheader("Spending by category")
    debit_df = df[df["type"] == "debit"]

    if not debit_df.empty:
        category_totals = debit_df.groupby("category")["amount"].sum().sort_values(ascending=False)
        col1, col2 = st.columns([1, 1])
        with col1:
            st.bar_chart(category_totals)
        with col2:
            st.dataframe(category_totals.reset_index().rename(columns={"amount": "Total Spent (Rs.)"}))
    else:
        st.info("No debit transactions yet.")

    st.divider()

    st.subheader("🔁 Recurring charges & subscriptions")
    recurring = find_recurring_charges(all_transactions, min_occurrences=2)

    if recurring:
        for item in recurring:
            warning = " ⚠️ Price increased!" if item["price_increased"] else ""
            st.write(
                f"**{item['merchant']}** — seen {item['occurrences']}x, "
                f"latest: Rs.{item['latest_amount']:.2f}{warning}"
            )
    else:
        st.info("No recurring charges detected yet — add more transactions across different dates.")

    st.divider()

    st.subheader("All transactions")
    st.dataframe(df[["date", "merchant", "category", "amount", "type"]])
