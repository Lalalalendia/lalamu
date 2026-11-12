# AIR-EDITOR-PUBLISHER-PARITY-SWEEP-01 — current-shell tranche 1

This tranche checks current Chaptera Desktop source, not stale feature claims.

**Pinned Chaptera authority:** `HeisLuka/rar@8751688f1509397f4d2c591e6f7b12d6a9fed4a5`, `apps/chaptera-desktop/src/main.rs` blob `f503783c771310998086420a05e06af4e3acda99`.

Publisher interaction evidence is first-party Microsoft Support:
- Keyboard shortcuts: https://support.microsoft.com/en-us/publisher/keyboard-shortcuts-in-publisher
- Text-box entry/editing: https://support.microsoft.com/en-us/publisher/add-text-and-link-text-boxes-in-publisher
- Paragraph alignment: https://support.microsoft.com/en-us/publisher/align-text-within-a-text-box
- Master pages: https://support.microsoft.com/en-us/publisher/create-and-edit-master-pages

## Result

Seven bounded interaction rows: **2 MATCH / 5 MISMATCH / 0 UNKNOWN / 0 CHAPTERA-ONLY**.

| Interaction | Verdict | Current Chaptera observation | Existing owner |
| --- | --- | --- | --- |
| Ctrl+O open | MATCH | Global Ctrl+O reaches the PUB picker | — |
| Enter/edit text | MISMATCH | Select text object → explicit **Edit Text** → canvas session; Publisher ordinary flow is directly contextual to the text box | EDITOR-TEXT-SESSION-GESTURES-01 |
| Ctrl+B / Ctrl+I | MISMATCH | No current shell binding/control; modified keys are fenced inside canvas text input | EDITOR-TEXT-RANGE-FORMAT-UI-01 |
| Paragraph Left/Center/Right | MISMATCH | No paragraph controls in current desktop main.rs | EDITOR-PARAGRAPH-ALIGN-UI-01 |
| Ctrl+PageUp / Ctrl+PageDown | MISMATCH | Clickable page navigation exists; keyboard route does not | EDITOR-PAGE-NAV-SHORTCUTS-01 |
| Ctrl+Z / Ctrl+Y | MISMATCH | Undo/Redo buttons and history authority exist; keyboard route does not | EDITOR-DESKTOP-HISTORY-SHORTCUTS-01 |
| Master content read-only on ordinary page | MATCH | Projected instances remain read-only | — |

## Scheduler correction discovered by the sweep

`EDITOR-PARAGRAPH-ALIGN-UI-01` still said **Waiting upstream**, but both named producers are now DONE/Closed:
- `AUTHORING-PARAGRAPH-ALIGN-01`
- `LAYOUT-PARAGRAPH-ALIGN-01`

The UI owner was re-admitted to **Runnable now**. No new paragraph task was created.

## Current-main delivery drift

`EDITOR-TEXT-RANGE-FORMAT-UI-01` is historically DONE, but current `chaptera-desktop/main.rs` contains no Bold/Italic shell control/binding. The sweep records this against the existing owner rather than creating a competing formatting model.

## Master-page fence

Publisher has a separate Master Page editing view and documents that master elements cannot be edited from ordinary publication view. Chaptera's current projected/read-only normal-page behavior therefore matches that specific law.

This tranche does **not** authorize a Ctrl+M binding or fake master editing. Master edit mode is not a currently reachable Chaptera interaction.

## Remaining sweep

This is not the every-interaction closure. Subsequent tranches still need current-main rows for selection/nudge/group/z-order, clipboard, save/reopen/export, image/table interactions, view controls, context modifiers, off-page behavior, and visible error/focus laws.

No documentation result here is a PUB wire-format claim.
