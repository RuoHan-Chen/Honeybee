// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Honeybee AttestationRegistry
/// @notice Append-only registry of agent research, trades, and resolutions.
/// @dev Deployed once per chain (Arc testnet for the MVP). Anchors are
///      content-addressed so peer agents can short-circuit recompute via
///      `hasResearch(hash)`. Trade and resolution attestations form an
///      auditable reputation history bound to each agent's wallet address.
contract AttestationRegistry {
    // ─────────────────── events ───────────────────
    event ResearchAttested(
        bytes32 indexed researchHash,
        address indexed agent,
        string ens,
        string marketId,
        uint256 timestamp
    );

    event TradeAttested(
        bytes32 indexed recId,
        address indexed agent,
        address indexed user,
        string marketId,
        uint8 side,           // 0 = BUY, 1 = SELL
        uint256 priceE6,      // price * 1e6 (so 0.512345 → 512345)
        uint256 sizeUsdE6,    // notional USD * 1e6
        uint256 timestamp
    );

    event ResolutionAttested(
        bytes32 indexed recId,         // matches a prior TradeAttested.recId
        address indexed agent,
        string resolvedOutcome,
        int256 pnlUsdE6,               // realised PnL (signed) * 1e6
        uint256 timestamp
    );

    // ─────────────────── storage ──────────────────
    mapping(bytes32 => bool) public hasResearch;
    mapping(bytes32 => address) public researchBy;   // hash → agent that anchored first

    mapping(bytes32 => bool) public hasTrade;
    mapping(bytes32 => Trade) public trades;
    mapping(bytes32 => bool) public hasResolution;

    struct Trade {
        address agent;
        address user;
        uint8 side;
        uint256 priceE6;
        uint256 sizeUsdE6;
        uint256 timestamp;
        string marketId;
    }

    // ─────────────────── writes ───────────────────
    /// @notice Anchor a research artifact. Idempotent — first writer wins.
    /// @dev    Other agents calling with the same hash get a cheap revert,
    ///         which they treat as "use the cached blob".
    function attestResearch(
        bytes32 researchHash,
        string calldata ens,
        string calldata marketId
    ) external {
        require(!hasResearch[researchHash], "research already attested");
        hasResearch[researchHash] = true;
        researchBy[researchHash] = msg.sender;
        emit ResearchAttested(researchHash, msg.sender, ens, marketId, block.timestamp);
    }

    /// @notice Anchor an executed trade. `recId` MUST be unique per
    ///         recommendation+user — replay-protected.
    function attestTrade(
        bytes32 recId,
        address user,
        string calldata marketId,
        uint8 side,
        uint256 priceE6,
        uint256 sizeUsdE6
    ) external {
        require(!hasTrade[recId], "trade already attested");
        require(side <= 1, "invalid side");
        require(priceE6 > 0 && priceE6 < 1_000_000, "price out of range");
        hasTrade[recId] = true;
        trades[recId] = Trade({
            agent: msg.sender,
            user: user,
            side: side,
            priceE6: priceE6,
            sizeUsdE6: sizeUsdE6,
            timestamp: block.timestamp,
            marketId: marketId
        });
        emit TradeAttested(recId, msg.sender, user, marketId, side, priceE6, sizeUsdE6, block.timestamp);
    }

    /// @notice Anchor the resolution of a prior trade.
    /// @dev    Only the original attesting agent may resolve. PnL is signed.
    function attestResolution(
        bytes32 recId,
        string calldata resolvedOutcome,
        int256 pnlUsdE6
    ) external {
        require(hasTrade[recId], "no such trade");
        require(!hasResolution[recId], "already resolved");
        require(trades[recId].agent == msg.sender, "only original agent");
        hasResolution[recId] = true;
        emit ResolutionAttested(recId, msg.sender, resolvedOutcome, pnlUsdE6, block.timestamp);
    }

    // ─────────────────── reads ────────────────────
    function getTrade(bytes32 recId) external view returns (Trade memory) {
        require(hasTrade[recId], "no such trade");
        return trades[recId];
    }
}
