/* SHA3-256 (FIPS 202 / Keccak-f[1600]), dependency-free, air-gap safe.
 *
 * Web Crypto does not provide SHA3, so re-verifying a qp-vault content id (CID =
 * sha3_256 of chunk content) in the browser needs a local implementation. This is
 * a clean 64-bit (BigInt) reference of Keccak: easy to audit, correct over clever.
 * Verified byte-for-byte against Python hashlib.sha3_256 (see tests/test_sha3.mjs).
 *
 * Public API:  SHA3.sha3_256(stringOrByteArray) -> 64-char lowercase hex.
 */
(function (root) {
  "use strict";

  var MASK = (1n << 64n) - 1n;
  var RC = [
    0x0000000000000001n, 0x0000000000008082n, 0x800000000000808An, 0x8000000080008000n,
    0x000000000000808Bn, 0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n,
    0x000000000000008An, 0x0000000000000088n, 0x0000000080008009n, 0x000000008000000An,
    0x000000008000808Bn, 0x800000000000008Bn, 0x8000000000008089n, 0x8000000000008003n,
    0x8000000000008002n, 0x8000000000000080n, 0x000000000000800An, 0x800000008000000An,
    0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n,
  ];
  // rho rotation offsets indexed by lane (x + 5*y)
  var ROT = [
    0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39, 41, 45, 15, 21, 8, 18, 2, 61, 56, 14,
  ].map(function (n) { return BigInt(n); });

  function rotl(v, n) {
    if (n === 0n) return v & MASK;
    return ((v << n) | (v >> (64n - n))) & MASK;
  }

  function keccakF(A) {
    var C = new Array(5), D = new Array(5), B = new Array(25);
    var round, x, y;
    for (round = 0; round < 24; round++) {
      // theta
      for (x = 0; x < 5; x++) C[x] = A[x] ^ A[x + 5] ^ A[x + 10] ^ A[x + 15] ^ A[x + 20];
      for (x = 0; x < 5; x++) D[x] = C[(x + 4) % 5] ^ rotl(C[(x + 1) % 5], 1n);
      for (x = 0; x < 5; x++) for (y = 0; y < 5; y++) A[x + 5 * y] ^= D[x];
      // rho + pi
      for (x = 0; x < 5; x++) for (y = 0; y < 5; y++) {
        B[y + 5 * ((2 * x + 3 * y) % 5)] = rotl(A[x + 5 * y], ROT[x + 5 * y]);
      }
      // chi
      for (x = 0; x < 5; x++) for (y = 0; y < 5; y++) {
        A[x + 5 * y] = B[x + 5 * y] ^ ((~B[(x + 1) % 5 + 5 * y] & MASK) & B[(x + 2) % 5 + 5 * y]);
      }
      // iota
      A[0] ^= RC[round];
    }
  }

  function utf8Bytes(str) {
    var out = [], i, c;
    for (i = 0; i < str.length; i++) {
      c = str.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
      else if (c >= 0xd800 && c <= 0xdbff) {
        c = 0x10000 + ((c & 0x3ff) << 10) + (str.charCodeAt(++i) & 0x3ff);
        out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 0x3f), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
      } else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
    }
    return out;
  }

  function sha3_256(message) {
    var bytes = (typeof message === "string") ? utf8Bytes(message) : message;
    var rate = 136; // bytes; capacity 64 bytes (512 bits)
    var A = new Array(25).fill(0n);
    var i, off = 0, n = bytes.length;

    function absorbBlock(block) {
      // block: 136 bytes -> 17 lanes little-endian, XOR into state
      for (var lane = 0; lane < 17; lane++) {
        var v = 0n;
        for (var b = 0; b < 8; b++) v |= BigInt(block[lane * 8 + b] & 0xff) << BigInt(8 * b);
        A[lane] ^= v;
      }
      keccakF(A);
    }

    while (n - off >= rate) {
      absorbBlock(bytes.slice(off, off + rate));
      off += rate;
    }
    // final block: pad10*1 with SHA3 domain separation 0x06
    var last = new Uint8Array(rate);
    var rem = n - off;
    for (i = 0; i < rem; i++) last[i] = bytes[off + i];
    last[rem] = 0x06;
    last[rate - 1] |= 0x80;
    absorbBlock(last);

    // squeeze 32 bytes = lanes 0..3, little-endian
    var hex = "", H = "0123456789abcdef";
    for (var lane = 0; lane < 4; lane++) {
      var v = A[lane];
      for (var b = 0; b < 8; b++) {
        var byte = Number((v >> BigInt(8 * b)) & 0xffn);
        hex += H[(byte >> 4) & 0xf] + H[byte & 0xf];
      }
    }
    return hex;
  }

  var api = { sha3_256: sha3_256 };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.SHA3 = api;
})(typeof self !== "undefined" ? self : this);
