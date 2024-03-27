import argparse
import asyncio
import json
import logging
from decimal import Decimal
from bitcart import APIManager
from bitcart.utils import bitcoins

logging.basicConfig(level=logging.DEBUG)

def load_seed():
    try:
        with open('config.json') as config_file:
            config = json.load(config_file)
            seed_phrase = config.get('seed_phrase')
            if not seed_phrase:
                logging.error("Seed phrase not found in config.json")
                exit()
            return seed_phrase
    except FileNotFoundError:
        logging.error("config.json not found")
        exit()
    except Exception as e:
        logging.error("Error loading seed phrase from config", exc_info=True)
        exit()

async def open_channel(wallet, node_id, amount):
    try:
        txid_output_index = await wallet.open_channel(node_id, amount)
        logging.debug("Channel opened successfully!")
        logging.debug(f"Transaction ID and Output Index: {txid_output_index}")
    except Exception as e:
        logging.error("Error occurred while opening channel", exc_info=True)

async def close_channel(wallet, channel_id):
    try:
        txid = await wallet.close_channel(channel_id)
        logging.debug("Channel closed successfully!")
        logging.debug(f"Transaction ID: {txid}")
    except Exception as e:
        logging.error("Error occurred while closing channel", exc_info=True)

async def list_channels(wallet):
    try:
        channels = await wallet.list_channels()
        logging.debug("List of Lightning Network Channels:")
        for channel in channels:
            logging.debug(channel)
    except Exception as e:
        logging.error("Error occurred while listing channels", exc_info=True)

async def make_deposit(wallet, amount, description=None, expire=None):
    try:
        request_data = await wallet.add_request(amount, description, expire)
        logging.debug("Deposit request created successfully!")

        # Define a helper function to handle Decimal
        def default(obj):
            if isinstance(obj, Decimal):
                return str(obj)  # Convert Decimal to string
            raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

        # Extract and print only the specified fields
        filtered_data = {
            "amount_BTC": request_data.get("amount_BTC", "Not available"),
            "address": request_data.get("address", "Not available"),
            "URI": request_data.get("URI", "Not available")
        }
        print("Invoice Data (Filtered):")
        print(json.dumps(filtered_data, indent=4, default=default))

    except Exception as e:
        logging.error("Error occurred while making deposit request", exc_info=True)

async def lnpay(wallet, invoice):
    try:
        # Assuming wallet.server.lnpay(invoice) returns the full JSON response on success
        response = await wallet.server.lnpay(invoice)
        
        # Print the full JSON response
        print(f"LN Payment Response: {response}")
        
        # Logging the JSON response using logging instead of print for production usage
        logging.debug(f"LN Payment Response: {response}")
        
        # Determine success from the response, assuming 'success' key indicates operation success or not
        # Adjust the key according to the actual structure of your JSON response
        success = response.get('success', False)
        
        logging.debug("Payment successful!" if success else "Payment failed.")
        return response  # Return the full response for further processing or inspection
    except Exception as e:
        logging.error("Error occurred while paying the invoice", exc_info=True)
        # Return False, or consider returning None or an error structure for better error handling
        return {'error': str(e), 'success': False}

async def get_balance(wallet):
    try:
        balance_data = await wallet.balance()
        for balance_type, amount in balance_data.items():
            logging.debug(f"{balance_type.capitalize()}: {amount} BTC")
    except Exception as e:
        logging.error("Error occurred while retrieving balance", exc_info=True)

async def get_total_balance(wallet, balance_type="local"):
    try:
        channels = await wallet.list_channels()
        if balance_type == "local":
            total_balance = sum(int(channel['local_balance']) for channel in channels)
        elif balance_type == "remote":
            total_balance = sum(int(channel['remote_balance']) for channel in channels)
        elif balance_type == "both":
            # Both refers to the sum of both balances, showing overall channel capacity
            total_balance = sum(int(channel['local_balance']) + int(channel['remote_balance']) for channel in channels)
        else:
            logging.error(f"Invalid balance type: {balance_type}")
            return Decimal('0')
        return bitcoins(total_balance)
    except Exception as e:
        logging.error("Error occurred while calculating total balance", exc_info=True)
        return Decimal('0')

async def add_invoice(wallet, amount, description='', expire=15):
    try:
        invoice_data = await wallet.add_invoice(amount, description, expire)
        logging.debug("Invoice created successfully!")
        logging.debug(f"Invoice data: {invoice_data}")
        return invoice_data
    except Exception as e:
        logging.error("Error occurred while creating an invoice", exc_info=True)
        return {}

async def calculate_send_liquidity(wallet):
    try:
        channels = await wallet.list_channels()
        total_local = sum(int(channel['local_balance']) for channel in channels)
        total_remote = sum(int(channel['remote_balance']) for channel in channels)
        total_capacity = total_local + total_remote
        
        if total_capacity > 0:
            percentage_local = (total_local / total_capacity) * 100
        else:
            return "No channels or zero capacity found, cannot calculate liquidity."
        
        return f"Local balance as a percentage of total channel capacity: {percentage_local:.2f}%"
    except Exception as e:
        logging.error("Error occurred while calculating send liquidity", exc_info=True)
        return "Failed to calculate send liquidity."

async def main():
    parser = argparse.ArgumentParser(description="Bitcart BTC Lightning Node CLI Utility")
    parser.add_argument("--open", nargs=2, metavar=("node_id", "amount"), help="Open a LN channel")
    parser.add_argument("--close", metavar="channel_id", help="Close a LN channel")
    parser.add_argument("--list", action="store_true", help="List all LN channels")
    parser.add_argument("--deposit", nargs=1, metavar=("amount",), help="Create a deposit request")
    parser.add_argument("--pay", metavar="invoice", help="Pay a LN invoice")
    parser.add_argument("--balance", action="store_true", help="Get wallet balance")
    parser.add_argument("--total-balance", nargs="?", const="local", default=False, choices=["local", "remote", "both"], help="Get total balance in BTC of all LN channels. Specify 'local', 'remote', or 'both'. Defaults to 'local' if not specified.")
    parser.add_argument("--create-invoice", nargs=2, metavar=("amount", "description"), help="Create a LN invoice")
    parser.add_argument("--send-liquidity", action="store_true", help="Calculate and display the local balance as a percentage of the total channel capacity")
    args = parser.parse_args()
    seed_phrase = load_seed()

    try:
        manager = APIManager({"BTC": [seed_phrase]})
        wallet = manager.BTC[seed_phrase]

        if args.open:
            await open_channel(wallet, *args.open)
        elif args.close:
            await close_channel(wallet, args.close)
        elif args.list:
            await list_channels(wallet)
        elif args.deposit:
            await make_deposit(wallet, *args.deposit)
        elif args.pay:
            await lnpay(wallet, args.pay)
        elif args.balance:
            await get_balance(wallet)
        elif args.total_balance != False:
            balance_type = args.total_balance
            total_balance_btc = await get_total_balance(wallet, balance_type)
            print(f"Total {balance_type.capitalize()} Balance: {total_balance_btc} BTC")
        elif args.create_invoice:
            invoice_data = {}
            amount, description = args.create_invoice
            invoice_data = await add_invoice(wallet, amount, description)
            if 'lightning_invoice' in invoice_data:
                print(f"Created Invoice: {invoice_data['lightning_invoice']}")
            else:
                logging.error("Invoice data does not contain a valid invoice string.")
        elif args.send_liquidity:
            liquidity_message = await calculate_send_liquidity(wallet)
            print(liquidity_message)
       
        else:
            parser.print_help()
            
    except Exception as e:
        logging.error("A general error occurred", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())