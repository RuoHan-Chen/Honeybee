// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AttestationRegistry} from "../src/AttestationRegistry.sol";

contract AttestationRegistryTest is Test {
    AttestationRegistry r;
    address alice = address(0xA11CE);
    address user  = address(0xBEEF);

    function setUp() public { r = new AttestationRegistry(); }

    function test_attestResearch_idempotent() public {
        bytes32 h = keccak256("research-1");
        vm.prank(alice);
        r.attestResearch(h, "alice.honeybee.agent.eth", "pm-42");
        assertTrue(r.hasResearch(h));
        vm.expectRevert(); vm.prank(alice);
        r.attestResearch(h, "alice.honeybee.agent.eth", "pm-42");
    }

    function test_attestTrade_and_resolve() public {
        bytes32 recId = keccak256("rec-1");
        vm.prank(alice);
        r.attestTrade(recId, user, "pm-42", 0, 512345, 25_000_000);
        assertTrue(r.hasTrade(recId));

        // only original agent can resolve
        vm.expectRevert(); vm.prank(address(0xCAFE));
        r.attestResolution(recId, "YES", 12_500_000);

        vm.prank(alice);
        r.attestResolution(recId, "YES", 12_500_000);
        assertTrue(r.hasResolution(recId));
    }

    function test_rejectsInvalidSide() public {
        vm.prank(alice); vm.expectRevert();
        r.attestTrade(keccak256("rec-2"), user, "pm-42", 2, 500_000, 1_000_000);
    }
}
