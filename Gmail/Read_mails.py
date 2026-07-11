from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os, pickle
import base64
import base64
from email.mime.text import MIMEText
import pandas as pd

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']  # read + send + labels

def get_service():
    creds = None
    if os.path.exists(r'Gmail/token.pickle'):
        with open(r'Gmail/token.pickle', 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('Gmail/ss.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open(r'Gmail/token.pickle', 'wb') as f:
            pickle.dump(creds, f)
    return build('gmail', 'v1', credentials=creds)

    
def get_email_body(payload):
    # for multiparts mail
    if 'parts' in payload:
        for part in payload['parts']:
            # Look for plain text part first
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data', '')
                return base64.urlsafe_b64decode(data).decode('utf-8')
            # Fallback to HTML if no plain text is found
            elif part['mimeType'] == 'text/html':
                data = part['body'].get('data', '')
                return base64.urlsafe_b64decode(data).decode('utf-8')
# Simple single-part email
    else:
        data = payload['body'].get('data', '')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8')
    return "No body content found."

def list_messages(service, query='is:unread', max_results=10):
    results = service.users().messages().list(
        userId='me', q=query, maxResults=max_results
    ).execute()
    messages = results.get('messages', [])
    for msg in messages:
        full = service.users().messages().get(
            userId='me', id=msg['id'], format='full'
        ).execute()
        headers = full['payload']['headers']
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
        body = get_email_body(full['payload'])
        print(f"From: {sender} | Subject: {subject} | Body : {body}")

def send_message_with_attachments(service, to, subject, body_text, file_paths):
    message = MIMEMultipart()
    message['to'] = to
    message['subject'] = subject
    message.attach(MIMEText(body_text))

    for path in file_paths:
        with open(path, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(path))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
        message.attach(part)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(userId='me', body={'raw': raw}).execute()

def send_message(service, to, subject, body_text):
    message = MIMEText(body_text)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(
        userId='me', body={'raw': raw}
    ).execute()



if __name__ == '__main__':
    svc = get_service()
    list_messages(svc, query='test')
    send_message_with_attachments(svc, "faizanclaudeuser1@gmail.com" , "test mail" , "hi", [r"Gmail/Data/x.png" , r"Gmail/Data/x.pdf"] )    
    send_message(svc, "faizanclaudeuser1@gmail.com" , "test mail" , "hi" )    
    
    
    
    
    
    
    
    
    
    