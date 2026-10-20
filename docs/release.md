# Release checklist

Repository: [JiangZehua/AgenticPCG-Demo](https://github.com/JiangZehua/AgenticPCG-Demo). Version `0.1.0` identifies the source baseline; a version field alone does not imply a published or validated binary.

## Source and Python package

- Run all Python checks and the offline demo from a clean checkout.
- Build a wheel and source distribution; install the wheel into a fresh environment and run `unity-pcg demo` outside the checkout.
- Inspect archive contents: source distribution must contain Unity scene, scripts, PNG assets, metadata, Packages, and ProjectSettings. The wheel contains only the Python package and bundled JSON examples; obtain Unity from the repository or source distribution.
- Exclude `.env`, credentials, `.bridge`, run artifacts, caches, recovery scenes, and personal paths. Include `.env.example` with blank credentials.
- Keep README, package version, CITATION, changelog, and release notes consistent.

```bash
python3 -m unittest discover -s tests -v
python3 -m unity_pcg demo --output runs/release-check
python3 -m pip install build
python3 -m build
```

For a repository archive, use `git archive` on the reviewed commit rather than zipping a local working directory. Never distribute Unity Library, Temp, or local environment files.

## Unity and model verification

- Compile with the recorded Unity patch; run the scripted demo through actual Unity physics.
- Check movement, walls, locked door before pickup, key pickup, hazard death, winning, restart, and panel focus in Play mode.
- Exercise a live model run with Unity verification. Keep sanitized request, trace, candidate maps, summary, model route, token counts, and exact Unity backend/version.
- Exercise invalid input, unmet targets, Cancel, timeout, and stopping Play during a worker. The displayed map must remain unchanged when generation fails.
- Confirm distribution permission for each reused sprite or replace it with a documented alternative. See [sprite provenance](architecture.md#sprite-provenance).

## Desktop build

Use **Agentic PCG → Add Current Scene to Build** and Unity Build Profiles to export a declared desktop target. Launch the result independently and repeat gameplay checks. Embedded-map play requires neither Python nor credentials.

If the binary includes generation, validate repository/Python discovery and local configuration outside the Editor. The worker currently needs the checkout, Python, and `.env`. WebGL generation is outside the supported subprocess architecture.

## Release contents and sign-off

Publish the reviewed source archive, wheel, tested desktop build, sanitized example artifacts, and concise release notes. State the tested OS, Unity patch, supported entry points, and known limitations. One validated route does not certify all gameplay policies, and hazard counts do not measure player difficulty.

Complete the open gates in [validation.md](validation.md) before describing a desktop package as release-ready. The [delivery backlog](roadmap.md) provides the handoff acceptance criteria.
