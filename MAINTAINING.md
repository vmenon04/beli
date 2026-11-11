# Maintaining beli

## Release

1. Run the checks and the live tests.
2. Set the version in `src/beli/_version.py` and finish its entry in `CHANGELOG.md`.
3. Merge to `main`, then tag it:

   ```bash
   git tag v0.2.0 && git push origin v0.2.0
   ```

4. Approve the `pypi` environment when `release.yml` asks. It publishes to PyPI.

## Agentic Maintenance

A long-term goal for this project is an agentic maintenance system, where AI agents notice Beli's API changes, propose and test the fix, and keep the package working with minimal human intervention. There is no automated check against the live API yet, because that needs a dedicated Beli account, and creating one requires a phone number. For now, bug reports are the signal: an `UnexpectedResponseError` names the endpoint and the fields that changed, which is enough to propose a fix.

Ideas, experience and insights that would help reach this goal are very welcome. Please [open an issue](https://github.com/vmenon04/beli/issues) or contact the primary maintainer, [@vmenon04](https://github.com/vmenon04).
