#xmr.py

import asyncio
import aiohttp
import logging
from decimal import Decimal
import requests


def construct_monero_uri(subaddress, xmr_amount_with_fee=None):
    """
    Constructs a Monero URI that can be used for transactions.

    Args:
        subaddress (str): The Monero subaddress to which XMR is to be sent.
        xmr_amount_with_fee (Decimal/str/None): The amount of Monero to send, including the transaction fee. If None, no amount is appended.

    Returns:
        str: A Monero URI string.
    """
    monero_uri = f'monero:{subaddress}'
    if xmr_amount_with_fee is not None:
        monero_uri += f'?tx_amount={xmr_amount_with_fee}'
    return monero_uri

async def create_monero_address(rpc_url, rpc_username, rpc_password):
    """
    Asynchronously creates a Monero subaddress using the Monero daemon RPC interface.

    Args:
        rpc_url (str): The URL of the Monero RPC interface.
        rpc_username (str): The RPC username for authentication.
        rpc_password (str): The RPC password for authentication.

    Returns:
        tuple: A tuple containing the subaddress as the first element and its index as the second element.

    Raises:
        ValueError: If the RPC call fails or returns an unexpected result.
    """
    payload_create_address = {
        "jsonrpc": "2.0",
        "id": "0",
        "method": "create_address",
        "params": {"account_index": 0, "count": 1}
    }

    headers = {'Content-Type': 'application/json'}
    auth = aiohttp.BasicAuth(rpc_username, rpc_password)

    async with aiohttp.ClientSession() as session:
        async with session.post(rpc_url, json=payload_create_address, headers=headers, auth=auth) as response:
            if response.status == 200:
                response_json = await response.json()
                if not response_json:
                    raise ValueError("Error: Empty JSON response received.")
                
                result = response_json.get('result', {})
                subaddress = result.get('addresses', [''])[0]
                subaddress_index = result.get('address_index', -1)
                if not subaddress:
                    raise ValueError("Error: Empty subaddress received.")
                return subaddress, subaddress_index
            else:
                logging.error(f"Error creating Monero address: HTTP status {response.status}")
                logging.error(await response.text())
                raise ValueError(f"Error creating Monero address: HTTP status {response.status}")




async def check_unlocked(subaddress_index, rpc_url, rpc_username, rpc_password):
    """
    Asynchronously checks if there are unlocked funds in a specific Monero subaddress.
    
    This function sends a request to a Monero daemon's JSON RPC interface to query the balance
    and unlocked balance of the given subaddress index within the primary account. It reports
    the current balance, unlocked balance, and how many blocks are needed until the next
    balance unlock, if applicable.
    
    Args:
        subaddress_index (int): Index of the subaddress within the account to be checked.
        rpc_url (str): URL to the Monero daemon's JSON RPC interface.
        rpc_username (str): The RPC username for authentication.
        rpc_password (str): The RPC password for authentication.
    
    Returns:
        tuple: A 2-tuple where the first element is a boolean indicating if there are unlocked funds,
               and the second element is the number of blocks until the funds are unlocked (0 if already unlocked).
               In the event of an error, it returns (False, 0).
    """
    try:
        # Constructing the payload for the RPC request
        payload_get_balance = {
            "jsonrpc": "2.0",
            "id": "0",
            "method": "get_balance",
            "params": {
                "account_index": 0,  # Assuming we're only dealing with the primary account
                "address_indices": [subaddress_index]
            }
        }

        # Using aiohttp ClientSession for the asynchronous POST request
        async with aiohttp.ClientSession() as session:
            async with session.post(rpc_url, json=payload_get_balance,
                                    auth=aiohttp.BasicAuth(rpc_username, rpc_password)) as response_get_balance:
                response_data = await response_get_balance.json()
                
                if 'error' in response_data:
                    # If there's an error in the response, log it and raise an exception
                    message = response_data['error']['message']
                    logging.error(f"RPC error getting balance: {message}")
                    raise ValueError(f"RPC Error getting balance: {message}")
                
                # Extracting balance information from the response
                result_get_balance = response_data.get('result', {})
                subaddress_info = next((subaddr for subaddr in result_get_balance.get('per_subaddress', []) 
                                        if subaddr.get('address_index') == subaddress_index), None)

                if subaddress_info:
                    # Convert the balance and unlocked balance from atomic units to XMR
                    balance = Decimal(subaddress_info.get('balance', 0)) / Decimal(10**12)
                    unlocked_balance = Decimal(subaddress_info.get('unlocked_balance', 0)) / Decimal(10**12)
                    blocks_to_unlock = subaddress_info.get('blocks_to_unlock', 0)
                    
                    
                    return unlocked_balance > 0, blocks_to_unlock
                else:
                    # If no specific subaddress information was found, log an error
                    logging.error("Subaddress info not found.")
                    return False, 0
    
    except Exception as e:
        # Log any unexpected exceptions during execution
        logging.error(f"Exception checking if funds are unlocked: {e}")
        return False, 0


