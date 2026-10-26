# justdocs Changelog

Stable GitHub and PyPI release history is recorded here. Entries contain user-visible behavior
and the exact commit boundary included by each immutable version tag.

## Unreleased

## v1.1.1 - 2026-10-26

- release tag: `v1.1.1`
- previous release: `v1.1.0`

### Included commits

- [`506b35f`](https://github.com/FanaticPythoner/justdocs/commit/506b35f4d9d6419a3a2dcc55e5b0e300cbbcfa10) fix: repair release checks and PR distribution publishing
  > Remove duplicated dependency pins from release assertions and build tooling.
  > Resolve PR distribution runs through commit associations when workflow event
  > payloads omit pull requests, and coordinate publication with artifact cleanup.
  > 
  > Release build dependencies:
  > - Install .[release] through the selected Python interpreter instead of
  >   duplicating build and Twine requirements in build-python-package.sh.
  > - Follow the package release extras for build==1.6.1 and twine==7.0.0 instead
  >   of installing the script's obsolete build==1.5.1 and twine==6.2.0 pins.
  > - Advance the build composite from setup-python v6 at
  >   ece7cb06caefa5fff74198d8649806c4678c61a1 to v7.0.0 at
  >   5fda3b95a4ea91299a34e894583c3862153e4b97.
  > - Align the composite's Python setup revision with workflow references.
  > 
  > Release workflow assertions:
  > - Replace copied action SHAs with action identities for checkout, Python
  >   setup, artifact upload/download, PyPI publication, provenance,
  >   dependency review, and CodeQL initialization and analysis.
  > - Retain the requirement that every external action reference contains
  >   an immutable 40-character lowercase hexadecimal revision.
  > - Require repeated references to each action identity to use one revision
  >   across workflows and composite actions.
  > - Compare expected action inventories independently of revision values,
  >   allowing dependency maintenance without duplicating pins in tests.
  > - Keep artifact upload/download assertions associated with action identity
  >   as revisions change.
  > - Require exact numeric setuptools, build, and Twine pins in package
  >   metadata without asserting obsolete version values.
  > - Reject duplicate build-tool pins in the build script and require
  >   installation through .[release].
  > - Assert artifact-deletion permission on the PR publisher job.
  > 
  > PR run identity:
  > - Add _run_pull_request to query the repository's
  >   commits/<head_sha>/pulls endpoint with explicit pagination.
  > - Resolve associations through the API regardless of empty or conflicting
  >   embedded workflow_run.pull_requests entries.
  > - Require nonempty source repository and source branch identities.
  > - Match candidates against the client repository as the PR base, the
  >   workflow run's source repository, and the workflow run's source branch.
  > - Accept fork associations only when their source repository matches.
  > - Require positive integer PR numbers and reject boolean values.
  > - Deduplicate matching numbers and reject multiple distinct matches
  >   immediately; reject an exhausted inventory without a unique match.
  > - Examine up to 100 pages of 100 candidates and raise an explicit error
  >   when enumeration exhausts that bound.
  > - Reject malformed inventories and candidate objects; propagate API
  >   failures through DistributionCommentError.
  > - Pass GitHubClient into _load_context and derive the expected run URL
  >   from its repository identity.
  > - Reject event repository mismatches before association API access,
  >   retaining completed-CI, SHA, URL, run ID, and attempt checks.
  > - Resolve associations independently of the PR's current head SHA so
  >   existing stale-run and closed-PR cleanup paths remain reachable.
  > - Pass the client through main to the revised context loader.
  > 
  > Publisher permissions and coordination:
  > - Grant actions: write to the publisher job for artifact deletion while
  >   retaining contents: read and pull-requests: write.
  > - Preserve trusted default-branch checkout and disabled credential
  >   persistence for the job receiving write permissions.
  > - Replace embedded-PR-number concurrency groups with repository, source
  >   repository, and source branch identities.
  > - Use matching group identities for workflow-run publication and
  >   pull-request closure.
  > - Add queue: max to both jobs and retain cancel-in-progress: false so
  >   publication and cleanup queue without cancelling running mutations.
  > 
  > PR association regression assertions:
  > - Add 15 test methods with temporary event payloads, mocked repository
  >   responses, captured output, and explicit API-call assertions.
  > - Cover empty embedded associations, retained run identity, and the exact
  >   commit-association query.
  > - Assert that conflicting embedded PR numbers do not override API identity.
  > - Cover pagination through a full unrelated page before a matching PR.
  > - Reject multiple matches, mismatched source branches or repositories,
  >   mismatched base repositories, and missing head repositories.
  > - Accept a correctly bound fork source.
  > - Reject invalid run IDs, attempts, workflow names, events, completion
  >   states, conclusions, SHAs, URLs, repositories, and source identities
  >   before API access.
  > - Reject malformed API inventories, invalid candidate objects, boolean
  >   PR numbers, and nonpositive PR numbers.
  > - Assert the 100-request enumeration bound and API error propagation.
  > 
  > Publisher lifecycle regression assertions:
  > - Assert successful publication creates one comment containing the
  >   run-bound artifact URL when embedded associations are empty.
  > - Assert closed PRs resolve through commit associations, delete their
  >   distribution artifact, and create no comment.
  > - Assert an advanced PR head deletes stale-run artifacts without posting.
  > - Assert failed CI removes distribution artifacts and posts an unavailable
  >   distribution comment.
  > - Parse both workflow definitions to assert the PR-event guard, artifact
  >   cleanup permissions, matching source locks, maximum queuing, and
  >   disabled cancellation.
  > - Adapt the existing event/artifact/bot-comment fixture to provide run
  >   repository metadata and a mocked commit-association client while
  >   retaining its managed-comment ownership and artifact-cleanup assertions.
  > 
  > Checks:
  > - git diff --cached --check passes with exit code 0 and no output.
  > - Index-backed Python parsing and compilation pass for all three staged
  >   Python files.
  > - Index-backed YAML parsing passes for the build composite and both
  >   changed PR workflows.
  > - bash -n passes for the staged release build script.
  > - An in-memory unittest harness executes the staged release-pipeline
  >   contract method with every file read served from staged blobs.
  > - That contract test passes; the full package suite, new publisher suite,
  >   distribution builds, and hosted workflows are not rerun during this
  >   staged inspection.
  > - Final inspection confirms unchanged HEAD and cached patch identity,
  >   with no tracked unstaged or nonignored untracked paths.
  > - Documentation and recorded execution artifacts are excluded because
  >   none are staged.
  > 
  > Measurements:
  > - Staged scope: seven files, 417 insertions, 54 deletions.
  > - File topology: six modifications and one added test module.
  > - Added publisher regression methods: 15.
  > - Current index-backed release-contract run: one test passes in 0.038s.

## v1.1.0 - 2026-10-26

- release tag: `v1.1.0`
- previous release: `v1.0.0`

### Included commits

- [`c9c7ff7`](https://github.com/FanaticPythoner/justdocs/commit/c9c7ff759cc17f68ee5f3c909edb2aa6898729b2) Ensures reliable process interruption and cleanup
  > Improves the handling of `KeyboardInterrupt` (Ctrl+C) in the CLI to ensure robust termination of child processes and release of system resources.
  > 
  > Changes include:
  > - Spawns child processes in new process groups to enable correct signal propagation.
  > - Implements a staged process reaping strategy (SIGINT, then SIGTERM, then SIGKILL) with timeouts to gracefully shut down the entire process tree.
  > - The `free-port` recipe now actively waits for TCP ports to be released after terminating binding processes, preventing orphaned listeners.
  > - The CLI exits with status code 130 upon `KeyboardInterrupt`, adhering to standard Unix conventions.
  > - Adds comprehensive tests to validate these interruption and resource cleanup mechanisms.
- [`771f92a`](https://github.com/FanaticPythoner/justdocs/commit/771f92a7d67af5df5eb4426ce055d21d3e2944f4) build(deps-dev): bump twine from 6.2.0 to 7.0.0
  > Bumps [twine](https://github.com/pypa/twine) from 6.2.0 to 7.0.0.
  > - [Release notes](https://github.com/pypa/twine/releases)
  > - [Changelog](https://github.com/pypa/twine/blob/main/docs/changelog.rst)
  > - [Commits](https://github.com/pypa/twine/compare/6.2.0...7.0.0)
  > 
  > ---
  > updated-dependencies:
  > - dependency-name: twine
  >   dependency-version: 7.0.0
  >   dependency-type: direct:development
  >   update-type: version-update:semver-major
  > ...
  > 
  > Signed-off-by: dependabot[bot] <support@github.com>
- [`55d6d2a`](https://github.com/FanaticPythoner/justdocs/commit/55d6d2af331de5e71128eef6947cb3356d663db7) build(deps-dev): bump setuptools from 83.0.0 to 84.0.0
  > Bumps [setuptools](https://github.com/pypa/setuptools) from 83.0.0 to 84.0.0.
  > - [Release notes](https://github.com/pypa/setuptools/releases)
  > - [Changelog](https://github.com/pypa/setuptools/blob/main/NEWS.rst)
  > - [Commits](https://github.com/pypa/setuptools/compare/v83.0.0...v84.0.0)
  > 
  > ---
  > updated-dependencies:
  > - dependency-name: setuptools
  >   dependency-version: 84.0.0
  >   dependency-type: direct:development
  >   update-type: version-update:semver-major
  > ...
  > 
  > Signed-off-by: dependabot[bot] <support@github.com>
- [`46f83b3`](https://github.com/FanaticPythoner/justdocs/commit/46f83b33dc395f20014ceee6ef88ed80a12f79c1) build(deps): bump the github-actions group across 1 directory with 6 updates
  > Bumps the github-actions group with 6 updates in the / directory:
  > 
  > | Package | From | To |
  > | --- | --- | --- |
  > | [actions/checkout](https://github.com/actions/checkout) | `7.0.0` | `7.0.1` |
  > | [actions/setup-python](https://github.com/actions/setup-python) | `6.3.0` | `7.0.0` |
  > | [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish) | `1.14.0` | `1.14.2` |
  > | [actions/attest-build-provenance](https://github.com/actions/attest-build-provenance) | `4.1.1` | `4.2.2` |
  > | [github/codeql-action/init](https://github.com/github/codeql-action) | `4.37.0` | `4.37.6` |
  > | [github/codeql-action/analyze](https://github.com/github/codeql-action) | `4.37.0` | `4.37.6` |
  > 
  > 
  > 
  > Updates `actions/checkout` from 7.0.0 to 7.0.1
  > - [Release notes](https://github.com/actions/checkout/releases)
  > - [Changelog](https://github.com/actions/checkout/blob/main/CHANGELOG.md)
  > - [Commits](https://github.com/actions/checkout/compare/9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0...3d3c42e5aac5ba805825da76410c181273ba90b1)
  > 
  > Updates `actions/setup-python` from 6.3.0 to 7.0.0
  > - [Release notes](https://github.com/actions/setup-python/releases)
  > - [Commits](https://github.com/actions/setup-python/compare/ece7cb06caefa5fff74198d8649806c4678c61a1...5fda3b95a4ea91299a34e894583c3862153e4b97)
  > 
  > Updates `pypa/gh-action-pypi-publish` from 1.14.0 to 1.14.2
  > - [Release notes](https://github.com/pypa/gh-action-pypi-publish/releases)
  > - [Commits](https://github.com/pypa/gh-action-pypi-publish/compare/cef221092ed1bacb1cc03d23a2d87d1d172e277b...dc37677b2e1c63e2034f94d8a5b11f265b73ba33)
  > 
  > Updates `actions/attest-build-provenance` from 4.1.1 to 4.2.2
  > - [Release notes](https://github.com/actions/attest-build-provenance/releases)
  > - [Changelog](https://github.com/actions/attest-build-provenance/blob/main/RELEASE.md)
  > - [Commits](https://github.com/actions/attest-build-provenance/compare/0f67c3f4856b2e3261c31976d6725780e5e4c373...4d101475d8b20a2381f78447822ac1eab6504dd8)
  > 
  > Updates `github/codeql-action/init` from 4.37.0 to 4.37.6
  > - [Release notes](https://github.com/github/codeql-action/releases)
  > - [Changelog](https://github.com/github/codeql-action/blob/main/CHANGELOG.md)
  > - [Commits](https://github.com/github/codeql-action/compare/99df26d4f13ea111d4ec1a7dddef6063f76b97e9...5595ccaf912efad79be6eef63a5619ff05969be3)
  > 
  > Updates `github/codeql-action/analyze` from 4.37.0 to 4.37.6
  > - [Release notes](https://github.com/github/codeql-action/releases)
  > - [Changelog](https://github.com/github/codeql-action/blob/main/CHANGELOG.md)
  > - [Commits](https://github.com/github/codeql-action/compare/99df26d4f13ea111d4ec1a7dddef6063f76b97e9...5595ccaf912efad79be6eef63a5619ff05969be3)
  > 
  > ---
  > updated-dependencies:
  > - dependency-name: actions/checkout
  >   dependency-version: 7.0.1
  >   dependency-type: direct:production
  >   update-type: version-update:semver-patch
  >   dependency-group: github-actions
  > - dependency-name: actions/setup-python
  >   dependency-version: 7.0.0
  >   dependency-type: direct:production
  >   update-type: version-update:semver-major
  >   dependency-group: github-actions
  > - dependency-name: pypa/gh-action-pypi-publish
  >   dependency-version: 1.14.2
  >   dependency-type: direct:production
  >   update-type: version-update:semver-patch
  >   dependency-group: github-actions
  > - dependency-name: actions/attest-build-provenance
  >   dependency-version: 4.2.2
  >   dependency-type: direct:production
  >   update-type: version-update:semver-minor
  >   dependency-group: github-actions
  > - dependency-name: github/codeql-action/init
  >   dependency-version: 4.37.6
  >   dependency-type: direct:production
  >   update-type: version-update:semver-patch
  >   dependency-group: github-actions
  > - dependency-name: github/codeql-action/analyze
  >   dependency-version: 4.37.6
  >   dependency-type: direct:production
  >   update-type: version-update:semver-patch
  >   dependency-group: github-actions
  > ...
  > 
  > Signed-off-by: dependabot[bot] <support@github.com>
- [`92472d2`](https://github.com/FanaticPythoner/justdocs/commit/92472d234b825dded0a0937e0132d591d13e0270) build(deps-dev): bump build from 1.5.1 to 1.6.1
  > Bumps [build](https://github.com/pypa/build) from 1.5.1 to 1.6.1.
  > - [Release notes](https://github.com/pypa/build/releases)
  > - [Changelog](https://github.com/pypa/build/blob/main/CHANGELOG.rst)
  > - [Commits](https://github.com/pypa/build/compare/1.5.1...1.6.1)
  > 
  > ---
  > updated-dependencies:
  > - dependency-name: build
  >   dependency-version: 1.6.1
  >   dependency-type: direct:development
  >   update-type: version-update:semver-minor
  > ...
  > 
  > Signed-off-by: dependabot[bot] <support@github.com>
- [`d9797a7`](https://github.com/FanaticPythoner/justdocs/commit/d9797a7f4c879d187d1aea731f4939af16e170f3) feat: validate artifact dependencies and link heading references
  > Extend justdocs-linker with declared page and section references, scoped
  > artifact prerequisites, and an opt-in dependency graph report. Adjust
  > anchor offsets, content wrapping, and responsive table layout.
  > 
  > Heading references:
  > - Share heading, reference ID, declaration, and fenced-code patterns
  >   between smart linking and dependency parsing in justdocs.references.
  > - Recognize case-insensitive bracketed IDs with an alphabetic start,
  >   trailing digits, and optional numeric hyphen segments.
  > - Resolve level-one declarations to pages and deeper declarations to
  >   heading fragments; expose both ID and title aliases.
  > - Collect heading targets once per source page.
  > - Exclude fenced examples from target discovery, including backtick
  >   and tilde fences with longer closing markers or no closing marker.
  > - Permit reference IDs shorter than min_phrase_chars while retaining
  >   ordinary phrase eligibility and ambiguity filtering.
  > - Reject case-insensitive reference ID collisions across different
  >   destinations instead of silently excluding conflicting references.
  > - Link declared IDs in prose and inline code, including existing
  >   action IDs, while preserving protected Markdown ranges.
  > - Exempt reference IDs from max_links_per_target while retaining the
  >   shared max_links_per_page ceiling and ordinary phrase repetition cap.
  > - Permit same-page section references and emit fragment-only URLs.
  >   Continue excluding ordinary same-page phrases and page-self references.
  > - Remove the ordinary phrase repetition argument from inline-code
  >   reference processing.
  > 
  > Artifact declarations:
  > - Add immutable DependencyNode records containing ID, title, prerequisites,
  >   owner, scope, produced artifact, verification, source path, and line.
  > - Parse metadata immediately following each reference heading, stopping
  >   at the next heading so nested sections cannot supply parent metadata.
  > - Require nonempty Owner, Requires, Scope, Produces, and Verify fields;
  >   accept optional list prefixes and reject duplicate required fields.
  > - Mask fenced content while preserving newlines and source locations.
  > - Normalize declaration and prerequisite IDs to uppercase.
  > - Accept exactly None for an empty prerequisite list or comma-separated
  >   reference IDs; reject prose, negation, malformed or empty entries,
  >   and duplicate prerequisites.
  > - Restrict scopes to shared, build, and target.
  > - Raise DependencyError with declaration locations for parsing failures.
  > 
  > Dependency graph:
  > - Reject empty declaration sets, duplicate IDs, unknown prerequisites,
  >   invalid scopes, and target declarations without configured bindings.
  > - Require unique target names matching [a-z][a-z0-9-]*.
  > - Enforce shared < build < target scope ordering; reject dependencies
  >   on a later scope.
  > - Instantiate shared and build nodes once and target nodes separately
  >   as ID@target for each configured binding.
  > - Bind target prerequisites to the consuming target while retaining
  >   shared and build prerequisites without target suffixes.
  > - Canonicalize templates by ID and retain configured target order.
  > - Compute sorted topological layers and flatten them into a
  >   prerequisite-first order independent of input-node ordering.
  > - Reject self-dependencies and disconnected cycles across the complete
  >   expanded graph.
  > - Report a closed cycle path through an iterative traversal that avoids
  >   Python recursion-depth dependence.
  > - Return schema version 1 with targets, full declaration metadata,
  >   source locations, expanded nodes and prerequisite edges, layers,
  >   execution order, and template/node/edge/layer counts.
  > - Bound expanded graph processing to O(v log v + e) time and O(v + e)
  >   space, where v and e count instantiated nodes and edges.
  > 
  > MkDocs integration:
  > - Add validate_dependencies=false and dependency_targets=[] options.
  > - Run dependency checks independently of enabled link insertion.
  > - Scan documentation pages for declarations when checking is enabled;
  >   preserve the early return when both features are disabled.
  > - Generate dependency-graph.json through File.generated after successful
  >   checking, with indented JSON and a trailing newline.
  > - Reserve dependency-graph.json while checking is enabled and reject
  >   an existing source file at that path.
  > - Change JustdocsLinkerError from RuntimeError to MkDocs PluginError.
  > - Translate parsing and graph failures into chained JustdocsLinkerError
  >   exceptions for native MkDocs build diagnostics.
  > 
  > Responsive layout:
  > - Introduce --topbar-min-height at 64px and initialize --topbar-height
  >   from that minimum.
  > - Use an automatic first grid row and apply the minimum height to the
  >   topbar instead of fixing the row to --topbar-height.
  > - Offset document scrolling by --topbar-height plus 1rem.
  > - Allow arbitrary wrapping in main content while restoring normal
  >   wrapping for table headers.
  > - Remove the drawer-specific fixed table-layout override.
  > - Replace mobile table cells' two-column grid with block layout.
  > - Place mobile data labels above values with 0.25rem bottom spacing.
  > 
  > Documentation:
  > - Extend README and bundled smart-link guidance with reference
  >   declarations, destination uniqueness, short IDs, same-page sections,
  >   inline-code references, and reference repetition behavior.
  > - Document independent dependency checking, target configuration,
  >   required metadata, scope ordering, cycle rejection, report contents,
  >   and reserved-path handling.
  > - Include F7-1 library and T1 producer declarations with explicit
  >   ownership, prerequisites, outputs, and verification requirements.
  > - State parsing complexity as O(p + h) and distinguish declared ordering
  >   feasibility from implementation completion and live execution evidence.
  > - Add JustdocsLinkerError to the documented error surface.
  > 
  > Dependency regression assertions:
  > - Add 17 dependency tests covering declaration locations, fenced
  >   exclusions, longer closing markers, and unclosed fences.
  > - Check every required field for missing, empty, and duplicate values;
  >   reject metadata borrowed from nested headings.
  > - Cover lowercase ID normalization, list-prefixed metadata, malformed
  >   prerequisites, invalid scopes and target names, duplicate IDs,
  >   unknown prerequisites, and empty graphs.
  > - Accept the F7-1 -> T1 -> F7 milestone chain and reject the resulting
  >   F7 -> T1 -> F7 cycle when T1 requires the complete F7 artifact.
  > - Cover self-cycles, disconnected cycles, scope inversions, and
  >   target declarations without bindings.
  > - Assert eight expanded nodes for a four-template, three-target fixture,
  >   same-target prerequisite binding, and input-node reversal invariance.
  > - Compare all 64 directed three-node graphs without self-edges against
  >   an independent permutation oracle.
  > - Exercise a 1,200-node cycle and require an explicit cycle diagnostic.
  > - Add native strict-build assertions for report generation, same-page
  >   prerequisite links, and cycle errors through MkDocs Abort handling.
  > - Assert opt-in behavior, independent checking with linking disabled,
  >   and rejection of a conflicting dependency-graph.json source.
  > - Add CLI assertions for exit code 1, a dependency-cycle diagnostic,
  >   and absence of a Python traceback.
  > 
  > Reference regression assertions:
  > - Add nine tests covering page/section destinations, title aliases,
  >   fenced target exclusion, short-ID eligibility, and conflicting IDs.
  > - Assert exact reference boundaries, relative section URLs, protected
  >   existing links and fences, and inline-code reference insertion.
  > - Assert four repeated reference links alongside one ordinary phrase
  >   link with max_links_per_target=1.
  > - Assert the two-link page ceiling still limits repeated references.
  > - Cover same-page prose/code section jumps and unchanged page-self
  >   references without fragments.
  > - Remove the CSS assertion requiring fixed drawer table layout.
  > 
  > Checks:
  > - git diff --cached --check passes with exit code 0 and no output.
  > - Index-backed Python parsing and compilation pass for all five staged
  >   Python files.
  > - An in-memory unittest harness using staged module and assertion bytes
  >   passes 23 tests: 14 dependency tests and nine reference-link tests.
  > - Run the selected assertions with PYTHONDONTWRITEBYTECODE=1 and
  >   PYTHONHASHSEED=0, without repository artifacts.
  > - The three native build/CLI methods, existing package suite, browser
  >   behavior, and packaging builds are not executed in this check.
  > - Final inspection confirms unchanged HEAD and cached patch identity,
  >   with no tracked unstaged or nonignored untracked paths.
  > 
  > Measurements:
  > - Staged scope: eight files, 744 insertions, 47 deletions.
  > - File topology: three additions and five modifications.
  > - Test topology: 26 added methods and one removed method.
  > - Current index-backed assertion run: 23 tests pass in 0.026 seconds.
- [`4e7b60a`](https://github.com/FanaticPythoner/justdocs/commit/4e7b60a46f609ecc22bf3669ad6708fc3541560f) ci fix
- [`40ee793`](https://github.com/FanaticPythoner/justdocs/commit/40ee793bf632eeddddf59f52c9a4a86d55beecbc) Potential fix for code scanning alert no. 6: Cache Poisoning via execution of untrusted code
  > Co-authored-by: Copilot Autofix powered by AI <62310815+github-advanced-security[bot]@users.noreply.github.com>
- [`012e8a6`](https://github.com/FanaticPythoner/justdocs/commit/012e8a6456ab31b4a28f810ebbd3fc3064305ddd) Merge pull request #14 from FanaticPythoner/alert-autofix-6
  > Potential fix for code scanning alert no. 6: Cache Poisoning via execution of untrusted code
- [`cb31ad1`](https://github.com/FanaticPythoner/justdocs/commit/cb31ad189b63efefe185a940bb68ef244a30423e) Merge pull request #13 from FanaticPythoner/dependabot/pip/main/build-1.6.1
  > build(deps-dev): bump build from 1.5.1 to 1.6.1
- [`58a86f0`](https://github.com/FanaticPythoner/justdocs/commit/58a86f0411abca8560fedefabe414a66dc40af29) Merge pull request #11 from FanaticPythoner/dependabot/github_actions/main/github-actions-9e7f420af7
  > build(deps): bump the github-actions group across 1 directory with 6 updates
- [`9b60919`](https://github.com/FanaticPythoner/justdocs/commit/9b60919d573a5430be954d7833d5e19409a0e887) Merge pull request #10 from FanaticPythoner/dependabot/pip/main/setuptools-84.0.0
  > build(deps-dev): bump setuptools from 83.0.0 to 84.0.0
- [`34a3438`](https://github.com/FanaticPythoner/justdocs/commit/34a3438aa5010a1967871fba841202c487beab1d) Merge branch 'main' into dependabot/pip/main/twine-7.0.0
- [`062deef`](https://github.com/FanaticPythoner/justdocs/commit/062deefcb25ab964114ba2b706dfab76cec6e613) Merge pull request #9 from FanaticPythoner/dependabot/pip/main/twine-7.0.0
  > build(deps-dev): bump twine from 6.2.0 to 7.0.0
- [`a7963ae`](https://github.com/FanaticPythoner/justdocs/commit/a7963ae0b646dd917315b6d7ed87b66064b6566f) Bump version from 1.0.0 to 1.1.0
- [`39e7a07`](https://github.com/FanaticPythoner/justdocs/commit/39e7a07002bdee3886769210034f228d91be1ad4) Revert commit version from 1.1.0 to 1.0.0

## v1.0.0 - 2026-07-12

- release tag: `v1.0.0`
- previous release: `v0.1.0`

### Included commits

- [`4452ad9`](https://github.com/FanaticPythoner/justdocs/commit/4452ad948dab78c8dc639acfbaf839f96ab6604e) fix: harden PR artifact cleanup and release preparation
  > Extend PR distribution handling with closed-PR cleanup, run-bound comment
  > identity, stale-run artifact deletion, and repository-bound pull-request
  > validation. Correct initial release bumping, remove local release-note output,
  > and strengthen concurrent GitHub release reads and recovery.
  > 
  > PR distribution lifecycle:
  > - Add a pinned `pull_request_target` workflow for closed PR cleanup.
  > - Restrict lifecycle permissions to actions deletion, repository reads, and PR comment writes.
  > - Serialize cleanup per pull request without cancellation.
  > - Validate pull-request number, closed state, head SHA, and base repository identity.
  > - Delete only `justdocs-python-dist` artifacts bound to the managed workflow run.
  > - Preserve unrelated artifacts during cleanup.
  > - Replace the managed bot comment with a terminal unavailable message after closure.
  > - Reject multiple managed comments and incomplete comment identities.
  > - Encode workflow run ID, attempt, and head SHA in the managed comment marker.
  > - Remove stale artifacts when a workflow run targets an outdated PR head.
  > - Remove failed-run artifacts before synchronizing unavailable comments.
  > - Reconcile older run identities while preventing older runs from replacing newer comments.
  > - Extend workflow contract tests for pinned actions, permissions, checkout safety, and cleanup arguments.
  > 
  > Release preparation:
  > - Apply the requested SemVer bump when no stable tag exists.
  > - Preserve latest-tag and project-version equality checks for established releases.
  > - Stop writing local release-note artifacts during release preparation.
  > - Support `--` argument forwarding for Just recipe dispatch.
  > - Update README and bundled reference documentation with initial-bump and runner-generated release behavior.
  > - Document closed-PR artifact deletion and terminal comment synchronization.
  > 
  > GitHub release transactions:
  > - Compare the second release metadata snapshot against all fields except `is_latest`.
  > - Preserve the second metadata snapshot when only latest-release binding changes during asset retrieval.
  > - Continue rejecting disappearance or concurrent mutation of every other release field.
  > - Return verified post-query metadata with the independently queried asset inventory.
  > - Treat committed transactions as idempotent only when published state still matches the journal.
  > - Reject committed transaction recovery when published release state diverges.
  > 
  > Tests:
  > - Verify initial major release creation updates `pyproject.toml`, changelog headings, commit subject, and annotated tag.
  > - Verify initial and subsequent release preparation writes no `artifacts` directory.
  > - Verify forwarded patch-bump arguments create the next stable tag.
  > - Verify stale PR workflow runs delete their bound artifact and preserve newer comment ownership.
  > - Verify closed PR cleanup deletes the bound artifact, preserves unrelated artifacts, and patches one terminal comment.
  > - Verify concurrent `is_latest` mutation during release querying remains accepted while other mutations remain rejected.
  > - Extend package workflow assertions to include the lifecycle workflow and its pinned action set.
  > 
  > Checks:
  > - `git diff --cached --check` passes with no output.
  > - `PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 PYTHONPATH=. python3 -m unittest tests.test_package.ThemePackageTest.test_create_next_release_applies_initial_major_bump_without_artifacts tests.test_package.ThemePackageTest.test_pr_distribution_comment_binds_event_artifact_and_bot_comment tests.test_package.ThemePackageTest.test_pr_distribution_close_removes_artifact_and_terminates_comment tests.test_package.ThemePackageTest.test_release_transaction_rejects_release_race_tag_cas_and_nonmonotonic` passes: 4 tests in 2.317 seconds.
  > 
  > Measurements:
  > - Staged scope: 8 files, 420 insertions, 48 deletions.
- [`4184429`](https://github.com/FanaticPythoner/justdocs/commit/41844296d7fbd6aadce038a6226ed1c3838e43e1) fix: harden workflow concurrency and release tag isolation
  > Scope CI cancellation to each workflow and pull request, cancel superseded
  > latest publication runs, and add dependency review for pull requests. Refresh
  > pinned security actions, shorten distribution retention, and fetch only
  > version-prefixed release tags so a moving `latest` alias cannot block
  > next-release preparation.
  > 
  > Workflow coordination:
  > - group CI runs by workflow and pull-request number or full ref
  > - cancel an in-progress `latest-main` run when a newer run enters the group
  > - retain `justdocs-python-dist` for 30 days instead of 90
  > - synchronize the README artifact-retention contract
  > 
  > Security and provenance:
  > - add a pull-request-only dependency-review job on Ubuntu 24.04
  > - check out review inputs with the pinned checkout v7 action
  > - pin dependency review to an immutable action commit
  > - refresh CodeQL initialization and analysis pins within v4
  > - refresh the build-provenance attestation pin within v4
  > 
  > Release preparation:
  > - replace broad `--tags` fetching with `--no-tags` and explicit refspecs
  > - force-refresh every remote branch tracking ref while pruning stale branches
  > - fetch only `refs/tags/v*` into matching local version-tag refs
  > - leave moving nonversion tags such as `latest` outside release preparation
  > 
  > Tests:
  > - extend the security action allowlist for dependency review and refreshed pins
  > - require 30-day CI artifact retention and cancellable latest publication
  > - create and advance a remote `latest` tag before next-release preparation
  > - require `latest` to remain intact while the next `v*` release tag is created

## v0.1.0 - 2026-07-12

- release tag: `v0.1.0`
- previous release: none

- Add the installable `justdocs` CLI, isolated global installers, project recipe commands,
  self-update support, and reproducible Python distributions.
- Add the packaged MkDocs theme, local search, smart links, responsive navigation, Mermaid,
  syntax highlighting, copy controls, and persistent display preferences.
- Add transactional GitHub Release publication with exact-length uploads, descriptor-bound
  filesystem operations, rollback recovery, and moving `latest` prerelease support.
- Add Python 3.10 through 3.14, free-threaded Python, macOS, Windows, distribution, security,
  documentation, and artifact-integrity checks.

### Included commits

- [`13a2fd8`](https://github.com/FanaticPythoner/justdocs/commit/13a2fd86b974dcd608e72a13cea3399ae1700af6) Initial commit
- [`dc28c39`](https://github.com/FanaticPythoner/justdocs/commit/dc28c3970c88647e196eebc9f00e4e523f52eb27) Add justdocs MkDocs theme package
  > - Package justdocs 0.1.0 with setuptools metadata, Python 3.10+ support,
  >   MkDocs >=1.6,<3, console script, theme entry point, and linker plugin entry
  >   point.
  > - Include theme templates, static CSS/JS assets, Mermaid license text, and the
  >   project Justfile template as setuptools package data.
  > - Add `justdocs theme-dir` to validate and print the bundled MkDocs theme path.
  > - Add `justdocs init` to write project-local Justfiles with root, MkDocs config,
  >   bind address, package spec, and forced overwrite controls.
  > - Add typed asset errors for incomplete theme and project template bundles.
  > - Add project Justfile generation with frozen config, address-derived port,
  >   placeholder replacement, existing-file preservation, forced regeneration, and
  >   editable install flag rejection.
  > - Add source Justfile recipes for package install, theme path lookup, unit tests,
  >   generated example Justfile refresh, strict example build, serve, and aggregate
  >   check.
  > - Add generated project recipes for install, check/build, serve, serve-clean,
  >   free-port, clean, dist-clean, env overrides, local source install locking via
  >   `flock`, and `pymdown-extensions==10.12`.
  > - Add MkDocs theme config extending stock MkDocs with 404 template, navigation
  >   depth, primary nav style, color mode, and user color mode toggle.
  > - Add base, main, and 404 templates for topbar, left navigation, right TOC,
  >   pagination, mobile navigation, search, theme toggle, preferences, sidebar
  >   controls, sidebar resizers, sidebar restore buttons, and drawer scrim.
  > - Inject `extra.justdocs` palette, typography, shape, layout, preference,
  >   feature, sidebar, breakpoint, and search values into CSS tokens and
  >   `window.JUSTDOCS`.
  > - Add theme CSS for responsive grid layout, drawer/mobile states, collapsible
  >   sidebars, resizable rails, preferences, search results, light/dark tokens,
  >   table labels, mobile table cards, code blocks, linked inline code, Mermaid
  >   blocks, reduced motion, and print output.
  > - Add theme JS for viewport state, topbar height sync, sidebar width clamping,
  >   localStorage sidebar state, pointer and keyboard resizing, preferences
  >   persistence, preferences reset, local search loading, result scoring, snippet
  >   highlighting, navigation scroll persistence, theme switching, table labels,
  >   Highlight.js setup, code copy setup, and Mermaid render/re-render.
  > - Bundle Highlight.js v11.9.0 GitHub Dark CSS/JS, copy-button CSS/JS with
  >   browser global export, Mermaid JS, and Mermaid MIT license text.
  > - Add `justdocs-linker` to collect heading, page-stem, and action-ID targets;
  >   remove stop phrases and ambiguous targets; normalize whitespace, dashes, and
  >   case; compute relative URLs; protect fences, links, reference definitions,
  >   tags, headings, and inline code; and bound links per page and per target.
  > - Link inline action IDs matching `P\d+-\d{4}` while preserving fenced code and
  >   existing Markdown links.
  > - Add an executable example site with search, `justdocs-linker`,
  >   `pymdownx.highlight`, Mermaid superfences, TOC permalinks, complete
  >   `extra.justdocs` configuration, and pages covering Service Discovery,
  >   Deployment Guide, Traffic Policy, tables, code, and Mermaid.
  > - Add reference content recording theme, search, smart-link, and complexity
  >   contracts, including O(n), O(p * q), and O(p * t * s) operation bounds.
  > - Expand README from a stub into package, configuration, CLI, generated recipe,
  >   source command, and runtime behavior reference.
  > - Add audit artifact mapping project Justfile generation files, flows, guards,
  >   deterministic invariants, scope completion, and verification evidence.
  > - Ignore generated `examples/**/site/` outputs.
  > - Add 23 unittest cases covering packaged assets, template availability,
  >   Justfile rendering, overwrite refusal, forced overwrite, editable package spec
  >   rejection, theme metadata, template assets, sidebar controls, preferences,
  >   Mermaid, code copy, feature gates, CSS layout contracts, example config,
  >   relative URLs, prose/table smart links, and inline action-ID links.
- [`ba6433b`](https://github.com/FanaticPythoner/justdocs/commit/ba6433b2787955a210a193e47d1d0884d257c247) Refresh Justdocs docs and example contract coverage
  > - Expand the README into a complete Justdocs reference for package metadata,
  >   Python and MkDocs requirements, console script binding, theme entry point,
  >   plugin entry point, packaged theme assets, and the project Justfile template.
  > - Document the full MkDocs integration surface with `search`,
  >   `justdocs-linker`, tables, `pymdownx.highlight`, Mermaid superfences, TOC
  >   permalinks, and the complete `extra.justdocs` config shape.
  > - Define every documented theme config default for title, favicon, palette,
  >   typography, shape, content width, density, motion, breakpoints, sidebars,
  >   preferences, feature gates, and client search limits.
  > - Add browser runtime contracts for viewport datasets, compact topbar state,
  >   small viewport state, theme, density, content width, motion, sidebar state,
  >   sidebar widths, nav scroll storage, search index resolution, search scoring,
  >   Mermaid initialization, and sidebar resizing keys.
  > - Document `justdocs theme-dir` and `justdocs init` CLI behavior, including
  >   asset validation, generated Justfile output, init flags, overwrite policy, and
  >   typed failure classes.
  > - Document generated project recipes for install, check, build, serve,
  >   serve-clean, free-port, clean, and dist-clean, including every
  >   `JUSTDOCS_*` environment override.
  > - Record local source install locking through `flock`, lock directory layout,
  >   extra package installation with `pymdown-extensions==10.12`, and editable
  >   install rejection.
  > - Add source-repo recipe docs for local package install, theme path lookup,
  >   example Justfile regeneration, unit tests, strict example build, example
  >   serve, and aggregate check.
  > - Define `justdocs-linker` plugin config defaults for enabled state, minimum
  >   phrase length, per-page link cap, and per-target link cap.
  > - Document smart-link target generation from page H1s, ATX headings, file
  >   stems, action stems, and action IDs.
  > - Document smart-link filtering for stop phrases, ambiguous phrases, phrase
  >   eligibility, deterministic ordering, and current-page exclusions.
  > - Document protected Markdown ranges for fenced code, existing links, reference
  >   definitions, HTML tags, ATX headings, inline code, and linkable inline action
  >   IDs.
  > - Add complexity bounds for target collection, target dedupe, protected range
  >   merging, smart-link passes, theme asset validation, template rendering, and
  >   search scoring.
  > - Add packaged asset and runtime error reference tables covering required theme
  >   files, Highlight.js assets, copy-button assets, Mermaid assets, template
  >   files, search failures, missing controls, and missing browser globals.
  > - Replace the example service-topic docs with Justdocs-specific pages for
  >   Theme Configuration, Project Setup, Smart Links, and Reference.
  > - Update the example index to exercise the current docs graph, runtime feature
  >   table, required MkDocs plugins, Mermaid rendering, Python API snippet, and
  >   mobile table label behavior.
  > - Add explicit example nav entries for Theme Configuration, Project Setup,
  >   Smart Links, and Reference in `examples/basic/mkdocs.yml`.
  > - Remove obsolete Service Discovery, Deployment Guide, and Traffic Policy
  >   example pages from the staged docs surface.
  > - Extend docs tests to require the new example nav entries, verify README and
  >   example docs both cover current contract terms, and reject stale service-topic
  >   terms from the example docs.
  > - Update smart-link table/prose tests to use current Justdocs page targets while
  >   preserving coverage for tables, prose, inline code protection, existing link
  >   preservation, and Mermaid fenced code protection.
  > - Keep staged scope to 11 files with 648 insertions and 117 deletions across
  >   README, example docs, example nav, and docs coverage tests.
- [`15edb7e`](https://github.com/FanaticPythoner/justdocs/commit/15edb7ee689b4222a1ecc106e69ec34e4badccd4) perf: compile smart-link targets into one match graph
  > Build a compiled smart-link graph during MkDocs file discovery and reuse it
  > while each page is linked, replacing repeated per-target regex scans with one
  > aggregate matcher plus normalized-key lookup.
  > 
  > Smart-link compilation:
  > - Replace per-target compiled regex storage with normalized target keys and
  >   reusable pattern text.
  > - Add `CompiledLinkGraph` for compiled targets, exact-key target lookup, and an
  >   optional aggregate regex.
  > - Build empty target sets as `pattern=None` so link segments return unchanged
  >   without regex work.
  > 
  > Linking behavior:
  > - Change `_link_segment()` to search the aggregate regex from each cursor
  >   position instead of scanning every target pattern.
  > - Resolve matches through normalized `match.group(0)` keys before applying
  >   self-link and per-target cap checks.
  > - Keep unmatched, current-page, and cap-exhausted matches as plain text.
  > - Reuse the compiled key lookup for inline action-ID code references.
  > 
  > Plugin lifecycle:
  > - Store `_link_graph` on `JustdocsLinkerPlugin` instead of raw targets.
  > - Reset disabled or empty plugin state to an empty compiled graph.
  > - Compile deduped page candidates once in `on_files()` and pass the graph into
  >   page-level Markdown linking.
  > - Keep `_smart_link_markdown()` compatible with tuple target inputs by compiling
  >   only when callers have not supplied `CompiledLinkGraph`.
  > 
  > Checks:
  > - `git diff --cached --check`
  > - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest discover -s tests`
  >   (`Ran 24 tests in 0.006s`, `OK`)
- [`60a3900`](https://github.com/FanaticPythoner/justdocs/commit/60a3900ac777467247e8549ce38379a98ec4abe3) Remove audits dir
- [`829dc62`](https://github.com/FanaticPythoner/justdocs/commit/829dc627fb551d0550e3b37b62949354bb05ee1b) Add GNU GPL v3 license file
  > Added the GNU General Public License version 3 to the project.
- [`912a5c5`](https://github.com/FanaticPythoner/justdocs/commit/912a5c5f14af7874d932dee473e74cddacf520f4) Update README with public status note
  > Updated README to reflect public status change.
- [`26b4d58`](https://github.com/FanaticPythoner/justdocs/commit/26b4d5815ac65b07c75123086dde2dd32ab489b5) Update repository visibility and license note
- [`550dd8c`](https://github.com/FanaticPythoner/justdocs/commit/550dd8c154fcf8c24e185bc73eb17afc62e723d7) Fix punctuation in README note about repository status
- [`5dff853`](https://github.com/FanaticPythoner/justdocs/commit/5dff853d73a0d95a94f5a405df80c1cd05cfb73c) feat: ship installable justdocs CLI and release automation
  > Expose justdocs as a user-global command without cloning, mirror generated
  > project recipes through the installed CLI, add package self-maintenance commands,
  > and wire the repository for validated Python distribution releases.
  > 
  > Global Installation:
  > - Add executable `install.sh` for `curl -fsSL .../install.sh | sh` installs.
  > - Add `install.ps1` for `irm .../install.ps1 | iex` Windows installs.
  > - Default bootstrap installs to the GitHub `main` archive at
  >   `https://github.com/FanaticPythoner/justdocs/archive/main.tar.gz`.
  > - Support `JUSTDOCS_INSTALL_SOURCE=github`, `pypi`, and `url` across both
  >   bootstrap installers.
  > - Support exact PyPI versions with `JUSTDOCS_INSTALL_VERSION`.
  > - Support full pip requirement overrides with `JUSTDOCS_INSTALL_SPEC`.
  > - Support custom archive URLs with `JUSTDOCS_INSTALL_URL`.
  > - Support custom repositories and refs with `JUSTDOCS_REPOSITORY` and
  >   `JUSTDOCS_INSTALL_REF`.
  > - Add `JUSTDOCS_INSTALL_DRY_RUN` so CI can assert resolved pip commands without
  >   mutating global user state.
  > - Require Python 3.10+ before invoking pip in both bootstrap installers.
  > - Use `ensurepip --user` when pip is absent before global install.
  > - Verify the installed `justdocs` command resolves from the selected
  >   interpreter user scripts directory.
  > - Fail when `justdocs` is absent from `PATH` or shadowed by another command.
  > - Add source-tree `just global-install` and `just install-global` aliases.
  > - Add source-tree `just global-uninstall` and `just uninstall-global` aliases.
  > - Route source global install and uninstall through `justdocs.global_cli`.
  > - Validate source installs by `pyproject.toml` presence before invoking pip.
  > - Detect platform console script names for POSIX and Windows user script dirs.
  > - Verify uninstall by checking that user script candidates were removed.
  > - Share cross-platform source install locks through `justdocs.install_support`.
  > 
  > Project Recipe CLI:
  > - Make bare `justdocs` exit successfully with parser help and common commands.
  > - Add `justdocs project` and `justdocs projects` namespaces.
  > - Expose `init`, `install`, `check`, `build`, `serve`, `serve-clean`,
  >   `free-port`, `clean`, and `dist-clean` as CLI recipe equivalents.
  > - Preserve `justdocs init` as the direct project Justfile generator.
  > - Add `ProjectRecipeConfig` for root, MkDocs config, bind address, port,
  >   package spec, extra packages, virtualenv path, and Python executable.
  > - Resolve virtualenv paths under the selected project root.
  > - Create virtualenvs only when the configured interpreter is missing.
  > - Run project installs as virtualenv pip commands.
  > - Upgrade pip before installing the configured package and extra packages.
  > - Reuse `split_package_spec` so CLI recipes inherit editable-install rejection.
  > - Serialize local source package installs with the shared install lock.
  > - Run strict MkDocs builds as `mkdocs build -f <config> --strict --clean`.
  > - Implement serve and serve-clean through the configured address.
  > - Validate free-port inputs as TCP ports in `1..65535`.
  > - Use `lsof` or `fuser` for POSIX listener discovery.
  > - Use `netstat -ano -p TCP` and `taskkill /F` for Windows listener cleanup.
  > - Remove `site`, `.cache`, `.mkdocs_cache`, and the configured virtualenv for
  >   cleanup recipes.
  > 
  > Version And Package Maintenance:
  > - Add `justdocs version` and `justdocs version --json`.
  > - Add `justdocs version --check` to combine installed version output with
  >   remote metadata checks.
  > - Add `justdocs self check-update` with PyPI JSON and GitHub latest release
  >   sources.
  > - Add `justdocs self update` with PyPI and GitHub release tag install targets.
  > - Parse versions through `packaging.version.Version` for PEP 440 ordering.
  > - Normalize GitHub tags by removing a leading `v`.
  > - Report malformed PyPI and GitHub metadata through `UpdateCheckError`.
  > - Report pip install failures through `UpdateInstallError`.
  > - Resolve GitHub repository slugs from installed package metadata Project-URL
  >   entries.
  > - Emit JSON result payloads for automation consumers.
  > 
  > Release Automation:
  > - Add a reusable `build-dist` composite action around the release build script.
  > - Add a reusable `release-assets` composite action for GitHub Release create,
  >   edit, purge, and upload flows.
  > - Add CI for Python `3.10`, `3.11`, `3.12`, `3.13`, `3.13t`, `3.14`, and
  >   `3.14t`.
  > - Add CI coverage on `ubuntu-24.04`, `macos-15`, and `windows-2025`.
  > - Build and upload distribution artifacts from the Python `3.12` CI row.
  > - Add a reusable workflow to build Python distributions from an arbitrary ref.
  > - Add a tagged release workflow for `v*.*.*` pushes and manual existing-tag
  >   dispatch.
  > - Validate release tags against `pyproject.toml` version before publishing.
  > - Require the release tag commit to be reachable from `origin/main`.
  > - Publish to PyPI through `pypa/gh-action-pypi-publish@release/v1` only when
  >   `PYPI_API_TOKEN` exists.
  > - Stage only `.whl` and `.tar.gz` files into `artifacts/pypi`.
  > - Attest wheel and sdist provenance through `actions/attest-build-provenance`.
  > - Verify public PyPI visibility after credentialed publishes.
  > - Add a scheduled and push-triggered `latest` prerelease workflow for `main`.
  > - Generate release notes from commits since the previous semantic version tag.
  > - Stage `install.sh` and `install.ps1` with release assets.
  > - Generate `SHA256SUMS.txt` over release installers, wheel, and sdist.
  > - Add Dependabot coverage for pip and GitHub Actions dependencies.
  > - Add CodeQL analysis for Python and GitHub Actions.
  > - Add dependency review for pull requests.
  > 
  > Packaging Metadata:
  > - Raise the build backend requirement to `setuptools>=77`.
  > - Add `README.md` as package readme metadata.
  > - Add SPDX license metadata with `GPL-3.0-only`.
  > - Add `license-files = ["LICENSE"]`.
  > - Add `packaging>=24,<26` as a runtime dependency for version ordering.
  > - Add Python `3.14` and free-threading classifiers.
  > - Add CPython, MkDocs, console, developer audience, and documentation topic
  >   classifiers.
  > - Add Homepage, Repository, Issues, and Releases project URLs.
  > - Ignore generated release artifacts while keeping audit markdown files tracked.
  > 
  > Documentation And Audit Artifacts:
  > - Document no-clone POSIX and PowerShell bootstrap install commands.
  > - Document bootstrap environment variables and PATH verification failures.
  > - Document global install and uninstall source recipes.
  > - Document project recipe CLI command parity.
  > - Document version checks, package self-maintenance commands, and release flows.
  > - Document PyPI credential gating and GitHub release asset behavior.
  > - Add example docs coverage for bootstrap installers and release automation.
  > - Add reference docs for `ProjectRecipeConfig`, `ProjectRecipeError`,
  >   `GlobalCliError`, `UpdateCheckError`, and `UpdateInstallError`.
  > - Add audit artifacts mapping file roles, flows, invariants, fixed locations,
  >   scope completion, tests, and complexity for global CLI and release work.
  > 
  > Tests:
  > - Add contract coverage for source Justfile global install recipes and aliases.
  > - Add project init alias coverage for `justdocs projects init`.
  > - Add no-arg CLI command hub coverage.
  > - Add project recipe dispatch coverage for CLI arguments and environment
  >   override plumbing.
  > - Add PyPI and GitHub version candidate selection coverage.
  > - Add current-version and PEP 440 ordering coverage.
  > - Add pip command construction coverage for PyPI and GitHub updates.
  > - Add CLI self-update dispatch coverage.
  > - Add release workflow assertions for setup-python v6, PyPI publishing,
  >   artifact staging, release actions, Python 3.14, and free-threaded rows.
  > - Add bootstrap installer assertions for shell syntax, default GitHub archive
  >   dry-run, explicit PyPI dry-run, and tagged GitHub archive dry-run.
  > - Add global CLI script candidate coverage for POSIX and Windows names.
  > - Add locked user pip install coverage for source global install.
  > - Add uninstall verification coverage for global CLI removal.
  > - Add project recipe install coverage for venv creation, pip upgrade, package
  >   install, extra packages, and lock use.
  > - Add project recipe strict MkDocs command coverage.
  > - Add project clean and invalid free-port coverage.
  > - Extend docs coverage required terms to CLI, release, installer, and package
  >   metadata contracts.
  > 
  > Checks:
  > - `git diff --cached --check`
  > - `sh -n install.sh`
  > - `bash -n scripts/release/build-python-package.sh scripts/release/release-artifacts.sh scripts/release/release-versioning.sh scripts/release/resolve-release-metadata.sh scripts/release/verify-pypi.sh scripts/release/write-release-notes.sh`
  > - `JUSTDOCS_INSTALL_DRY_RUN=1 JUSTDOCS_PYTHON=$(command -v python3) sh install.sh`
  > - `JUSTDOCS_INSTALL_DRY_RUN=1 JUSTDOCS_PYTHON=$(command -v python3) JUSTDOCS_INSTALL_SOURCE=pypi sh install.sh`
  > - `JUSTDOCS_INSTALL_DRY_RUN=1 JUSTDOCS_PYTHON=$(command -v python3) JUSTDOCS_INSTALL_SOURCE=github JUSTDOCS_INSTALL_REF=v0.1.0 sh install.sh`
  > - `.venv/bin/python - <<'PY' ... yaml.safe_load(...) ... PY`
  > - `just test`
  > - `just check`
  > - `just dist`
  > 
  > Measurements:
  > - Staged diff: 33 files changed, 3156 insertions, 32 deletions.
  > - Workflow parse: 9 YAML files parsed.
  > - Unit suite: 44 tests passed.
  > - Strict docs build: documentation built in 0.14 seconds.
  > - Distribution validation: wheel and sdist passed Twine checks.
  > - Release artifact set: `SHA256SUMS.txt`, `install.ps1`, `install.sh`,
  >   `justdocs-0.1.0-py3-none-any.whl`, and `justdocs-0.1.0.tar.gz`.
- [`d87e960`](https://github.com/FanaticPythoner/justdocs/commit/d87e9608de0119028cf699eaac1418ef395e777d) feat: unify CLI project, install, update, and release flows
  > Replace alias-heavy user-site lifecycle paths with canonical `projects`
  > commands, stored project configuration, isolated platform installers,
  > release-wheel updates, and reproducible PEP 440 release automation. Enforce
  > ownership, path confinement, bounded metadata, deterministic lock order,
  > atomic writes, publication authentication, and synchronized documentation.
  > 
  > CLI contract:
  > - Make `projects` the sole project namespace with `init`, `install`, `check`,
  >   `build`, `serve`, `serve-clean`, `free-port`, `clean`, and `dist-clean`.
  > - Move update discovery and installation to top-level `check-update` and
  >   `update`; default update source selection to `auto` across PyPI and GitHub.
  > - Remove top-level `init`, singular `project`, nested `self` commands,
  >   `version --check`, `update --user`, and source recipe aliases
  >   `install-global` and `uninstall-global`.
  > - Load theme, project, and update modules only for matching commands so bare
  >   help and version lookup avoid unrelated engines.
  > - Read installed version solely from distribution metadata through the new
  >   `version` module; remove the static package `__version__` fallback and fail
  >   explicitly when metadata is absent.
  > - Centralize package name, 3-second network timeout, default address, and
  >   default extra-package requirement in `constants.py`.
  > - Report exact updated/current outcomes and preserve partial source failures as
  >   stderr warnings.
  > 
  > Project configuration:
  > - Persist schema-1, sorted, ASCII-safe JSON in the first generated Justfile
  >   line with exact `mkdocs_config`, `addr`, `package`, `extra_packages`, and
  >   `venv` fields.
  > - Bound stored configuration reads to 65,536 bytes and reject symlinks,
  >   non-regular files, non-UTF-8 text, malformed JSON, unknown or missing fields,
  >   non-string values, and unsupported schemas.
  > - Resolve project settings by CLI option, `JUSTDOCS_*` environment value,
  >   stored Justfile value, then package default; derive port from the effective
  >   address when no explicit port exists.
  > - Validate template marker cardinality and JSON-escape quotes, newlines, and
  >   shell-shaped values before rendering.
  > - Write generated Justfiles through same-directory temporary files, `fsync`,
  >   mode preservation, and atomic replacement; replace forced symlinks without
  >   following their targets.
  > - Preserve PEP 508 requirements, URLs, and filesystem paths with spaces as
  >   single pip arguments while rejecting empty specs and every pip option token.
  > - Replace 43-line Bash-specific generated recipes with 28-line,
  >   platform-neutral delegates to `justdocs projects`; retain all eight recipe
  >   names.
  > - Add Windows PowerShell shell selection, platform Python defaults, canonical
  >   example generation, and repository-venv PATH injection to the source
  >   Justfile.
  > 
  > Project execution and locking:
  > - Lock the configured virtualenv plus every local source package from primary
  >   and extra requirements in deduplicated lexical order across venv creation
  >   and pip installation.
  > - Remove the independent pip self-upgrade from project installation.
  > - Secure shared install-lock storage with canonical full SHA-256 names, POSIX
  >   owner checks, `0700` root mode, `0600` file mode, and symlink rejection.
  > - Restrict virtualenv paths to strict descendants of the resolved project root,
  >   including symlink-mediated paths.
  > - Unlink output symlinks without traversal, reject regular-file cleanup
  >   targets, and translate filesystem failures into project errors.
  > - Reject malformed POSIX and Windows listener PIDs, preserve the `1..65535`
  >   port invariant, and translate subprocess launch failures.
  > - Reject Boolean and nonpositive integer values for linker limits during
  >   MkDocs configuration.
  > - Preserve existing theme/template asset resolution and smart-link transforms;
  >   limit new linker behavior to configuration-bound validation.
  > 
  > Bootstrap installers:
  > - Replace current-interpreter user-site installs with isolated managed roots at
  >   `$HOME/.justdocs` on POSIX and `%LOCALAPPDATA%\justdocs` on Windows.
  > - Create a dedicated virtualenv and managed `bin/justdocs[.exe]` command;
  >   verify command execution with `justdocs version`.
  > - Resolve the default GitHub source from the latest-release API and select
  >   exactly one `justdocs-*-py3-none-any.whl`; retain explicit PyPI, URL,
  >   source-spec, and GitHub-ref archive modes.
  > - Bound release metadata to 2 MiB with a positive finite 10-second default
  >   timeout; validate repository syntax, UTF-8 JSON shape, tag presence, asset
  >   count, HTTPS GitHub host, and filename agreement.
  > - Require Python 3.10 or newer and reject invalid Boolean controls or specs
  >   beginning with pip options.
  > - Require the `justdocs-managed-v1` ownership marker and reject filesystem
  >   roots, user-home roots, Windows reparse roots, nonempty unmanaged roots,
  >   invalid markers, and unowned commands.
  > - Serialize installer mutation through recoverable POSIX PID locks or exclusive
  >   Windows file locks; reject live lock owners.
  > - Require exact managed symlink ownership on POSIX and SHA-256 executable
  >   equality on Windows before replacement or removal.
  > - Manage POSIX shell/fish profile blocks and Windows user PATH idempotently;
  >   reject malformed POSIX marker blocks and remove duplicate Windows entries.
  > - Expose dry-run output for venv, pip, command, and PATH operations without
  >   acquiring the install lock or mutating the managed root.
  > - Route source-tree global install and uninstall through the same platform
  >   bootstrappers with explicit action, source root, and interpreter environment.
  > 
  > Self-update:
  > - Bound PyPI and GitHub JSON to 2 MiB, require positive finite timeouts, and
  >   distinguish HTTP 404 publication absence from transport or metadata failure.
  > - Deduplicate requested sources, retain source warnings when a candidate
  >   survives, and fail when transport errors leave no candidate.
  > - Normalize versions with PEP 440 and select the newest candidate across
  >   enabled sources.
  > - Derive the GitHub repository only from canonical installed HTTPS metadata;
  >   remove the hardcoded repository fallback.
  > - Require canonical release HTML metadata and exactly one version-matched
  >   `py3-none-any` wheel with an HTTPS GitHub download URL.
  > - Install GitHub updates from release wheels instead of VCS checkouts.
  > - Reject downgrades and explicit versions with ambiguous `auto` source; return
  >   without pip execution when the installed version is current.
  > - Infer `--user` only for base-interpreter distributions under user site and
  >   omit it for virtualenv or system distributions.
  > - Re-read installed metadata after pip and require exact normalized target
  >   version equality.
  > 
  > Packaging and release automation:
  > - Pin `setuptools==83.0.0`, add release extras `build==1.5.1` and
  >   `twine==6.2.0`, and widen runtime packaging to `packaging>=24`.
  > - Seed builds with `PYTHONHASHSEED=0` and the latest commit timestamp as
  >   `SOURCE_DATE_EPOCH`.
  > - Repack sdists in sorted PAX order with gzip mtime zero, normalized member
  >   timestamps, zero UID/GID, empty owner names, and cleared pax headers.
  > - Replace regex tag ordering with `packaging.version.Version`, discard invalid
  >   PEP 440 tags, and derive prerelease state from `Version.is_prerelease`.
  > - Require the release tag to equal the raw `pyproject.toml` version and retain
  >   tagged-commit ancestry verification against remote `main`.
  > - Percent-encode PyPI verification paths, use a 15-second interval,
  >   600-second deadline, and 10-second request cap, reject non-finite bounds,
  >   cap responses at 2 MiB, and require exact published-version equality.
  > - Prefer PyPI trusted publishing, fall back to API-token authentication with
  >   publisher attestations disabled, skip publication when neither is
  >   configured, record the mode, and retain independent provenance attestation.
  > - Stage sorted wheel and sdist artifacts through the shared release inventory
  >   helper; remove inherited secrets and the unused reusable-build
  >   `release_tag` input.
  > - Install Python 3.12 plus `packaging>=24` before stable and nightly release
  >   note generation.
  > 
  > Documentation and tests:
  > - Rewrite README and example project/reference docs for canonical commands,
  >   release-asset bootstrap URLs, isolated roots, PATH controls, uninstall,
  >   stored-config precedence, typed errors, update semantics, and publishing
  >   authentication.
  > - Remove stale raw-main installers, user-site behavior, legacy command aliases,
  >   static version claims, and the `packaging<26` contract from documentation.
  > - Expand `tests/test_package.py` from 44 to 75 test methods with project JSON,
  >   atomic/symlink writes, package parsing, CLI removals, and config precedence
  >   coverage.
  > - Add update tests for 404 handling, canonical repository and wheel metadata,
  >   2 MiB bounds, PEP 440 selection, exact pip commands, no-op, downgrade,
  >   ambiguous source, pip scope, and post-install verification.
  > - Add installer tests for platform dry-runs, latest-wheel resolution, ownership
  >   refusal, preserved external targets, stale/live locks, invalid controls, and
  >   bootstrap delegation.
  > - Add release tests for trusted/token publication, deterministic build markers,
  >   PEP 440 tag ordering, polling bounds, artifact staging, and removed workflow
  >   secret/input surfaces.
  > - Add project-runtime tests for deterministic multi-root locking, strict MkDocs
  >   builds, confined cleanup, symlink unlinking, PID parsing, and linker limits.
  > - Enforce docs freshness by requiring canonical surfaces and rejecting removed
  >   aliases and stale taxonomy.
  > 
  > Algorithmic bounds:
  > - Let `L` be first-line bytes; read stored configuration in
  >   O(min(L, 65,537)) time and space.
  > - Let `r` be lock roots; discover and sort them in O(r log r) time and O(r)
  >   space.
  > - Let `a` be release assets; filter them in O(a) time and O(a) candidate space.
  > - Let `m` be sdist members and `b` payload bytes; normalize them in
  >   O(m log m + b) time, O(m) memory, and O(b) temporary disk.
  > - Let `T` be polling duration and `i` interval; issue at most
  >   floor(T / i) + 1 requests when request duration approaches zero.
  > 
  > Checks:
  > - `PYTHONDONTWRITEBYTECODE=1 just check`: 75 tests pass; strict example build
  >   completes.
  > - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m unittest
  >   discover -s tests`: 75 tests pass in 0.973s.
  > - `ruff check .`: pass.
  > - `ruff format --check .`: 14 files already formatted.
  > - `sh -n install.sh` plus Bash syntax checks for staged release scripts: pass.
  > - `git diff --cached --check`: pass.
  > - `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_package`: 74 of
  >   75 pass; `test_release_versioning_orders_pep440_tags` receives no tags
  >   because the staged helper invokes unavailable `python` and `mapfile` masks
  >   that process-substitution failure.
  > 
  > Measurements:
  > - Staged delta: 28 files, 3,090 insertions, 876 deletions, two new modules.
  > - Test inventory: 44 -> 75 methods, +31 net.
  > - Repo-native test run: 75 tests in 1.087s; example documentation build in
  >   0.15s.
- [`2493c0c`](https://github.com/FanaticPythoner/justdocs/commit/2493c0c4d760381123425444548805ca4ac81ce5) feat: make release publication transactional
  > Replace direct tag mutation and unverified asset uploads with a versioned,
  > journaled release transaction that snapshots immutable inputs, verifies remote
  > identity around every mutation, and converges through commit-forward or
  > rollback. Reconcile PyPI by exact filename and SHA-256 sets, pin workflows to
  > immutable commits and artifact digests, tighten dependency automation, and add
  > deterministic fault-injection coverage.
  > 
  > Transactional GitHub releases:
  > - add `preflight`, `publish`, and `cleanup` commands with typed errors, exit code
  >   2, SIGINT/SIGTERM handling, and exclusive per-transaction locking
  > - model release assets, release state, and transaction metadata as frozen data
  >   classes updated through immutable replacements
  > - persist schema-version-4 journals as compact sorted JSON through exclusive
  >   temporary files, file and directory fsyncs, and atomic replacement
  > - track original and target tag SHAs, original and prepared release snapshots,
  >   desired metadata, desired asset digests, created release identity, owned asset
  >   IDs, and transaction phase
  > - enforce phase invariants across `preflight`, `prepared`, `mutating`, `tagging`,
  >   `committing`, `committed`, `rolled_back`, and `rolled_back_with_tag`
  > - reject malformed journals, unknown fields, invalid IDs, invalid digests,
  >   inconsistent snapshots, noncanonical parents, repository drift, and boundary
  >   escapes
  > - validate repository identity, tag syntax, Boolean operands, target commit, and
  >   transaction parent before creating a journal
  > - resolve target commits through GitHub and require tags without movement enabled
  >   to reference the exact release commit
  > - compare existing `latest` targets against the requested commit and permit only
  >   `ahead` or `identical` movement
  > - compare-and-set remote tags against the preflight SHA, use non-forced ref
  >   updates, and verify the resulting target
  > - sample release metadata before and after paginated asset enumeration to reject
  >   concurrent release changes
  > - validate positive release and asset IDs, strict Boolean fields, unique asset
  >   names, uploaded or starter states, sizes, content types, and SHA-256 digests
  > - reject incomplete existing uploads before mutation
  > - verify staged snapshots, notes bytes, asset hashes, and asset sizes before
  >   preparation and again immediately before uploads
  > - create absent releases as marker-owned drafts tied to the exact target commit,
  >   persist the created ID, apply desired metadata, upload assets, and publish only
  >   after exact prepared-state verification
  > - transform existing releases into non-latest drafts, rename selected originals
  >   to database-ID rollback names, upload replacements, move the tag, delete
  >   retained originals, and publish in deterministic order
  > - preserve noncolliding original assets when purge is disabled and replace the
  >   complete original inventory when purge is enabled
  > - upload through verified regular-file descriptors under deterministic temporary
  >   names derived from the transaction and final filename
  > - persist every returned upload ID before further mutation, rename uploads into
  >   final names, and verify ID, label, MIME type, digest, size, and uploaded state
  > - treat exact immutable releases as mutation-free committed transactions and
  >   reject immutable releases that differ from staged metadata or assets
  > - recover `tagging` and `committing` journals by completing publication forward,
  >   including accepted publish or delete operations whose client call failed
  > - recover `mutating` journals by deleting transaction-owned assets, restoring
  >   original asset names and metadata, restoring release flags and text, or
  >   deleting a marker-owned newly created release
  > - preserve an implicitly created target tag as `rolled_back_with_tag` when no
  >   original tag existed, permitting a later independent transaction to converge
  > - delete transaction-owned starter uploads left by failed asset requests
  > - reject and preserve unknown concurrent assets, externally replaced drafts,
  >   reserved-name collisions, asset-ID drift, and indeterminate ownership
  > - retain recovery journals when rollback cannot prove safe ownership
  > - recover active journals during cleanup and remove transaction directories only
  >   after reaching a terminal phase
  > - use GitHub GraphQL for stable release and tag snapshots and REST API version
  >   `2026-03-10` for commit, comparison, ref, release, and asset operations
  > 
  > Release-input snapshots:
  > - add `stage`, `verify`, and `cleanup` commands with snapshot schema version 2
  > - confine distribution and notes operands beneath `GITHUB_WORKSPACE`
  > - accept a lexical workspace alias while rejecting symlinks inside the
  >   workspace-relative path
  > - require `O_DIRECTORY`, `O_NOFOLLOW`, and `O_NONBLOCK` instead of weakening
  >   filesystem checks on unsupported platforms
  > - require exact manifest lines containing 64 lowercase SHA-256 characters, two
  >   spaces, and a confined basename
  > - reject empty manifests, duplicate or self entries, extra or missing files,
  >   symlinks, directories, FIFOs, unreadable files, and digest mismatches
  > - create private `justdocs-release-*` roots under a nonsymlink `RUNNER_TEMP`
  > - copy assets and optional notes through bound descriptors in 1 MiB chunks,
  >   create files exclusively, flush and fsync bytes, and set copied files to mode
  >   `0400`
  > - preserve the literal `SHA256SUMS.txt` bytes and record its digest with every
  >   asset and optional notes digest
  > - serialize deterministic `snapshot.json` metadata and restrict the asset
  >   directory to mode `0500`
  > - verify exact metadata keys, integer snapshot version, root identity, asset
  >   inventory, asset hashes, notes hash, and root inventory
  > - keep staged bytes independent from later source artifact or notes mutation
  > - clean partial snapshots after setup or copy failures and retain both primary
  >   and cleanup errors when removal fails
  > - constrain cleanup to the named child of the supplied parent, reject symlinks
  >   and special entries, and compare root device and inode before removal
  > - retain `O(B + n log n)` staging and verification time with `O(n + 1 MiB)`
  >   auxiliary state for `B` bytes and `n` assets
  > 
  > PyPI reconciliation:
  > - add typed local-artifact, remote-query, and artifact-mismatch errors
  > - bind local wheel and source distributions to no-follow descriptors and hash
  >   them in 1 MiB chunks
  > - query percent-encoded package and version endpoints with JSON headers, a
  >   15-second request bound, and a 4 MiB response ceiling
  > - classify HTTP 404 as `absent` and reject other HTTP, transport, encoding, JSON,
  >   and response-shape failures explicitly
  > - compare versions through PEP 440 normalization, including equality between
  >   forms such as `1.2.3` and `1.2.3.0`
  > - require unique nonempty remote filenames and exact lowercase SHA-256 metadata
  > - return deterministic `absent`, `partial`, or `exact` states with sorted missing
  >   inventories
  > - reject unexpected remote filenames or mismatched shared-file digests
  > - stage only missing files into a previously absent destination using exclusive
  >   mode-`0400` outputs, fsync, byte-count checks, and post-copy hash verification
  > - remove partial staging destinations after failure and report cleanup failure
  >   alongside the primary error
  > - poll with a monotonic deadline, shrinking request bounds, retrying transient
  >   remote failures and incomplete states while propagating artifact mismatches
  > - validate interval and total duration as positive finite values
  > - delegate `verify-pypi.py` to the exact artifact checker through the active
  >   interpreter and pass `artifacts/release` from the shell wrapper
  > - remove the 21-line `release-artifacts.sh` path-only inventory helper
  > 
  > Release workflows:
  > - validate action inputs and stage immutable bytes before any GitHub mutation
  > - route action operands through environment variables, log values with `printf
  >   %q`, and avoid raw workflow expressions inside shell bodies
  > - derive transaction targets from checked-out `HEAD^{commit}` instead of the
  >   workflow event SHA
  > - replace force-pushed tags, direct release create/edit, direct asset deletion,
  >   and `gh release upload --clobber` with transaction preflight and publication
  > - preserve staging and preflight failures while surfacing cleanup failures
  > - run final transaction and snapshot cleanup unconditionally and attempt both
  >   removals independently
  > - upgrade checkout to v7, upload-artifact to v7, download-artifact to v8, CodeQL
  >   to v4, and build-provenance attestation to v4
  > - archive both distribution uploads and reject digest mismatches on all five
  >   distribution downloads
  > - add a CI artifact round trip that downloads `justdocs-python-dist` and verifies
  >   `SHA256SUMS.txt`
  > - replace pattern-based merged downloads with exact named `python-dist`
  >   retrieval
  > - require a tag for manual stable releases and serialize runs by dispatch tag or
  >   pushed ref name
  > - check out the selected stable tag, validate event type and SHA, and carry the
  >   resolved immutable commit through build and publication
  > - fetch `origin/main` for latest releases, require checked-out HEAD equality,
  >   and derive full and 12-character release SHAs from the fetched commit
  > - disable latest-run cancellation so an active publication reaches a terminal
  >   transaction phase
  > - inspect PyPI before credential selection, skip uploads for exact existing
  >   artifacts, and stage only missing distributions for absent or partial states
  > - select trusted publishing before API-token authentication and expose
  >   `existing`, `trusted`, `token`, and `none` publication modes
  > - reject unknown PyPI classifications with exit code 2
  > - provision Python 3.12, exact downloaded artifacts, digest checks, and
  >   `packaging>=24` in the public PyPI verification job
  > - pass release-note and publication values through environment variables instead
  >   of interpolating expressions into executable shell
  > 
  > Release metadata and platform tooling:
  > - add shared validators for exact lowercase Booleans, Git-compatible tags,
  >   control-free release names, and canonical `OWNER/REPOSITORY` identities
  > - constrain owners to 1..39 valid characters and repository names to 1..100
  >   valid characters while excluding malformed hyphen and dot forms
  > - replace Bash nameref and `mapfile` tag selection with a Bash-3.2-compatible
  >   Python implementation
  > - resolve Python from `PYTHON_BIN` or `python3`, require Python 3.10+, return 127
  >   for a missing executable, and preserve interpreter failures
  > - ignore invalid version tags, order valid tags by PEP 440 plus literal tag, and
  >   select the highest or first strictly lower semantic version
  > - dispatch release metadata by `workflow_dispatch` or tag `push` and reject
  >   unsupported events or nontag pushes
  > - require fetched tag, checked-out HEAD, and push event SHA to resolve to the
  >   same commit
  > - emit `release_ref` as the immutable release SHA instead of the mutable tag
  > - wrap PowerShell interpreter resolution in array syntax to preserve one-token
  >   paths and multi-token `py -3` prefixes
  > - quote the POSIX `profile_kind='sh'` assignment
  > - preserve Markdown commit-link backticks through the release-note `printf`
  >   format
  > - ignore the complete `TODOS_LISTS/` tree and `.tmp-workflow-tools/`
  > 
  > Security automation:
  > - group all GitHub Actions dependency changes under one weekly Dependabot group
  > - replace pull-request-only dependency review with pinned `pip-audit==2.10.1`
  >   strict resolved-project auditing across every security workflow trigger
  > - retain Python and Actions CodeQL matrices while upgrading initialization and
  >   analysis to v4
  > 
  > Tests:
  > - add 26 test methods, including 15 transactional release scenarios
  > - add a stateful fake GitHub CLI covering GraphQL reads, paginated assets,
  >   commits, comparisons, refs, releases, binary uploads, renames, deletes, and
  >   deterministic failure injection
  > - cover immutable exact no-op and mismatch rejection, malformed operands,
  >   release-query races, nonmonotonic latest movement, and tag compare-and-set
  >   failures
  > - verify absent-release marker creation, payloads, target SHA, temporary upload
  >   naming, MIME types, digests, journal contents, and final publication
  > - cover create failure, post-create query failure, external marker replacement,
  >   retained-target-tag retry, purge and preserve modes, and exact mutation order
  > - inject failures after retained deletes and publish patches plus process death
  >   after tag movement, partial deletion, partial upload, and final publication
  > - prove commit-forward convergence after irreversible boundaries and rollback
  >   before those boundaries
  > - verify starter cleanup, asset-ID preservation, unknown concurrent-asset
  >   preservation, successful committing-phase reconciliation, and interrupted
  >   cleanup recovery
  > - execute composite-action cleanup against real transaction and snapshot roots
  >   and require an empty runner temporary directory
  > - cover one valid action input set and 22 fail-closed Boolean, tag, path,
  >   permission, directory, FIFO, and symlink cases
  > - cover workspace aliases, internal symlinks, source mutation independence,
  >   asset and notes tampering, malformed metadata, extra inventories, cleanup
  >   boundaries, partial cleanup failure, and setup failure residue
  > - classify absent, exact, normalized, partial, mismatched, transient, and HTTP
  >   500 PyPI responses and verify missing-only staging
  > - assert shrinking PyPI request bounds of 9, 7, and 5 seconds
  > - cover Bash 3.2 source constraints, PEP 440 alias ordering, interpreter exit
  >   propagation, and missing-interpreter exit 127
  > - require resolved force-overwrite project paths and reject user-site prefix
  >   collisions when selecting pip scope
  > - assert PowerShell array initialization and complete configured-interpreter
  >   dry-run output
  > - extend workflow contracts for transaction ordering, checked-out commit
  >   targeting, expression confinement, action versions, artifact names, digest
  >   gates, and helper removal
  > 
  > Checks:
  > - `git diff --cached --check`: pass, no output
  > - `bash -n install.sh scripts/release/github-repository.sh
  >   scripts/release/release-versioning.sh
  >   scripts/release/resolve-release-metadata.sh scripts/release/verify-pypi.sh
  >   scripts/release/write-release-notes.sh`: pass
  > - `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`: 100 tests
  >   run in 46.167 seconds, 1 failure in
  >   `test_release_pipeline_uses_dist_action_pypi_publish_and_release_assets`
  > - the failing staged counter expects setup-python 7, download-artifact 4, and
  >   dependency-review v5 once; staged workflows contain setup-python 9,
  >   download-artifact 5, and no dependency-review action
  > - later staged assertions also expect four digest gates, four `python-dist`
  >   names, and the prior concurrency expression; staged workflows contain five
  >   digest gates, five names, and event-aware tag concurrency
  > 
  > Measurements:
  > - staged index: 21 files changed, 7,060 insertions, 330 deletions
  > - major additions: 2,259-line transaction engine, 533-line snapshot engine,
  >   380-line PyPI reconciler, and 3,429 added test lines
- [`add19ae`](https://github.com/FanaticPythoner/justdocs/commit/add19aededca27c0b8ef07e0e66d2035325aeb00) fix: harden cross-platform release filesystem boundaries
  > Make PyPI artifact binding native on Windows and canonicalize trusted POSIX
  > system aliases without weakening descriptor-relative confinement. Rework
  > snapshot and transaction boundaries around canonical parents, then replace
  > brittle global workflow counts with source-local and step-local contracts.
  > 
  > Windows artifact binding:
  > - add conditional ctypes bindings for CreateFileW, GetFileInformationByHandle,
  >   GetFileInformationByHandleEx, GetFileType, and CloseHandle
  > - model stable identity as a 64-bit volume serial plus 128-bit file ID
  > - capture handle attributes, 64-bit size, and 64-bit last-write time
  > - open every ancestor from the filesystem root through the artifact directory
  >   before inventory enumeration
  > - retain ancestor handles with read/write sharing but no delete sharing
  > - open artifact files with read-only sharing to deny concurrent writes,
  >   deletion, and renaming
  > - inspect reparse points directly with FILE_FLAG_OPEN_REPARSE_POINT
  > - reject non-disk handles, reparse points, and directory/file type mismatches
  > - transfer native file handles into noninheritable binary CRT descriptors
  >   without double-closing ownership
  > - hash retained descriptors and reject identity, attribute, size, or write-time
  >   changes after reading
  > - rescan the distribution directory and require exact ordered inventory
  >   equality after artifact binding
  > - recheck every ancestor identity and leaf-directory state before exposing
  >   bound artifacts
  > - close artifact descriptors before directory handles and release ancestors in
  >   reverse acquisition order
  > - preserve Win32 failures through use_last_error and typed PyPIArtifactError
  >   translation
  > 
  > Cross-platform artifact inventory:
  > - centralize wheel and sdist enumeration for path-based and descriptor-based
  >   directory scans
  > - accept only .whl and .tar.gz regular files
  > - reject symlink entries, nonregular entries, empty inventories, and duplicate
  >   names
  > - return immutable lexicographically sorted artifact names
  > - preserve O_DIRECTORY, O_NOFOLLOW, O_NONBLOCK, and dir_fd confinement on
  >   POSIX
  > - dispatch transparently between native Windows and existing POSIX binders
  >   through the unchanged _open_local_artifacts contract
  > 
  > Secure POSIX paths:
  > - add SecurePathError and shared O_RDONLY | O_DIRECTORY | O_NOFOLLOW flag
  >   validation
  > - open absolute directories component-by-component relative to the preceding
  >   descriptor
  > - reject nonabsolute paths, explicit parent traversal, missing flags, and
  >   descendant symlinks
  > - permit only first-component system aliases owned by UID 0 beneath a UID-0,
  >   non-group-writable, non-world-writable filesystem root
  > - bind trusted aliases through device, inode, mode, owner, size, mtime, and
  >   ctime identity
  > - compare alias identity before and after readlink, securely open the canonical
  >   target, then verify the original alias again
  > - normalize absolute and relative alias targets before appending remaining path
  >   components
  > - canonicalize child parents while preserving final basenames for later
  >   descriptor-relative no-follow opens
  > - replace duplicated path traversal in snapshot and transaction engines with
  >   domain-specific error translation wrappers
  > 
  > Snapshot lifecycle:
  > - map workspace-relative operands directly beneath the resolved workspace after
  >   per-component symlink checks
  > - canonicalize absolute RUNNER_TEMP paths while retaining final-component
  >   symlink rejection
  > - accept root-owned system aliases such as macOS /var to /private/var without
  >   admitting nested writable aliases
  > - verify each mkdtemp result remains an immediate child of the canonical stage
  >   parent before writing snapshot data
  > - pass canonical parent and root identities explicitly into partial-failure
  >   cleanup
  > - reject cleanup when the created root does not belong to the supplied
  >   canonical parent
  > - canonicalize snapshot parents during verify and cleanup while retaining
  >   prefix, inventory, digest, permission, device, and inode checks
  > - preserve snapshot schema version 2 and existing manifest semantics
  > 
  > Transaction boundaries:
  > - canonicalize transaction parents through the shared secure POSIX path layer
  > - report invalid parents as expected secure directories
  > - verify each preflight transaction root remains beneath its canonical parent
  >   before journal creation
  > - canonicalize caller-supplied transaction-root parents before descriptor-bound
  >   journal loading
  > - require persisted parent metadata to be absolute, abspath-normalized, securely
  >   canonical, and already stored in canonical spelling
  > - reject transaction roots whose parent differs from canonical journal metadata
  > - canonicalize staged distribution directories without unrestricted
  >   resolve(strict=True) traversal
  > - require staged distributions to remain the verified assets directory
  > - canonicalize release-note parents while requiring the exact
  >   release-notes.md child
  > - preserve transaction schema version 4, release state transitions, GitHub
  >   mutation ordering, and recovery semantics
  > 
  > Workflow contract tests:
  > - replace one repository-wide action Counter with exact per-source action sets
  > - require 5 CI, 5 Latest, 7 Release, 3 reusable-build, 4 Security, 1
  >   build-composite, and 0 release-composite unique action references
  > - parse individual six-space-indented workflow steps instead of comparing
  >   offsettable global text counts
  > - require every download-artifact v8 step to set digest-mismatch: error
  > - require justdocs-python-dist for CI transfers and python-dist for Latest and
  >   Release transfers
  > - require every upload-artifact v7 step to set archive: true
  > - require justdocs-python-dist for CI uploads and python-dist for reusable
  >   build uploads
  > - require pip-audit==2.10.1 with strict resolved-project auditing
  > - require removal of dependency-review-action from the Security contract
  > - require manual releases to group by inputs.tag and other release events by
  >   github.ref_name
  > - require cancel-in-progress: false for Release and Latest publication groups
  > 
  > Platform regression tests:
  > - reject a directory named invalid.whl as malformed local inventory before any
  >   PyPI request
  > - require Windows-bound wheels to reject concurrent overwrite and rename
  >   attempts
  > - prove Windows file handles release after leaving the binding context
  > - create a Windows directory junction with mklink /J and reject it before any
  >   PyPI request
  > - discover trusted root aliases from /var, /tmp, /bin, /sbin, and /lib
  > - require trusted UID-0 aliases to resolve to their absolute targets
  > - reject temporary user-owned directory aliases with SecurePathError
  > - increase the test-method inventory from 100 to 101
  > 
  > Complexity:
  > - retain Windows binding time O(d + e + B) for path depth d, directory entries
  >   e, and aggregate artifact bytes B
  > - retain Windows auxiliary state O(d + n + 1 MiB) with d ancestor handles and
  >   n artifact descriptors
  > - retain POSIX artifact time O(e + B) and state O(n + 1 MiB)
  > - bound secure POSIX canonical traversal to O(d) opens and O(1) live traversal
  >   descriptors
  > 
  > Checks:
  > - git diff --cached --check: pass with no output
  > - PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest discover -s tests:
  >   101 tests pass on Linux in 43.936 seconds
  > - Ruff check: pass
  > - Ruff format check: 5 changed Python files formatted
  > - Actionlint 1.7.12: pass for all GitHub workflows
  > - ShellCheck 0.11.0: pass for installer and release shell scripts
  > - SOURCE_DATE_EPOCH=0 PYTHONHASHSEED=0 just dist: wheel and sdist build
  > - SHA256SUMS.txt verification: pass for every release artifact
  > - Twine 6.2.0: wheel and sdist metadata pass
  > - read-only latest preflight against FanaticPythoner/justdocs at
  >   2493c0c4d760381123425444548805ca4ac81ce5: pass with local journal cleanup
  > - hosted Windows and macOS reruns are not claimed by local evidence
  > 
  > Measurements:
  > - staged index: 5 files changed, 862 insertions, 232 deletions
  > - new secure POSIX helper: 163 lines
  > - POSIX 2 MiB artifact-binding benchmark, 400 alternating samples:
  >   baseline p50 2.6244 ms, p95 3.3116 ms, 762.1 MiB/s
  > - repaired POSIX binding: p50 2.6133 ms, p95 3.3126 ms, 765.3 MiB/s
  > - baseline and repaired peak RSS: 22,348 KiB
- [`35949a6`](https://github.com/FanaticPythoner/justdocs/commit/35949a61da3db21511d730ad0351244cc0d2272d) feat: harden release transactions and recover detached latest releases
  > Strengthens release publication, rollback, filesystem confinement, and legacy
  > latest-release recovery across the staged release pipeline.
  > 
  > Release transaction recovery:
  > - Persist transaction version 6 journals with root identity, creation-attempt
  >   state, pre-create release inventory, owned asset IDs, and phase invariants.
  > - Serialize transaction access with an exclusive descriptor lock.
  > - Verify transaction root device and inode identity before journal reads,
  >   mutations, recovery, and cleanup.
  > - Recover release creation failures by identifying exactly one post-baseline
  >   draft marked with the transaction identity.
  > - Preserve externally modified or published releases when rollback ownership is
  >   indeterminate.
  > - Reconcile tagging and committing phases forward when the publish mutation
  >   already succeeded.
  > - Restore original release metadata, tag ownership, asset names, asset IDs,
  >   and observable asset contents with post-mutation verification.
  > - Detect lost journals, detached transaction releases, marker releases, and
  >   reserved transaction assets before further GitHub mutations.
  > - Reject pre-existing draft releases, incomplete uploads, concurrent release
  >   changes, tag ownership changes, and non-monotonic tag movement.
  > - Reserve `justdocs-rollback-*` and `justdocs-upload-*` asset names against
  >   staged and pre-existing release assets.
  > - Use exclusive descriptor-relative JSON writes with explicit regular-file
  >   validation and durable flushes.
  > - Require transaction cleanup to authenticate the original root identity,
  >   recover active phases, and remove only terminal transaction trees.
  > 
  > GitHub transport and API verification:
  > - Require curl 7.76.0 or newer and readable `/dev/fd` descriptor semantics
  >   during preflight.
  > - Construct authorization headers through a pipe-backed descriptor and remove
  >   `GH_TOKEN` and `GITHUB_TOKEN` from the curl child environment.
  > - Supply exact content lengths for authenticated upload and JSON requests.
  > - Reject unsafe authorization tokens, malformed curl commands, invalid response
  >   encodings, missing executables, and non-regular transaction inputs.
  > - Parse release metadata with strict type, identity, asset-name, digest, and
  >   pagination checks.
  > - Query release metadata and assets around stable before-and-after snapshots to
  >   detect concurrent GitHub mutations.
  > - Verify release creation responses contain the expected draft marker, target
  >   commit, prerelease state, and empty asset set.
  > 
  > Detached latest recovery:
  > - Add `recover-detached latest` for the
  >   `FanaticPythoner/justdocs` repository only.
  > - Identify detached GitHub Actions releases through exact tag, author, name,
  >   description, target-commit, prerelease, draft, and five-asset invariants.
  > - Stream and verify detached asset bytes against GitHub-provided size and
  >   SHA-256 metadata.
  > - Parse the four-entry `SHA256SUMS.txt` manifest and map each digest to its
  >   installer, wheel, and source distribution.
  > - Rename assets through deterministic rollback names, persist progress through
  >   each boundary, and verify every rename before continuing.
  > - Rebind the recovered release to `latest`, publish it as prerelease, and
  >   verify final release, tag, asset, and residue invariants.
  > - Treat already-bound releases as idempotent no-ops while still scanning for
  >   detached transaction residue.
  > - Reject malformed manifests, duplicate candidates, altered asset metadata,
  >   changed tags, unexpected detached refs, invalid authors, and ambiguous
  >   recovery states.
  > 
  > Secure snapshot staging:
  > - Introduce `BoundCreatedDirectory` bindings containing parent descriptor,
  >   directory descriptor, device, and inode identity.
  > - Bind newly created snapshot roots to the expected parent and required
  >   `justdocs-release-` prefix before population or cleanup.
  > - Perform asset, manifest, metadata, and notes writes relative to retained
  >   directory descriptors with `O_NOFOLLOW`, exclusive creation, mode
  >   hardening, and `fsync`.
  > - Verify directory-entry identity after opening, staging, recursive cleanup,
  >   and before root removal.
  > - Detect nested directory substitution, snapshot-root replacement, inventory
  >   tampering, and cleanup races.
  > - Centralize the snapshot prefix and retain snapshot metadata version 2.
  > 
  > Workflow coordination:
  > - Serialize release mutation jobs per repository in `latest.yml` and
  >   `release.yml` with non-canceling queued concurrency.
  > - Run detached latest recovery before latest-release preflight.
  > 
  > Tests and fixtures:
  > - Extend the transactional GitHub fixture with REST and GraphQL-like metadata,
  >   pagination, asset streaming, tag races, release races, crash injection,
  >   partial uploads, external mutation, and transport-failure scenarios.
  > - Cover absent-release creation, existing-release replacement, immutable-release
  >   no-op and mismatch handling, rollback, commit-forward recovery, cleanup
  >   recovery, retained assets, asset-ID preservation, and residue detection.
  > - Cover every detached latest recovery boundary, terminal convergence,
  >   idempotent execution, invalid profiles, duplicate candidates, transport
  >   validation, and repository/tag scoping.
  > - Cover secure descriptor binding, symlink boundaries, inventory tampering,
  >   nested substitution, partial cleanup failure, and setup failure cleanup.
  > - Preserve exact mutation assertions ensuring unknown-length standard-input
  >   mutations are rejected.
  > 
  > Checks:
  > - `git diff --cached --check` exits cleanly.
  > - `python3 -m unittest tests.test_package -k release` passes 44 tests in
  >   72.112 seconds.
  > - Six targeted secure snapshot and path-boundary tests pass in 1.407 seconds.
  > 
  > Measurements:
  > - Staged index: 7 modified files, 3,874 insertions, 391 deletions.
- [`2b18875`](https://github.com/FanaticPythoner/justdocs/commit/2b1887590b302e643115fd92b07f1b54806df5b1) macos fix
- [`7b16366`](https://github.com/FanaticPythoner/justdocs/commit/7b16366b4b74c7ae14ed9d5aeb9165fff7841c56) feat(release): automate verified Python package publication
  > Release preparation:
  > - Add `just next-release` with patch, minor, and major SemVer increments.
  > - Require a clean default branch synchronized with its remote before release preparation.
  > - Generate dated changelog entries from the Unreleased section and chronological NUL-delimited Git records.
  > - Atomically replace version and changelog files with preserved modes, file fsync, directory fsync, and symlink rejection.
  > - Create the version commit and annotated tag locally; require `--push` for an atomic branch-and-tag push.
  > - Generate stable release notes from the resulting immutable tag boundary.
  > 
  > Publication:
  > - Default PyPI publication to OIDC trusted publishing when no API token is configured.
  > - Retain `PYPI_API_TOKEN` as an explicit authenticated publication path.
  > - Remove the repository-variable gate and the silent no-publication mode.
  > - Require PyPI completion before GitHub Release creation.
  > - Verify the public GitHub release tag target, title, notes, draft state, prerelease state, latest-release binding, asset inventory, byte lengths, and SHA-256 digests.
  > - Resolve annotated tag chains through at most eight validated Git objects.
  > - Bound GitHub REST responses to 2 MiB and reject malformed identities, JSON, tags, metadata, and local artifact paths.
  > 
  > PR distributions:
  > - Retain CI distribution artifacts for 90 days with overwrite semantics.
  > - Add a trusted `workflow_run` publisher with minimal read and pull-request write permissions.
  > - Check out only the default-branch implementation with persisted credentials disabled.
  > - Validate the completed CI run identity, pull-request binding, commit SHA, artifact uniqueness, expiry, byte length, and SHA-256 digest.
  > - Create or replace exactly one marker-bound `github-actions[bot]` comment.
  > - Publish artifact, workflow, expiry, digest, and isolated-install security metadata without executing pull-request code under write permissions.
  > - Bound API responses to 4 MiB and comment traversal to 10,000 entries.
  > 
  > Supply chain:
  > - Pin checkout, Python setup, artifact upload and download, PyPI publication, provenance attestation, and CodeQL actions to immutable 40-hex revisions.
  > - Preserve human-readable action release annotations beside each pinned revision.
  > - Extend workflow contract tests to reject every unpinned external action reference.
  > - Verify downloaded artifact digests and retain provenance attestation for wheel, source archive, installers, and checksum manifest.
  > 
  > Packaging and documentation:
  > - Add persistent release history in `CHANGELOG.md`.
  > - Include changelog, license, and README files in source distributions through `MANIFEST.in`.
  > - Expose the changelog through package project metadata.
  > - Replace Bash `mapfile` usage with a portable NUL-delimited read loop.
  > - Document trusted-publisher identity, token fallback, release commands, publication invariants, PR artifacts, and public digest verification.
  > - Synchronize release guidance across the README and bundled example documentation.
  > 
  > Tests:
  > - Add an isolated Git repository test covering initial changelog generation, release commit creation, annotated tagging, release-note generation, and no implicit remote tag publication.
  > - Add PR comment tests covering rendered artifact metadata, workflow-event binding, artifact selection, bot ownership, and spoofed user-comment rejection.
  > - Add exact local-to-remote GitHub asset size and SHA-256 equivalence coverage.
  > - Expand packaging and workflow assertions for pinned actions, trusted publication defaults, artifact retention, release verification, manifest contents, and documentation surfaces.
  > 
  > Checks:
  > - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest discover -s tests`: 124 tests passed in 134.462 seconds.
  > - `SOURCE_DATE_EPOCH=0 PYTHONHASHSEED=0 just dist`: wheel and source distribution built; Twine checks passed.
  > - Two deterministic builds produced byte-identical wheel, source archive, installers, and checksum manifest.
  > - Isolated wheel installation, project initialization, project checking, and strict documentation build passed.
  > - Ruff checking, Ruff formatting verification, Python byte-compilation, and 33 ShellCheck Bash-block checks passed.
  > - Actionlint reported two schema diagnostics for the GitHub-supported `queue: max` expression and no other diagnostics.
  > - `git diff --cached --check` reports `CHANGELOG.md:16: new blank line at EOF`.
  > 
  > Measurements:
  > - Staged scope: 19 files, 1,531 insertions, 76 deletions.
  > - File topology: 6 additions and 13 modifications.
  > - Test topology: 405 insertions and 27 deletions in the package contract suite.
  > - Test inventory: 124 test methods.
  > - Release assets verified across 5 byte-identical outputs.
