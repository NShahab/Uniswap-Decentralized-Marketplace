import requests
import time
from web3 import Web3
from decimal import Decimal, getcontext

# Set precision for Decimal calculations
getcontext().prec = 50

# --- Configuration for each network ---
INFURA_PROJECT_ID = "6cb906401b0b4ab4a53beef2c28ba519" # Your Infura Project ID

NETWORKS = {
    "Arbitrum Goerli": {
        # Using Infura RPC for Arbitrum Goerli
        "rpc": f"https://arbitrum-goerli.infura.io/v3/{INFURA_PROJECT_ID}",
        # Using your provided addresses for Arbitrum Goerli initially
        "factory": "0x4893376342d5D7b3e31d4184c08b265e5aB2A3f6", # !! Verify this address for Arb Goerli Uniswap V3 !!
        "weth": "0x980B62Da83eFf3D4576C647993b0c1D7faf17c73",    # !! Verify this address & its decimals (usually 18) !!
        "usdc": "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d",    # !! Verify this address & its decimals (usually 6) !!
        "weth_decimals": 18, # Assuming standard decimals
        "usdc_decimals": 6,  # Assuming standard decimals
        # Unofficial but commonly used subgraph for Arb Goerli
        "subgraph_url": "https://api.thegraph.com/subgraphs/name/ianlapham/arbitrum-goerli-uniswap-v3",
        "chain_name_short": "arb_goerli"
    },
    "Goerli": {
        # Note: Goerli is deprecated. Using Infura RPC for Goerli.
        "rpc": f"https://goerli.infura.io/v3/{INFURA_PROJECT_ID}",
        "factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984", # Standard Goerli Factory
        "weth": "0xB4FBF271143F4FBf7B91A5ded31805e42b2208d6",    # Standard Goerli WETH
        "usdc": "0x07865c6E87B9F70255377e024ace6630C1Eaa37F",    # Standard Goerli USDC
        "weth_decimals": 18,
        "usdc_decimals": 6,
        # Official Goerli subgraph (might be slow/outdated due to deprecation)
        "subgraph_url": "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3-goerli",
         "chain_name_short": "goerli"
    },
    "Sepolia": {
        # Using Infura RPC for Sepolia
        "rpc": f"https://sepolia.infura.io/v3/{INFURA_PROJECT_ID}",
        "factory": "0x0227628f3F023bb0B980b67D528571c95c6DaC1c", # Sepolia Uniswap V3 deployment factory
        "weth": "0x980B62Da83eFf3D4576C647993b0c1D7faf17c73",    # Common Sepolia WETH
        "usdc": "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d",    # Common Sepolia mock USDC
        "weth_decimals": 18,
        "usdc_decimals": 6,
        # Community/Studio subgraph for Sepolia
        "subgraph_url": "https://api.studio.thegraph.com/query/48271/uniswap-v3-sepolia/version/latest",
         "chain_name_short": "sepolia"
    }
}

# --- The rest of the script (ABIs, functions, main) remains the same ---
# ... (Paste the rest of the Python code from the previous response here)

# --- ABIs (Remain the same) ---
FACTORY_ABI = [{
    "inputs": [
        {"internalType": "address", "name": "tokenA", "type": "address"},
        {"internalType": "address", "name": "tokenB", "type": "address"},
        {"internalType": "uint24", "name": "fee", "type": "uint24"}
    ],
    "name": "getPool",
    "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
    "stateMutability": "view",
    "type": "function"
}]

POOL_ABI = [
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}
]

# --- Functions ---

def get_web3_instance(rpc_url):
    """Creates a Web3 instance for the given RPC URL."""
    try:
        return Web3(Web3.HTTPProvider(rpc_url))
    except Exception as e:
        print(f"  [Error] Failed to connect to RPC: {rpc_url} - {e}")
        return None

def checksum_address(address):
    """Converts an address to its checksummed version."""
    try:
        return Web3.to_checksum_address(address)
    except ValueError:
        print(f"  [Warning] Invalid address format: {address}")
        return address # Return original if conversion fails

