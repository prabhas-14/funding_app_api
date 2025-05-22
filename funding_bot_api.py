from flask import Flask, jsonify
from flask_cors import CORS
import logging
import time

# --- Your existing Hyperliquid Bot Functions ---
# (Make sure these are in the same file or properly imported if they are in a separate module)
from hyperliquid.info import Info
from hyperliquid.utils import constants

# Configure logging (can be configured once)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s')
# For more detailed Flask/Werkzeug logs during development, you might want DEBUG for the root logger
# logging.getLogger().setLevel(logging.DEBUG)


def initialize_info_client():
    """Initializes and returns the Hyperliquid Info client."""
    try:
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        logging.info("Successfully initialized Hyperliquid Info client for API.")
        return info
    except Exception as e:
        logging.error(f"API: Failed to initialize Hyperliquid Info client: {e}")
        return None

def get_all_perpetual_markets(info_client: Info):
    """Fetches and returns the names of all available perpetual markets."""
    if not info_client:
        return []
    try:
        logging.debug("API: Fetching metadata and asset contexts...")
        meta, _ = info_client.meta_and_asset_ctxs() # We only need meta for names here
        
        perpetual_markets = []
        if meta and "universe" in meta and isinstance(meta["universe"], list):
            for asset_meta_info in meta["universe"]:
                if isinstance(asset_meta_info, dict):
                    asset_name = asset_meta_info.get("name") 
                    if asset_name:
                        perpetual_markets.append(asset_name)
            logging.info(f"API: Extracted {len(perpetual_markets)} market names from meta['universe'].")
        else:
            logging.warning("API: Could not identify any perpetual markets from meta['universe'].")
            return []
        return list(set(perpetual_markets)) # Ensure uniqueness, though meta should be unique
    except Exception as e:
        logging.error(f"API: Error fetching perpetual markets: {e}", exc_info=True)
        return []

def get_all_market_details(info_client: Info):
    """
    Retrieves current funding rates, APR, and volume for all markets.
    Returns a list of dictionaries, one for each market.
    """
    if not info_client:
        logging.warning("API: get_all_market_details called with no client.")
        return []

    all_market_data_list = []
    try:
        logging.debug("API: Fetching fresh metadata and asset contexts in get_all_market_details.")
        meta, asset_contexts_with_state = info_client.meta_and_asset_ctxs()

        if not (meta and "universe" in meta and isinstance(meta["universe"], list)):
            logging.error("API: Meta data or meta['universe'] is not in the expected format.")
            return []
        
        if not (asset_contexts_with_state and isinstance(asset_contexts_with_state, list)):
            logging.error("API: asset_contexts_with_state is not a list as expected.")
            return []

        current_market_names = []
        name_to_meta_map = {} # To store full meta info if needed, like szDecimals
        for asset_detail in meta["universe"]:
            if isinstance(asset_detail, dict) and asset_detail.get("name"):
                name = asset_detail.get("name")
                current_market_names.append(name)
                name_to_meta_map[name] = asset_detail # Store the whole meta dict for the asset
        
        if len(current_market_names) != len(asset_contexts_with_state):
            logging.error(
                f"API: Critical Error: Mismatch in lengths between names from meta ({len(current_market_names)}) "
                f"and asset context states ({len(asset_contexts_with_state)})."
            )
            return []
        
        logging.info(f"API: Processing {len(current_market_names)} markets for detailed data.")

        for i in range(len(current_market_names)):
            market_name = current_market_names[i]
            asset_state_data = asset_contexts_with_state[i]
            # asset_meta_detail = name_to_meta_map.get(market_name, {}) # Get meta details for this asset

            if not isinstance(asset_state_data, dict):
                logging.warning(f"API: State data for market '{market_name}' (at index {i}) is not a dict. Skipping.")
                continue

            hourly_rate_str = asset_state_data.get("funding")
            volume_24h_str = asset_state_data.get("dayNtlVlm") # Notional volume in USD

            market_data_entry = {
                "market": market_name + "-PERP", # Append -PERP for display consistency
                "hourly_percentage": 0.0,
                "apr": 0.0,
                "volume_24h": 0,
                # "open_interest": float(asset_state_data.get("openInterest", "0")) # Example
            }

            if hourly_rate_str is not None:
                try:
                    hourly_rate_decimal = float(hourly_rate_str)
                    market_data_entry["hourly_percentage"] = hourly_rate_decimal * 100
                    market_data_entry["apr"] = hourly_rate_decimal * 24 * 365 * 100
                except ValueError:
                    logging.warning(f"API: Could not parse funding rate for {market_name}: value '{hourly_rate_str}'")
            
            if volume_24h_str is not None:
                try:
                    market_data_entry["volume_24h"] = float(volume_24h_str)
                except ValueError:
                     logging.warning(f"API: Could not parse 24h volume for {market_name}: value '{volume_24h_str}'")
            
            all_market_data_list.append(market_data_entry)
        
        return all_market_data_list
    except Exception as e:
        logging.error(f"API: Error in get_all_market_details: {e}", exc_info=True)
        return []


