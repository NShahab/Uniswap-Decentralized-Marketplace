from web3 import Web3
import json
import requests

# اتصال به نود Hardhat که فورک گرفته از Ethereum Mainnet
RPC_URL = "http://127.0.0.1:8545"
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# آدرس متامسک مقصد
MY_ADDRESS = "0xD8e187c840c8A1D320B19281A8AfAf51D161B397"

# نهنگ‌ها و توکن‌ها
WETH_WHALE = "0x06920c9fc643de77b99cbc0356477fa0d394a757"
USDC_WHALE = "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8"

WETH_ADDRESS = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
USDC_ADDRESS = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"

# ABI ساده فقط با متدهای transfer و balanceOf
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]

def impersonate_and_transfer(token_address, whale_address, recipient, amount, decimals):
    token = w3.eth.contract(address=token_address, abi=ERC20_ABI)

    # impersonate account
    requests.post(RPC_URL, json={
        "jsonrpc":"2.0",
        "method":"hardhat_impersonateAccount",
        "params":[whale_address],
        "id":1
    })

    tx = token.functions.transfer(
        recipient,
        int(amount * (10 ** decimals))
    ).build_transaction({
        'from': whale_address,
        'nonce': w3.eth.get_transaction_count(whale_address),
        'gas': 100000,
        'gasPrice': w3.toWei('10', 'gwei')
    })

    tx_hash = w3.eth.send_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"✅ Transferred {amount} tokens from {whale_address[:6]}... to {recipient[:6]}... (tx: {receipt.transactionHash.hex()})")

def set_eth_balance(address, eth_amount):
    hex_balance = hex(w3.to_wei(eth_amount, 'ether'))
    requests.post(RPC_URL, json={
        "jsonrpc":"2.0",
        "method":"hardhat_setBalance",
        "params":[address, hex_balance],
        "id":1
    })
    print(f"✅ Set ETH balance of {address[:6]}... to {eth_amount} ETH")

# اجرای کارها
set_eth_balance(MY_ADDRESS, 100)
impersonate_and_transfer(WETH_ADDRESS, WETH_WHALE, MY_ADDRESS, 100, 18)
impersonate_and_transfer(USDC_ADDRESS, USDC_WHALE, MY_ADDRESS, 1000, 6)
