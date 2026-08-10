import pandas as pd
# df has ["id","email","send","return","time","bounced"]

def response(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return", "email", "time"])
    return df.loc[(df["return"] == True) & (df["id"] == comp_id), ["email", "time"]].copy()

def conversion(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send", "return"])
    sends = len(df.loc[(df["send"] == True) & (df["id"] == comp_id)])
    returns = len(df.loc[(df["return"] == True) & (df["id"] == comp_id)])
    if sends == 0:
        return "no sends to compute conversion rate"
    return f"conversion rate {returns / sends}"

def avg_response_time(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return", "time"])
    replied = df.loc[(df["return"] == True) & (df["id"] == comp_id)]
    if replied.empty:
        return "no replies to compute response time"
    return f"avg response time: {replied['time'].mean()}"

def response_time_distribution(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return", "time"])
    replied = df.loc[(df["return"] == True) & (df["id"] == comp_id)]
    if replied.empty:
        return "no replies to compute response time distribution"
    return {"p50": replied["time"].quantile(0.5), "p90": replied["time"].quantile(0.9), "mean": replied["time"].mean(), "max": replied["time"].max(), }

def sends_by_period(df, comp_id, freq="D"):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send", "time"])
    sent = df.loc[(df["send"] == True) & (df["id"] == comp_id)].copy()
    sent["time"] = pd.to_datetime(sent["time"])
    return sent.groupby(pd.Grouper(key="time", freq=freq)).size()

def funnel_by_period(df, comp_id, freq="D"):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send", "return", "time"]).copy()
    df["time"] = pd.to_datetime(df["time"])
    scoped = df.loc[df["id"] == comp_id]
    sends = scoped.loc[scoped["send"] == True].groupby(pd.Grouper(key="time", freq=freq)).size()
    returns = scoped.loc[scoped["return"] == True].groupby(pd.Grouper(key="time", freq=freq)).size()
    out = pd.DataFrame({"sends": sends, "returns": returns}).fillna(0)
    out["conversion_rate"] = out["returns"] / out["sends"].replace(0, pd.NA)
    return out

def top_repliers(df, comp_id, n=10):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return", "email"])
    return df.loc[(df["return"] == True) & (df["id"] == comp_id), "email"].value_counts().head(n)

def non_responders(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send", "return", "email"])
    scoped = df.loc[df["id"] == comp_id]
    sent_emails = set(scoped.loc[scoped["send"] == True, "email"])
    replied_emails = set(scoped.loc[scoped["return"] == True, "email"])
    return sorted(sent_emails - replied_emails)

def bounce_rate(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    if "bounced" not in df.columns:
        return "no bounce data available"
    df = df.dropna(subset=["send", "bounced"])
    sent = len(df.loc[(df["send"] == True) & (df["id"] == comp_id)])
    bounced = len(df.loc[(df["bounced"] == True) & (df["id"] == comp_id)])
    if sent == 0:
        return "no sends to compute bounce rate"
    return f"bounce rate {bounced / sent}"

def summary(df, comp_id):
    if df is None or df.empty:
        return {"error": "empty analytics"}
    df = df.dropna(subset=["send", "return"])
    sends = len(df.loc[(df["send"] == True) & (df["id"] == comp_id)])
    returns = len(df.loc[(df["return"] == True) & (df["id"] == comp_id)])
    return {"total_sends": sends, "total_returns": returns,"conversion_rate": returns / sends if sends else None,"reason": None if sends else "no sends",}