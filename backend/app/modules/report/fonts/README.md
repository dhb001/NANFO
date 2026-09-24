# Embedded report font

`DejaVuSansMono.ttf` is embedded (subset) into every generated report PDF so
non-ASCII names render as text instead of escapes. `LICENSE` is the upstream
DejaVu/Bitstream Vera licence, which requires it to accompany the font; both files
ship in the backend image (`deploy/Dockerfile.backend.dockerignore` keeps
`backend/app/**` except `*.md`).

| File | SHA-256 |
| --- | --- |
| `DejaVuSansMono.ttf` | `b4a6c3e4faab8773f4ff761d56451646409f29abedd68f05d38c2df667d3c582` |
| `LICENSE` | `7a083b136e64d064794c3419751e5c7dd10d2f64c108fe5ba161eae5e5958a93` |

Provenance: DejaVu Fonts 2.37, official release archive
`https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2`
(archive SHA-256 `fa9ca4d13871dd122f61258a80d01751d603b4d3ee14095d65453b4e846e17d7`),
files `dejavu-fonts-ttf-2.37/ttf/DejaVuSansMono.ttf` and `dejavu-fonts-ttf-2.37/LICENSE`,
downloaded 2026-09-23 (ADR-028). The files are unmodified.

`app.modules.report.artifacts` verifies the TTF SHA-256 above before registering
it with ReportLab and never embeds unverified bytes. When the file is missing,
unreadable, altered (SHA-256 mismatch) or not monospaced, PDFs fall back (logged
once per process as `report_pdf_font_fallback`) to ReportLab's bundled standard
Courier -- the pre-ADR-028 renderer -- whose coverage is printable ASCII only, so
every other character keeps its reversible JSON `\uXXXX` escape; the PDF's first
line names the font in use. CSV output never depends on the font. The font has
3,322 glyphs, all with one advance width (the wrapping code asserts this).
Characters it does not cover (for example CJK), right-to-left, control, format,
private-use and unassigned characters are shown as reversible JSON `\uXXXX`
escapes; every PDF states this on its first line. Replacing the font requires
updating this table, the constant `FONT_SHA256` and the PDF tests intentionally.
