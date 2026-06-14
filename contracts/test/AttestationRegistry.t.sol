// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AttestationRegistry} from "../src/AttestationRegistry.sol";
import {AgentIdentity} from "../src/AgentIdentity.sol";

contract AttestationRegistryTest is Test {
    AgentIdentity id;
    AttestationRegistry r;

    address admin = address(0xA0);
    address alice = address(0xA11CE);   // alpha-trader owner + addr
    address user  = address(0xBEEF);
    address bob   = address(0xB0B);     // not registered

    bytes32 aliceNode;

    function setUp() public {
        id = new AgentIdentity(admin, "honeybee.agent");
        r  = new AttestationRegistry(address(id));
        aliceNode = id.register("alpha-trader", alice);
    }

    function test_attestResearch_idempotent() public {
        bytes32 h = keccak256("research-1");
        vm.prank(alice);
        r.attestResearch(h, aliceNode, "pm-42");
        assertTrue(r.hasResearch(h));
        assertEq(r.researchBy(h), aliceNode);

        vm.expectRevert(bytes("research already attested"));
        vm.prank(alice);
        r.attestResearch(h, aliceNode, "pm-42");
    }

    function test_attestResearch_rejectsUnknownAgent() public {
        bytes32 fakeNode = keccak256("not-a-real-node");
        vm.expectRevert(bytes("unknown agent"));
        vm.prank(alice);
        r.attestResearch(keccak256("r"), fakeNode, "pm-42");
    }

    function test_attestResearch_rejectsWrongCaller() public {
        // bob tries to attest as alice's node — must revert
        vm.expectRevert(bytes("not agent addr"));
        vm.prank(bob);
        r.attestResearch(keccak256("r"), aliceNode, "pm-42");
    }

    function test_attestTrade_and_resolve() public {
        bytes32 recId = keccak256("rec-1");
        vm.prank(alice);
        r.attestTrade(recId, aliceNode, user, "pm-42", 0, 512345, 25_000_000);
        assertTrue(r.hasTrade(recId));

        // only the agent identity that recorded the trade can resolve
        vm.expectRevert(bytes("not agent addr"));
        vm.prank(bob);
        r.attestResolution(recId, "YES", 12_500_000);

        vm.prank(alice);
        r.attestResolution(recId, "YES", 12_500_000);
        assertTrue(r.hasResolution(recId));
    }

    function test_resolveSurvivesKeyRotation() public {
        bytes32 recId = keccak256("rec-rot");
        vm.prank(alice);
        r.attestTrade(recId, aliceNode, user, "pm-42", 1, 400_000, 10_000_000);

        // alice rotates the operational address to bob (still owner)
        vm.prank(alice);
        id.setAddr(aliceNode, bob);

        // alice can no longer resolve; bob (the new addr) can
        vm.expectRevert(bytes("not agent addr"));
        vm.prank(alice);
        r.attestResolution(recId, "NO", -1_000_000);

        vm.prank(bob);
        r.attestResolution(recId, "NO", -1_000_000);
        assertTrue(r.hasResolution(recId));
    }

    function test_rejectsInvalidSide() public {
        vm.expectRevert(bytes("invalid side"));
        vm.prank(alice);
        r.attestTrade(keccak256("rec-2"), aliceNode, user, "pm-42", 2, 500_000, 1_000_000);
    }

    function test_rejectsPriceOutOfRange() public {
        vm.expectRevert(bytes("price out of range"));
        vm.prank(alice);
        r.attestTrade(keccak256("rec-3"), aliceNode, user, "pm-42", 0, 0, 1_000_000);

        vm.expectRevert(bytes("price out of range"));
        vm.prank(alice);
        r.attestTrade(keccak256("rec-4"), aliceNode, user, "pm-42", 0, 1_000_000, 1_000_000);
    }
}
