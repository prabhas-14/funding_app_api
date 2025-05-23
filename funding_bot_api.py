from flask import Flask, jsonify
from flask_cors import CORS
import logging
import time
import pkg_resources 

# Hyperliquid imports
from hyperliquid.info import Info as HyperliquidInfo 
from hyperliquid.utils import constants as hyperliquid_constants 

# CoinGecko import
from pycoingecko import CoinGeckoAPI

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(funcName)s:%(lineno)d - %(message)s')

# Log library versions
try:
    HL_LIB_VERSION = pkg_resources.get_distribution("hyperliquid-python-sdk").version 
    logging.info(f"Using hyperliquid-python-sdk version: {HL_LIB_VERSION}")
except pkg_resources.DistributionNotFound:
    logging.warning("hyperliquid-python-sdk library not found by pkg_resources. Ensure it's installed if you expect version logging.")
except Exception as e:
    logging.error(f"Error getting hyperliquid-python-sdk version: {e}")

try:
    COINGECKO_LIB_VERSION = pkg_resources.get_distribution("pycoingecko").version
    logging.info(f"Using pycoingecko version: {COINGECKO_LIB_VERSION}")
except pkg_resources.DistributionNotFound:
    logging.warning("pycoingecko library not found by pkg_resources. Ensure it's installed.")
except Exception as e:
    logging.error(f"Error getting pycoingecko version: {e}")


# --- Initialize Clients ---
hl_client_global = None 
cg_client_global = None 

def initialize_hyperliquid_client():
    global hl_client_global 
    try:
        hl_client_global = HyperliquidInfo(hyperliquid_constants.MAINNET_API_URL, skip_ws=True)
        logging.info("Successfully initialized Hyperliquid Info client for API.")
        return hl_client_global
    except Exception as e:
        logging.error(f"API: Failed to initialize Hyperliquid Info client: {e}")
        hl_client_global = None
        return None

def initialize_coingecko_client():
    global cg_client_global 
    try:
        cg_client_global = CoinGeckoAPI()
        status = cg_client_global.ping()
        if status.get('gecko_says', '').startswith('(V3) To the Moon!'):
            logging.info("Successfully initialized and pinged CoinGeckoAPI client.")
        else:
            logging.warning(f"CoinGeckoAPI ping was not successful: {status}")
        return cg_client_global
    except Exception as e:
        logging.error(f"API: Failed to initialize CoinGeckoAPI client: {e}")
        cg_client_global = None
        return None

initialize_hyperliquid_client() 
initialize_coingecko_client()   


# --- Hyperliquid Data Fetching Functions (as provided by user) ---
def get_all_perpetual_markets(info_client: HyperliquidInfo):
    if not info_client:
        logging.warning("API (Hyperliquid): get_all_perpetual_markets called with no client.")
        return []
    try:
        logging.debug("API (Hyperliquid): Fetching metadata and asset contexts...")
        meta, _ = info_client.meta_and_asset_ctxs() 
        
        perpetual_markets = []
        if meta and "universe" in meta and isinstance(meta["universe"], list):
            for asset_meta_info in meta["universe"]:
                if isinstance(asset_meta_info, dict):
                    asset_name = asset_meta_info.get("name") 
                    if asset_name:
                        perpetual_markets.append(asset_name)
            logging.info(f"API (Hyperliquid): Extracted {len(perpetual_markets)} market names from meta['universe'].")
        else:
            logging.warning("API (Hyperliquid): Could not identify any perpetual markets from meta['universe'].")
            return []
        return list(set(perpetual_markets)) 
    except Exception as e:
        logging.error(f"API (Hyperliquid): Error fetching perpetual markets: {e}", exc_info=True)
        return []

