// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AgentIdentity} from "./AgentIdentity.sol";

/// @title Honeybee AttestationRegistry
/// @notice Append-only registry of agent research, trades, and resolutions.
/// @dev Deployed once per chain (Arc testnet for the MVP). Anchors are
///      content-addressed so peer agents can short-circuit recompute via
///      `hasResearch(hash)`. Trade and resolution attestations form an
///      auditable reputation history bound to each agent's identity node
///      in `AgentIdentity` — not to a free-text ENS string. That means
///      reputation is non-forgeable: only `identity.addrOf(node)` can
///      attest as `node`.
contract AttestationRegistry {
    // ─────────────────── identity binding ────────
    AgentIdentity public immutable identity;

    constructor(address identity_) {
        require(identity_ != address(0), "identity=0");
        identity = AgentIdentity(identity_);
    }

    // ─────────────────── events ───────────────────
    event ResearchAttested(
        bytes32 indexed researchHash,
        bytes32 indexed agentNode,
        address agent,
        string  label,
        string  marketId,
        uint256 timestamp
    );

    event TradeAttested(
        bytes32 indexed recId,
        bytes32 indexed agentNode,
        address indexed user,
        address agent,
        string  marketId,
        uint8   side,         // 0 = BUY, 1 = SELL
        uint256 priceE6,      // price * 1e6
        uint256 sizeUsdE6,    // notional USD * 1e6
        uint256 timestamp
    );

    event ResolutionAttested(
        bytes32 indexed recId,
        bytes32 indexed agentNode,
        address agent,
        string  resolvedOutcome,
        int256  pnlUsdE6,     // signed
        uint256 timestamp
    );

    // ─────────────────── storage ──────────────────
    mapping(bytes32 => bool)    public hasResearch;
    mapping(bytes32 => bytes32) public researchBy;   // researchHash -> agentNode (first writer)

    mapping(bytes32 => bool)  public hasTrade;
    mapping(bytes32 => Trade) public trades;
    mapping(bytes32 => bool)  public hasResolution;

    struct Trade {
        bytes32 agentNode;
        address agent;
        address user;
        uint8   side;
        uint256 priceE6;
        uint256 sizeUsdE6;
        uint256 timestamp;
        string  marketId;
    }

    // ─────────────────── modifiers ────────────────
    /// @dev Enforces that `msg.sender` is the operational address bound to
    ///      `agentNode` in `AgentIdentity`. Reputation can therefore only
    ///      grow under an identity the caller actually controls.
    modifier asAgent(bytes32 agentNode) {
        require(identity.exists(agentNode), "unknown agent");
        require(identity.addrOf(agentNode) == msg.sender, "not agent addr");
        _;
    }

    // ─────────────────── writes ───────────────────
    /// @notice Anchor a research artifact. Idempotent — first writer wins.
    function attestResearch(
        bytes32 researchHash,
        bytes32 agentNode,
        string calldata marketId
    ) external asAgent(agentNode) {
        require(!hasResearch[researchHash], "research already attested");
        hasResearch[researchHash] = true;
        researchBy[researchHash] = agentNode;
        emit ResearchAttested(
            researchHash,
            agentNode,
            msg.sender,
            identity.labelOf(agentNode),
            marketId,
            block.timestamp
        );
    }

    /// @notice Anchor an executed trade. `recId` MUST be unique per
    ///         recommendation+user — replay-protected.
    function attestTrade(
        bytes32 recId,
        bytes32 agentNode,
        address user,
        string calldata marketId,
        uint8 side,
        uint256 priceE6,
        uint256 sizeUsdE6
    ) external asAgent(agentNode) {
        require(!hasTrade[recId], "trade already attested");
        require(side <= 1, "invalid side");
        require(priceE6 > 0 && priceE6 < 1_000_000, "price out of range");
        hasTrade[recId] = true;
        trades[recId] = Trade({
            agentNode: agentNode,
            agent: msg.sender,
            user: user,
            side: side,
            priceE6: priceE6,
            sizeUsdE6: sizeUsdE6,
            timestamp: block.timestamp,
            marketId: marketId
        });
        emit TradeAttested(
            recId, agentNode, user, msg.sender, marketId, side, priceE6, sizeUsdE6, block.timestamp
        );
    }

    /// @notice Anchor the resolution of a prior trade.
    /// @dev    Only the agent identity that recorded the trade may resolve it.
    function attestResolution(
        bytes32 recId,
        string calldata resolvedOutcome,
        int256 pnlUsdE6
    ) external {
        require(hasTrade[recId], "no such trade");
        require(!hasResolution[recId], "already resolved");
        Trade storage t = trades[recId];
        // Identity check: caller must currently be the operational address
        // for the same agentNode that recorded the trade. This lets agents
        // rotate their signing key (via AgentIdentity.setAddr) without losing
        // the ability to resolve their own historical trades.
        require(identity.addrOf(t.agentNode) == msg.sender, "not agent addr");
        hasResolution[recId] = true;
        emit ResolutionAttested(recId, t.agentNode, msg.sender, resolvedOutcome, pnlUsdE6, block.timestamp);
    }

    // ─────────────────── reads ────────────────────
    function getTrade(bytes32 recId) external view returns (Trade memory) {
        require(hasTrade[recId], "no such trade");
        return trades[recId];
    }
}
