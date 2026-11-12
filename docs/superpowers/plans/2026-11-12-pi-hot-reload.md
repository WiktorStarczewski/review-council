# Pi Council hot-reload repair

The agreed fix is to load Council through Pi's transformed TypeScript entrypoint instead of Node's cached native ESM import. Keep Council behavior unchanged. The regression must replace the entrypoint at the same path and load it twice inside one real Pi loader process, then observe the updated footer.

- [ ] Prove the regression fails for the released .mjs entrypoint.
- [ ] Rename the entrypoint to .ts, update all callers and release metadata, and prove the regression plus existing contracts pass.
- [ ] Obtain one independent normal review, pass current-head macOS/Ubuntu and package CI, squash merge, publish signed 0.9.2 and install it here. Preserve local data and verify released identity. Do not claim visual verification without a screenshot.

The previous fresh-process RPC test did not cover in-process upgrades. No provider call, new dependency, review-policy change or Pi core patch is needed. Existing /rev compatibility, independent footer, session persistence and explicit/frozen roster precedence remain unchanged.
