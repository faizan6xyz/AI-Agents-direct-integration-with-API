import pandas as pd
# df has ["id","email" , send" , "return" , "time"]

def response(df , comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return", "mail", "time"])
    return df.loc[(df["return"] == True) & (df["id"]==comp_id) , ["mail","time"]].copy()

def conversion(df,comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send", "return"])
    sends = len(df.loc[(df["send"] == True) & (df["id"]==comp_id) ])
    returns = len(df.loc[(df["return"] == True) & (df["id"]==comp_id) ])
    if sends == 0:
        return "no sends to compute conversion rate"
    return f"conversion rate {returns / sends}"

def avg_response_time(df,comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return", "time"])
    replied = df.loc[(df["return"] == True) & (df["id"]==comp_id) ]
    if replied.empty:
        return "no replies to compute response time"
    return f"avg response time: {replied['time'].mean()}"

def sends_by_period(df, comp_id , freq="D"):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send", "time"])
    sent = df.loc[(df["send"] == True) & (df["id"]==comp_id) ].copy()
    sent["time"] = pd.to_datetime(sent["time"])
    return sent.groupby(pd.Grouper(key="time", freq=freq)).size()

def top_repliers(df,comp_id, n=10):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["return", "mail"])
    return df.loc[(df["return"] == True) & (df["id"]==comp_id) , "mail"].value_counts().head(n)

def bounce_rate(df,comp_id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.dropna(subset=["send", "bounced"])
    sent = len(df.loc[(df["send"] == True) & (df["id"]==comp_id) ])
    bounced = len(df.loc[(df["bounced"] == True) & (df["id"]==comp_id) ])
    if sent == 0:
        return "no sends to compute bounce rate"
    return f"bounce rate {bounced / sent}"

def summary(df,comp_id):
    if df is None or df.empty:
        return {"error": "empty analytics"}
    df = df.dropna(subset=["send", "return"])
    sends = len(df.loc[(df["send"] == True) & (df["id"]==comp_id) ])
    returns = len(df.loc[(df["return"] == True) & (df["id"]==comp_id) ])
    return { "total_sends": sends, "total_returns": returns, "conversion_rate": returns / sends if sends else None, }