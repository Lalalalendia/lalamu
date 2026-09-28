# AIR-EDITOR-PUBLISHER-PARITY-SWEEP-01 — current-shell tranche 2

This tranche re-checks the **current** Chaptera Desktop Editor rather than relying on the older partial parity notes.

**Pinned Chaptera authority:** `HeisLuka/rar@f1ddae8f60c4437dd4a809642c8057f69dac8b6b`, `apps/chaptera-desktop/src/main.rs` blob `f503783c771310998086420a05e06af4e3acda99`.

## Result

Twelve bounded rows: **2 MATCH / 9 MISMATCH / 0 UNKNOWN / 1 CHAPTERA-ONLY**.

| Interaction | Verdict | Classification | Existing owner |
| --- | --- | --- | --- |
| Ordinary object drag | MATCH | shipped | — |
| Shift straight-line drag | MISMATCH | planned capability | EDITOR-MOVE-MODIFIERS-01 |
| Ordinary handle resize | MATCH | shipped | — |
| Ctrl/Shift resize constraints | MISMATCH | planned capability | EDITOR-RESIZE-MODIFIERS-01 |
| Shift-click multi-selection | MISMATCH | current-main delivery drift | EDITOR-DESKTOP-MULTISELECT-RESTORE-01 |
| Canvas Arrow nudge | MISMATCH | current-main delivery drift | EDITOR-DESKTOP-SELECTION-KEYBOARD-RESTORE-01 |
| Canvas Ctrl/Cmd+A | MISMATCH | current-main delivery drift | EDITOR-DESKTOP-SELECTION-KEYBOARD-RESTORE-01 |
| Esc clears object selection | MISMATCH | current-main delivery drift | EDITOR-DESKTOP-SELECTION-KEYBOARD-RESTORE-01 |
| Group/Ungroup reachability | MISMATCH | not-yet-shipped capability | EDITOR-AUTHORED-GROUP-UI-01 |
| Bring/Send z-order | MISMATCH | not-yet-shipped capability | EDITOR-AUTHORED-ZORDER-UI-01 |
| Semantic Copy/Cut/Paste router | MISMATCH | not-yet-shipped capability | EDITOR-CLIPBOARD-01 |
| Search Copy match/full Story | CHAPTERA-ONLY | shipped successor convenience | — |

## Fresh current-main findings

### Object drag

The ordinary drag law is present and coherent. The canvas starts a `MoveTransaction` from the press origin, uses transient preview bounds during motion, and emits one semantic commit on drag stop. That matches Publisher's ordinary "select and drag object" interaction law.

Publisher's **Shift straight-line drag** is not wired in current Chaptera. This is not a new task: `EDITOR-MOVE-MODIFIERS-01` already owns the user-visible constraint, while `AIR-MOVE-SHIFT-AXIS-01` owns the still-undocumented exact axis/tie/mid-drag micro-law.

### Resize

Ordinary handle drag is shipped and matches the base Publisher law.

Publisher separately documents:
- Ctrl = resize around the fixed center;
- Shift on a corner = preserve proportions;
- Ctrl+Shift = combine both.

Current Chaptera's ordinary-object canvas resize route does not consume those modifiers. `EDITOR-RESIZE-MODIFIERS-01` already owns the shell binding and `INTERACTION-RESIZE-CONSTRAINTS-01` the deterministic rectangle math.

### Selection and keyboard delivery drift

`SceneSelectionState` already stores a set plus primary item, but the current reachable canvas route ends through `select_only()`, which clears the set before inserting the hit instance. Shift-click multi-selection is therefore absent from current main even though the semantic selection work exists. This is the exact scope of `EDITOR-DESKTOP-MULTISELECT-RESTORE-01`.

The current top-level update route has Ctrl+O but does not wire:
- canvas Arrow-key nudge;
- canvas Ctrl/Cmd+A object Select All;
- final Esc object-selection clear.

Story text mode still owns unmodified text navigation, which is correct. `EDITOR-DESKTOP-SELECTION-KEYBOARD-RESTORE-01` already owns the focus split and the Alt+Arrow text-object escape hatch; creating another key router would be a duplicate.

### Group, stacking and clipboard

These are **not current-main regressions from supposedly shipped features**.

They are admitted capabilities that still have explicit product owners:

- Group/Ungroup → `EDITOR-AUTHORED-GROUP-UI-01`;
- Bring/Send → `EDITOR-AUTHORED-ZORDER-UI-01`;
- semantic object/text clipboard routing → `EDITOR-CLIPBOARD-01`.

The parity sweep therefore records MISMATCH while preserving their current Waiting/Parked state. It does not open shortcut-only tasks before their underlying product surfaces are admitted.

Current scene hit testing already consumes z/paint order when deciding the topmost object. That is **read/interaction order**, not permission to treat current hit-test order as authored z-order mutation authority.

### Search copy is Chaptera-only

`Copy match` and `Copy full story` are useful recovery/search conveniences. They are not evidence that the semantic Editor clipboard feature is implemented, and they do not need a Publisher analogue.

## Publisher evidence

First-party Microsoft Support used by this tranche:

- Keyboard: https://support.microsoft.com/en-us/publisher/keyboard-shortcuts-in-publisher
- Move: https://support.microsoft.com/en-us/publisher/move-an-object
- Resize: https://support.microsoft.com/en-us/publisher/resize-a-picture-shape-text-box-or-other-object
- Group/Ungroup: https://support.microsoft.com/en-gb/publisher/group-and-ungroup-text-boxes-pictures-and-other-objects-in-publisher
- Z-order: https://support.microsoft.com/en-us/publisher/move-an-object-forward-or-backward
- Copy/Paste objects: https://support.microsoft.com/en-us/publisher/copy-and-paste-objects-in-publisher

## Routing outcome

**Zero duplicate owners created.**

The main useful scheduler result is that current-main delivery drift must remain distinct from unimplemented capability:

- multiselect + selection-keyboard rows are restoration work over already-grounded semantics;
- Group/Z-order/Clipboard remain intentionally gated capability lanes;
- Move/Resize modifier rows have existing interaction/implementation owners;
- no Publisher documentation claim is converted into a PUB wire-format claim.

This tranche is **not** the full every-interaction closure.
