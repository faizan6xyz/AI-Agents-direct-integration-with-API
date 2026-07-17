import os
import pickle
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.settings.basic',
]

def get_service(credentials_path='credentials.json', token_path='token.pickle'):
    creds = None
    if os.path.exists(token_path):
        with open(token_path, 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'wb') as f:
            pickle.dump(creds, f)
    return build('gmail', 'v1', credentials=creds)

def list_messages(service, query='', max_results=10, label_ids=None):
    results = service.users().messages().list(
        userId='me', q=query, maxResults=max_results, labelIds=label_ids or []
    ).execute()
    return results.get('messages', [])

def get_message(service, msg_id, format='full'):
    return service.users().messages().get(userId='me', id=msg_id, format=format).execute()

def _decode_body(data):
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

def get_message_body(service, msg_id):
    msg = get_message(service, msg_id)
    payload = msg['payload']

    def walk(part):
        if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
            return _decode_body(part['body']['data'])
        for sub in part.get('parts', []):
            result = walk(sub)
            if result:
                return result
        return None

    if 'data' in payload.get('body', {}):
        return _decode_body(payload['body']['data'])
    return walk(payload) or ''

def send_message(service, to, subject, body_text):
    message = MIMEText(body_text)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(userId='me', body={'raw': raw}).execute()

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

def list_labels(service):
    return service.users().labels().list(userId='me').execute().get('labels', [])

def create_label(service, name, list_visibility='labelShow', label_visibility='labelShow'):
    body = {
        'name': name,
        'labelListVisibility': list_visibility,
        'messageListVisibility': label_visibility,
    }
    return service.users().labels().create(userId='me', body=body).execute()

def delete_label(service, label_id):
    return service.users().labels().delete(userId='me', id=label_id).execute()

def modify_labels(service, msg_id, add_labels=None, remove_labels=None):
    body = {'addLabelIds': add_labels or [], 'removeLabelIds': remove_labels or []}
    return service.users().messages().modify(userId='me', id=msg_id, body=body).execute()

def mark_as_read(service, msg_id):
    return modify_labels(service, msg_id, remove_labels=['UNREAD'])

def mark_as_unread(service, msg_id):
    return modify_labels(service, msg_id, add_labels=['UNREAD'])

def archive_message(service, msg_id):
    return modify_labels(service, msg_id, remove_labels=['INBOX'])

def trash_message(service, msg_id):
    return service.users().messages().trash(userId='me', id=msg_id).execute()

def delete_message_permanently(service, msg_id):
    return service.users().messages().delete(userId='me', id=msg_id).execute()

def batch_modify(service, msg_ids, add_labels=None, remove_labels=None):
    body = {
        'ids': msg_ids,
        'addLabelIds': add_labels or [],
        'removeLabelIds': remove_labels or [],
    }
    return service.users().messages().batchModify(userId='me', body=body).execute()

def batch_delete(service, msg_ids):
    body = {'ids': msg_ids}
    return service.users().messages().batchDelete(userId='me', body=body).execute()

def list_threads(service, query='', max_results=10):
    results = service.users().threads().list(userId='me', q=query, maxResults=max_results).execute()
    return results.get('threads', [])

def get_thread(service, thread_id):
    return service.users().threads().get(userId='me', id=thread_id).execute()

def trash_thread(service, thread_id):
    return service.users().threads().trash(userId='me', id=thread_id).execute()

def list_attachment_ids(service, msg_id):
    msg = get_message(service, msg_id)
    found = []
    def walk(part):
        body = part.get('body', {})
        if body.get('attachmentId') and part.get('filename'):
            found.append((part['filename'], body['attachmentId']))
        for sub in part.get('parts', []):
            walk(sub)
    walk(msg['payload'])
    return found

def download_attachment(service, msg_id, attachment_id, save_path):
    att = service.users().messages().attachments().get(
        userId='me', messageId=msg_id, id=attachment_id
    ).execute()
    data = base64.urlsafe_b64decode(att['data'])
    with open(save_path, 'wb') as f:
        f.write(data)
    return save_path

def create_draft(service, to, subject, body_text):
    message = MIMEText(body_text)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().drafts().create(userId='me', body={'message': {'raw': raw}}).execute()

def update_draft(service, draft_id, to, subject, body_text):
    message = MIMEText(body_text)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().drafts().update(
        userId='me', id=draft_id, body={'message': {'raw': raw}}
    ).execute()

def send_draft(service, draft_id):
    return service.users().drafts().send(userId='me', body={'id': draft_id}).execute()

def delete_draft(service, draft_id):
    return service.users().drafts().delete(userId='me', id=draft_id).execute()

def list_drafts(service, max_results=10):
    return service.users().drafts().list(userId='me', maxResults=max_results).execute().get('drafts', [])

def create_filter(service, criteria, action):
    body = {'criteria': criteria, 'action': action}
    return service.users().settings().filters().create(userId='me', body=body).execute()

def list_filters(service):
    return service.users().settings().filters().list(userId='me').execute().get('filter', [])

def delete_filter(service, filter_id):
    return service.users().settings().filters().delete(userId='me', id=filter_id).execute()

def watch_mailbox(service, topic_name, label_ids=None):
    body = {'topicName': topic_name, 'labelIds': label_ids or ['INBOX']}
    return service.users().watch(userId='me', body=body).execute()

def stop_watch(service):
    return service.users().stop(userId='me').execute()

def get_vacation_settings(service):
    return service.users().settings().getVacation(userId='me').execute()

def set_vacation_responder(service, subject, body_text, enabled=True):
    body = {
        'enableAutoReply': enabled,
        'responseSubject': subject,
        'responseBodyPlainText': body_text,
    }
    return service.users().settings().updateVacation(userId='me', body=body).execute()

def list_send_as_aliases(service):
    return service.users().settings().sendAs().list(userId='me').execute().get('sendAs', [])

def list_forwarding_addresses(service):
    return service.users().settings().forwardingAddresses().list(userId='me').execute().get(
        'forwardingAddresses', []
    )

def get_current_history_id(service):
    profile = service.users().getProfile(userId='me').execute()
    return profile['historyId']

def list_history_since(service, start_history_id, history_types=None):
    records = []
    page_token = None
    while True:
        resp = service.users().history().list(
            userId='me',
            startHistoryId=start_history_id,
            historyTypes=history_types or [],
            pageToken=page_token,
        ).execute()
        records.extend(resp.get('history', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return records

if __name__ == '__main__':
    service = get_service()
    unread = list_messages(service, query='is:unread', max_results=5)
    for m in unread:
        body = get_message_body(service, m['id'])
        print(body[:200])
    draft = create_draft(service, 'someone@example.com', 'Test', 'Hello from the agent')
    history_id = get_current_history_id(service)