from flask import Flask, render_template, request, redirect, url_for, session
from datetime import datetime, timedelta
from werkzeug.exceptions import HTTPException
import logging
from uuid import uuid4
import asyncio
from decimal import Decimal
import os

from decoder import decode_lightning_invoice
from invoice import generate_monero_invoice
from checker import check_incoming_transfers, check_incoming_transfers_0conf
from ln import lnpay, APIManager, load_seed, get_total_balance, calculate_send_liquidity
from xmr import validate_monero_address

app = Flask(__name__)
app.secret_key = 'enter secret session key'

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

#stagenet monero wallet rpc
rpc_url = "http://127.0.0.1:38083/json_rpc"
rpc_username = 'your_rpc_username'
rpc_password = 'your_rpc_password'


@app.errorhandler(404)
def error_404(error):
    logging.debug('Session content before clearing on 404: %s', session)
    return render_template('error.html', error_message='Page not found. Please start over.'), 404

@app.errorhandler(500)
def error_500(error):
    session.clear()
    return render_template('error.html', error_message='Internal server error. Please start over.'), 500

@app.errorhandler(Exception)
def handle_exception(error):
    session.clear()
    if isinstance(error, HTTPException):
        # Pass through HTTP errors
        return error
    return render_template('error.html', error_message='An unexpected error has occurred. Please start over.'), 500


@app.route('/')
def index():
    session.clear()
    session['session_id'] = str(uuid4())
    return render_template('index.html')

@app.route('/quote', methods=['POST'])
async def process_invoice():
    logging.debug('Session content at the start of processing invoice: %s', session)
    invoice = request.form.get('invoice')
    refund_address = request.form.get('refund_address')
    if not invoice or not refund_address:
        return render_error("Missing invoice or refund address")

    if not await is_valid_refund_address(refund_address):
        return render_error("Invalid Monero refund address")
    
    try:
        decoded_info = await decode_and_validate_invoice(invoice)
        if not decoded_info:
            return render_error("Decoding returned empty data.")

        # Prepare session data
        prepare_session(decoded_info, refund_address)

        return render_template('invoice_details.html', decoded_info=decoded_info, refund_address=refund_address)
    except Exception as e:
        logging.error(f"Error processing invoice: {e}")
        return render_error("Failed to process the invoice.")

async def is_valid_refund_address(refund_address):
    is_valid, *_ = await validate_monero_address(refund_address)
    return is_valid

async def decode_and_validate_invoice(invoice):
    decoded_info = await decode_lightning_invoice(invoice)
    if not decoded_info:
        return None

    seed_phrase = load_seed()  # Assuming this function is implemented elsewhere.
    manager = APIManager({"BTC": [seed_phrase]})
    wallet = manager.BTC[seed_phrase]

    if not await has_sufficient_balance(decoded_info['amount_btc'], wallet):
        raise ValueError("Insufficient wallet balance for this invoice.")

    if not await is_liquidity_sufficient(wallet):
        raise ValueError("Total spend liquidity is below 10%.")

    if Decimal(decoded_info['amount_btc']) > Decimal('0.0015'):
        raise ValueError("Decoded amount is greater than 0.0015 BTC.")

    return decoded_info

async def has_sufficient_balance(amount_btc, wallet):
    local_balance = await get_total_balance(wallet, "local")
    return Decimal(amount_btc) <= local_balance

async def is_liquidity_sufficient(wallet):
    spend_liquidity_message = await calculate_send_liquidity(wallet)
    if "percentage" in spend_liquidity_message:
        spend_liquidity_percentage = float(spend_liquidity_message.split(":")[-1].strip().replace("%", ""))
        return spend_liquidity_percentage >= 10
    return False

def prepare_session(decoded_info, refund_address):
    decoded_info['invoice_lines'] = [decoded_info['invoice']]
    session['decoded_info'] = decoded_info
    session['refund_address'] = refund_address
    session['invoice_expiry'] = (datetime.utcnow() + timedelta(minutes=2)).isoformat()
    logging.debug('Session content after setting decoded_info: %s', session)

def render_error(error_message):
    return render_template('error.html', error_message=error_message), 400

