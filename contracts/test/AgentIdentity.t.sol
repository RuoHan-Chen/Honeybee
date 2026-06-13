// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AgentIdentity} from "../src/AgentIdentity.sol";

contract AgentIdentityTest is Test {
    AgentIdentity id;
    address admin = address(0xA0);
    address alice = address(0xA11CE);
    address bob   = address(0xB0B);

    function setUp() public {
        id = new AgentIdentity(admin, "honeybee.agent");
    }

    function test_parentNamehash_matchesEns() public view {
        // ENS namehash("honeybee.agent") computed off-chain via the algorithm.
        // We re-derive on-chain via the public pure helper and assert equality.
        bytes32 expected = id.namehash("honeybee.agent");
        assertEq(id.parentNode(), expected);
        // sanity: namehash("") == 0x0
        assertEq(id.namehash(""), bytes32(0));
    }

    function test_register_and_resolve() public {
        bytes32 node = id.register("alpha-trader", alice);
        assertTrue(id.exists(node));
        assertEq(id.ownerOf(node), alice);
        assertEq(id.addrOf(node), alice);
        assertEq(id.labelOf(node), "alpha-trader");

        // nodeFor(label) must agree with what register() returned.
        assertEq(id.nodeFor("alpha-trader"), node);
    }

    function test_register_rejectsDottedLabel() public {
        vm.expectRevert(bytes("label has dot"));
        id.register("alpha.trader", alice);
    }

    function test_register_rejectsDuplicate() public {
        id.register("alpha-trader", alice);
        vm.expectRevert(bytes("label taken"));
        id.register("alpha-trader", bob);
    }

    function test_setAddr_onlyOwner() public {
        bytes32 node = id.register("alpha-trader", alice);
        vm.expectRevert(bytes("not owner"));
        vm.prank(bob);
        id.setAddr(node, bob);

        vm.prank(alice);
        id.setAddr(node, bob);
        assertEq(id.addrOf(node), bob);
        assertEq(id.ownerOf(node), alice); // owner unchanged
    }

    function test_setText_andRead() public {
        bytes32 node = id.register("alpha-trader", alice);
        vm.prank(alice);
        id.setText(node, "role", "research");
        vm.prank(alice);
        id.setText(node, "model", "claude-sonnet-4-5");
        assertEq(id.text(node, "role"), "research");
        assertEq(id.text(node, "model"), "claude-sonnet-4-5");
        assertEq(id.text(node, "missing"), "");
    }

    function test_transferOwnership() public {
        bytes32 node = id.register("alpha-trader", alice);
        vm.prank(alice);
        id.transferOwnership(node, bob);
        assertEq(id.ownerOf(node), bob);
        // alice can no longer set records
        vm.expectRevert(bytes("not owner"));
        vm.prank(alice);
        id.setText(node, "role", "x");
    }
}

contract NamehashVectorsTest is Test {
    AgentIdentity id;
    function setUp() public { id = new AgentIdentity(address(0x1), "honeybee.agent"); }

    function test_namehash_vectors() public view {
        // Vectors from `cast namehash ...` (ENS canonical)
        assertEq(id.namehash(""),           bytes32(0));
        assertEq(id.namehash("eth"),            0x93cdeb708b7545dc668eb9280176169d1c33cfd8ed6f04690a0bcc88a93fc4ae);
        assertEq(id.namehash("honeybee.agent"), 0x145f2f9a89f08492350eda256b7ad83b2239b6165d1281f110229b53d118cbdc);
    }
}
