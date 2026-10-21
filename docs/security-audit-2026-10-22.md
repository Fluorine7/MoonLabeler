# MoonLabeler security audit — 2026-10-22

## Scope and evidence

Audited tracked main at `d630c5708d59c707497a1079d70fd0447fd5fd53`, the cumulative PR #1–#4 tree at `7bf8de212740f6fa1ced48b0309947cca13eaf3d`, the actual local Python environment (30 distributions), declared dependency minimums, and current Python 3.12 Windows/Linux resolutions with FITS, test and GPU extras. The Windows and Linux resolutions contained the same 27 package/version pairs; that identical inventory reuses one audit result. The local Apple GPU dependencies and the four newly resolved FITS dependencies were also checked.

Used `pip-audit 2.10.1` against the live PyPI advisory service, upstream advisories, installed-wheel component metadata, and OSV for the exact wgpu-native Rust lockfile. Duplicate advisory records are deduplicated below. A package match does not prove exploitability through this application. A clean Python package audit does not cover every embedded native library.

No tracked Cargo, Composer or Go manifests, Rust/PHP/Go source projects, submodules, Docker images or pre-existing CI workflows were found. The ignored `moonlib-core` reference directory is not imported or shipped by MoonLabeler. Other repositories, global runtimes, historical release binaries and unpublished external packaging environments were not changed by this audit.

## Installed Python packages: findings before repair

