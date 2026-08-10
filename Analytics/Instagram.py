import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# df  ["id" , "views" , "hour" ,"likes" , "comments" , "shares" , "month" , "year" ]
# df = pd.read_csv('hi.csv')

def engagement_check(df,id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.loc[df["id"] == id]
    df = df.sort_values(by="views", ascending=False).reset_index(drop=True)
    return df

def engagement(df):
    if df is None or df.empty : 
        return "empty analytics"
    agg = df.groupby("id")[["views", "comments", "likes", "shares"]].mean()
    agg["comment_rate"] = (agg["comments"] / agg["views"])
    agg["like_rate"] = (agg["likes"] / agg["views"])
    agg["share_rate"] = (agg["shares"] / agg["views"])
    agg["engagement_rate"] = agg["comment_rate"] + agg["like_rate"] + agg["share_rate"]
    return agg

def growth_over_time(df, ):
    if df is None or df.empty:
        return "empty analytics"
    return df.groupby("month")[["views", "likes", "comments", "shares"]].sum().reset_index()

def growth_over_time(df):
    if df is None or df.empty:
        return "empty analytics"
    return df.groupby("year")[["views", "likes", "comments", "shares"]].sum().reset_index()

def top_posts(df, metric="views", n=10):
    if df is None or df.empty:
        return "empty analytics"
    return df.sort_values(by=metric, ascending=False).head(n)

def best_posting_hour(df):
    # avg engagement by hour of day — tells you when to post
    if df is None or df.empty:
        return "empty analytics"
    df = df.copy()
    df["engagement"] = df["likes"] + df["comments"] + df["shares"]
    return df.groupby("hour")["engagement"].mean().sort_values(ascending=False)

def virality_score(df):
    if df is None or df.empty:
        return "empty analytics"
    df = df.copy()
    df["virality"] = (df["shares"] / df["views"])
    return df.sort_values("virality", ascending=False)

def month_over_month_growth(df):
    if df is None or df.empty:
        return "empty analytics"
    monthly = df.groupby(["year", "month"])[["views", "likes", "comments", "shares"]].sum()
    monthly["total_engagement"] = monthly[["likes", "comments", "shares"]].sum(axis=1)
    monthly["mom_growth"] = monthly["total_engagement"].pct_change() * 100
    return monthly

def 