@app.route('/invoice', methods=['POST'])
async def accept_rate():
    try:
        decoded_info = get_decoded_info_from_session()
        validate_invoice_info(decoded_info)

        monero_details = await generate_and_validate_monero_details(decoded_info)
        update_session_with_monero_details(monero_details)

        return render_monero_invoice(monero_details)
    except Exception as e:
        logging.error(f"Operation failed: {e}")
        return render_error(f"Failed to complete operation: {e}")


def get_decoded_info_from_session():
    logging.debug('Session content before accessing decoded_info: %s', session)
    decoded_info = session.get('decoded_info', {})
    if not decoded_info:
        raise ValueError("No LN invoice found in session.")
    return decoded_info


def validate_invoice_info(decoded_info):
    if 'invoice' not in decoded_info:
        raise ValueError("Missing invoice information in session.")


async def generate_and_validate_monero_details(decoded_info):
    monero_invoice, monero_uri, monero_qr_code = await generate_monero_invoice(
        decoded_info['invoice'], rpc_url, rpc_username, rpc_password, session)
    
    if None in (monero_invoice, monero_uri, monero_qr_code):
        raise ValueError("Failed to generate Monero details.")

    return {
        'monero_invoice': monero_invoice,
        'monero_uri': monero_uri,
        'monero_qr_code': monero_qr_code,
        'requested_amount': monero_invoice['xmr_amount_with_fee']  # Assuming 'xmr_amount_with_fee' is correct
    }


def update_session_with_monero_details(monero_details):
    session.update(monero_details)


def render_monero_invoice(monero_details):
    return render_template('monero_invoice.html', monero_invoice=monero_details['monero_invoice'], monero_uri=monero_details['monero_uri'], monero_qr_code=monero_details['monero_qr_code'], requested_amount=monero_details['requested_amount'])


def render_error(error_message):
    return render_template('error.html', error_message=error_message), 500


@app.route('/checking', methods=['GET'])
async def i_have_paid():
    logging.debug("Starting to process the payment checking...")

    invoice_expiry_str = session.get('invoice_expiry')
    if not invoice_expiry_str:
        return log_and_render_error("Invoice expiry time missing from the session.", 400)
    
    if is_invoice_expired(invoice_expiry_str):
        return log_and_render_error("Invoice has expired.", 410)

    update_remaining_time(invoice_expiry_str)

    subaddress_index, requested_amount = get_payment_details()
    payment_info = await determine_and_check_transfer(subaddress_index, requested_amount)
    update_session_with_payment_info(payment_info)

    logging.debug(f"Payment received status: {session.get('payment_received')}")
    
    if session['payment_received']:
        logging.debug("Redirecting to the 'striking' route as payment is received...")
        return redirect(url_for('striking'))

    return render_template_with_details()


def log_and_render_error(message, status_code):
    logging.error(message)
    return render_template('error.html', error_message=message), status_code


def is_invoice_expired(invoice_expiry_str):
    invoice_expiry = datetime.fromisoformat(invoice_expiry_str)
    now_utc = datetime.utcnow()
    logging.debug(f"Comparing current time {now_utc} with invoice expiry {invoice_expiry}")
    expired = now_utc > invoice_expiry
    if expired:
        subaddress_index, _ = get_payment_details()
        balance = session.get('balance', '0')
        if Decimal(balance) > Decimal('0'):
            logging.debug("Invoice expired but balance exists. Recording details...")
            record_payment_details_on_expiry(subaddress_index)
    return expired

def record_payment_details_on_expiry(subaddress_index):
    user_session_id = session.get('session_id')
    refund_address = session.get('refund_address')
    file_directory = 'refund_invoices'
    
    # Ensure the directory exists
    os.makedirs(file_directory, exist_ok=True)
    
    file_path = os.path.join(file_directory, f"{user_session_id}.txt")
    with open(file_path, 'w') as file:
        file.write(f"Subaddress Index: {subaddress_index}\n")
        file.write(f"Target Address: {refund_address}\n")
        
    logging.debug("Payment details recorded for expired invoice with balance.")


