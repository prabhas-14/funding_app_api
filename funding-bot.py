from hyperliquid.info import Info
from hyperliquid.utils import constants # For MAINNET_API_URL if needed, though Info might default
import time # To potentially add delays and respect rate limits
import logging

# CHANGE THIS LINE:
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
def initialize_info_client():
    """Initializes and returns the Hyperliquid Info client."""
    try:
        # You can specify the API URL, or it might default to mainnet
        # For testnet, use constants.TESTNET_API_URL
        info = Info(constants.MAINNET_API_URL, skip_ws=True) # skip_ws=True if not using WebSockets for this task
        logging.info("Successfully initialized Hyperliquid Info client.")
        return info
    except Exception as e:
        logging.error(f"Failed to initialize Hyperliquid Info client: {e}")
        return None

def get_all_perpetual_markets(info_client: Info):
    """Fetches and returns the names of all available perpetual markets."""
    if not info_client:
        return []
    try:
        logging.info("Fetching metadata and asset contexts...")
        meta, asset_contexts = info_client.meta_and_asset_ctxs()
        
        perpetual_markets = []
        processed_names = set() # To keep track of names already added

        # Attempt 1: Try to get names from meta data's "universe"
        # 'meta' usually contains a list of all assets in its 'universe' field
        if meta and "universe" in meta and isinstance(meta["universe"], list):
            for asset_meta_info in meta["universe"]:
                if isinstance(asset_meta_info, dict):
                    # The key for the asset name in meta['universe'] is typically "name"
                    asset_name = asset_meta_info.get("name") 
                    if asset_name and asset_name not in processed_names:
                        perpetual_markets.append(asset_name)
                        processed_names.add(asset_name)
            if perpetual_markets:
                logging.info(f"Extracted {len(perpetual_markets)} market names from meta['universe'].")
        
        # Attempt 2: Try to get names from asset_contexts if not found in meta or to supplement
        # This is useful if asset_contexts is the definitive list of *active* perpetuals with state
        if asset_contexts and isinstance(asset_contexts, list): # Ensure asset_contexts is a list
            initial_count_from_meta = len(perpetual_markets)
            for asset_ctx in asset_contexts:
                if isinstance(asset_ctx, dict): # Ensure each item is a dictionary
                    asset_name = asset_ctx.get("name") # Still trying "name" key for asset_contexts
                    if asset_name and asset_name not in processed_names:
                        perpetual_markets.append(asset_name)
                        processed_names.add(asset_name)
            
            if len(perpetual_markets) > initial_count_from_meta:
                logging.info(f"Extracted {len(perpetual_markets) - initial_count_from_meta} additional/unique market names from asset_contexts.")
            # This specific warning should trigger if asset_contexts was checked but yielded no *new* names via the 'name' key
            elif not processed_names and meta.get("universe") is None : # if meta was also empty and asset_contexts yielded nothing
                 logging.warning("Asset contexts were found, but no asset names could be extracted using 'name' key.")
                 logging.debug(f"Problematic asset_contexts (first 3 items): {asset_contexts[:3]}")


        if perpetual_markets:
            logging.info(f"Final list of {len(perpetual_markets)} unique perpetual markets. First few: {perpetual_markets[:5]}")
            return perpetual_markets # Already unique due to processed_names set
        else:
            logging.warning("Could not identify any perpetual markets from either meta['universe'] or asset_contexts.")
            # Detailed debug output if absolutely no markets are found
            if meta is not None and 'universe' in meta:
                 logging.debug(f"meta['universe'] (first 3 items): {meta['universe'][:3] if isinstance(meta['universe'], list) else meta['universe']}")
            else:
                logging.debug(f"Meta or meta['universe'] is not as expected or empty. Meta: {meta}")
            
            if asset_contexts:
                logging.debug(f"asset_contexts (first 3 items): {asset_contexts[:3] if isinstance(asset_contexts, list) else asset_contexts}")
            else:
                logging.debug(f"asset_contexts is empty or None.")
            return []

    except Exception as e:
        logging.error(f"Error fetching perpetual markets: {e}", exc_info=True) # Log full traceback
        return []
