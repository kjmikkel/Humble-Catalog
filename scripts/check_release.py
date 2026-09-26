"""The gate a release passes before anything is published (#112).

.github/workflows/release.yml builds the package into dist/ and runs
this before `gh release create`. Everything that can be decided from
files is decided here, in tested Python, so the workflow is only steps:

- the tag names the version being released (`v` + project.version), so
  a tag pushed before the version bump cannot publish the old wheel
  under the new release's name;
- dist/ holds exactly one wheel and one sdist, so a leftover artifact is
  never published beside the new one;
- the wheel carries every file in the viewer's static folder -- #107's
  rule, checked against the artifact actually being released rather
  than a test build.

Every problem is reported in one run rather than one per attempt: each
attempt costs a tag.

Run: python scripts/check_release.py --dist dist [--tag vX.Y.Z]
(no --tag: the pull-request dry run, which has none to compare)
"""
import argparse
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
STATIC = ROOT / "humble_catalog" / "webapp" / "static"
# Where STATIC's files sit inside the wheel.
STATIC_IN_WHEEL = "humble_catalog/webapp/static"


def project_version(pyproject=PYPROJECT):
    with open(pyproject, "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def tag_problem(tag, version):
    """Why `tag` cannot release `version`, or None when it can."""
    if tag != f"v{version}":
        return (f"tag {tag} does not match the version in pyproject.toml "
                f"({version}); tag v{version}, or bump the version first")
    return None


def dist_problems(dist):
    """What is wrong with dist/ as a set of files to publish."""
    wheels = sorted(p.name for p in Path(dist).glob("*.whl"))
    sdists = sorted(p.name for p in Path(dist).glob("*.tar.gz"))
    problems = []
    for kind, found in (("wheel", wheels), ("sdist", sdists)):
        if len(found) != 1:
            problems.append(f"dist/ must hold exactly one {kind}, found "
                            f"{len(found)}: {', '.join(found) or 'none'}")
    return problems


def missing_static(wheel, static=STATIC):
    """The static files `wheel` lacks, as paths inside a wheel."""
    with zipfile.ZipFile(wheel) as z:
        inside = set(z.namelist())
    expected = sorted(f"{STATIC_IN_WHEEL}/{p.name}"
                      for p in Path(static).iterdir() if p.is_file())
    return [name for name in expected if name not in inside]


def main(argv=None, pyproject=PYPROJECT, static=STATIC):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", required=True,
                        help="The directory the build wrote to")
    parser.add_argument("--tag",
                        help="The tag being released; omit for a dry run")
    args = parser.parse_args(argv)
    problems = []
    if args.tag is not None:
        problem = tag_problem(args.tag, project_version(pyproject))
        if problem:
            problems.append(problem)
    dist = dist_problems(args.dist)
    problems += dist
    if not dist:
        wheel = next(Path(args.dist).glob("*.whl"))
        problems += [f"the wheel lacks {name}"
                     for name in missing_static(wheel, static)]
    if problems:
        print("NOT RELEASABLE:")
        for p in problems:
            print(f"  - {p}")
        return 1
    what = f"{args.tag}" if args.tag else "dry run (no tag)"
    print(f"releasable: {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
