# Preserved ADR014 V4

Before any ADR015 source edit/build, tagged the existing image (no rebuild):

- Tag: `nanfo-emulation:adr014-v4`
- Image: `sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff`
- Matched/OSPF envSpec version: `4`
- Schedule version: `seeded-stationary-capacity-v3`
- Spec SHA256: `bb15142a19ed3ee87a6aec2c6f9109d789d9736a5e6afda826ad898ef5fe7200`
- Source SHA256: `08c312c64154c9aedcd3b22eeb3573783590e0eb7183bc999cb8ef39b958dbbd`
- Pre-edit source archive: `output/adr015-prechange-v4-source.tar.gz`
- Archive SHA256: `444663dc3a7223044a9e8830ba5dd24cd3e1b041c60dc278e4bba56eb7252384`

Archive includes existing uncommitted emulation source/tests/docs, excluding only
output/commands/results and caches. Existing raw evidence and historical release
documents were not deleted or rewritten. Source spec/hash was checked against
`DRAIN-V4-VALIDATION.md` before preservation. The pinned image contains its own
original source and tests; use it, not the new workspace client/spec, for V4 replay.
Do not rebuild or move the preserved tag. Incumbent model files remain untouched.
