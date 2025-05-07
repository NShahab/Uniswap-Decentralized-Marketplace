#!/bin/bash

# --- Configuration ---
# Project directory on the Linux VPS
PROJECT_DIR="/root/Uniswap-Decentralized-Marketplace/Phase3_Smart_Contract" # <<<=== !!! Verify this path !!!
# Log file for this script's output
LOG_FILE="$PROJECT_DIR/fork_test_run.log"

# Deployment Scripts
DEPLOY_SCRIPT_PREDICTIVE_PATH="$PROJECT_DIR/scripts/deployPredictiveManager.js"
DEPLOY_SCRIPT_BASELINE_PATH="$PROJECT_DIR/scripts/deployMinimal.js"

# Python Test Scripts
PYTHON_SCRIPT_PREDICTIVE_PATH="$PROJECT_DIR/test/predictive/predictive_test.py" # Corrected path
PYTHON_SCRIPT_BASELINE_PATH="$PROJECT_DIR/test/baseline_test.py"             # Verify path

# Address Files (Separate for each contract)
ADDRESS_FILE_PREDICTIVE="$PROJECT_DIR/predictiveManager_address.json"
ADDRESS_FILE_BASELINE="$PROJECT_DIR/baselineMinimal_address.json"

# Python script to fund the deployer wallet
FUNDING_SCRIPT_PATH="$PROJECT_DIR/test/utils/fund_my_wallet.py" # Corrected path

# Local fork RPC URL (Hardhat default)
LOCAL_RPC_URL="http://127.0.0.1:8545"

# Python Virtual Environment Path (adjust if needed)
VENV_ACTIVATE_PATH="$PROJECT_DIR/venv/bin/activate"

