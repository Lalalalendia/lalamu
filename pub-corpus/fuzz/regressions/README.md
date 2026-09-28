# Retained defensive fuzz regressions

This directory is populated only by the scheduled public defensive fuzz lane.

A retained case must:

- derive from an already-public admitted PUB seed;
- trigger a crash/panic, timeout, signal, or unexpected non-zero exit in a bounded Chaptera public parser/admission target;
- survive deterministic reduction;
- reproduce twice after reduction;
- be named by the SHA-256 of the minimized bytes;
- carry a JSON receipt identifying the public seed, mutation class, target, and failure class.

Ordinary parser rejections are **not** regressions and are not retained.

These files are inert test inputs. They must never contain private/customer bytes, credentials, or licensed Microsoft binaries.
