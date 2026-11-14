# Making a release

1. Set the version in `package.json`, and add a `CHANGELOG.md` entry and `docs/releases/<version>.md`. These are the only places the version is written.
2. In a clean clone, in a rootless container with `/sys` masked and no network, run `python3 -B scripts/check.py`.
3. Install that `dist/Ayaneo3-Decky.zip` on an AYANEO 3 and run the hardware checks in [VALIDATION.md](VALIDATION.md). Record only the checks that ran.
4. Run `python3 scripts/build-source-package.py`, then `python3 scripts/check-release.py`.
5. Tag the commit and create a GitHub release with `Ayaneo3-Decky.zip`, the source archive, `SHA256SUMS` and a `RELEASE-MANIFEST.json` naming the commit, the file hashes and the checks. The ZIP keeps the same name in every release, so the download link in the README always gets the latest one. Download the published files and check them against `SHA256SUMS`.

Any hardware regression blocks a release.