async def sweep_subaddress(subaddress_index, target_address,
                           rpc_url="http://127.0.0.1:38083/json_rpc",
                           rpc_username='your_rpc_username',
                           rpc_password='your_rpc_password'):
    """
    Asynchronously sweeps all funds from a specified subaddress to a target address.

    This function sends an asynchronous RPC request to a Monero daemon to sweep (transfer)
    all available funds from the designated subaddress index of the primary account to a
    specified target address. Additionally, the function retrieves transaction keys for the
    performed transactions.

    Args:
        subaddress_index (int): Index of the subaddress from which funds will be swept.
        target_address (str): Monero address to which the funds will be transferred.
        rpc_url (str, optional): URL to the Monero daemon's JSON RPC interface. Defaults to 'http://127.0.0.1:38083/json_rpc'.
        rpc_username (str, optional): Username for RPC authentication. Defaults to 'your_rpc_username'.
        rpc_password (str, optional): Password for RPC authentication. Defaults to 'your_rpc_password'.

    Side Effects:
        Logs information on the outcome of the sweep operation, including transaction hashes
        if the operation was successful, or an error message if unsuccessful.
    """
    # Construct the payload for the "sweep_all" RPC method.
    payload_sweep = {
        "jsonrpc": "2.0",
        "id": "0",
        "method": "sweep_all",
        "params": {
            "address": target_address,
            "account_index": 0,  # Assuming operation is performed within the primary account.
            "subaddr_indices": [subaddress_index],
            "get_tx_keys": True  # Requesting transaction keys for accountability.
        }
    }

    try:
        # Execute the asynchronous RPC request.
        async with aiohttp.ClientSession() as session:
            async with session.post(rpc_url, json=payload_sweep,
                                    auth=aiohttp.BasicAuth(rpc_username, rpc_password)) as response_sweep:
                response_data = await response_sweep.json()
                
                if 'error' in response_data:
                    message = response_data['error']['message']
                    logging.error(f"Error sweeping funds: {message}")
                    raise ValueError(f"Error sweeping funds: {message}")
                
                # Process and log the transaction hash list from the response.
                tx_hash_list = response_data.get('result', {}).get('tx_hash_list', [])
                if tx_hash_list:
                    logging.info("Sweep transaction successfully sent.")
                    for tx_hash in tx_hash_list:
                        logging.info(f"Transaction Hash: {tx_hash}")
                else:
                    logging.info("No funds to sweep.")
    
    except Exception as e:
        # General exception handling to capture and log unexpected errors.
        logging.error(f"Error sweeping funds: {e}")


async def validate_monero_address(address):
    """
    Asynchronously validates a Monero address using the Monero daemon's RPC interface.

    This function queries the Monero daemon to validate the given address. It checks whether
    the address is valid, integrated, or a subaddress, identifies the net type, and retrieves
    any associated OpenAlias address.

    Args:
        address (str): The Monero address to be validated.

    Returns:
        tuple: A 5-tuple containing the following:
            - valid (bool): True if the address is a valid Monero address, False otherwise.
            - integrated (bool): True if the address is an integrated address, False otherwise.
            - subaddress (bool): True if the address is a subaddress, False otherwise.
            - nettype (str): The network type of the address ('mainnet', 'testnet', or 'stagenet').
            - openalias_address (str): The OpenAlias address, if available. Empty string if not.

    Raises:
        Exception: If there's an issue with the network request or an unexpected error occurs.
    """
    url = "http://127.0.0.1:38083/json_rpc"  # Adjust the URL as necessary
    data = {
        "jsonrpc": "2.0",
        "id": "0",
        "method": "validate_address",
        "params": {
            "address": address
        }
    }
    headers = {'Content-Type': 'application/json'}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    result = result.get('result', {})
                    return (
                        result.get('valid', False),
                        result.get('integrated', False),
                        result.get('subaddress', False),
                        result.get('nettype', ''),
                        result.get('openalias_address', '')
                    )
                else:
                    error_message = await response.text()
                    logging.error(f"Error validating address: HTTP {response.status} - {error_message}")
                    raise Exception(f"Error validating address: HTTP {response.status}")

    except Exception as e:
        logging.error(f"Exception occurred during request: {e}")
        raise  # Re-raise exception to handle it outside or log it appropriately.