def get_funding_rates(info_client: Info, markets_from_meta_func: list): # 'markets_from_meta_func' are the names like "BTC", "ETH"
    """
    Retrieves current funding rates.
    It uses the fact that meta['universe'] and asset_contexts_with_state are parallel lists.
    """
    if not info_client:
        logging.warning("get_funding_rates called with no client.")
        return {}

    funding_data = {}
    try:
        logging.debug(f"Fetching fresh metadata and asset contexts in get_funding_rates.")
        # Fetch meta and asset_contexts_with_state together to ensure they are aligned
        meta, asset_contexts_with_state = info_client.meta_and_asset_ctxs()

        if not (meta and "universe" in meta and isinstance(meta["universe"], list)):
            logging.error("Meta data or meta['universe'] is not in the expected format.")
            return {}
        
        if not (asset_contexts_with_state and isinstance(asset_contexts_with_state, list)):
            logging.error("asset_contexts_with_state is not a list as expected.")
            return {}

        # Get the authoritative list of names from the fresh meta['universe']
        # These names correspond positionally to the items in asset_contexts_with_state
        current_market_names = []
        for asset_detail in meta["universe"]:
            if isinstance(asset_detail, dict) and asset_detail.get("name"):
                current_market_names.append(asset_detail.get("name"))
            else:
                logging.warning(f"Skipping an item in meta['universe'] as it's not a dict or has no name: {asset_detail}")
        
        if len(current_market_names) != len(asset_contexts_with_state):
            logging.error(
                f"Critical Error: Mismatch in lengths between names from meta ({len(current_market_names)}) "
                f"and asset context states ({len(asset_contexts_with_state)}). "
                "Cannot reliably map funding rates."
            )
            logging.debug(f"Names from meta (first 10): {current_market_names[:10]}")
            logging.debug(f"Asset contexts length: {len(asset_contexts_with_state)}")
            # To see what's in asset_contexts if length mismatches:
            # if asset_contexts_with_state:
            #     logging.debug(f"First item of asset_contexts_with_state: {asset_contexts_with_state[0]}")
            return {}
        
        logging.info(f"Processing {len(current_market_names)} markets with their corresponding states.")

        for i in range(len(current_market_names)):
            market_name = current_market_names[i]
            asset_state_data = asset_contexts_with_state[i] # This is the dict like {'funding': ..., 'openInterest': ...}

            if not isinstance(asset_state_data, dict):
                logging.warning(f"State data for market '{market_name}' (at index {i}) is not a dictionary. Skipping. Data: {asset_state_data}")
                continue

            # From your debug log, the key for the funding rate is "funding"
            # This 'funding' field in Hyperliquid's state objects is typically the 1-hour funding rate.
            hourly_rate_str = asset_state_data.get("funding")

            if hourly_rate_str is not None:
                try:
                    hourly_rate = float(hourly_rate_str)
                    funding_data[market_name] = hourly_rate # This is the direct hourly rate
                    logging.info(f"Market: {market_name}, Hourly Funding Rate: {hourly_rate:.8f}") # Changed to INFO for successful rates
                except ValueError:
                    logging.warning(f"Could not parse funding rate for {market_name}: value '{hourly_rate_str}'")
            else:
                logging.warning(f"Funding rate field 'funding' not found for {market_name} in its state object.")
                logging.debug(f"Full state data for {market_name} (where 'funding' field is missing): {asset_state_data}")
        
        return funding_data
    except Exception as e:
        logging.error(f"Error in get_funding_rates: {e}", exc_info=True)
        return {}


