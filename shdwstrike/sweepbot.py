import os
import asyncio
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from xmr import check_unlocked, sweep_subaddress  # Ensure your 'xmr' module is correctly imported.

# Configure Logging
def setup_logging():
    """
    Setup and configure logging for the application.
    """
    log_file = 'sweep_bot.log'
    handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    handler.setFormatter(formatter)
    logger = logging.getLogger('sweep_bot')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    return logger

logger = setup_logging()

# Application Configuration
CONFIG = {
    'folders_to_scan': ['/root/app4/refund_invoices', '/root/app4/successful_invoices'],
    'rpc_url': "http://127.0.0.1:38083/json_rpc",
    'rpc_username': 'your_rpc_username',
    'rpc_password': 'your_rpc_password',
    'sweep_interval_hours': 1,  # Interval between subsequent sweeps per subaddress
    'sleep_interval': 20 * 60,  # Interval between full folder scans.
    'max_errors': 10
}

# Globals
error_count = 0
last_sweep_attempt = {}

async def process_file(file_path):
    """
    Processes a single file, attempting to sweep if conditions are met.
    """
    global error_count
    try:
        with open(file_path, 'r') as file:
            content = file.read().strip().split('\n')

        if len(content) < 2:
            logger.warning(f"Insufficient content in {file_path}. Skipping.")
            return

        subaddress_index, target_address = parse_file_content(content)
        now = datetime.now()

        # Check if sufficient time has elapsed since the last sweep attempt.
        if subaddress_index in last_sweep_attempt and (now - last_sweep_attempt[subaddress_index]) < timedelta(hours=CONFIG.get('sweep_interval_hours', 1)):
            logger.info(f"Skipping sweep for subaddress index {subaddress_index} due to recent attempt.")
            return

        # Attempt to sweep
        await handle_sweep(subaddress_index, target_address, file_path)
        last_sweep_attempt[subaddress_index] = now  # Update the last attempt time.

    except Exception as e:
        logger.error(f"Error while processing file {file_path}: {e}")
        error_count += 1
        if error_count >= CONFIG['max_errors']:
            logger.critical(f"Max errors reached: {error_count}. Exiting.")
            raise

def parse_file_content(content):
    """
    Extracts and returns subaddress index and target address from file content.
    """
    subaddress_index = content[0].strip().split(':')[-1].strip()
    target_address = content[1].strip().split(':')[-1].strip()
    return int(subaddress_index), target_address

async def handle_sweep(subaddress_index, target_address, file_path):
    """
    Handles the logic to sweep a subaddress if funds are unlocked.
    """
    unlocked, blocks_to_unlock = await check_unlocked(subaddress_index, CONFIG['rpc_url'], CONFIG['rpc_username'], CONFIG['rpc_password'])
    if unlocked:
        logger.info(f"Sweeping funds from subaddress index {subaddress_index} to {target_address}.")
        await sweep_subaddress(subaddress_index, target_address, CONFIG['rpc_url'], CONFIG['rpc_username'], CONFIG['rpc_password'])
        os.remove(file_path)  # Remove processed file
    else:
        logger.info(f"Funds still locked for subaddress index {subaddress_index}. Blocks to unlock: {blocks_to_unlock}")

async def scan_and_sweep():
    """
    Main loop for scanning folders and attempting sweeps.
    """
    global error_count
    try:
        while error_count < CONFIG['max_errors']:
            for folder in CONFIG['folders_to_scan']:
                await process_folder(folder)
                
            logger.debug(f"Sleeping for {CONFIG['sleep_interval']} seconds before next scan.")
            await asyncio.sleep(CONFIG['sleep_interval'])

    except Exception as e:
        logger.error(f"Critical error in scan_and_sweep: {e}")
        error_count += 1
        if error_count >= CONFIG['max_errors']:
            logger.critical(f"Encountered maximum allowed errors: {error_count}. Terminating.")

async def process_folder(folder):
    """
    Processes each file within a specified folder.
    """
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith('.txt')]
    if not files:
        logger.debug(f"No files found in {folder}.")
        return

    logger.info(f"Processing {len(files)} files in {folder}.")
    await asyncio.gather(*(process_file(f) for f in files))

if __name__ == '__main__':
    logger.info("Starting sweep bot...")
    asyncio.run(scan_and_sweep())