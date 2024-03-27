import asyncio
import json
from websockets import connect
from websockets_proxy import Proxy, proxy_connect

async def get_xmr_btc_price():
    """
    Fetches the exchange rate between XMR and BTC from a provided WebSocket service accessed via a SOCKS5 proxy.
    
    Returns:
        float: The exchange rate of XMR to BTC, rounded to 12 decimal places, or
        None if the information could not be retrieved.
    """
    #I am useing featherwallets onions price oracle needs to change probably 
    ws_uri = "ws://7e6egbawekbkxzkv4244pqeqgoo4axko2imgjbedwnn6s5yb6b7oliqd.onion/ws"
    socks5_proxy_url = 'socks5://127.0.0.1:9050'

    try:
        # Initialize a Proxy object with the SOCKS5 URL
        proxy = Proxy.from_url(socks5_proxy_url)
        
        # Connect to the WebSocket service through the proxy
        async with proxy_connect(ws_uri, proxy=proxy) as websocket:
            # Continuously listen for messages
            while True:
                # Receive and parse the WebSocket message
                message = await websocket.recv()
                data = json.loads(message)
                
                # Check if the received message is the expected 'crypto_rates'
                if 'cmd' in data and data['cmd'] == 'crypto_rates':
                    crypto_rates = data.get('data', [])
                    return calculate_xmr_btc_ratio(crypto_rates)
    except Exception as e:
        print(f"Error encountered: {e}")
        return None

def calculate_xmr_btc_ratio(crypto_rates):
    """
    Calculates the exchange rate of Monero to Bitcoin from the given cryptocurrency rates.
    
    Args:
        crypto_rates (list of dict): A list of dictionaries containing currency symbols and their current prices.
    
    Returns:
        float: The calculated exchange rate, rounded to 12 decimal places, or
        None if the rates for XMR and BTC were not found.
    """
    btc_rate = next((rate['current_price'] for rate in crypto_rates if rate['symbol'] == 'btc'), None)
    xmr_rate = next((rate['current_price'] for rate in crypto_rates if rate['symbol'] == 'xmr'), None)

    if btc_rate and xmr_rate:
        return round(xmr_rate / btc_rate, 12)

    return None

async def display_xmr_btc_price_ratio():
    """
    Main function to fetch the XMR to BTC price ratio and display it.
    """
    ratio = await get_xmr_btc_price()
    if ratio is not None:
        print(f"XMR to BTC Price Ratio: {ratio}")
    else:
        print("Failed to fetch the price ratio.")

if __name__ == "__main__":
    asyncio.run(display_xmr_btc_price_ratio())