# --- find_top_positive_funding_rates function ---
def find_top_positive_funding_rates(funding_data: dict, top_n: int = 5):
    """
    Identifies the top N markets with the highest positive hourly funding rates
    and calculates their APRs.
    Logs the findings and returns a list of the top N market data.
    """
    positive_funding_markets = []

    # Filter for markets with positive funding rates
    for market, rate in funding_data.items():
        if rate > 0:  # Only consider strictly positive rates
            positive_funding_markets.append({"market": market, "hourly_rate": rate})

    if not positive_funding_markets:
        logging.info("No positive funding rates found at the moment.")
        return []  # Return an empty list if no positive rates

    # Sort the markets by hourly_rate in descending order
    # Using a lambda function to specify the sorting key
    sorted_markets = sorted(
        positive_funding_markets, key=lambda x: x["hourly_rate"], reverse=True
    )

    # Get the top N markets (or fewer if less than N positive rates were found)
    top_markets_to_display = sorted_markets[:top_n]

    logging.info(f"--- Top {len(top_markets_to_display)} Positive Funding Rates ---")
    results_for_return = []
    for entry in top_markets_to_display:
        market_name = entry["market"]
        hourly_rate = entry["hourly_rate"]
        
        # Calculate display percentages
        hourly_percentage = hourly_rate * 100
        # APR = Hourly Rate * 24 hours/day * 365 days/year
        apr = hourly_rate * 24 * 365 * 100 
        
        logging.info(
            f"Market: {market_name:<12} | Hourly: {hourly_percentage:8.4f}% | APR: {apr:8.2f}%"
        )
        results_for_return.append(
            {
                "market": market_name,
                "hourly_rate": hourly_rate,
                "hourly_percentage": hourly_percentage,
                "apr": apr,
            }
        )
    
    # This check is mostly for completeness; if top_markets_to_display is populated, results_for_return will be too.
    if not results_for_return and positive_funding_markets: 
        logging.info("No top positive funding rates to display after processing (this is unexpected if positive rates existed).")
        
    return results_for_return


# --- main function ---
def main():
    logging.info("Starting Hyperliquid Funding Bot...")
    
    # Assumes initialize_info_client() is defined elsewhere in your script
    # and returns an instance of the Hyperliquid Info client or None on failure.
    info_client = initialize_info_client() 

    if not info_client:
        logging.error("Exiting due to Info client initialization failure.")
        return

    # Assumes get_all_perpetual_markets(info_client) is defined elsewhere
    # and returns a list of market names or an empty list.
    perpetual_markets = get_all_perpetual_markets(info_client) 
    
    if perpetual_markets:
        # Assumes get_funding_rates(info_client, market_list) is defined elsewhere
        # and returns a dictionary of {market_name: hourly_rate} or an empty dict.
        funding_rates = get_funding_rates(info_client, perpetual_markets) 
        
        if funding_rates:
            # Call the function to find and log top N funding rates
            top_funding_opportunities = find_top_positive_funding_rates(
                funding_rates, top_n=5  # You can change top_n here if desired
            )
            
            # The find_top_positive_funding_rates function already logs the details.
            # You can add further processing of the 'top_funding_opportunities' list here if needed.
            # For example, you might want to send a notification if a very high APR is found.
            if top_funding_opportunities:
                logging.debug(f"Successfully processed and returned {len(top_funding_opportunities)} top opportunities.")
            # If funding_rates was not empty but had no positive rates, 
            # find_top_positive_funding_rates would have logged it and returned [].
            
        else:
            # This 'else' corresponds to 'if funding_rates:'
            logging.info("No funding rate data was retrieved or available to process.")
    else:
        # This 'else' corresponds to 'if perpetual_markets:'
        logging.warning("No perpetual markets were found to process.")

    logging.info("Hyperliquid Funding Bot run finished.")
if __name__ == "__main__":
    main()

# --- Example of how your full script might start and end ---
# (Ensure your other functions are defined in between)
#
# import logging
# from hyperliquid.info import Info
# from hyperliquid.utils import constants
# import time
#
# # Configure logging (ideally once at the start of your script)
# logging.basicConfig(
#     level=logging.DEBUG,  # Or logging.INFO for less verbose output
#     format='%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s'
# )
#
# def initialize_info_client():
#     # ... your implementation ...
#     pass
#
# def get_all_perpetual_markets(info_client: Info):
#     # ... your implementation ...
#     pass
#
# def get_funding_rates(info_client: Info, markets_from_meta_func: list):
#     # ... your implementation ...
#     pass
#
# # Paste the find_top_positive_funding_rates and main functions here
#
# if __name__ == "__main__":
#     main()
#     # Example for periodic execution:
#     # try:
#     #     while True:
#     #         main()
#     #         logging.info(f"Next check in 60 seconds...")
#     #         time.sleep(60) # Check every 60 seconds
#     # except KeyboardInterrupt:
#     #     logging.info("Bot stopped by user.")