# --- Helper Functions ---
log() {
  # Logs a message to both stdout and the LOG_FILE
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

kill_hardhat_node() {
  # Attempts to gracefully stop the Hardhat node, force killing if necessary
  log "Attempting to stop Hardhat node..."
  if pgrep -f 'hardhat node' > /dev/null; then
      log "Found running Hardhat node process(es). Sending SIGTERM..."
      pkill -f 'hardhat node'
      sleep 5
      if pgrep -f 'hardhat node' > /dev/null; then
          log "Node did not terminate gracefully. Sending SIGKILL."
          pkill -9 -f 'hardhat node'
          log "Hardhat node stopped using SIGKILL."
      else
          log "Hardhat node stopped successfully."
      fi
  else
      log "No Hardhat node process found running."
  fi
}

# Function to check script success and exit on failure
check_exit_code() {
  # $1: Exit code of the previous command
  # $2: Error message description
  if [ $1 -ne 0 ]; then
    log "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    log "ERROR: $2 failed (Exit Code: $1). Check $LOG_FILE for details."
    log "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    kill_hardhat_node
    exit 1
  fi
}

# --- Main Script ---
log "=================================================="
log "Starting Fork Test Run (Predictive & Baseline)"
log "=================================================="

# Navigate to the project directory
cd "$PROJECT_DIR" || { log "CRITICAL ERROR: Could not change directory to $PROJECT_DIR"; exit 1; }

# Activate Python virtual environment
if [ -f "$VENV_ACTIVATE_PATH" ]; then
  log "Activating Python virtual environment..."
  source "$VENV_ACTIVATE_PATH"
else
  log "WARNING: Python venv not found at $VENV_ACTIVATE_PATH. Using system python."
fi


# Clean up from previous run
log "Cleaning up previous Hardhat node if any..."
kill_hardhat_node
log "Removing old address files if they exist..."
rm -f "$ADDRESS_FILE_PREDICTIVE"
rm -f "$ADDRESS_FILE_BASELINE"

# Load environment variables from .env file
if [ -f ".env" ]; then
    log "Loading environment variables from .env file..."
    set -o allexport; source .env; set +o allexport
else
    log "WARNING: .env file not found in $PROJECT_DIR."
fi

# Check for necessary environment variables
if [ -z "$MAINNET_RPC_URL" ]; then log "ERROR: MAINNET_RPC_URL not set."; exit 1; fi
if [ -z "$PRIVATE_KEY" ]; then log "ERROR: PRIVATE_KEY not set."; exit 1; fi
if [ -z "$DEPLOYER_ADDRESS" ]; then log "ERROR: DEPLOYER_ADDRESS not set."; exit 1; fi


# 1. Start Hardhat Node with Forking in Background
log "Starting Hardhat node with mainnet fork..."
nohup npx hardhat node --hostname 0.0.0.0 > hardhat_node.log 2>&1 &
HARDHAT_PID=$!
log "Hardhat node started (PID: $HARDHAT_PID). Waiting 40 seconds for boot..."
sleep 40 # Increased wait time

# Check if Hardhat node process exists
if ! kill -0 $HARDHAT_PID 2>/dev/null; then
  log "ERROR: Hardhat node process $HARDHAT_PID is not running after wait. Check hardhat_node.log."
  exit 1
fi
log "Hardhat node process check passed (PID: $HARDHAT_PID)."

# Check if Hardhat node RPC is responsive
log "Checking Hardhat node RPC responsiveness at $LOCAL_RPC_URL..."
if curl --output /dev/null --silent --head --fail --max-time 10 "$LOCAL_RPC_URL"; then
    log "Hardhat node RPC endpoint is responsive."
else
    log "ERROR: Hardhat node RPC ($LOCAL_RPC_URL) NOT responding. Check 'hardhat_node.log'."
    kill_hardhat_node
    exit 1
fi


# 2. Fund Deployer Account
log "Funding deployer account ($DEPLOYER_ADDRESS) using $FUNDING_SCRIPT_PATH..."
python3 "$FUNDING_SCRIPT_PATH" >> "$LOG_FILE" 2>&1
check_exit_code $? "Funding script ($FUNDING_SCRIPT_PATH)"
log "Funding script executed successfully."


# 3. Deploy Predictive Contract
log "Deploying Predictive contract ($DEPLOY_SCRIPT_PREDICTIVE_PATH)..."
npx hardhat run "$DEPLOY_SCRIPT_PREDICTIVE_PATH" --network localhost >> "$LOG_FILE" 2>&1
check_exit_code $? "Predictive contract deployment"
# Verify address file exists
if [ ! -f "$ADDRESS_FILE_PREDICTIVE" ]; then
    log "ERROR: Predictive address file '$ADDRESS_FILE_PREDICTIVE' was not created."
    kill_hardhat_node; exit 1;
fi
log "Predictive contract deployed. Address saved to $ADDRESS_FILE_PREDICTIVE."


# 4. Deploy Baseline Contract
log "Deploying Baseline contract ($DEPLOY_SCRIPT_BASELINE_PATH)..."
npx hardhat run "$DEPLOY_SCRIPT_BASELINE_PATH" --network localhost >> "$LOG_FILE" 2>&1
check_exit_code $? "Baseline contract deployment"
# Verify address file exists
if [ ! -f "$ADDRESS_FILE_BASELINE" ]; then
    log "ERROR: Baseline address file '$ADDRESS_FILE_BASELINE' was not created."
    kill_hardhat_node; exit 1;
fi
log "Baseline contract deployed. Address saved to $ADDRESS_FILE_BASELINE."


# 5. Run Predictive Python Test Script
log "Running Predictive Python test script ($PYTHON_SCRIPT_PREDICTIVE_PATH)..."
export MAINNET_FORK_RPC_URL="$LOCAL_RPC_URL" # Export RPC for Python script
python3 "$PYTHON_SCRIPT_PREDICTIVE_PATH" >> "$LOG_FILE" 2>&1
PYTHON_PREDICTIVE_EXIT_CODE=$? # Save exit code
if [ $PYTHON_PREDICTIVE_EXIT_CODE -ne 0 ]; then
  log "ERROR: Predictive Python test script failed (Exit Code: $PYTHON_PREDICTIVE_EXIT_CODE)."
  # Continue to baseline test even if predictive fails? Set overall error flag.
else
  log "Predictive Python test script finished successfully."
fi


# 6. Run Baseline Python Test Script
log "Running Baseline Python test script ($PYTHON_SCRIPT_BASELINE_PATH)..."
export MAINNET_FORK_RPC_URL="$LOCAL_RPC_URL" # Ensure it's set again if needed
python3 "$PYTHON_SCRIPT_BASELINE_PATH" >> "$LOG_FILE" 2>&1
PYTHON_BASELINE_EXIT_CODE=$? # Save exit code
if [ $PYTHON_BASELINE_EXIT_CODE -ne 0 ]; then
  log "ERROR: Baseline Python test script failed (Exit Code: $PYTHON_BASELINE_EXIT_CODE)."
else
  log "Baseline Python test script finished successfully."
fi


# 7. Stop Hardhat Node
kill_hardhat_node

# Deactivate virtual environment (optional)
if type deactivate &> /dev/null; then
    log "Deactivating Python virtual environment."
    deactivate
fi

log "Fork Test Run Completed."
log "=================================================="

# Final exit code based on test script results
if [ $PYTHON_PREDICTIVE_EXIT_CODE -eq 0 ] && [ $PYTHON_BASELINE_EXIT_CODE -eq 0 ]; then
  exit 0 # Success
else
  exit 1 # Failure
fi