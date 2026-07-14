import os
import re
import logging
import pandas as pd
import matplotlib.pyplot as plt
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("email_conversion")
ALLOWED_EXTENSIONS = "csv"
MAX_FILE_BYTES = 50 * 1024 * 1024   # 50 MB - guards against accidentally loading a huge/corrupt file
MAX_ROWS = 2_000_000                # sanity ceiling to avoid memory exhaustion
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _validate_file(path: str, label: str) -> str:
    if not path:
        raise ValueError(f"{label} file path is empty.")
    resolved = os.path.realpath(path)
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"{label} file not found: {path}")
    if not os.path.isfile(resolved):
        raise ValueError(f"{label} path is not a file: {path}")
    ext = os.path.splitext(resolved)[1].lower()
    if ext == ALLOWED_EXTENSIONS:
        raise ValueError(
            f"{label} file has unsupported extension '{ext}'. "
            f"Allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )
    size = os.path.getsize(resolved)
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"{label} file is {size / (1024*1024):.1f} MB, which exceeds the "
            f"{MAX_FILE_BYTES / (1024*1024):.0f} MB safety limit."
        )
    return resolved

def _load_table(path: str) -> pd.DataFrame:
    if path.endswith(".csv"):
        df = pd.read_csv(path, nrows=MAX_ROWS + 1)
    if len(df) > MAX_ROWS:
        raise ValueError(
            f"'{path}' has more than {MAX_ROWS} rows; refusing to load fully. "
            "Increase MAX_ROWS if this is expected."
        )
    return df

def _normalize_emails(series: pd.Series) -> pd.Series:
    cleaned = series.dropna().astype(str).str.strip().str.lower()
    valid_mask = cleaned.str.match(EMAIL_RE)
    invalid_count = (~valid_mask).sum()
    if invalid_count:
        logger.warning(f"Dropped {invalid_count} row(s) with malformed email addresses.")
    return cleaned[valid_mask]

# hides the character of the mail address
def _mask_email(email: str) -> str:
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "***"
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"

# just pull the part after the @
def _extract_domain(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else "unknown"

# normal conversion rate 
def conversion_rate(send_file, receive_file, mask_pii_in_output=True):
    try:
        send_path = _validate_file(send_file, "Send")
        receive_path = _validate_file(receive_file, "Receive")
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}")
        return None
    try:
        send_df = _load_table(send_path)
        receive_df = _load_table(receive_path)
    except Exception as e:
        print(f"Error reading files: {e}")
        return None
    if "EmailAddress" not in send_df.columns or "EmailAddress" not in receive_df.columns:
        print("Error: 'EmailAddress' column not found in one or both files.")
        return None
    sent_series = _normalize_emails(send_df["EmailAddress"])
    received_series = _normalize_emails(receive_df["EmailAddress"])
    raw_sent_count = send_df["EmailAddress"].dropna().shape[0]
    duplicate_sent = raw_sent_count - sent_series.nunique()
    if duplicate_sent > 0:
        logger.info(f"Removed {duplicate_sent} duplicate sent email row(s).")
    sent_emails = set(sent_series.unique())
    received_emails = set(received_series.unique())
    converted_emails = sent_emails.intersection(received_emails)
    total_sent = len(sent_emails)
    total_received = len(converted_emails)
    if total_sent == 0:
        print("Warning: No sent emails found.")
        return None
    conversion_rate_pct = (total_received / total_sent) * 100
    send_df = send_df.loc[sent_series.index].copy()
    send_df["_normalized_email"] = sent_series
    converted_df = send_df[send_df["_normalized_email"].isin(converted_emails)]
    if "Business Type" in converted_df.columns:
        business_summary = converted_df["Business Type"].value_counts().reset_index()
        business_summary.columns = ["Business Type", "Count"]
        sent_by_type = send_df["Business Type"].value_counts() if "Business Type" in send_df.columns else None
        if sent_by_type is not None:
            business_summary["Sent"] = business_summary["Business Type"].map(sent_by_type).fillna(0).astype(int)
            business_summary["Conversion Rate (%)"] = (
                business_summary["Count"] / business_summary["Sent"].replace(0, pd.NA) * 100
            ).round(2)
    else:
        business_summary = None
    domain_summary = _domain_breakdown(sent_series, received_series)
    print(f"Total Emails Sent:      {total_sent}")
    print(f"Total Emails Converted: {total_received}")
    print(f"Conversion Rate:        {conversion_rate_pct:.2f}%")
    if business_summary is not None:
        print("\nConversions by Business Type:")
        print(business_summary)
    print("\nConversions by Email Domain:")
    print(domain_summary)
    non_converted = sent_emails - received_emails
    if mask_pii_in_output:
        sample_non_converted = [_mask_email(e) for e in list(non_converted)[:10]]
    else:
        sample_non_converted = list(non_converted)[:10]
    print(f"\nSample of non-converted emails ({len(non_converted)} total, showing up to 10):")
    for e in sample_non_converted:
        print(f"  {e}")
    plot_conversion_metrics(total_sent, total_received, conversion_rate_pct)
    if business_summary is not None:
        plot_conversion_metrics_by_categories(business_summary)
    plot_domain_breakdown(domain_summary)
    return {
        "total_sent": total_sent,
        "total_converted": total_received,
        "conversion_rate": conversion_rate_pct,
        "duplicate_sent_rows_removed": duplicate_sent,
        "business_breakdown": business_summary,
        "domain_breakdown": domain_summary,
        "non_converted_emails": sorted(non_converted) if not mask_pii_in_output else None,
    }

