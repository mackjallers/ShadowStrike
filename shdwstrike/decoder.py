import decimal
import asyncio
from electrum.lnaddr import lndecode, LnDecodeException
from xmrbtc import get_xmr_btc_price

async def decode_lightning_invoice(invoice):
    """
    Decode a lightning network invoice and calculate the equivalent amount in Monero (XMR) including fees.

    Parameters:
    - invoice (str): The lightning network invoice string to decode.

    Returns:
    - dict: A dictionary containing decoded invoice details and the equivalent XMR amount including fees, if the rate is available.
    
    Raises:
    - ValueError: If there's an error decoding the invoice or if the XMR/BTC rate is not available.
    """
    try:
        decoded_info = lndecode(invoice)
        
        # Extracting necessary details from the decoded invoice
        payment_hash = decoded_info.paymenthash.hex()
        amount_btc = decoded_info.amount
        description = decoded_info.get_description()
        
        # Fetching the XMR/BTC exchange rate
        xmr_btc_rate = await get_xmr_btc_price()
        if xmr_btc_rate is None:
            raise Exception("XMR/BTC rate is not available")
        
        # Calculating the equivalent amount in XMR including the 5% fee
        equivalent_xmr, equivalent_xmr_with_fee = calculate_equivalent_xmr(amount_btc, xmr_btc_rate)

        return {
            'invoice': invoice,
            'payment_hash': payment_hash,
            'amount_btc': amount_btc,
            'description': description,
            'xmr_btc_rate': xmr_btc_rate,
            'equivalent_xmr_with_fee': equivalent_xmr_with_fee
        }
        
    except LnDecodeException as e:
        raise ValueError(f'Error decoding invoice: {str(e)}')
    except Exception as e:
        raise ValueError(f'An unexpected error occurred: {str(e)}')

def calculate_equivalent_xmr(amount_btc, xmr_btc_rate):
    """
    Calculate the equivalent amount in XMR from BTC and apply a 5% fee.

    Parameters:
    - amount_btc (Decimal): The amount in Bitcoin.
    - xmr_btc_rate (float): The exchange rate from XMR to BTC.

    Returns:
    - tuple: The equivalent amount in XMR without fee, and with a 5% fee applied (considering fee).
    """
    equivalent_xmr_without_fee = decimal.Decimal(amount_btc) / decimal.Decimal(xmr_btc_rate)
    fee_percentage = decimal.Decimal('0.05')  # 5% fee
    fee_amount = equivalent_xmr_without_fee * fee_percentage
    equivalent_xmr_with_fee = equivalent_xmr_without_fee + fee_amount

    # Round equivalent_xmr_with_fee to 12 decimals
    equivalent_xmr_with_fee = equivalent_xmr_with_fee.quantize(decimal.Decimal('0.000000000001'))
    
    return equivalent_xmr_without_fee, equivalent_xmr_with_fee

if __name__ == "__main__":
    test_invoice = "<paste_a_lightning_network_invoice_here>"
    asyncio.run(decode_lightning_invoice(test_invoice))