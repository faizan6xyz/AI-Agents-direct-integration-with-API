import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# df  ["id" , "views" , "hour" ,"likes" , "comments" , "shares" ]

def engagement_check(df,id):
    if df is None or df.empty:
        return "empty analytics"
    df = df.loc[df["id"] == id]
    df = df.sort_values(by="views", ascending=False).reset_index(drop=True)
    return df