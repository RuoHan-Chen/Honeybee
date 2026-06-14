.PHONY: setup demo wallet api web up test clean contracts-build contracts-test contracts-deploy contracts-deploy-local bootstrap-privy provision-agents agent-loop

NPM := npm --cache .npm-cache

setup:
	python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[dev]"
	$(NPM) install
	cd web && $(NPM) install

wallet:
	$(NPM) run start

api:
	.venv/bin/python -m honeybee.api

demo:
	.venv/bin/python -m honeybee.orchestrator

web:
	cd web && $(NPM) run dev

# Run wallet (8787), orchestrator API (8000), orchestrator loop, and web (3000).
up:
	@echo "Starting all services. Press Ctrl-C to stop."
	@(trap 'kill 0' SIGINT; \
	  $(NPM) run start & \
	  .venv/bin/python -m honeybee.api & \
	  .venv/bin/python -m honeybee.orchestrator & \
	  cd web && $(NPM) run dev & \
	  wait)

test:
	.venv/bin/pytest -q

# ─── on-chain identity + reputation (AgentIdentity + AttestationRegistry) ───
contracts-build:
	cd contracts && forge build

contracts-test:
	cd contracts && forge test -vv

# Deploy to Arc testnet using ARC_RPC_URL + DEPLOYER_PRIVATE_KEY from .env.
# Optionally registers DEMO_AGENT_LABEL with role/model text records.
contracts-deploy:
	@set -a; . ./.env; set +a; \
	cd contracts && forge script script/Deploy.s.sol:Deploy \
	  --rpc-url "$$ARC_RPC_URL" \
	  --broadcast \
	  -vvv

# Deploy to a local anvil for smoke testing the full stack.
# Run `anvil` in another terminal first.
contracts-deploy-local:
	@set -a; . ./.env; set +a; \
	DEPLOYER_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
	ENS_PARENT=honeybee.agent \
	DEMO_AGENT_LABEL=alpha-trader \
	cd contracts && forge script script/Deploy.s.sol:Deploy \
	  --rpc-url http://127.0.0.1:8545 \
	  --broadcast \
	  -vvv

# ─── Privy fleet bootstrap ─────────────────────────────────────────────────
# One-time: generate P-256 auth key, register key quorum, create chain-locked
# policy. Writes PRIVY_AUTH_PRIVATE_KEY / PRIVY_OWNER_KEY_QUORUM_ID /
# PRIVY_POLICY_ID back to .env.
bootstrap-privy:
	@set -a; . ./.env; set +a; \
	./node_modules/.bin/tsx scripts/bootstrap_privy.ts

# Mint Privy wallets for the agent roster, register each on AgentIdentity,
# write text records (role/model/description/privy.wallet_id), fund from
# DEPLOYER_PRIVATE_KEY. Persists var/agents.json for downstream tooling.
provision-agents:
	@set -a; . ./.env; set +a; \
	./node_modules/.bin/tsx scripts/provision_agents.ts

# Run the alpha-trader autonomous loop: every TICK_SEC it pays the analysts
# in USDC via x402 and anchors a blended research attestation on Arc.
# Requires the wallet service (`make wallet`) to be running on :8787.
agent-loop:
	@set -a; . ./.env; set +a; \
	./node_modules/.bin/tsx scripts/agent_loop.ts

clean:
	rm -rf var/*.db __pycache__ .pytest_cache dist node_modules web/node_modules web/.next
