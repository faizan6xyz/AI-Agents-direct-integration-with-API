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
        print(f"From: {sender} | Subject: {subject}")