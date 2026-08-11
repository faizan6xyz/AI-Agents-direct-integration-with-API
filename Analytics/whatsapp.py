import pandas as pd
import numpy as np

# df = ["id", "number", "sent_time", "recieve_time"]

def conversion(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    scoped = df.loc[df["id"] == comp_id]
    sends = scoped["sent_time"].notna().sum()
    if sends == 0:
        return "no sends to compute conversion rate"
    receives = scoped["recieve_time"].notna().sum()
    rate = receives / sends
    return f"the conversion rate is the {rate} and the percentage is the {rate * 100}"

def bounced_rate(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    scoped = df.loc[df["id"] == comp_id]
    sends = scoped["sent_time"].notna().sum()
    if sends == 0:
        return "no sends to compute bounced rate"
    receives = scoped["recieve_time"].notna().sum()
    bounced = sends - receives
    rate = bounced / sends
    return f"the bounced rate is the {rate} and the percentage is the {rate * 100}"

def top_repliers(df, comp_id, n=10):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["recieve_time", "number"])
    return df.loc[df["recieve_time"].notna() & (df["id"] == comp_id), "number"].value_counts().head(n)

def avg_response_time(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["recieve_time", "sent_time"]).copy()
    replied = df.loc[df["recieve_time"].notna() & (df["id"] == comp_id)]
    if replied.empty:
        return "no replies to compute response time"
    delta = pd.to_datetime(replied["recieve_time"]) - pd.to_datetime(replied["sent_time"])
    return f"avg response time: {delta.mean()}"

def response_time_distribution(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["recieve_time", "sent_time"]).copy()
    replied = df.loc[df["recieve_time"].notna() & (df["id"] == comp_id)]
    if replied.empty:
        return "no replies to compute response time distribution"
    delta = pd.to_datetime(replied["recieve_time"]) - pd.to_datetime(replied["sent_time"])
    return {"p50": delta.quantile(0.5), "p90": delta.quantile(0.9), "mean": delta.mean(), "max": delta.max()}

def sends_by_period(df, comp_id, freq="D"):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["sent_time"])
    sent = df.loc[df["sent_time"].notna() & (df["id"] == comp_id)].copy()
    sent["sent_time"] = pd.to_datetime(sent["sent_time"])
    return sent.groupby(pd.Grouper(key="sent_time", freq=freq)).size()

def funnel_by_period(df, comp_id, freq="D"):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["sent_time", "recieve_time"]).copy()
    df["sent_time"] = pd.to_datetime(df["sent_time"])
    scoped = df.loc[df["id"] == comp_id]
    sends = scoped.loc[scoped["sent_time"].notna()].groupby(pd.Grouper(key="sent_time", freq=freq)).size()
    returns = scoped.loc[scoped["recieve_time"].notna()].groupby(pd.Grouper(key="sent_time", freq=freq)).size()
    out = pd.DataFrame({"sends": sends, "returns": returns}).fillna(0)
    out["conversion_rate"] = out["returns"] / out["sends"].replace(0, np.nan)
    return out

def non_responders(df, comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["sent_time", "recieve_time", "number"])
    scoped = df.loc[df["id"] == comp_id]
    sent_numbers = set(scoped.loc[scoped["sent_time"].notna(), "number"])
    replied_numbers = set(scoped.loc[scoped["recieve_time"].notna(), "number"])
    return sorted(sent_numbers - replied_numbers)

def summary(df, comp_id):
    if df is None or df.empty:
        return {"error": "empty analytics"}
    df = df.dropna(subset=["sent_time", "recieve_time"])
    sends = len(df.loc[df["sent_time"].notna() & (df["id"] == comp_id)])
    returns = len(df.loc[df["recieve_time"].notna() & (df["id"] == comp_id)])
    return {"total_sends": sends, "total_returns": returns, "conversion_rate": returns / sends if sends else None, "reason": None if sends else "no sends"}