def get_all_market_details(info_client: HyperliquidInfo):
    if not info_client:
        logging.warning("API (Hyperliquid): get_all_market_details called with no client.")
        return []

    all_market_data_list = []
    try:
        logging.debug("API (Hyperliquid): Fetching fresh metadata and asset contexts in get_all_market_details.")
        meta, asset_contexts_with_state = info_client.meta_and_asset_ctxs()

        if not (meta and "universe" in meta and isinstance(meta["universe"], list)):
            logging.error("API (Hyperliquid): Meta data or meta['universe'] is not in the expected format.")
            return []
        
        if not (asset_contexts_with_state and isinstance(asset_contexts_with_state, list)):
            logging.error("API (Hyperliquid): asset_contexts_with_state is not a list as expected.")
            return []

        current_market_names = []
        for asset_detail in meta["universe"]:
            if isinstance(asset_detail, dict) and asset_detail.get("name"):
                name = asset_detail.get("name")
                current_market_names.append(name)
        
        if len(current_market_names) != len(asset_contexts_with_state):
            logging.error(
                f"API (Hyperliquid): Critical Error: Mismatch in lengths between names from meta ({len(current_market_names)}) "
                f"and asset context states ({len(asset_contexts_with_state)})."
            )
            return []
        
        logging.info(f"API (Hyperliquid): Processing {len(current_market_names)} markets for detailed data.")

        for i in range(len(current_market_names)):
            market_name = current_market_names[i]
            asset_state_data = asset_contexts_with_state[i]

            if not isinstance(asset_state_data, dict):
                logging.warning(f"API (Hyperliquid): State data for market '{market_name}' (at index {i}) is not a dict. Skipping.")
                continue

            hourly_rate_str = asset_state_data.get("funding")
            volume_24h_str = asset_state_data.get("dayNtlVlm") 
            open_interest_str = asset_state_data.get("openInterest")


            market_data_entry = {
                "exchange": "Hyperliquid", 
                "market": market_name + "-PERP", 
                "hourly_percentage": 0.0,
                "apr": 0.0,
                "volume_24h": 0.0, 
                "open_interest": 0.0, 
                "next_funding_time": None, 
                "funding_interval_hours": 1 
            }

            if hourly_rate_str is not None:
                try:
                    hourly_rate_decimal = float(hourly_rate_str)
                    market_data_entry["hourly_percentage"] = hourly_rate_decimal * 100
                    market_data_entry["apr"] = hourly_rate_decimal * 24 * 365 * 100
                except ValueError:
                    logging.warning(f"API (Hyperliquid): Could not parse funding rate for {market_name}: value '{hourly_rate_str}'")
            
            if volume_24h_str is not None:
                try:
                    market_data_entry["volume_24h"] = float(volume_24h_str)
                except ValueError:
                    logging.warning(f"API (Hyperliquid): Could not parse 24h volume for {market_name}: value '{volume_24h_str}'")
            
            if open_interest_str is not None:
                try:
                    market_data_entry["open_interest"] = float(open_interest_str)
                except ValueError:
                    logging.warning(f"API (Hyperliquid): Could not parse open interest for {market_name}: value '{open_interest_str}'")
            
            all_market_data_list.append(market_data_entry)
        
        return all_market_data_list
    except Exception as e:
        logging.error(f"API (Hyperliquid): Error in get_all_market_details: {e}", exc_info=True)
        return []


def get_top_funding_opportunities(all_market_data_list: list, top_n: int = 5):
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

# --- CoinGecko Data Fetching Function (Ensures 1h, 24h, 7d data) ---
def get_coingecko_market_overview(client: CoinGeckoAPI, coins_per_page: int = 250):
    if not client:
        logging.warning("API (CoinGecko): get_coingecko_market_overview called with no client.")
        return []
    
    processed_coins = []
    try:
        logging.info(f"API (CoinGecko): Fetching top {coins_per_page} coins from CoinGecko...")
        coins_market_data = client.get_coins_markets(
            vs_currency='usd',
            order='market_cap_desc',
            per_page=coins_per_page,
            page=1,
            sparkline=True,
            price_change_percentage='1h,24h,7d' # Crucial parameter for 1h, 24h, 7d data
        )

        if not coins_market_data:
            logging.warning("API (CoinGecko): No market data received from CoinGecko.")
            return []

        for rank_idx, coin in enumerate(coins_market_data, 1):
            def get_safe(data, key, default_val=None):
                return data.get(key, default_val)

            market_cap_num = get_safe(coin, 'market_cap', 0.0)
            circulating_supply_num = get_safe(coin, 'circulating_supply', 0.0)
            fdv_num = get_safe(coin, 'fully_diluted_valuation', 0.0) 
            total_volume_num = get_safe(coin, 'total_volume', 0.0)
            
            raw_sparkline = get_safe(coin, 'sparkline_in_7d', {}).get('price', [])
            sampled_sparkline = raw_sparkline[::7] if raw_sparkline and len(raw_sparkline) > 14 else raw_sparkline

            coin_data = {
                "rank": rank_idx, 
                "id": get_safe(coin, 'id'),
                "name": get_safe(coin, 'name'),
                "symbol": get_safe(coin, 'symbol', '').upper(),
                "image": get_safe(coin, 'image'),
                "price": get_safe(coin, 'current_price', 0.0),
                "price_change_percentage_1h": get_safe(coin, 'price_change_percentage_1h_in_currency', 0.0),
                "price_change_percentage_24h": get_safe(coin, 'price_change_percentage_24h_in_currency', 0.0),
                "price_change_percentage_7d": get_safe(coin, 'price_change_percentage_7d_in_currency', 0.0),
                "marketCapNum": market_cap_num,
                "marketCap": f"${market_cap_num:,.0f}", 
                "circulatingSupplyNum": circulating_supply_num,
                "circulatingSupply": f"{circulating_supply_num:,.0f} {get_safe(coin, 'symbol', '').upper()}",
                "fdvNum": fdv_num if fdv_num else 0.0,
                "fdv": f"${fdv_num:,.0f}" if fdv_num else "N/A", 
                "volume_24h": total_volume_num,
                "sparkline_in_7d": {"price": sampled_sparkline } 
            }
            processed_coins.append(coin_data)
        
        logging.info(f"API (CoinGecko): Successfully processed {len(processed_coins)} coins.")
        return processed_coins

    except Exception as e:
        logging.error(f"API (CoinGecko): Error fetching or processing market overview data: {e}", exc_info=True)
        return []


