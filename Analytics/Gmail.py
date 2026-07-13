import os 
import pandas as pd
import matplotlib.pyplot as plt
import os
import pandas as pd
import matplotlib.pyplot as plt

def conversion_rate(send_file, receive_file):
    if not send_file or not os.path.exists(send_file):
        print("Error: Send file is missing or path is invalid.")
        return None
    if not receive_file or not os.path.exists(receive_file):
        print("Error: Receive file is missing or path is invalid.")
        return None
    try:
        if send_file.endswith('.csv'):
            send_df = pd.read_csv(send_file)
        elif send_file.endswith(('.xlsx', '.xls')):
            send_df = pd.read_excel(send_file)
        else:
            print("Error: Unsupported file format for send file.")
            return None
        if receive_file.endswith('.csv'):
            receive_df = pd.read_csv(receive_file)
        elif receive_file.endswith(('.xlsx', '.xls')):
            receive_df = pd.read_excel(receive_file)
        else:
            print("Error: Unsupported file format for receive file.")
            return None
    except Exception as e:
        print(f"Error reading files: {e}")
        return None
    if 'EmailAddress' not in send_df.columns or 'EmailAddress' not in receive_df.columns:
        print("Error: 'EmailAddress' column not found in one or both files.")
        return None
    sent_emails = set(send_df['EmailAddress'].dropna().unique())  # ✅ Use set for O(1) lookup
    received_emails = set(receive_df['EmailAddress'].dropna().unique())
    converted_emails = sent_emails.intersection(received_emails)
    total_sent = len(sent_emails)
    total_received = len(converted_emails)
    if total_sent == 0:
        print("Warning: No sent emails found.")
        return None
    conversion_rate_pct = (total_received / total_sent) * 100
    converted_df = send_df[send_df['EmailAddress'].isin(converted_emails)]
    if 'Business Type' in converted_df.columns:
        business_summary = converted_df['Business Type'].value_counts()
    else:
        business_summary = None
    print(f"Total Emails Sent:     {total_sent}")
    print(f"Total Emails Converted:{total_received}")
    print(f"Conversion Rate:       {conversion_rate_pct:.2f}%")

    if business_summary is not None:
        print("\nConversions by Business Type:")
        print(business_summary)
    plot_conversion_metrics(total_sent, total_received, conversion_rate_pct)
    return {"total_sent": total_sent,
        "total_converted": total_received,
        "conversion_rate": conversion_rate_pct,
        "business_breakdown": business_summary}
    
def plot_conversion_metrics(sent, converted, rate):
    categories = ['Sent', 'Converted']
    values = [sent, converted]
    colors = ['#4CAF50', '#2196F3']
    plt.figure(figsize=(8, 6))
    bars = plt.bar(categories, values, color=colors, edgecolor='black')
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,
                 f'{int(height)}',
                 ha='center', va='bottom', fontsize=12)
    plt.title('Email Conversion Metrics', fontsize=14)
    plt.ylabel('Number of Emails', fontsize=12)
    plt.xlabel('Status', fontsize=12)
    plt.ylim(0, max(values) * 1.1)  # Add space above bars
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.show()
# result = conversion_rate('sent_emails.csv', 'received_emails.xlsx')