def check_pool_exists(web3, factory_address, token_a_address, token_b_address, fee):
    """Checks if a pool exists for the given tokens and fee."""
    try:
        factory_address = checksum_address(factory_address)
        token_a_address = checksum_address(token_a_address)
        token_b_address = checksum_address(token_b_address)

        factory = web3.eth.contract(address=factory_address, abi=FACTORY_ABI)
        pool_address = factory.functions.getPool(token_a_address, token_b_address, fee).call()

        if pool_address == "0x0000000000000000000000000000000000000000":
            # Try swapping token order (Uniswap V3 is order-invariant for getPool)
            pool_address = factory.functions.getPool(token_b_address, token_a_address, fee).call()
            if pool_address == "0x0000000000000000000000000000000000000000":
                print(f"  استخر WETH/USDC با کارمزد {fee/10000}% وجود ندارد.")
                return None

        print(f"  استخر پیدا شد! آدرس قرارداد: {pool_address}")
        return pool_address
    except Exception as e:
        print(f"  [Error] خطای Web3 در زمان بررسی وجود استخر: {e}")
        return None

def get_pool_data(web3, pool_address, weth_addr, usdc_addr, weth_decimals, usdc_decimals):
    """Gets basic data (liquidity, price) from the pool contract."""
    try:
        pool_address = checksum_address(pool_address)
        pool = web3.eth.contract(address=pool_address, abi=POOL_ABI)

        # Get liquidity
        liquidity = pool.functions.liquidity().call()

        # Get slot0 data for price calculation
        slot0 = pool.functions.slot0().call()
        sqrt_price_x96 = Decimal(slot0[0])

        # Determine which token is token0 and token1
        token0_address = pool.functions.token0().call()
        # token1_address = pool.functions.token1().call() # Not strictly needed for price calc if we know inputs

        # Calculate raw price (token1/token0)
        price_raw = (sqrt_price_x96 / Decimal(2**96))**2

        # Adjust price based on token decimals
        # Price is Price of Token1 in terms of Token0
        if checksum_address(token0_address) == checksum_address(usdc_addr):
            # Price is WETH/USDC (how many WETH per USDC)
            # We want USDC per WETH, so we invert and adjust decimals
            price_adjusted = (Decimal(1) / price_raw) * (Decimal(10)**(usdc_decimals - weth_decimals))
            price_unit = "USDC per WETH"
        elif checksum_address(token0_address) == checksum_address(weth_addr):
            # Price is USDC/WETH (how many USDC per WETH)
            price_adjusted = price_raw * (Decimal(10)**(usdc_decimals - weth_decimals))
            price_unit = "USDC per WETH"
        else:
            print("  [Warning] Could not determine token0/token1 order for price calculation.")
            price_adjusted = Decimal(0)
            price_unit = "N/A"


        print(f"\n  داده‌های استخر:")
        print(f"  نقدینگی کل (Liquidity): {liquidity}")
        if price_adjusted != 0:
             print(f"  قیمت فعلی: {price_adjusted:.6f} {price_unit}")

        return pool # Return the contract instance if needed later
    except Exception as e:
        print(f"  [Error] خطای Web3 در زمان دریافت داده‌های استخر: {e}")
        return None


def get_24h_volume_thegraph(pool_address, subgraph_url):
    """Gets 24h volume and transaction count from The Graph."""
    # The Graph expects lowercase addresses for IDs
    pool_id = pool_address.lower()

    # Query for pool day data, ordered by date descending, limit 2 to try get yesterday's volume
    # Some subgraphs might not have *exactly* 24h data readily available this way,
    # often `volumeUSD` on the main pool entity represents *all time* volume.
    # We query PoolDayData for potentially more accurate recent volume.
    query = """
    query PoolInfo($poolId: ID!) {
      pool(id: $poolId) {
        volumeUSD
        txCount
        poolDayData(orderBy: date, orderDirection: desc, first: 2) {
          date
          volumeUSD
          txCount
        }
      }
    }
    """
    variables = {"poolId": pool_id}

    try:
        # Adding timeout to requests
        response = requests.post(subgraph_url, json={"query": query, "variables": variables}, timeout=30)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()

        volume_24h = 0
        tx_count_24h = 0
        total_tx_count = 0

        if "errors" in data:
            print(f"  [Error] خطای GraphQL: {data['errors']}")
            return 0, 0 # Return zero values on error

        if "data" in data and data["data"]["pool"]:
            pool_data = data["data"]["pool"]
            total_tx_count = int(pool_data.get("txCount", 0))

            if pool_data.get("poolDayData"):
                day_data = pool_data["poolDayData"]
                if len(day_data) > 0:
                    # Use the most recent day's volume as an approximation for 24h
                    volume_24h = float(day_data[0].get("volumeUSD", 0))
                    tx_count_24h = int(day_data[0].get("txCount", 0))
                else:
                     print("  داده روزانه (PoolDayData) برای این استخر در TheGraph یافت نشد.")
                     # Fallback to total volume if day data is empty (less accurate for 24h)
                     # volume_24h = float(pool_data.get("volumeUSD", 0)) # This is TOTAL volume
            else:
                 print("  فیلد PoolDayData در پاسخ TheGraph وجود ندارد.")

            print(f"\n  آمار تقریبی 24 ساعته (از آخرین داده روزانه):")
            print(f"  حجم معاملات دلاری: ${volume_24h:,.2f}")
            print(f"  تعداد تراکنش‌ها در آن روز: {tx_count_24h}")
            print(f"  تعداد کل تراکنش‌های استخر: {total_tx_count}")
            return volume_24h, tx_count_24h # Return volume and daily tx count

        else:
            print(f"  داده‌ای برای استخر {pool_id} در این ساب‌گراف یافت نشد ({subgraph_url}).")
            return 0, 0

    except requests.exceptions.Timeout:
        print(f"  [Error] Timeout در زمان اتصال به TheGraph: {subgraph_url}")
        return 0, 0
    except requests.exceptions.RequestException as e:
        print(f"  [Error] خطا در دریافت داده از TheGraph: {e}")
        return 0, 0
    except Exception as e:
        print(f"  [Error] خطای ناشناخته در پردازش داده TheGraph: {str(e)}")
        return 0, 0

