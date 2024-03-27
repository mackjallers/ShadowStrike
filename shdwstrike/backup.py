import asyncio
import argparse
from bitcart import BTC, errors

async def export_channel_backup(btc, channel_point):
    try:
        channel_backup = await btc.server.export_channel_backup(channel_point)
        print(f"Exported Channel Backup: {channel_backup}")
    except Exception as e:
        print(f"Failed to export channel backup: {e}")

async def handle_lightning_operations(btc, channel_point):
    print(f"Node ID: {await btc.node_id}")
    print(f"Invoice: {await btc.add_invoice(0.5, 'Description')}")
    print(f"Peers: {await btc.list_peers()}")
    print(f"Channels: {await btc.list_channels()}")
    
    if channel_point:
        await export_channel_backup(btc, channel_point)

async def main():
    parser = argparse.ArgumentParser(description="Lightning Network Operations CLI")
    parser.add_argument("-xpub", "--xpub", help="Your extended public key or Electrum seed phrase", required=True)
    parser.add_argument("-cp", "--channel_point", help="The channel point for backup export")

    args = parser.parse_args()

    btc = BTC(xpub=args.xpub)
    
    await handle_lightning_operations(btc, args.channel_point)

if __name__ == "__main__":
    asyncio.run(main())