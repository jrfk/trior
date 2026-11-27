# Releasing Trior

The [Python distributions workflow](../.github/workflows/python-release.yml)
builds CPython 3.12 wheels for manylinux x86_64 and macOS ARM64, plus one
source distribution. It installs each wheel in a fresh environment and
runs the test suite with the default reactor and poll. Build artifacts are
available on GitHub Actions for inspection.

Before publishing, verify that the build includes Trior's MIT license and
the upstream notice in `LICENSE.Trio`.
Review the repository's branches and history before switching it to public.
See [licensing and attribution](licensing.md).

## Configure publishing

Create the `testpypi` and `pypi` GitHub Environments. Configure
`testpypi` for `main` and restrict `pypi` to release tags. Set a required
reviewer on the production environment if available. Review repository
tag protections before enabling production uploads.

Set up a [Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
on each index using the corresponding environment:

| Setting | TestPyPI | PyPI |
|---|---|---|
| Project | `trior` | `trior` |
| Owner / repository | `jrfk/trior` | `jrfk/trior` |
| Workflow filename | `python-release.yml` | `python-release.yml` |
| Environment | `testpypi` | `pypi` |

For a new project, use the pending publisher settings for
[TestPyPI](https://test.pypi.org/manage/account/publishing/) or
[PyPI](https://pypi.org/manage/account/publishing/). For an existing project,
configure its publisher in the project's management settings. The workflow
uses OIDC and requires no API token secret.

## Build, rehearse, publish

1. Review the distribution artifacts from a pull request or a build on
   `main`. You can also start **Python distributions** manually with
   **Publish to TestPyPI** unchecked to build and verify artifacts.
2. For a rehearsal, run **Python distributions** on `main` and check
   **Publish to TestPyPI**. Each index treats distribution filenames as
   single use, so use a new version for a new upload to the same index.
   Install the candidate into an empty Python 3.12 environment:

   ```sh
   python -m pip install --index-url https://test.pypi.org/simple/ --only-binary=:all: --no-deps 'trior==0.1.0'
   python -c 'import trior; trior.run(trior.sleep, 0)'
   ```

3. When ready to release, push an explicit tag such as `v0.1.0` for the
   intended commit on `main`. The workflow checks that the tag matches the
   version in `pyproject.toml`, builds and verifies the artifacts, then
   publishes to PyPI with the production environment.

The usual CI and the separately triggered steady-state benchmark have
their own workflows.
