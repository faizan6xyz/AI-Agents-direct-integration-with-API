import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
CSV_PATH = "Data/Instagram_Engagement.csv"

def load_history():
    if not os.path.exists(CSV_PATH):
        print("History not found!")
        return None
    df = pd.read_excel(CSV_PATH)
    if df.empty:
        print("History empty.")
        return None
    return df

#  Shared cleanup used by almost every analysis function: parses period_end into real datetimes, drops rows with bad dates, optionally filters to one year/month, drops rows missing gained_likes/gained_views, and adds hour, day_name, day_of_week columns. Written once so it's not repeated in five different functions.
def _prep(df, year=None, month=None):
    df = df.copy()
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df = df.dropna(subset=["period_end"])
    now = datetime.now()
    if year is not None or month is not None:
        year = year or now.year
        month = month or now.month
        df = df[(df["period_end"].dt.year == year) & (df["period_end"].dt.month == month)]
    df = df.dropna(subset=["gained_likes", "gained_views"])
    df["hour"] = df["period_end"].dt.hour
    df["day_name"] = df["period_end"].dt.day_name()
    df["day_of_week"] = df["period_end"].dt.dayofweek  # Monday=0
    return df

def analyze_best_upload_hour(year=None, month=None):
    df = load_history()
    if df is None:
        return
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    monthly_df = _prep(df, year, month)
    if monthly_df.empty:
        print(f"No growth data available for {year}-{month:02d}.")
        return
    hourly_avg = monthly_df.groupby("hour")[["gained_likes", "gained_views"]].mean()
    hourly_avg["combined_score"] = hourly_avg["gained_likes"] + hourly_avg["gained_views"]
    best_hour = hourly_avg["combined_score"].idxmax()
    worst_hour = hourly_avg["combined_score"].idxmin()

    print(f"\n--- Engagement analysis for {year}-{month:02d} ---")
    print(hourly_avg.round(1))
    print(f"\nBest hour to post: {best_hour}:00 "
          f"(avg {hourly_avg.loc[best_hour, 'gained_likes']:.1f} likes, "
          f"{hourly_avg.loc[best_hour, 'gained_views']:.1f} views gained)")
    print(f"Worst hour to post: {worst_hour}:00 "
          f"(avg {hourly_avg.loc[worst_hour, 'gained_likes']:.1f} likes, "
          f"{hourly_avg.loc[worst_hour, 'gained_views']:.1f} views gained)")

    plot_hourly_engagement(hourly_avg, year, month)
    return hourly_avg, best_hour, worst_hour

def analyze_best_upload_day(year=None, month=None):
    df = load_history()
    if df is None:
        return
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    monthly_df = _prep(df, year, month)
    if monthly_df.empty:
        print(f"No growth data available for {year}-{month:02d}.")
        return
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    daily_avg = monthly_df.groupby("day_name")[["gained_likes", "gained_views"]].mean()
    daily_avg = daily_avg.reindex(day_order).dropna(how="all")
    daily_avg["combined_score"] = daily_avg["gained_likes"] + daily_avg["gained_views"]
    best_day = daily_avg["combined_score"].idxmax()
    worst_day = daily_avg["combined_score"].idxmin()

    print(f"\n--- Day-of-week analysis for {year}-{month:02d} ---")
    print(daily_avg.round(1))
    print(f"\nBest day to post: {best_day} "
          f"(avg {daily_avg.loc[best_day, 'gained_likes']:.1f} likes, "
          f"{daily_avg.loc[best_day, 'gained_views']:.1f} views gained)")
    print(f"Worst day to post: {worst_day} "
          f"(avg {daily_avg.loc[worst_day, 'gained_likes']:.1f} likes, "
          f"{daily_avg.loc[worst_day, 'gained_views']:.1f} views gained)")

    plot_daily_engagement(daily_avg, year, month)
    return daily_avg, best_day, worst_day

def analyze_day_hour_heatmap(year=None, month=None, metric="gained_likes"):
    df = load_history()
    if df is None:
        return
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    monthly_df = _prep(df, year, month)
    if monthly_df.empty:
        print(f"No growth data available for {year}-{month:02d}.")
        return
    if metric not in monthly_df.columns:
        print(f"Metric '{metric}' not found in data.")
        return
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    pivot = monthly_df.pivot_table(
        index="day_name", columns="hour", values=metric, aggfunc="mean"
    ).reindex(day_order)
    best_cell = pivot.stack().idxmax()
    print(f"\n--- Day x Hour heatmap ({metric}) for {year}-{month:02d} ---")
    print(pivot.round(1))
    print(f"\nBest single slot: {best_cell[0]} at {best_cell[1]}:00 "
          f"(avg {pivot.loc[best_cell[0], best_cell[1]]:.1f} {metric})")
    fig, ax = plt.subplots(figsize=(12, 5))
    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("Hour of Day")
    ax.set_title(f"{metric} heatmap by Day x Hour ({year}-{month:02d})")
    fig.colorbar(im, ax=ax, label=metric)
    plt.tight_layout()
    out_path = f"Analytics/Report/day_hour_heatmap_{year}_{month:02d}.png"
    plt.savefig(out_path)
    print(f"Heatmap saved to {out_path}")
    plt.show()
    return pivot, best_cell

