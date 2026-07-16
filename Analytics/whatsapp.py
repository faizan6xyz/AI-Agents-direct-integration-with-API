import sys
import json
import argparse
from pathlib import Path
import pandas as pd
COLUMN_MAP = {
    "contact_id": "contact_id",   # e.g. phone number or customer id
    "direction": "direction",     # "sent" / "received"
    "timestamp": "timestamp",
    "converted": "converted",     # optional, may not exist in your data
}

def load_data(path: str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Could not find file: {path}")
    if path.suffix.lower() == ".json":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        df = pd.json_normalize(raw)
    else:
        df = pd.read_csv(path)
    # Rename to standard internal names where present
    rename_map = {v: k for k, v in COLUMN_MAP.items() if v in df.columns}
    df = df.rename(columns=rename_map)
    required = {"contact_id", "direction", "timestamp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Input file is missing required columns: {missing}. "
            f"Update COLUMN_MAP at the top of the script to match your data."
        )
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["direction"] = df["direction"].str.strip().str.lower()
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    return df

def compute_engagement(df: pd.DataFrame) -> dict:
    total_sent = (df["direction"] == "sent").sum()
    total_received = (df["direction"] == "received").sum()
    contacts_messaged = df.loc[df["direction"] == "sent", "contact_id"].unique()
    contacts_who_replied = df.loc[df["direction"] == "received", "contact_id"].unique()
    replied_set = set(contacts_who_replied) & set(contacts_messaged)
    reply_rate = (len(replied_set) / len(contacts_messaged) * 100) if len(contacts_messaged) else 0
    if "converted" in df.columns:
        # Use real business-defined conversions if the column exists
        converted_contacts = df.loc[df["converted"].astype(bool), "contact_id"].unique()
        converted_contacts = set(converted_contacts) & set(contacts_messaged)
        conversion_source = "explicit 'converted' column"
    else:
        # Fallback proxy: replying counts as a "conversion" (engaged lead)
        converted_contacts = replied_set
        conversion_source = "proxy: contact replied at least once"
    conversion_rate = (
        len(converted_contacts) / len(contacts_messaged) * 100 if len(contacts_messaged) else 0
    )
    # Per-contact breakdown
    per_contact = (
        df.groupby("contact_id")["direction"]
        .value_counts()
        .unstack(fill_value=0)
        .reindex(columns=["sent", "received"], fill_value=0)
    )
    per_contact["replied"] = per_contact["received"] > 0
    per_contact["converted"] = per_contact.index.isin(converted_contacts)
    return {
        "total_messages": len(df),
        "total_sent": int(total_sent),
        "total_received": int(total_received),
        "unique_contacts_messaged": len(contacts_messaged),
        "unique_contacts_replied": len(replied_set),
        "reply_rate_pct": round(reply_rate, 2),
        "conversion_rate_pct": round(conversion_rate, 2),
        "conversion_definition": conversion_source,
        "per_contact_breakdown": per_contact,
    }
    
def print_report(results: dict):
    print("\n===== WhatsApp Engagement Report =====")
    print(f"Total messages         : {results['total_messages']}")
    print(f"  - Sent (you -> them) : {results['total_sent']}")
    print(f"  - Received (them ->) : {results['total_received']}")
    print(f"Unique contacts messaged : {results['unique_contacts_messaged']}")
    print(f"Unique contacts replied  : {results['unique_contacts_replied']}")
    print(f"Reply rate               : {results['reply_rate_pct']}%")
    print(f"Conversion rate          : {results['conversion_rate_pct']}%")
    print(f"  (definition used: {results['conversion_definition']})")
    print("\n--- Per-contact breakdown (first 10 rows) ---")
    print(results["per_contact_breakdown"].head(10).to_string())
    print("=======================================\n")

def main():
    parser = argparse.ArgumentParser(description="WhatsApp engagement & conversion analysis")
    parser.add_argument("input_file", help="Path to CSV or JSON message log")
    parser.add_argument(
        "--export-csv",
        help="Optional path to save the per-contact breakdown as CSV",
        default=None,
    )
    args = parser.parse_args()
    df = load_data(args.input_file)
    results = compute_engagement(df)
    print_report(results)
    if args.export_csv:
        results["per_contact_breakdown"].to_csv(args.export_csv)
        print(f"Per-contact breakdown saved to: {args.export_csv}")

if __name__ == "__main__":
    main()