def get_top_funding_opportunities(all_market_data_list: list, top_n: int = 5):
    """
    Derives top N funding opportunities from the list of all market data.
    """
    if not all_market_data_list:
        return []

    positive_funding_markets = [
        market for market in all_market_data_list if market.get("hourly_percentage", 0) > 0
    ]

    if not positive_funding_markets:
        return []

    sorted_markets = sorted(
        positive_funding_markets, key=lambda x: x["hourly_percentage"], reverse=True
    )
    return sorted_markets[:top_n]

# --- Flask App Setup ---
app = Flask(__name__)
CORS(app) # This will allow requests from your React app (typically on localhost:3000)

# Initialize the client globally or manage its lifecycle appropriately
# For a simple API that fetches on each request, initializing here is okay.
# For higher performance, you might cache data or use a background thread.
info_client = initialize_info_client()

@app.route('/api/funding-data', methods=['GET'])
def get_funding_data_endpoint():
    global info_client # Use the global client

    if not info_client:
        # Attempt to re-initialize if it failed earlier
        info_client = initialize_info_client()
        if not info_client:
            logging.error("API Endpoint: Info client is not available.")
            return jsonify({"error": "Failed to connect to Hyperliquid services"}), 500

    logging.info("API Endpoint: /api/funding-data called")
    
    # Fetch all market details (this now includes rates, APR, volume)
    all_markets_detailed = get_all_market_details(info_client)
    
    if not all_markets_detailed:
        logging.warning("API Endpoint: No detailed market data retrieved.")
        # Return empty lists but still a 200, or an error if appropriate
        return jsonify({
            "all_markets": [],
            "top_funding_opportunities": [],
            "last_updated_timestamp": time.time(),
            "error_message": "Could not retrieve market data from Hyperliquid."
        }), 200 # Or 503 Service Unavailable

    # Derive top funding opportunities from the detailed list
    top_opportunities = get_top_funding_opportunities(all_markets_detailed, top_n=5)

    response_data = {
        "all_markets": all_markets_detailed,
        "top_funding_opportunities": top_opportunities,
        "last_updated_timestamp": time.time() # Unix timestamp
    }
    
    logging.info(f"API Endpoint: Sending data for {len(all_markets_detailed)} markets, {len(top_opportunities)} top opportunities.")
    return jsonify(response_data)

if __name__ == '__main__':
    # Make sure to run this script directly to start the Flask server
    # The Hyperliquid client is initialized once when the app starts.
    # If the client initialization fails, the endpoint will try to re-initialize.
    logging.info("Starting Flask API server for Hyperliquid Funding Data...")
    app.run(debug=True, port=5001, use_reloader=False) # use_reloader=False can be important if client init is costly
