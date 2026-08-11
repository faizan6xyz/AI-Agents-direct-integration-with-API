import pandas as pd
# metrics = ("id","views","reach","likes","comments","saved","shares",
#            "total_interactions","profile_activity","follows","time")
# long-term data, collected ~monthly, per post

def coversion(df: pd.DataFrame):  # always first
    if df is None or df.empty:
        return "empty analytics"
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    time_first = df.groupby("id")["time"].first()  # capture month/year before it's aggregated away
    df = df.groupby("id").mean(numeric_only=True)
    df["comment_rate"] = df["comments"] / df["views"]
    df["like_rate"] = df["likes"] / df["views"]
    df["share_rate"] = df["shares"] / df["views"]
    df["visit"] = df["total_interactions"] - df["follows"]
    df["month"] = time_first.dt.month
    df["year"] = time_first.dt.year
    return df

def growth_over_time_monthly(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df.groupby("month")["total_interactions"].sum().reset_index()

def growth_over_time_yearly(df: pd.DataFrame):
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
    monthly = df.groupby(["year", "month"])[["likes", "comments", "shares", "total_interactions"]].sum()
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
    return df.sort_values("follows", ascending=False)

def profile_visits(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df.sort_values("visit", ascending=False)

def new_reach(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    return df.sort_values("reach", ascending=False)

def filtering(df: pd.DataFrame, ids: list[int] | None = None):  # 2nd step, after coversion()
    if df is None or df.empty:
        return df
    if ids is not None:
        try:
            ids = [int(i) for i in ids]
        except (ValueError, TypeError):
            return df.iloc[0:0]
        if "id" in df.columns:
            df = df[df["id"].astype(int).isin(ids)]
        else:
            # id is the index (e.g. after coversion())
            df = df[df.index.astype(int).isin(ids)]
    return df

# metrics = ("id","views","likes","reach","replies","shares","navigation",
#            "profile_activity","hour","follows") — 24h short-term/story data.
# most "comments" for a post live in "replies".

def best_posting_hour(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    df = df.copy()
    df["total_engagement"] = df[["likes", "replies", "shares"]].sum(axis=1)
    return df.groupby("hour")["total_engagement"].mean().sort_values(ascending=False)

def coversion_stories(df: pd.DataFrame):
    if df is None or df.empty:
        return "empty analytics"
    df = df.groupby("id").mean(numeric_only=True)
    df["comment_rate"] = df["replies"] / df["views"]
    df["like_rate"] = df["likes"] / df["views"]
    df["share_rate"] = df["shares"] / df["views"]
    return df

# virality_score, public_engagement, public_love_score, follower_gain, new_reach
# are reused as-is for stories, since coversion_stories() also leaves id as the index.