# --- Flask App Setup ---
app = Flask(__name__)
CORS(app) 

# Hyperliquid endpoint (as provided by user)
@app.route('/api/funding-data', methods=['GET'])
def get_hyperliquid_funding_data_endpoint(): 
    global hl_client_global 

    if not hl_client_global:
        logging.info("Hyperliquid client not initialized, attempting to initialize for this request...")
        initialize_hyperliquid_client() 
        if not hl_client_global: 
            logging.error("API Endpoint (Hyperliquid): Hyperliquid client is not available after re-attempt.")
            return jsonify({"error": "Failed to connect to Hyperliquid services"}), 500

    logging.info("API Endpoint: /api/funding-data (Hyperliquid) called")
    all_markets_detailed = get_all_market_details(hl_client_global)
    
    if not all_markets_detailed:
        logging.warning("API Endpoint (Hyperliquid): No market data retrieved.")
        return jsonify({
            "all_markets": [],
            "top_funding_opportunities": [],
            "last_updated_timestamp": time.time(),
            "error_message": "Could not retrieve market data from Hyperliquid."
        }), 200

    top_opportunities = get_top_funding_opportunities(all_markets_detailed, top_n=5)
    response_data = {
        "all_markets": all_markets_detailed,
        "top_funding_opportunities": top_opportunities,
        "last_updated_timestamp": time.time()
    }
    logging.info(f"API (Hyperliquid): Sending data for {len(all_markets_detailed)} markets, {len(top_opportunities)} top opportunities.")
    return jsonify(response_data)

# CoinGecko Market Overview Endpoint
@app.route('/api/market-overview', methods=['GET'])
def get_market_overview_endpoint():
    global cg_client_global
    if not cg_client_global:
        logging.info("CoinGecko client not initialized, attempting to initialize for this request...")
        initialize_coingecko_client()
        if not cg_client_global:
            logging.error("API Endpoint (Market Overview): CoinGecko client is not available after re-attempt.")
            return jsonify({"error": "Failed to connect to CoinGecko services"}), 503 
    
    logging.info("API Endpoint: /api/market-overview called")
    market_overview_data = get_coingecko_market_overview(cg_client_global, coins_per_page=250) 

    if not market_overview_data:
        logging.warning("API Endpoint (Market Overview): No market overview data retrieved from CoinGecko.")
        return jsonify({
            "all_coins": [], 
            "last_updated_timestamp": time.time(),
            "error_message": "Could not retrieve market overview data from CoinGecko."
        }), 200 
    
    response_data = {
        "all_coins": market_overview_data, 
        "last_updated_timestamp": time.time()
    }
    logging.info(f"API (Market Overview): Sending data for {len(market_overview_data)} coins.")
    return jsonify(response_data)


if __name__ == '__main__':
    logging.info("Starting Flask API server...")
    if not hl_client_global:
        logging.warning("Hyperliquid client FAILED to initialize at startup. Endpoint will attempt re-init.")
    if not cg_client_global:
        logging.warning("CoinGecko client FAILED to initialize at startup. Endpoint will attempt re-init.")
            
    app.run(debug=True, port=5001, use_reloader=False)
