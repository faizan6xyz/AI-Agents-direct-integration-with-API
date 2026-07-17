import re
import argparse
from pathlib import Path
import pandas as pd
CONVERSION_KEYWORDS = ["order", "buy", "purchase", "confirm", "book", "yes i want"]
UNSUPPORTED_TYPE_RE = re.compile(r"^\[Unsupported message type:\s*(\w+)\]$")

def load_data(path: str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Could not find file: {path}")
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        df = pd.read_excel(path, sheet_name="Messages")
    else:
        df = pd.read_csv(path)
    required = {"Timestamp", "Sender Number", "Message"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input file is missing expected columns: {missing}. "
            f"This script expects the exact headers written by "
            f"whatsapp_message_logger.py.")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"]).sort_values("Timestamp")
    df["Sender Number"] = df["Sender Number"].astype(str)
    df["Message"] = df["Message"].fillna("").astype(str)
    return df

def classify_message_type(message: str) -> str:
    m = UNSUPPORTED_TYPE_RE.match(message.strip())
    return m.group(1) if m else "text"

def compute_metrics(df: pd.DataFrame, keywords: list) -> dict:
    df = df.copy()
    df["msg_type"] = df["Message"].apply(classify_message_type)
    df["date"] = df["Timestamp"].dt.date
    df["hour"] = df["Timestamp"].dt.hour
    total_messages = len(df)
    unique_senders = df["Sender Number"].nunique()
    per_sender = df.groupby("Sender Number").agg(
        message_count=("Message", "count"),
        first_message=("Timestamp", "min"),
        last_message=("Timestamp", "max"),)
    per_sender["is_repeat"] = per_sender["message_count"] > 1
    repeat_senders = int(per_sender["is_repeat"].sum())
    repeat_rate = (repeat_senders / unique_senders * 100) if unique_senders else 0
    keyword_pattern = "|".join(re.escape(k) for k in keywords) if keywords else None
    if keyword_pattern:
        df["matched_keyword"] = df["Message"].str.contains(keyword_pattern, case=False, na=False, regex=True)
        converted_senders = set(df.loc[df["matched_keyword"], "Sender Number"].unique())
    else:
        converted_senders = set()
    per_sender["converted"] = per_sender.index.isin(converted_senders)
    conversion_rate = (len(converted_senders) / unique_senders * 100 if unique_senders else 0)
    daily_volume = df.groupby("date").size()
    hourly_distribution = df.groupby("hour").size().reindex(range(24), fill_value=0)
    type_breakdown = df["msg_type"].value_counts()
    return {"total_messages": total_messages,
        "unique_senders": unique_senders,
        "repeat_senders": repeat_senders,
        "repeat_rate_pct": round(repeat_rate, 2),
        "conversion_rate_pct": round(conversion_rate, 2),
        "converted_senders": len(converted_senders),
        "keywords_used": keywords,
        "daily_volume": daily_volume,
        "hourly_distribution": hourly_distribution,
        "type_breakdown": type_breakdown,
        "per_sender": per_sender.sort_values("message_count", ascending=False),}


def print_report(results: dict):
    print("\n===== WhatsApp Logger Engagement Report =====")
    print(f"Total incoming messages   : {results['total_messages']}")
    print(f"Unique senders            : {results['unique_senders']}")
    print(f"Repeat senders (>1 msg)   : {results['repeat_senders']}")
    print(f"Repeat rate               : {results['repeat_rate_pct']}%")
    print(f"Conversion keywords used  : {', '.join(results['keywords_used']) or '(none)'}")
    print(f"Senders matching keywords : {results['converted_senders']}")
    print(f"Conversion rate           : {results['conversion_rate_pct']}%")
    print("\n--- Message type breakdown ---")
    print(results["type_breakdown"].to_string())
    print("\n--- Daily volume (last 10 days) ---")
    print(results["daily_volume"].tail(10).to_string())
    print("\n--- Hourly distribution (0-23h) ---")
    print(results["hourly_distribution"].to_string())
    print("\n--- Top 10 most active senders ---")
    print(results["per_sender"].head(10).to_string())

def main():
    parser = argparse.ArgumentParser(description="WhatsApp message logger engagement analysis")
    parser.add_argument("input_file", help="Path to whatsapp_messages.csv or .xlsx")
    parser.add_argument("--keywords",
        help="Comma-separated conversion keywords (overrides the built-in list)",
        default=None,)
    parser.add_argument("--export-csv",
        help="Optional path to save the per-sender breakdown as CSV",
        default=None,)
    args = parser.parse_args()
    keywords = ([k.strip() for k in args.keywords.split(",") if k.strip()]
        if args.keywords
        else CONVERSION_KEYWORDS)
    df = load_data(args.input_file)
    results = compute_metrics(df, keywords)
    print_report(results)
    if args.export_csv:
        results["per_sender"].to_csv(args.export_csv)
        print(f"Per-sender breakdown saved to: {args.export_csv}")

if __name__ == "__main__":
    main()