import logging
import requests
import qrcode
from io import BytesIO
import base64
from decimal import Decimal, ROUND_HALF_UP
from decoder import decode_lightning_invoice  # Make sure this import points to the correct location
from xmr import create_monero_address, construct_monero_uri

async def generate_monero_invoice(invoice, rpc_url, rpc_username, rpc_password, session):
    """
    Generates a Monero invoice, Monero URI, and QR code based on a Lightning Network (LN) invoice.
    
    Parameters:
    - invoice (str): The LN invoice to base the Monero invoice on.
    - rpc_url (str): URL for the Monero wallet RPC.
    - rpc_username (str): Username for the RPC service authentication.
    - rpc_password (str): Password for the RPC service authentication.
    - session (dict): A session or similar data structure to cache generated values for reuse.
    
    Returns:
    - tuple: Containing Monero invoice (dict), Monero URI (str), and Monero QR code (base64 str) if generation succeeds, else (None, None, None).
    """
    # Check for pre-existing Monero invoice details in session to avoid re-generation
    if all(key in session for key in ['monero_invoice', 'monero_uri', 'monero_qr_code']):
        return session['monero_invoice'], session['monero_uri'], session['monero_qr_code']

    try:
        decoded_info = await decode_lightning_invoice(invoice)
        xmr_amount_with_fee = calculate_xmr_amount_with_fee(decoded_info)

        subaddress = await create_monero_subaddress(rpc_url, rpc_username, rpc_password, session)
        if not subaddress:
            return None, None, None

        monero_uri = construct_monero_uri(subaddress, xmr_amount_with_fee)
        monero_qr_code = generate_qr_code_base64(monero_uri)

        # Cache the generated values in the session
        monero_invoice = {'subaddress': subaddress, 'xmr_amount_with_fee': xmr_amount_with_fee}
        session.update({'monero_invoice': monero_invoice, 'monero_uri': monero_uri, 'monero_qr_code': monero_qr_code})

        return monero_invoice, monero_uri, monero_qr_code

    except Exception as e:
        logging.error(f"Error during Monero invoice generation: {e}")
        return None, None, None

def calculate_xmr_amount_with_fee(decoded_info):
    """
    Calculate XMR amount including the fee from the decoded invoice information.
    
    Parameters:
    - decoded_info (dict): Information from the decoded Lightning Network invoice.
    
    Returns:
    - Decimal: The XMR amount including a processing fee, quantized with 12 decimal places.
    """
    amount_btc = decoded_info.get('amount_btc')
    xmr_btc_rate = decoded_info.get('xmr_btc_rate')
    xmr_amount = Decimal(amount_btc) / Decimal(xmr_btc_rate)
    fee_percentage = Decimal('0.05')  # Assuming a 5% processing fee
    xmr_amount_with_fee = xmr_amount * (1 + fee_percentage)
    return xmr_amount_with_fee.quantize(Decimal('0.000000000001'), rounding=ROUND_HALF_UP)

async def create_monero_subaddress(rpc_url, rpc_username, rpc_password, session):
    """
    Create a Monero subaddress, caching the generated subaddress in the session.
    
    Parameters:
    - rpc_url, rpc_username, rpc_password (str): Monero RPC authentication details.
    - session (dict): A session or similar to cache the subaddress index.
    
    Returns:
    - str: The generated subaddress if successful, None otherwise.
    """
    try:
        # This assumes an asynchronous function to create a subaddress exists and returns it
        subaddress, subaddress_index = await create_monero_address(rpc_url, rpc_username, rpc_password)
        session['subaddress_index'] = subaddress_index  # Cache subaddress index
        return subaddress
    except Exception as e:
        logging.error(f"Failed to create Monero subaddress: {e}")
        return None

def generate_qr_code_base64(data):
    """
    Generate a QR code as a base64 encoded string for the given data.
    
    Parameters:
    - data (str): Data to encode in the QR code.
    
    Returns:
    - str: Base64 encoded string of the generated QR code image.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=6,  # Adjust size as needed
        border=3,  # Adjust border size as needed
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    img_io = BytesIO()
    img.save(img_io)  # Correct usage; no 'format' argument is needed
    img_io.seek(0)
    return base64.b64encode(img_io.getvalue()).decode('utf-8')


