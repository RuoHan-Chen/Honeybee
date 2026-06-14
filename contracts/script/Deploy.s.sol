// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {AgentIdentity} from "../src/AgentIdentity.sol";
import {AttestationRegistry} from "../src/AttestationRegistry.sol";

/// @notice Deploys the Honeybee on-chain identity + attestation stack.
///
/// Env vars consumed:
///   DEPLOYER_PRIVATE_KEY  (required)  raw hex private key (with or without 0x)
///   ENS_PARENT            (optional)  parent dotted name, default "honeybee.agent"
///   DEMO_AGENT_LABEL      (optional)  if set, registers this label under parent
///   DEMO_AGENT_OWNER      (optional)  owner of the demo agent (defaults to deployer)
///   DEMO_AGENT_ROLE       (optional)  text record "role"   (default "research")
///   DEMO_AGENT_MODEL      (optional)  text record "model"  (default "claude-sonnet-4-5")
///   DEMO_AGENT_DESC       (optional)  text record "description"
///
/// Run:
///   forge script script/Deploy.s.sol:Deploy \
///     --rpc-url $ARC_RPC_URL \
///     --broadcast \
///     -vvv
contract Deploy is Script {
    function run() external returns (AgentIdentity identity, AttestationRegistry registry) {
        uint256 pk = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address deployer = vm.addr(pk);

        string memory parent = _envOr("ENS_PARENT", "honeybee.agent");

        vm.startBroadcast(pk);

        identity = new AgentIdentity(deployer, parent);
        registry = new AttestationRegistry(address(identity));

        // Optional: register a demo agent so the deployment is immediately usable.
        string memory label = _envOr("DEMO_AGENT_LABEL", "");
        if (bytes(label).length > 0) {
            address owner = _envAddrOr("DEMO_AGENT_OWNER", deployer);
            bytes32 node = identity.register(label, owner);

            // Owner-gated record writes — only works when owner == deployer.
            // If you pass a different DEMO_AGENT_OWNER, set records yourself afterwards.
            if (owner == deployer) {
                identity.setText(node, "role",        _envOr("DEMO_AGENT_ROLE",  "research"));
                identity.setText(node, "model",       _envOr("DEMO_AGENT_MODEL", "claude-sonnet-4-5"));
                string memory desc = _envOr("DEMO_AGENT_DESC", "");
                if (bytes(desc).length > 0) identity.setText(node, "description", desc);
            }

            console2.log("Demo agent registered:");
            console2.log("  label:", label);
            console2.log("  owner:", owner);
            console2.log("  node :", vm.toString(node));
        }

        vm.stopBroadcast();

        console2.log("");
        console2.log("=== Honeybee deployment complete ===");
        console2.log("AgentIdentity      :", address(identity));
        console2.log("AttestationRegistry:", address(registry));
        console2.log("Parent             :", parent);
        console2.log("Parent node        :", vm.toString(identity.parentNode()));
        console2.log("Deployer           :", deployer);
    }

    function _envOr(string memory key, string memory dflt) internal view returns (string memory) {
        try vm.envString(key) returns (string memory v) { return v; } catch { return dflt; }
    }

    function _envAddrOr(string memory key, address dflt) internal view returns (address) {
        try vm.envAddress(key) returns (address v) { return v; } catch { return dflt; }
    }
}
