// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Honeybee AgentIdentity
/// @notice Minimal ENS-shaped identity registry for autonomous agents.
/// @dev    ENS proper lives on Ethereum mainnet; Arc has no native ENS.
///         This contract gives us the *useful* primitives of ENS — hierarchical
///         namehash-keyed nodes, owner-controlled mutation, text + addr records —
///         on whatever chain Honeybee settles on. Names registered here are
///         portable to real ENS later: the namehash algorithm is identical.
///
///         Tree shape (one parent, single-tier children for the MVP):
///
///           rootNode = bytes32(0)
///           parentNode = namehash("honeybee.agent")      (set in constructor)
///           agentNode  = keccak256(parentNode, labelhash(label))
///
///         A "label" is the leftmost component of an agent name, e.g.
///         "alpha-trader" in "alpha-trader.honeybee.agent".
contract AgentIdentity {
    // ─────────────────── events ───────────────────
    event ParentSet(bytes32 indexed parentNode, string parentName);
    event AgentRegistered(bytes32 indexed node, string label, address indexed owner);
    event OwnerTransferred(bytes32 indexed node, address indexed oldOwner, address indexed newOwner);
    event AddrChanged(bytes32 indexed node, address indexed addr);
    event TextChanged(bytes32 indexed node, string indexed indexedKey, string key, string value);

    // ─────────────────── storage ──────────────────
    /// @notice Owner of the registry itself; can rotate the parent node.
    address public admin;

    /// @notice Namehash of the parent domain (e.g. namehash("honeybee.agent")).
    bytes32 public parentNode;

    /// @notice Human-readable parent (informational; ENS resolution is by hash).
    string public parentName;

    struct Agent {
        address owner;        // who controls the identity (rotates keys, sets records)
        address addr;         // the agent's operational address (signs attestations)
        string  label;        // leftmost label, for off-chain display
        uint64  registeredAt; // unix seconds
        bool    exists;
    }

    /// @notice node => Agent record. node = keccak256(parentNode, keccak256(bytes(label))).
    mapping(bytes32 => Agent) private _agents;

    /// @notice node => key => text value. Mirrors ENS PublicResolver.text().
    mapping(bytes32 => mapping(string => string)) private _texts;

    /// @notice label hash => node, for reverse-style "does this label exist" lookups.
    mapping(bytes32 => bytes32) public nodeOfLabelHash;

    // ─────────────────── modifiers ────────────────
    modifier onlyAdmin() {
        require(msg.sender == admin, "not admin");
        _;
    }

    modifier onlyOwner(bytes32 node) {
        require(_agents[node].exists, "no such agent");
        require(_agents[node].owner == msg.sender, "not owner");
        _;
    }

    // ─────────────────── constructor ──────────────
    /// @param admin_     Registry admin (can rotate the parent + sudo-register).
    /// @param parentName_ Dotted parent domain. Used only for display + event log;
    ///                    the on-chain key is the namehash computed below.
    constructor(address admin_, string memory parentName_) {
        require(admin_ != address(0), "admin=0");
        admin = admin_;
        bytes32 node = _namehash(parentName_);
        parentNode = node;
        parentName = parentName_;
        emit ParentSet(node, parentName_);
    }

    // ─────────────────── admin ────────────────────
    function setAdmin(address newAdmin) external onlyAdmin {
        require(newAdmin != address(0), "admin=0");
        admin = newAdmin;
    }

    function setParent(string calldata newParentName) external onlyAdmin {
        bytes32 node = _namehash(newParentName);
        parentNode = node;
        parentName = newParentName;
        emit ParentSet(node, newParentName);
    }

    // ─────────────────── registration ─────────────
    /// @notice Register `label` under the parent and assign ownership to `owner`.
    /// @dev    Anyone can register (for the hackathon). To make this gated,
    ///         add `onlyAdmin` or a token-curated allowlist. The `addr` is set
    ///         to `owner` by default so the agent can immediately attest; the
    ///         owner can split keys later via `setAddr`.
    function register(string calldata label, address owner) external returns (bytes32 node) {
        require(owner != address(0), "owner=0");
        require(bytes(label).length > 0 && bytes(label).length <= 64, "bad label length");
        require(!_hasDot(label), "label has dot");

        bytes32 labelHash = keccak256(bytes(label));
        node = keccak256(abi.encodePacked(parentNode, labelHash));
        require(!_agents[node].exists, "label taken");

        _agents[node] = Agent({
            owner: owner,
            addr: owner,
            label: label,
            registeredAt: uint64(block.timestamp),
            exists: true
        });
        nodeOfLabelHash[labelHash] = node;

        emit AgentRegistered(node, label, owner);
        emit AddrChanged(node, owner);
    }

    function transferOwnership(bytes32 node, address newOwner) external onlyOwner(node) {
        require(newOwner != address(0), "owner=0");
        address old = _agents[node].owner;
        _agents[node].owner = newOwner;
        emit OwnerTransferred(node, old, newOwner);
    }

    // ─────────────────── records ──────────────────
    function setAddr(bytes32 node, address addr) external onlyOwner(node) {
        _agents[node].addr = addr;
        emit AddrChanged(node, addr);
    }

    function setText(bytes32 node, string calldata key, string calldata value) external onlyOwner(node) {
        _texts[node][key] = value;
        emit TextChanged(node, key, key, value);
    }

    // ─────────────────── views ────────────────────
    function ownerOf(bytes32 node) external view returns (address) {
        return _agents[node].owner;
    }

    function addrOf(bytes32 node) external view returns (address) {
        return _agents[node].addr;
    }

    function labelOf(bytes32 node) external view returns (string memory) {
        return _agents[node].label;
    }

    function text(bytes32 node, string calldata key) external view returns (string memory) {
        return _texts[node][key];
    }

    function exists(bytes32 node) external view returns (bool) {
        return _agents[node].exists;
    }

    function getAgent(bytes32 node) external view returns (Agent memory) {
        return _agents[node];
    }

    /// @notice Compute the node for a label under the current parent.
    /// @dev    Cheap helper for clients; same math as `register()`.
    function nodeFor(string calldata label) external view returns (bytes32) {
        return keccak256(abi.encodePacked(parentNode, keccak256(bytes(label))));
    }

    // ─────────────────── namehash ─────────────────
    /// @notice ENS-compatible namehash (EIP-137). Empty string -> bytes32(0).
    /// @dev    Pure: lets clients precompute parent / agent nodes without RPC.
    function namehash(string memory name) external pure returns (bytes32) {
        return _namehash(name);
    }

    function _namehash(string memory name) internal pure returns (bytes32 node) {
        bytes memory n = bytes(name);
        if (n.length == 0) return bytes32(0);
        // Split on '.' and hash right-to-left, ENS-style.
        // We scan once and recurse via an in-place pointer.
        node = bytes32(0);
        uint256 end = n.length;
        for (int256 i = int256(n.length) - 1; i >= -1; i--) {
            // treat i == -1 as the leading boundary
            bool atBoundary = (i == -1) || (n[uint256(i)] == 0x2e); // '.'
            if (atBoundary) {
                uint256 start = uint256(i + 1);
                if (end > start) {
                    bytes32 labelHash = _hashSlice(n, start, end);
                    node = keccak256(abi.encodePacked(node, labelHash));
                }
                end = uint256(i);
            }
        }
    }

    function _hashSlice(bytes memory src, uint256 start, uint256 end) private pure returns (bytes32 out) {
        uint256 len = end - start;
        bytes memory buf = new bytes(len);
        for (uint256 k = 0; k < len; k++) {
            buf[k] = src[start + k];
        }
        return keccak256(buf);
    }

    function _hasDot(string calldata s) private pure returns (bool) {
        bytes calldata b = bytes(s);
        for (uint256 i = 0; i < b.length; i++) {
            if (b[i] == 0x2e) return true;
        }
        return false;
    }
}