def analyze_monthly_trend():
    df = load_history()
    if df is None:
        return
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df = df.dropna(subset=["period_end", "gained_likes", "gained_views"])
    if df.empty:
        print("No usable data for trend analysis.")
        return
    df["year_month"] = df["period_end"].dt.to_period("M")
    monthly = df.groupby("year_month")[["gained_likes", "gained_views"]].sum()
    print("\n--- Month-over-month totals ---")
    print(monthly.round(0))
    fig, ax = plt.subplots(figsize=(10, 5))
    monthly.plot(ax=ax, marker="o")
    ax.set_title("Monthly Gained Likes/Views Over Time")
    ax.set_xlabel("Month")
    ax.set_ylabel("Total Gained")
    plt.tight_layout()
    out_path = "Analytics/Report/monthly_trend.png"
    plt.savefig(out_path)
    print(f"Chart saved to {out_path}")
    plt.show()
    return monthly

# Instead of averaging by hour/day, ranks individual rows/posts by a chosen metric and shows your best and worst performers directly.
def top_and_bottom_posts(year=None, month=None, n=5, metric="gained_likes"):
    df = load_history()
    if df is None:
        return
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    monthly_df = _prep(df, year, month)
    if monthly_df.empty:
        print(f"No growth data available for {year}-{month:02d}.")
        return
    if metric not in monthly_df.columns:
        print(f"Metric '{metric}' not found in data.")
        return
    ranked = monthly_df.sort_values(metric, ascending=False)
    cols = [c for c in ["period_end", "gained_likes", "gained_views"] if c in ranked.columns]
    print(f"\n--- Top {n} posts by {metric} ({year}-{month:02d}) ---")
    print(ranked[cols].head(n).to_string(index=False))
    print(f"\n--- Bottom {n} posts by {metric} ({year}-{month:02d}) ---")
    print(ranked[cols].tail(n).to_string(index=False))
    return ranked

def rolling_engagement_trend(window=7):
    df = load_history()
    if df is None:
        return
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df = df.dropna(subset=["period_end", "gained_likes", "gained_views"])
    df = df.sort_values("period_end")
    if df.empty:
        print("No usable data for rolling trend analysis.")
        return

    df["likes_rolling"] = df["gained_likes"].rolling(window, min_periods=1).mean()
    df["views_rolling"] = df["gained_views"].rolling(window, min_periods=1).mean()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["period_end"], df["likes_rolling"], label=f"Likes ({window}-period avg)")
    ax.plot(df["period_end"], df["views_rolling"], label=f"Views ({window}-period avg)")
    ax.set_title(f"Rolling {window}-Period Average Engagement")
    ax.set_xlabel("Date")
    ax.set_ylabel("Average Gained")
    ax.legend()
    plt.tight_layout()
    out_path = f"Analytics/Report/rolling_trend_{window}.png"
    plt.savefig(out_path)
    print(f"Chart saved to {out_path}")
    plt.show()
    return df[["period_end", "likes_rolling", "views_rolling"]]

def export_summary_report(year=None, month=None, out_path=None):
    df = load_history()
    if df is None:
        return
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    monthly_df = _prep(df, year, month)
    if monthly_df.empty:
        print(f"No growth data available for {year}-{month:02d}.")
        return
    hourly_avg = monthly_df.groupby("hour")[["gained_likes", "gained_views"]].mean()
    hourly_avg.index = [f"hour_{h}" for h in hourly_avg.index]
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    daily_avg = monthly_df.groupby("day_name")[["gained_likes", "gained_views"]].mean()
    daily_avg = daily_avg.reindex(day_order).dropna(how="all")
    combined = pd.concat([hourly_avg, daily_avg])
    out_path = out_path or f"Analytics/Report/summary_{year}_{month:02d}.csv"
    combined.to_csv(out_path)
    print(f"Summary report saved to {out_path}")
    return combined

def plot_hourly_engagement(hourly_avg, year, month):
    fig, ax = plt.subplots(figsize=(10, 5))
    hourly_avg[["gained_likes", "gained_views"]].plot(kind="bar", ax=ax)
    ax.set_title(f"Average Gained Likes/Views by Hour ({year}-{month:02d})")
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Average Gained")
    ax.legend(["Likes", "Views"])
    plt.tight_layout()
    plt.savefig(f"Data/hourly_engagement_{year}_{month:02d}.png")
    print(f"Chart saved to Data/hourly_engagement_{year}_{month:02d}.png")
    plt.show()

def plot_daily_engagement(daily_avg, year, month):
    fig, ax = plt.subplots(figsize=(10, 5))
    daily_avg[["gained_likes", "gained_views"]].plot(kind="bar", ax=ax)
    ax.set_title(f"Average Gained Likes/Views by Day of Week ({year}-{month:02d})")
    ax.set_xlabel("Day of Week")
    ax.set_ylabel("Average Gained")
    ax.legend(["Likes", "Views"])
    plt.tight_layout()
    plt.savefig(f"Data/daily_engagement_{year}_{month:02d}.png")
    print(f"Chart saved to Data/daily_engagement_{year}_{month:02d}.png")
    plt.show()

if __name__ == "__main__":
    analyze_best_upload_hour()
    analyze_best_upload_day()
    analyze_day_hour_heatmap()
    top_and_bottom_posts()
    analyze_monthly_trend()
    rolling_engagement_trend()
    export_summary_report()