# per domain converson rate 
def _domain_breakdown(sent_series: pd.Series, received_series: pd.Series) -> pd.DataFrame:
    sent_domains = sent_series.map(_extract_domain)
    received_domains = received_series.map(_extract_domain)
    sent_counts = sent_domains.value_counts()
    converted_emails = set(sent_series) & set(received_series)
    converted_domains = pd.Series([_extract_domain(e) for e in converted_emails])
    converted_counts = converted_domains.value_counts()
    summary = pd.DataFrame({"Sent": sent_counts}).fillna(0)
    summary["Converted"] = converted_counts
    summary["Converted"] = summary["Converted"].fillna(0).astype(int)
    summary["Sent"] = summary["Sent"].astype(int)
    summary["Conversion Rate (%)"] = (summary["Converted"] / summary["Sent"] * 100).round(2)
    summary = summary.sort_values("Sent", ascending=False)
    summary.index.name = "Domain"
    return summary.reset_index()

def export_results(results: dict, out_path: str = r"Analytics/Report/conversion_report.csv") -> None:
    if results is None:
        print("Nothing to export.")
        return
    with open(out_path, "w") as f:
        f.write(f"Total Sent,{results['total_sent']}\n")
        f.write(f"Total Converted,{results['total_converted']}\n")
        f.write(f"Conversion Rate (%),{results['conversion_rate']:.2f}\n")
        f.write(f"Duplicate Sent Rows Removed,{results['duplicate_sent_rows_removed']}\n\n")
    if results.get("business_breakdown") is not None:
        results["business_breakdown"].to_csv(out_path, mode="a", index=False)
    if results.get("domain_breakdown") is not None:
        with open(out_path, "a") as f:
            f.write("\n")
        results["domain_breakdown"].to_csv(out_path, mode="a", index=False)
    print(f"Report exported to {out_path}")

def plot_conversion_metrics(sent, converted, rate):
    categories = ["Sent", "Converted"]
    values = [sent, converted]
    colors = ["#4CAF50", "#2196F3"]
    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(categories, values, color=colors, edgecolor="black")
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, height, f"{int(height)}",
                ha="center", va="bottom", fontsize=12)
    ax.set_title(f"Email Conversion Metrics (Rate: {rate:.1f}%)", fontsize=14)
    ax.set_ylabel("Number of Emails", fontsize=12)
    ax.set_xlabel("Status", fontsize=12)
    ax.set_ylim(0, max(values) * 1.1 if max(values) > 0 else 1)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    plt.tight_layout()
    plt.savefig("conversion_metrics.png")
    print("Chart saved to conversion_metrics.png")
    plt.show()

def plot_conversion_metrics_by_categories(business_summary: pd.DataFrame):
    if business_summary is None or business_summary.empty:
        return
    categories = business_summary["Business Type"]
    values = business_summary["Count"]
    cmap = plt.get_cmap("tab10")
    colors = [cmap(i % 10) for i in range(len(categories))]
    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(categories, values, color=colors, edgecolor="black")
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, height, f"{int(height)}",
                ha="center", va="bottom", fontsize=12)
    ax.set_title("Conversions by Business Type", fontsize=14)
    ax.set_ylabel("Number of Converted Emails", fontsize=12)
    ax.set_xlabel("Business Type", fontsize=12)
    ax.set_ylim(0, max(values) * 1.1 if max(values) > 0 else 1)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig("conversion_by_business_type.png")
    print("Chart saved to conversion_by_business_type.png")
    plt.show()

def plot_domain_breakdown(domain_summary: pd.DataFrame, top_n: int = 10):
    if domain_summary is None or domain_summary.empty:
        return
    top = domain_summary.head(top_n)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(top["Domain"], top["Conversion Rate (%)"], color="#CA057f", edgecolor="black")
    ax.set_title(f"Conversion Rate by Email Domain (top {top_n} by volume)", fontsize=14)
    ax.set_ylabel("Conversion Rate (%)", fontsize=12)
    ax.set_xlabel("Domain", fontsize=12)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig("conversion_by_domain.png")
    print("Chart saved to conversion_by_domain.png")
    plt.show()

if __name__ == "__main__":
    result = conversion_rate("sent_emails.csv", "received_emails.csv")
    if result:
        export_results(result)