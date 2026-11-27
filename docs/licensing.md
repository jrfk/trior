# Licensing and attribution

## Trior

Trior's own source and documentation are licensed under the
[MIT License](../LICENSE). The Python and Rust package metadata declare MIT.
The Python wheel and source distribution carry both license files.

## Trio

Early experiments translated parts of [Trio](https://github.com/python-trio/trio)
and used its implementation as a reference. The Trio copyright and MIT
notice are retained verbatim in [LICENSE.Trio](../LICENSE.Trio). The archived
experiments in `research/stage20` also retain the notice.

Stage 20.5 removed the historical batch adapter and recv experiment from the
active package. The remaining source still needs a provenance review.
Retain the upstream notice in the repository and distribution artifacts.

## Preparing a release

Review the provenance of the shipped source. Inspect the wheel and source
distribution for Trior's license and third-party notices.

See the [release guide](release.md) for packaging and publishing steps.