def main():
    target_fee = 500 # 0.05% fee tier
    results = []

    print("="*50)
    print("شروع بررسی فعالیت استخر WETH/USDC (کارمزد 0.3%) در شبکه‌های تستی...")
    print(f"زمان فعلی: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)

    for network_name, config in NETWORKS.items():
        print(f"\n--- بررسی شبکه: {network_name} ---")

        web3 = get_web3_instance(config["rpc"])
        if not web3 or not web3.is_connected():
            print(f"  اتصال به شبکه {network_name} برقرار نشد. پرش از این شبکه...")
            results.append({"network": network_name, "volume": 0, "tx_count": 0, "pool_address": None, "error": True})
            continue

        print(f"  اتصال به RPC برقرار شد: {config['rpc']}")

        pool_address = check_pool_exists(web3, config["factory"], config["weth"], config["usdc"], target_fee)

        if pool_address:
            # Get on-chain data (optional, but good for confirmation)
            get_pool_data(web3, pool_address, config["weth"], config["usdc"], config["weth_decimals"], config["usdc_decimals"])

            # Get volume from The Graph
            volume, tx_count = get_24h_volume_thegraph(pool_address, config["subgraph_url"])
            results.append({"network": network_name, "volume": volume, "tx_count": tx_count, "pool_address": pool_address, "error": False})
        else:
            # Pool doesn't exist on this network with this fee
            results.append({"network": network_name, "volume": 0, "tx_count": 0, "pool_address": None, "error": False}) # Not an error, just doesn't exist

        # Small delay to avoid rate limiting on public RPCs/Subgraph
        time.sleep(1)

    print("\n" + "="*50)
    print("نتایج نهایی:")
    print("="*50)

    most_active_network = None
    max_volume = -1 # Use -1 to correctly handle cases where all volumes are 0

    if not results:
        print("هیچ شبکه‌ای بررسی نشد.")
        return

    for result in results:
        print(f"\nشبکه: {result['network']}")
        if result["error"]:
            print("  خطا در پردازش این شبکه.")
        elif result["pool_address"] is None:
            print(f"  استخر WETH/USDC با کارمزد {target_fee/10000}% یافت نشد.")
        else:
            print(f"  آدرس استخر: {result['pool_address']}")
            print(f"  حجم تقریبی 24 ساعته: ${result['volume']:,.2f}")
            print(f"  تعداد تراکنش‌های روزانه: {result['tx_count']}")

            # Update most active network based on volume
            if result['volume'] > max_volume:
                max_volume = result['volume']
                most_active_network = result['network']

    print("\n" + "="*50)
    if most_active_network:
        print(f"فعال‌ترین شبکه (بر اساس حجم معاملات تقریبی 24 ساعته): {most_active_network} با حجم ${max_volume:,.2f}")
    else:
        # Check if any pools were found at all
        pools_found = any(r['pool_address'] is not None for r in results)
        if pools_found:
             print("هیچ حجم معامله قابل توجهی در استخرهای یافت شده ثبت نشده است.")
        else:
             print("استخر مورد نظر در هیچ یک از شبکه‌های بررسی شده یافت نشد یا خطایی در اتصال رخ داد.")
    print("="*50)


if __name__ == "__main__":
    # You might need to install web3 and requests:
    # pip install web3 requests
    main()