| Package before repair | Advisory / CVE | Fixed version |
| --- | --- | --- |
| certifi 2026.7.22 | [PYSEC-2026-4320](https://github.com/advisories/GHSA-6q48-6c7w-9gw2) | 2026.10.19 |
| pillow 12.3.0 | [CVE-2026-112895](https://github.com/advisories/GHSA-p4wg-p73j-c528) | 13.0.0 |
| pillow 12.3.0 | [CVE-2026-112400](https://github.com/advisories/GHSA-65qm-jvmh-6pqg) | 13.0.0 |
| pillow 12.3.0 | [CVE-2026-112397](https://github.com/advisories/GHSA-58r4-6rv3-gfh8) | 13.0.0 |
| pillow 12.3.0 | [CVE-2026-112896](https://github.com/advisories/GHSA-pchr-8j38-3x4p) | 13.0.0 |
| pillow 12.3.0 | [CVE-2026-112897](https://github.com/advisories/GHSA-q45j-58j2-45rg) | 13.0.0 |
| pillow 12.3.0 | [CVE-2026-112395](https://github.com/advisories/GHSA-462x-pgg6-55fp) | 13.0.0 |
| pillow 12.3.0 | [CVE-2026-112404](https://github.com/advisories/GHSA-c6hw-5grf-ff96) | 13.0.0 |
| pillow 12.3.0 | [CVE-2026-112899](https://github.com/advisories/GHSA-vx6w-vv9f-6gvg) | 13.0.0 |
| pip 26.1.2 | [PYSEC-2026-3721, CVE-2026-13346](https://github.com/advisories/GHSA-qwm4-qh6w-59xr) | 26.2.0 |

`certifi` is directly imported by the download implementation but previously only arrived transitively through Skyfield. Its emSign CA incident has a GHSA rather than a CVE. The downloader constructs its TLS context from this bundle, so the issue applies to reference-data downloads. It now has an explicit `certifi>=2026.10.19` requirement. [Upstream advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2).

Pillow's TIFF decoder advisories and its bundled OpenJPEG advisory affect supported image-reading paths. PDF-append, morphology, animation-recovery and EPS-scaling findings require API usage not present in MoonLabeler; upgrading the library removes those vulnerable implementations as well. The old `<13` constraint prevented the fixed release from being selected. It is now `>=13,<14`. The upstream release also fixes JPEG decoding and Exif problems not yet fully represented in the package-audit response. [Pillow 13 security changes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html), [bundled OpenJPEG advisory](https://github.com/python-pillow/Pillow/security/advisories/GHSA-78g4-xqwv-q3g8).

The actual environment was updated to certifi 2026.10.19, Pillow 13.0.0 and pip 26.2.2. The complete package inventory then passed pip-audit with no known vulnerabilities. This conclusion is limited to that package inventory and database snapshot.

## Previously permitted old dependencies

The declared minimum Pillow 11.0.0 matched these CVEs; upstream release notes also cover bugs introduced in later previously permitted 12.x versions:

CVE-2026-112395, CVE-2026-112397, CVE-2026-112400, CVE-2026-112404, CVE-2026-112895, CVE-2026-112896, CVE-2026-112897, CVE-2026-112899, CVE-2026-25990, CVE-2026-40192, CVE-2026-42308, CVE-2026-42310, CVE-2026-42311, CVE-2026-54058, CVE-2026-54059, CVE-2026-54060, CVE-2026-55379, CVE-2026-55380, CVE-2026-55798, CVE-2026-59197, CVE-2026-59198, CVE-2026-59199, CVE-2026-59200, CVE-2026-59204, CVE-2026-59205.

The build backend permitted setuptools 77, affected by [CVE-2025-47273](https://github.com/advisories/GHSA-5rjg-fvgr-3xxf) and [CVE-2026-59890](https://github.com/advisories/GHSA-h35f-9h28-mq5c). The new build floor is 83. The developer extra permitted pytest 8, affected by [CVE-2025-71176](https://github.com/advisories/GHSA-6w46-j5rx-g56g); its new floor is 9.0.3. Both local packages were already newer than those fixes.

PySide6-Essentials' old floor 6.8 permitted Qt versions affected by [CVE-2026-8168](https://www.qt.io/blog/security-advisory-cve-2026-8168), [CVE-2026-101201](https://www.qt.io/blog/security-advisory-cve-2026-101201) and [CVE-2026-76151](https://www.qt.io/blog/security-advisory-cve-2026-76151). The actual Qt was already 6.12.0; the new floor is 6.12. QtWebEngine is not installed by the Essentials requirement. OpenCV's floor is raised to the tested 4.14.0.94 release, whose upstream wheels include a [CVE-2026-8461 FFmpeg fix](https://github.com/opencv/opencv-python/releases/tag/94); embedded libraries still need the separate treatment below.

No package advisory matched the other tested direct minimum versions (NumPy 2.0, Skyfield 1.49, PyShp 2.3, Astropy 6.0, wgpu 0.32, MLX 0.25 or OpenCC 0.1.7). This does not certify every intermediate or future version in those ranges.

## Python and TLS runtime

The original virtualenv used Homebrew Python 3.12.13 linked to OpenSSL 3.6.3. Those runtimes are outside pip-audit's package coverage. [Python 3.12.15](https://www.python.org/downloads/release/python-31215/) repairs additional ssl, zipfile, tarfile and urllib vulnerabilities, including CVE-2026-15310, CVE-2026-19445, CVE-2026-19553, CVE-2026-82049, CVE-2026-19672, CVE-2026-15806 and CVE-2026-87910. The application reads a downloaded ZIP and uses urllib, although the credential and extraction-specific prerequisites are not generally used.

The original OpenSSL version lies within upstream affected ranges for:

CVE-2026-35189, CVE-2026-35191, CVE-2026-42772, CVE-2026-54872, CVE-2026-54873, CVE-2026-54875, CVE-2026-72897, CVE-2026-75804, CVE-2026-75805, CVE-2026-75806, CVE-2026-77696, CVE-2026-84782, CVE-2026-84784, CVE-2026-75803, CVE-2026-14457, CVE-2026-18798, CVE-2026-54874, CVE-2026-63072, CVE-2026-63073, CVE-2026-63074, CVE-2026-63075, CVE-2026-63076, CVE-2026-14456, CVE-2026-54876.

Most require QUIC, DTLS, CMP, CMS or optional verification features that this HTTPS downloader does not enable. See [upstream version-specific advisory ranges](https://www.openssl-library.org/news/vulnerabilities-3.6/). They are component-version findings, not claims that MoonLabeler exposes all those APIs.

The project now uses a local Python 3.12.15 runtime with OpenSSL 3.5.9 and Expat 2.9.0, downloaded through uv from Astral's python-build-standalone distribution. The interpreter is kept in ignored `.python-runtime/`; the original virtualenv is retained under ignored `.cache/venv-before-security-20261022` for rollback. All 30 recorded distributions are restored at their audited versions. System Homebrew installations are outside this change. Other users should update their own maintained Python patch line and TLS runtime; editing requirements alone cannot do that.

## Native components and remaining work

- **Pillow:** installed-wheel SBOM inspection confirmed the original OpenJPEG 2.5.4. This bundled copy requires the Pillow 13 patch even when the OS library is updated. The updated wheel reports libtiff 4.7.2; the OpenJPEG version string remains 2.5.4 despite the vendor backport, so the fixed Pillow wheel/advisory is the relevant evidence, not the version string alone.
- **Rust through wgpu:** wgpu 0.32.0 identifies wgpu-native 29.0.1.1 at commit `6aed50955d934ac36049ba8d002034841633ae02`. Queried all 139 crates.io entries in that commit's Cargo.lock through OSV. Only `paste 1.0.15` matched [RUSTSEC-2024-0436](https://rustsec.org/advisories/RUSTSEC-2024-0436.html), an unmaintained notice without a CVE. A full lockfile includes target-specific/build dependencies, so this is a conservative dependency inventory, not binary attestation. No reason was found to replace the GPU backend for a CVE.
- **OpenCV residual risk:** the actual macOS 4.14.0.94 wheel reports libtiff 4.7.1, OpenJPEG 2.5.3, OpenEXR 2.3.0 and FFmpeg libavcodec 61.19.101. Python package version alone does not establish native patch status. The corresponding OpenCV source retains the signed 32-bit arithmetic involved in [CVE-2026-4775](https://access.redhat.com/security/cve/CVE-2026-4775); [libtiff 4.7.2](https://libtiff.gitlab.io/libtiff/releases/v4.7.2.html) contains relevant TIFF fixes. MoonLabeler delegates only high-bit-depth RGB TIFF decoding to OpenCV, whereas that CVE concerns an 8-bit YCbCr path; exploitability through this wrapper was not demonstrated. The OpenCV-bundled OpenJPEG has the upstream affected code lineage described by OSV-2025-219, but MoonLabeler sends JPEG2000 through the patched Pillow decoder. No video/EXR decoding is called. These embedded copies have **not** been rebuilt or certified free of other CVEs. A vendor-patched wheel or a separately validated TIFF decoder is the remaining remediation option; changing system libtiff cannot patch a static wheel.
- **libtiff tool-only finding:** CVE-2025-61145 is in the `tiffcrop` executable, which is not invoked or shipped by this application; it must not be treated as proof that Pillow/OpenCV image decoding triggers that CVE.
- **Distribution artifacts:** no new installer/release binary was produced. Any older PyInstaller bundle must be rebuilt with the repaired environment; updating a source checkout does not repair already-distributed binaries. Full per-platform native SBOM/binary scanning remains necessary for a release assurance claim.

## PR review and integration repairs

Reviewed [#1](https://github.com/Fluorine7/MoonLabeler/pull/1), [#2](https://github.com/Fluorine7/MoonLabeler/pull/2), [#3](https://github.com/Fluorine7/MoonLabeler/pull/3) and [#4](https://github.com/Fluorine7/MoonLabeler/pull/4) by mjrtmj. PR #1's standalone commit and the first commit in the later stack have identical stable patch IDs. The four PRs are integrated in order with merge commits to preserve contributor history.

### Standards

No documented-standard violation or actionable new Fowler code smell was found.

### Spec

Found three P2 gaps in the Traditional-language delivery: displayed Traditional names could not be searched, old macOS environments never installed the new OpenCC dependency, and Pillow OSError messages without a filename attribute still had embedded paths translated. The English candidate-crater selector also used the project's bilingual caption rather than the interface language. All four are repaired with focused regression coverage.

The macOS launcher now checks installed requirement versions offline, in addition to imports. An importable but outdated certifi/Pillow or a missing OpenCC triggers installation. An already-compliant environment starts without contacting a package index.

## Validation and ongoing checks

- Fixed aggregate PR tree, before switching interpreters: **435 passed, 33 skipped** with Python 3.12.13 and upgraded packages. A previous worktree-only permission/cache failure was resolved by using the existing ephemeris fixture. Optional photo/terrain cases without their files remain skipped.
- After the interpreter replacement, the complete suite passed again: **435 passed, 33 skipped** on Python 3.12.15 / OpenSSL 3.5.9. Its 30 installed package/version pairs exactly match the previously audited repaired inventory, so that still-valid audit result was reused rather than queried again.
- The 30-distribution installed package inventory and the four newly resolved FITS packages each passed pip-audit. Windows/Linux dependency resolution produced the same 27 package/version pairs; that inventory also passed.
- Existing requirement compatibility passed `pip check`; launcher dry-run confirms the installed environment meets the new runtime requirements.
- Added three-platform GitHub Actions tests and package audits, with all optional features, current packaging tools, read-only permissions and pinned action revisions. Added Dependabot configuration for pip and GitHub Actions. GitHub's Dependabot-alert endpoint reported disabled; this repository setting was not changed through the read-only integration.
- Native-component caveats above remain open; no claim of zero native CVEs or successful historical-installer rebuild is made.
