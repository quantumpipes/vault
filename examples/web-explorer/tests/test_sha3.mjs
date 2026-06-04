// SHA3-256 + in-browser verification tests for the web explorer.
// Run: node examples/web-explorer/tests/test_sha3.mjs
//
// Proves (1) sha3.js matches the FIPS 202 / qp-vault SHA3-256 used for content ids,
// and (2) the verifier accepts intact chunks and rejects tampered ones.

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const HERE = dirname(fileURLToPath(import.meta.url));
const { sha3_256 } = require(join(HERE, "..", "sha3.js"));

// Known-answer vectors (FIPS 202 SHA3-256), independently published.
const VECTORS = [
  ["", "a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a"],
  ["abc", "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532"],
  ["The quick brown fox jumps over the lazy dog",
    "69070dda01975c8c120c3aada1b282394e7f032fa9cf32f4cb2259a0897dfc04"],
];

test("sha3_256 matches known-answer vectors", () => {
  for (const [input, expected] of VECTORS) {
    assert.equal(sha3_256(input), expected, `vector len=${input.length}`);
  }
});

test("sha3_256 handles unicode and long input deterministically", () => {
  const u = "café ☕ → qp-vault";
  assert.equal(sha3_256(u), sha3_256(u), "deterministic");
  assert.match(sha3_256("x".repeat(10000)), /^[0-9a-f]{64}$/);
});

// Load the committed governance sample the same way the browser does.
globalThis.window = {};
require(join(HERE, "..", "manifest.sample.js"));
const W = globalThis.window;

function verify(chunks, hash) {
  let ok = 0;
  for (const c of chunks) if ("vault://sha3-256/" + sha3_256(c.c) === c.h) ok++;
  const rec = sha3_256(chunks.map((c) => c.h).slice().sort().join(""));
  return { ok, total: chunks.length, hashOK: rec === hash, all: ok === chunks.length && rec === hash };
}

test("sample manifest exposes governance + chunks", () => {
  assert.ok(Object.keys(W.VAULT_GOV).length >= 5);
  assert.ok(W.VAULT_CHUNKS["CANONICAL/company-handbook.md"]);
});

test("verifier ACCEPTS intact content (every chunk CID re-derives, digest matches)", () => {
  for (const path of W.VAULT_FILES) {
    const ch = W.VAULT_CHUNKS[path];
    if (!ch) continue;
    const v = verify(ch, W.VAULT_GOV[path].hash);
    assert.ok(v.all, `${path} should verify clean: ${JSON.stringify(v)}`);
  }
});

test("verifier REJECTS tampered content (CID no longer re-derives)", () => {
  const path = "CANONICAL/company-handbook.md";
  const g = W.VAULT_GOV[path];
  const tampered = JSON.parse(JSON.stringify(W.VAULT_CHUNKS[path]));
  tampered[0].c += " [silently edited]";
  const v = verify(tampered, g.hash);
  assert.ok(!v.all, "tampered content must fail");
  assert.ok(v.ok < v.total, "a chunk CID must stop matching");
});
