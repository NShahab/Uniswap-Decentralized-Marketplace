#!/bin/bash

# --- Helper Functions ---
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# --- Configuration ---
PROJECT_DIR="/root/Uniswap-Decentralized-Marketplace/Phase3_Smart_Contract" # مسیر صحیح پروژه روی VPS لینوکسی
LOG_FILE="$PROJECT_DIR/fork_test_run.log"
ADDRESS_FILE="$PROJECT_DIR/deployed_addresses.json"
PYTHON_SCRIPT_PATH="$PROJECT_DIR/test/predictive/predictive_test.py" # مسیر صحیح اسکریپت پایتون
DEPLOY_SCRIPT_PATH="$PROJECT_DIR/scripts/deployPredictiveManager.js" # مسیر صحیح اسکریپت دیپلوی

# Initial ETH balance for the deployer on the fork (in Wei, hex format)
# Example: 100 ETH = 100 * 10^18 = 100000000000000000000 Wei
# In hex: 0x56BC75E2D63100000
INITIAL_ETH_HEX="0x56BC75E2D63100000" # 100 ETH

# Local fork RPC URL (Hardhat default)
LOCAL_RPC_URL="http://127.0.0.1:8545"

kill_hardhat_node() {
  log "Attempting to stop Hardhat node..."
  # Find process running 'hardhat node' and kill it
  PID=$(pgrep -f 'hardhat node')
  if [ -n "$PID" ]; then
    log "Found Hardhat node process with PID: $PID. Killing..."
    kill "$PID"
    sleep 5 # Wait a bit for the process to terminate
    if kill -0 "$PID" 2>/dev/null; then
      log "Node did not terminate gracefully. Sending SIGKILL."
      kill -9 "$PID"
    else
      log "Hardhat node stopped successfully."
    fi
  else
    log "No Hardhat node process found running."
  fi
}

# --- Main Script ---
log "=================================================="
log "Starting Fork Test Run"
log "=================================================="

# Ensure we are in the project directory
cd "$PROJECT_DIR" || { log "ERROR: Could not change directory to $PROJECT_DIR"; exit 1; }

# Activate Python virtual environment
source "$PROJECT_DIR/venv/bin/activate"

# Clean up previous run (optional)
log "Cleaning up previous Hardhat node if any..."
kill_hardhat_node
rm -f "$ADDRESS_FILE" # Remove old address file

# Load environment variables from .env file
set -o allexport
source .env || log "WARNING: .env file not found or could not be sourced."
set +o allexport

# Check for necessary environment variables
if [ -z "$MAINNET_RPC_URL" ]; then
  log "ERROR: MAINNET_RPC_URL is not set in .env file."
  exit 1
fi
if [ -z "$PRIVATE_KEY" ]; then
  log "ERROR: PRIVATE_KEY is not set in .env file."
  exit 1
fi
if [ -z "$DEPLOYER_ADDRESS" ]; then
  log "ERROR: DEPLOYER_ADDRESS is not set in .env file."
  exit 1
fi

# 1. Start Hardhat Node with Forking in Background
log "Starting Hardhat node with mainnet fork..."
# Using --hostname 0.0.0.0 allows connections from other containers/machines if needed
nohup npx hardhat node --hostname 0.0.0.0 > hardhat_node.log 2>&1 &
HARDHAT_PID=$!
log "Hardhat node started in background with PID: $HARDHAT_PID. Waiting for it to boot..."
sleep 20 # Increased wait time for node and fork initialization

# Check if Hardhat node is running
if ! kill -0 $HARDHAT_PID 2>/dev/null; then
  log "ERROR: Hardhat node failed to start. Check hardhat_node.log."
  exit 1
fi
log "Hardhat node seems to be running."

# 2. Fund Deployer Account on the Fork (using fund_my_wallet.py)
log "Funding deployer account ($DEPLOYER_ADDRESS) with ETH, WETH, and USDC using fund_my_wallet.py..."
python3 test/utils/fund_my_wallet.py >> "$LOG_FILE" 2>&1
FUND_EXIT_CODE=$?
if [ $FUND_EXIT_CODE -ne 0 ]; then
  log "ERROR: fund_my_wallet.py failed (Exit Code: $FUND_EXIT_CODE). Check $LOG_FILE."
  kill_hardhat_node
  exit 1
fi
log "Funding successful (using fund_my_wallet.py)."

# 3. Deploy Contracts
log "Deploying contracts..."
npx hardhat run "$DEPLOY_SCRIPT_PATH" --network localhost >> "$LOG_FILE" 2>&1
DEPLOY_EXIT_CODE=$?

if [ $DEPLOY_EXIT_CODE -ne 0 ]; then
  log "ERROR: Contract deployment failed (Exit Code: $DEPLOY_EXIT_CODE). Check $LOG_FILE."
  kill_hardhat_node
  exit 1
fi

# Check if address file was created
if [ ! -f "$ADDRESS_FILE" ]; then
    log "ERROR: Deployment script finished but address file '$ADDRESS_FILE' was not created."
    kill_hardhat_node
    exit 1
fi

log "Contracts deployed successfully. Address saved to $ADDRESS_FILE."


# 4. Run Python Test Script
log "Running Python test script..."
# Ensure the correct Python environment is activated if needed (e.g., source venv/bin/activate)
# Make sure MAINNET_FORK_RPC_URL is set in .env or environment for the python script
export MAINNET_FORK_RPC_URL="$LOCAL_RPC_URL" # Explicitly set for the python script
python "$PYTHON_SCRIPT_PATH" >> "$LOG_FILE" 2>&1
PYTHON_EXIT_CODE=$?

if [ $PYTHON_EXIT_CODE -ne 0 ]; then
  log "ERROR: Python test script failed (Exit Code: $PYTHON_EXIT_CODE). Check $LOG_FILE and predictive_test.log."
  # Still stop the node even if python fails
  kill_hardhat_node
  exit 1
fi
log "Python test script finished successfully."


# 5. Stop Hardhat Node
kill_hardhat_node

log "Fork Test Run Completed."
log "=================================================="

exit 0