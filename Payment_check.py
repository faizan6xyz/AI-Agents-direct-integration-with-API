from flask import Flask, request, jsonify
import requests
import base64
import os
from dotenv import load_dotenv
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for mobile app communication

# PayPal Configuration
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID')
PAYPAL_SECRET = os.getenv('PAYPAL_SECRET')
PAYPAL_MODE = os.getenv('PAYPAL_MODE', 'sandbox')

if PAYPAL_MODE == 'live':
    PAYPAL_API_BASE = 'https://api-m.paypal.com'
else:
    PAYPAL_API_BASE = 'https://api-m.sandbox.paypal.com'
def get_paypal_access_token():
    try:
        auth_string = f"{PAYPAL_CLIENT_ID}:{PAYPAL_SECRET}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()
        
        response = requests.post(
            f"{PAYPAL_API_BASE}/v1/oauth2/token",
            headers={
                'Authorization': f'Basic {encoded_auth}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={'grant_type': 'client_credentials'}
        )
        
        if response.status_code == 200:
            return response.json()['access_token']
        else:
            raise Exception(f"Failed to get access token: {response.text}")
    except Exception as e:
        raise Exception(f"Error getting access token: {str(e)}")
@app.route('/api/create-order', methods=['POST'])
def create_order():
    try:
        data = request.json
        amount = data.get('amount', '99.00')
        currency = data.get('currency', 'USD')
        description = data.get('description', 'Payment')
        # Validate amount
        amount_float = float(amount)
        if amount_float <= 0:
            return jsonify({'success': False, 'error': 'Invalid amount'}), 400
        # Get access token
        access_token = get_paypal_access_token()
        # Create order
        order_payload = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {
                    "currency_code": currency,
                    "value": str(amount_float)
                },
                "description": description
            }]
        } 
        response = requests.post(
            f"{PAYPAL_API_BASE}/v2/checkout/orders",
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            },
            json=order_payload
        )
        
        if response.status_code in [200, 201]:
            order_data = response.json()
            return jsonify({
                'success': True,
                'order_id': order_data['id'],
                'status': order_data['status']
            })
        else:
            return jsonify({
                'success': False,
                'error': f"Failed to create order: {response.text}"
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
@app.route('/api/capture-payment', methods=['POST'])
def capture_payment():
    try:
        data = request.json
        order_id = data.get('order_id')
        if not order_id:
            return jsonify({'success': False, 'error': 'Order ID required'}), 400
        # Get access token
        access_token = get_paypal_access_token()
        # Capture the order
        response = requests.post(
            f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            },
            json={}
        )
        
        if response.status_code in [200, 201]:
            capture_data = response.json()
            return jsonify({
                'success': True,
                'transaction_id': capture_data['id'],
                'status': capture_data['status'],
                'amount': capture_data['purchase_units'][0]['payments']['captures'][0]['amount']['value'],
                'currency': capture_data['purchase_units'][0]['payments']['captures'][0]['amount']['currency_code'],
                'payer_email': capture_data.get('payer', {}).get('email_address', ''),
                'payer_name': f"{capture_data.get('payer', {}).get('name', {}).get('given_name', '')} {capture_data.get('payer', {}).get('name', {}).get('surname', '')}".strip()
            })
        else:
            return jsonify({
                'success': False,
                'error': f"Failed to capture payment: {response.text}"
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/order-status/<order_id>', methods=['GET'])
def check_order_status(order_id):
    """Check PayPal order status"""
    try:
        access_token = get_paypal_access_token()
        
        response = requests.get(
            f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}",
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
        )
        
        if response.status_code == 200:
            order_data = response.json()
            return jsonify({
                'success': True,
                'order_id': order_data['id'],
                'status': order_data['status'],
                'amount': order_data['purchase_units'][0]['amount']['value'],
                'currency': order_data['purchase_units'][0]['amount']['currency_code']
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Order not found'
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)