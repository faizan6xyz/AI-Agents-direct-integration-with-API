import numpy as np
import pandas as pd
# df has ["id","email","send_time","return_time","bounced"]

def response(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return_time", "email"])
    return df.loc[df["return_time"].notna() & (df["id"] == comp_id), ["email", "send_time"]].copy()

def conversion(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send_time", "return_time"])
    sends = len(df.loc[df["send_time"].notna() & (df["id"] == comp_id)])
    returns = len(df.loc[df["return_time"].notna() & (df["id"] == comp_id)])
    if sends == 0:
        return "no sends to compute conversion rate"
    return f"conversion rate {returns / sends} and the percentage is {(returns/sends)*100}"

def avg_response_time(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return_time", "send_time"]).copy()
    replied = df.loc[df["return_time"].notna() & (df["id"] == comp_id)]
    if replied.empty:
        return "no replies to compute response time"
    delta = pd.to_datetime(replied["return_time"]) - pd.to_datetime(replied["send_time"])
    return f"avg response time: {delta.mean()}"

def response_time_distribution(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return_time", "send_time"]).copy()
    replied = df.loc[df["return_time"].notna() & (df["id"] == comp_id)]
    if replied.empty:
        return "no replies to compute response time distribution"
    delta = pd.to_datetime(replied["return_time"]) - pd.to_datetime(replied["send_time"])
    return {"p50": delta.quantile(0.5), "p90": delta.quantile(0.9), "mean": delta.mean(), "max": delta.max()}

def sends_by_period(df, comp_id, freq="D"):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send_time"])
    sent = df.loc[df["send_time"].notna() & (df["id"] == comp_id)].copy()
    sent["send_time"] = pd.to_datetime(sent["send_time"])
    return sent.groupby(pd.Grouper(key="send_time", freq=freq)).size()

def funnel_by_period(df, comp_id, freq="D"):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send_time", "return_time"]).copy()
    df["send_time"] = pd.to_datetime(df["send_time"])
    scoped = df.loc[df["id"] == comp_id]
    sends = scoped.loc[scoped["send_time"].notna()].groupby(pd.Grouper(key="send_time", freq=freq)).size()
    returns = scoped.loc[scoped["return_time"].notna()].groupby(pd.Grouper(key="send_time", freq=freq)).size()
    out = pd.DataFrame({"sends": sends, "returns": returns}).fillna(0)
    out["conversion_rate"] = out["returns"] / out["sends"].replace(0, np.nan)
    return out

def top_repliers(df, comp_id, n=10):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return_time", "email"])
    return df.loc[df["return_time"].notna() & (df["id"] == comp_id), "email"].value_counts().head(n)

def non_responders(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send_time", "return_time", "email"])
    scoped = df.loc[df["id"] == comp_id]
    sent_emails = set(scoped.loc[scoped["send_time"].notna(), "email"])
    replied_emails = set(scoped.loc[scoped["return_time"].notna(), "email"])
    return sorted(sent_emails - replied_emails)

def bounce_rate(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    if "bounced" not in df.columns:
        return "no bounce data available"
    df = df.dropna(subset=["send_time", "bounced"])
    sent = len(df.loc[df["send_time"].notna() & (df["id"] == comp_id)])
    bounced = len(df.loc[(df["bounced"] == True) & (df["id"] == comp_id)])
    if sent == 0:
        return "no sends to compute bounce rate"
    return f"bounce rate {bounced / sent} and the percentage is {(bounced/sent)*100}"

def summary(df, comp_id):
    if df is None or df.empty:
        return {"error": "empty analytics"}
    df = df.dropna(subset=["send_time", "return_time"])
    sends = len(df.loc[df["send_time"].notna() & (df["id"] == comp_id)])
    returns = len(df.loc[df["return_time"].notna() & (df["id"] == comp_id)])
    return {"total_sends": sends, "total_returns": returns, "conversion_rate": returns / sends if sends else None, "reason": None if sends else "no sends"}