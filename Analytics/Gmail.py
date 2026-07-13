import os 
import pandas as pd
import matplotlib as plt

def conversion_rate(Sendfile , revievefile):
    if not Sendfile:
        return print("send file not file ")
    if not revievefile:
        return print("Recieve file not file ")
    if ".csv" in Sendfile :
        send = pd.read_csv(Sendfile)
    if ".csv" in revievefile :
        revieve = pd.read_csv(revievefile)
    if ".xlsx" in Sendfile :
        send = pd.read_csv(Sendfile)
    if ".xlsx" in revievefile :
        revieve = pd.read_csv(revievefile)
        
    x = send["EmailID"].unique   
    y = revieve["EmailID"].unique   
    
    plt.bar(x,y)
    plt.title("Line Plot")
    plt.xlabel("X values")
    plt.ylabel("sin(x)")
    plt.show()
    
    