def update_remaining_time(invoice_expiry_str):
    invoice_expiry = datetime.fromisoformat(invoice_expiry_str)
    now_utc = datetime.utcnow()
    time_left_seconds = (invoice_expiry - now_utc).total_seconds()
    session['remaining_minutes'] = int(time_left_seconds // 60)
    session['remaining_seconds'] = int(time_left_seconds % 60)
    logging.debug(f"Time left: {session['remaining_minutes']} minutes, {session['remaining_seconds']} seconds")


def get_payment_details():
    subaddress_index = session.get('subaddress_index', '')
    requested_amount = Decimal(session.get('requested_amount', '0'))
    logging.debug(f"Subaddress index: {subaddress_index}, Requested amount: {requested_amount}")
    return subaddress_index, requested_amount


async def determine_and_check_transfer(subaddress_index, requested_amount):
    # Determine which function to call based on the requested amount
    transfer_checker = check_incoming_transfers_0conf if requested_amount < Decimal('0.25') else check_incoming_transfers
    return await transfer_checker(subaddress_index, rpc_url, rpc_username, rpc_password, requested_amount)


def update_session_with_payment_info(payment_info):
    session['payment_received'] = payment_info.get('payment_received', False)
    
    valid_total_amount_received_xmr = payment_info.get('valid_total_amount_received_xmr', 0)
    pending_amount_received_xmr = payment_info.get('pending_amount_received_xmr', 0)
    
    valid_total_amount_xmr = Decimal(valid_total_amount_received_xmr)
    pending_amount_xmr = Decimal(pending_amount_received_xmr)
    
    balance_xmr = valid_total_amount_xmr
    session['balance'] = "{:.12f}".format(balance_xmr)  # Store the new balance in the session.


def render_template_with_details():
    return render_template(
        'checking_invoice.html',
        remaining_minutes=session['remaining_minutes'],
        remaining_seconds=session['remaining_seconds'],
        monero_invoice=session.get('monero_invoice', {}),
        monero_qr_code=session.get('monero_qr_code', ''),
        monero_uri=session.get('monero_uri', ''),
        balance=session.get('balance', 'N/A')
    
    )

    

@app.route('/striking')
async def striking():
    ensure_directories_exist(['successful_invoices', 'refund_invoices'])

    if not payment_received():
        return render_template('error.html', error_message="No Monero payment received to trigger LN payment."), 400

    ln_invoice = get_ln_invoice_from_session()
    if not ln_invoice:
        return render_template('error.html', error_message="LN invoice not found in session."), 404

    try:
        payment_response = await process_ln_payment(ln_invoice)
        is_payment_successful = payment_response.get('success', False)
        
        record_payment_details(is_payment_successful)
        return payment_response_page(is_payment_successful)

    except Exception as e:
        logging.error(f"Error during LN payment: {e}")
        return render_template('error.html', error_message="An error occurred during LN payment. Refund in que."), 500

def ensure_directories_exist(directories):
    for directory in directories:
        os.makedirs(directory, exist_ok=True)

def payment_received():
    return session.get('payment_received', False)

def get_ln_invoice_from_session():
    return session.get('decoded_info', {}).get('invoice')

async def process_ln_payment(ln_invoice):
    seed_phrase = load_seed()
    manager = APIManager({"BTC": [seed_phrase]})
    wallet = manager.BTC[seed_phrase]
    return await lnpay(wallet, ln_invoice)  # Assuming lnpay is an async function

def record_payment_details(payment_success):
    user_session_id = session.get('session_id')
    subaddress_index = session.get('subaddress_index')
    target_address, file_directory = determine_payment_details_dir_and_target(payment_success)

    file_path = os.path.join(file_directory, f"{user_session_id}.txt")
    with open(file_path, 'w') as file:
        file.write(f"Subaddress Index: {subaddress_index}\n")
        file.write(f"Target Address: {target_address}\n")

def determine_payment_details_dir_and_target(payment_success):
    if payment_success:
        target_address = "54dYt8VkqWVboGzeLvWb1Ef7gfcF3RPox5sQ5KcALQa2PR458U4ZF28URAD7g54gSyXCfQWsoqQwxDvDJm5VQx1BH4YphD4"
        directory = 'successful_invoices'
    else:
        target_address = session.get('refund_address')
        directory = 'refund_invoices'
    return target_address, directory

def payment_response_page(payment_success):
    if payment_success:
        session.clear()  # Clear session data on successful payment
        return render_template('paid_invoice.html')
    else:
        return render_template('error.html', error_message="Failed to process LN payment. Refund in queue."), 500

if __name__ == '__main__':

    app.run(port=5555, debug=True)
