import aiohttp
import json
import logging
import time
from decimal import Decimal, ROUND_HALF_UP

async def fetch_json_rpc_response(session, url, payload, auth):
    """
    Generic function to fetch JSON RPC response.
    
    :param session: An aiohttp session object.
    :param url: URL to make the post request.
    :param payload: JSON payload for the post request.
    :param auth: Authentication details for the request.
    :return: JSON response as a dictionary.
    """
    async with session.post(url, json=payload, auth=auth, headers={'Content-Type': 'application/json'}) as response:
        if response.status == 200:
            return await response.json()
        else:
            raise Exception(f"{response.status} - {await response.text}")



# Ensure logging is properly configured to capture debug messages and errors.
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


async def check_incoming_transfers(subaddress_index, rpc_url, rpc_username, rpc_password, requested_amount_str):
    requested_amount = Decimal(requested_amount_str)  # Convert the requested amount to Decimal.

    # Define the payload for the Monero RPC call.
    payload_get_transfers = {
        "jsonrpc": "2.0",
        "id": "0",
        "method": "get_transfers",
        "params": {
            "in": True, "out": False, "pending": True, "failed": False,
            "pool": True, "filter_by_height": False, 
            "account_index": 0, "subaddr_indices": [subaddress_index],
            "all_accounts": False
        }
    }

    try:
        # Create a session and post a request to the Monero RPC.
        async with aiohttp.ClientSession() as session:
            async with session.post(rpc_url, json=payload_get_transfers, auth=aiohttp.BasicAuth(rpc_username, rpc_password)) as response:
                if response.status == 200:
                    response_data = await response.json()
                    logging.debug("Raw transactions response: %s", response_data)

                    # Process the transactions from 'pool'.
                    pool_transfers = response_data.get('result', {}).get('pool', [])
                    logging.debug(f"Pending (pool) transfers: {pool_transfers}")
                    in_transfers = response_data.get('result', {}).get('in', [])
                    
                    pending_amount_received_atomic = sum(transfer['amount'] for transfer in pool_transfers)
                    pending_amount_received_xmr = Decimal(pending_amount_received_atomic) / Decimal('1e12')
                    
                    valid_transfers = [t for t in in_transfers if t.get('unlock_time', 0) == 0 and not t.get('double_spend_seen', False)]
                    logging.debug(f"Valid transfers: {valid_transfers}")
                    valid_total_amount_received_xmr = sum(Decimal(t['amount']) for t in valid_transfers) / Decimal('1e12')
                    
                    payment_received = valid_total_amount_received_xmr >= requested_amount

                    return {
                        'payment_received': payment_received,
                        'pending_amount_received_xmr': float(pending_amount_received_xmr),
                        'timestamp': int(time.time()),
                        'valid_total_amount_received_xmr': float(valid_total_amount_received_xmr),
                    }
                else:
                    logging.error("Monero RPC request failed with status: %s", response.status)
                    return {'error': f"RPC request failed with status {response.status}"}
    except Exception as e:
        logging.error("Error when checking incoming transfers: %s", e)
        return {'error': str(e)}

async def check_incoming_transfers_0conf(subaddress_index, rpc_url, rpc_username, rpc_password, requested_amount_str):
    requested_amount = Decimal(requested_amount_str)  # Convert the requested amount to Decimal.

    # Payload to check both pending and confirmed transactions to a specific subaddress.
    payload_get_transfers = {
        "jsonrpc": "2.0",
        "id": "0",
        "method": "get_transfers",
        "params": {
            "in": True,
            "pending": True,
            "failed": False,
            "pool": True,
            "filter_by_height": False, 
            "account_index": 0,
            "subaddr_indices": [subaddress_index]
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(rpc_url, json=payload_get_transfers, auth=aiohttp.BasicAuth(rpc_username, rpc_password)) as response:
                if response.status == 200:
                    response_data = await response.json()
                    pool_transfers = response_data.get('result', {}).get('pool', [])
                    in_transfers = response_data.get('result', {}).get('in', [])  # Confirmed incoming transfers.

                    # Considering both pending and confirmed transfers
                    total_transfers = pool_transfers + in_transfers
                    valid_transfers = [t for t in total_transfers if t.get('unlock_time', 0) == 0 and not t.get('double_spend_seen', False)]
                    valid_total_amount_received = sum(Decimal(t['amount']) for t in valid_transfers) / Decimal('1e12')

                    payment_received = valid_total_amount_received >= requested_amount

                    return {
                        'payment_received': payment_received,
                        'timestamp': int(time.time()),
                        'valid_total_amount_received_xmr': float(valid_total_amount_received),
                        # Assuming pending_amount_received_xmr may still be relevant.
                        'pending_amount_received_xmr': float(sum(Decimal(t['amount']) for t in pool_transfers) / Decimal('1e12')),
                    }
                else:
                    return {'error': f"RPC request failed with status {response.status}"}
    except Exception as e:
        return {'error': str(e)}