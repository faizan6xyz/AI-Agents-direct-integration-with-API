import pandas as pd
import matplotlib
matplotlib.use('QtAgg') 
import matplotlib.pyplot as plt
from datetime import datetime
# metrics = ("id", views","reach","likes","comments","saved","shares","total_interactions","profile_activity","follows", "time")     for the post for long tern data collection , aorund a month 
df = pd.read_csv('hi.csv')

def coversion(df: pd.DataFrame):   # initial step for the analyis , always first and compulasay
    if df is None or df.empty : 
        return "empty analytics"
    df = df.groupby("id")[["views", "comments", "likes", "shares"]].mean()
    df["comment_rate"] = (df["comments"] / df["views"])
    df["like_rate"] = (df["likes"] / df["views"])
    df["share_rate"] = (df["shares"] / df["views"])
    df["visit"] = (df["total_interactions"] - df["follows"])
    df["month"] = datetime.fromisoformat(df["time"]).month
    df["year"] = datetime.fromisoformat(df["time"]).year
    return df

def growth_over_time(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df.groupby("month")["total_interactions"].sum().reset_index()

def growth_over_time(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df.groupby("year")["total_interactions"].sum().reset_index()

def top_posts(df, metric="views", n=10):
    if df is None or df.empty:
        return "empty analytics"
    return df.sort_values(by=metric, ascending=False).head(n)

def virality_score(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df[["share_rate"]].sort_values("share_rate", ascending=False)

def month_over_month_growth(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    monthly = df.groupby(["year", "month"])["total_interaction"].sum()
    monthly["total_engagement"] = monthly[["likes", "comments", "shares"]].sum(axis=1)
    monthly["mom_growth"] = monthly["total_engagement"].pct_change() * 100
    return monthly

def public_love_score(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df[["like_rate"]].sort_values("like_rate", ascending=False)

def public_engagement(df: pd.DataFrame):
    if df is None or df.empty:
       return "empty analytics"
    return df[["comment_rate"]].sort_values("comment_rate", ascending=False)

def follower_gain(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df.groupby(["id"]).sort_values("follows" , ascending=False)

def profile_visits(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df.groupby(["id"]).sort_values("visit" , ascending=False)

def new_reach(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df.groupby(["id"]).sort_values("reach" , ascending=False)


def filtering(df: pd.DataFrame, ids: list[int] | None = None) :   # 2nd step after the intitial
    if df is None or df.empty:
        return df
    if ids is not None:
        try:
            ids = [int(i) for i in ids]
        except (ValueError, TypeError):
            return df.iloc[0:0]  
        df = df[df["id"].astype(int).isin(ids)]
    return df

# metrics = ("id" , "views","reach", "replies","shares","navigation","profile_activity", "hour", ) for the short term data collection , eg 24 hours


def best_posting_hour(df: pd.DataFrame):  
    if df is None or df.empty:
        return "empty analytics"
    df = df.copy()
    df["engagement"] = df["likes"] + df["comments"] + df["shares"]
    return df.groupby("hour")["engagement"].mean().sort_values(ascending=False)