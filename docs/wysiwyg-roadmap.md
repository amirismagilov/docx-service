# WYSIWYG DOCX Roadmap

## Goal
Provide in-browser editing with maximum preservation of Word layout while keeping reliable tag insertion and generation.

## Current constraints
- Plain-text editing cannot round-trip rich DOCX layout.
- Word may split placeholders across runs (`w:t`), which requires run-aware OOXML handling.
- Full DOCX parity in browser is not realistic for first release.

## Target architecture

1. **Two editing modes**
   - `TextTemplateMode`: for empty/plain templates.
   - `DocxTemplateMode`: for uploaded `.docx` templates, preserving binary OOXML.

2. **Server-side canonical source for DOCX mode**
   - Keep original `docx_bytes` as source of truth.
   - Apply placeholder operations directly in OOXML (run-aware).
   - Never rebuild binary templates from plain text.

3. **WYSIWYG layer (incremental)**
   - Start with a constrained editor model (paragraphs, bold/italic, lists, basic tables optional).
   - Add mention/tag insertion (`@tag`) bound to schema fields.
   - Export back to DOCX only for supported subset; fallback to DOCX-mode upload for unsupported constructs.

## Milestones

### M1: Stabilization (done/near done)
- Binary-mode guard in `PUT editor-text`.
- Run-aware token replacement.
- UI mode split and clear warnings.

### M2: Read-only rich preview + structured operations
- Keep `docx-preview` as read-only renderer.
- Add operations over OOXML: insert/remove/rename tags without rewriting layout.
- Add integrity checks for tables, numbering, styles after operation.

### M3: Limited WYSIWYG editing
- Integrate editor engine (candidate: Tiptap/ProseMirror wrapper).
- Support subset:
  - paragraphs
  - headings
  - bold/italic/underline
  - ordered/unordered lists
  - simple tables (optional, can be postponed)
- Explicitly block unsupported constructs with user notice.

### M4: Expanded fidelity
- Header/footer editing support.
- Better table model and merged cells.
- Numbering/style map parity improvements.

## Definition of done for WYSIWYG MVP
- Upload real customer DOCX.
- Edit supported blocks in browser.
- Insert tags using `@` mention.
- Generate DOCX with preserved layout for supported subset.
- Produce warning and safe fallback path for unsupported elements.

## Risks and mitigations
- **Risk:** Browser model diverges from OOXML.
  - **Mitigation:** keep DOCX binary as canonical source, use delta operations.
- **Risk:** Placeholder split behavior regression.
  - **Mitigation:** regression tests with split-run fixtures and complex docs.
- **Risk:** Scope explosion in editor parity.
  - **Mitigation:** strict supported-subset contract per milestone.
