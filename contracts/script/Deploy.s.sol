// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {AttestationRegistry} from "../src/AttestationRegistry.sol";

contract Deploy is Script {
    function run() external returns (AttestationRegistry registry) {
        uint256 pk = vm.envUint("DEPLOYER_PRIVATE_KEY");
        vm.startBroadcast(pk);
        registry = new AttestationRegistry();
        vm.stopBroadcast();
        console2.log("AttestationRegistry deployed at:", address(registry));
    }
}
