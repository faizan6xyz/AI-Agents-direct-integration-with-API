import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
EXCEL_PATH = "Data/Instagram_Engagement.xlsx"

def load_history():
    if not os.path.exists(EXCEL_PATH):
        print("History not found!")
        return None
    df = pd.read_excel(EXCEL_PATH)
    if df.empty:
        print("History empty.")
        return None
    return df

def analyze_best_upload_hour(year=None, month=None):
    df = load_history()
    if df is None:
        return
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df = df.dropna(subset=["period_end"])
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    monthly_df = df[(df["period_end"].dt.year == year) & (df["period_end"].dt.month == month)]
    monthly_df = monthly_df.dropna(subset=["gained_likes", "gained_views"])
    if monthly_df.empty:
        print(f"No growth data available for {year}-{month:02d}.")
        return
    monthly_df["hour"] = monthly_df["period_end"].dt.hour
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

# def anaylze_best_content():
    
if __name__ == "__main__":
    analyze_best_upload_hour()